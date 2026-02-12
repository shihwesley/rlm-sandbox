"""MCP server bridging Claude Code to the Docker sandbox."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from mcp_server.docker_manager import DockerManager
from mcp_server.session import SessionManager
from mcp_server.tools import register_tools

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[DockerManager]:
    """Start the sandbox container on startup, stop on shutdown."""
    manager = DockerManager()
    session = SessionManager()
    try:
        await manager.ensure_running()
        await session.restore()
        session.start_auto_save()
        SessionManager.cleanup_expired()
        yield manager
    finally:
        # Save before tearing down the container
        try:
            await session.save()
        except Exception:
            log.exception("Final session save failed")
        await session.stop_auto_save()
        await manager.stop()


mcp = MCPServer("rlm-sandbox", lifespan=lifespan)
register_tools(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")
