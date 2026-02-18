"""MCP server bridging Claude Code to the Docker sandbox."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from mcp.server.fastmcp import FastMCP

from mcp_server.apple_docs import register_apple_docs_tools
from mcp_server.docker_manager import BASE_URL, DockerManager
from mcp_server.fetcher import register_fetcher_tools
from mcp_server.knowledge import KnowledgeStore, get_store, register_knowledge_tools
from mcp_server.llm_callback import LLMCallbackServer, SANDBOX_TOOLS
from mcp_server.research import register_research_tools
from mcp_server.session import SessionManager
from mcp_server.sub_agent import inject_llm_stub, inject_tool_stubs
from mcp_server.tools import register_tools

log = logging.getLogger(__name__)


@dataclass
class AppContext:
    """Shared resources available to all tools via lifespan context."""

    manager: DockerManager
    http: httpx.AsyncClient
    llm_callback: LLMCallbackServer
    knowledge_store: KnowledgeStore | None = None


@asynccontextmanager
async def lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Create shared resources on startup, clean up on shutdown."""
    manager = DockerManager()
    client = httpx.AsyncClient()
    callback = LLMCallbackServer()
    session = SessionManager()
    store = get_store()
    try:
        await callback.start()
        await manager.ensure_running()

        # Inject llm_query() into the sandbox so all rlm_exec calls can use it.
        # Pick the right callback URL based on whether we're in Docker or bare mode.
        cb_url = callback.callback_url_local if manager._no_docker else callback.callback_url
        sandbox_client = httpx.AsyncClient(base_url=BASE_URL, timeout=10)
        try:
            await inject_llm_stub(sandbox_client, cb_url)
            log.info("Injected llm_query() stub (callback → %s)", cb_url)
            # Wire tool handlers on the callback server then inject stubs into sandbox
            cb_base = (
                callback.base_url_local if manager._no_docker else callback.base_url
            )
            callback.setup_tool_handlers(store, client)
            await inject_tool_stubs(sandbox_client, cb_base, SANDBOX_TOOLS)
            log.info("Injected tool stubs (callback base → %s)", cb_base)
        finally:
            await sandbox_client.aclose()

        await session.restore()
        session.start_auto_save()
        SessionManager.cleanup_expired()
        store.open()
        yield AppContext(
            manager=manager, http=client, llm_callback=callback,
            knowledge_store=store,
        )
    finally:
        # Save before tearing down the container
        try:
            await session.save()
        except Exception:
            log.exception("Final session save failed")
        try:
            store.close()
        except Exception:
            log.exception("Knowledge store close failed")
        await session.stop_auto_save()
        await callback.stop()
        await client.aclose()
        await manager.stop()


mcp = FastMCP("rlm-sandbox", lifespan=lifespan)
register_tools(mcp)
register_knowledge_tools(mcp)
register_fetcher_tools(mcp)
register_research_tools(mcp)
register_apple_docs_tools(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")
