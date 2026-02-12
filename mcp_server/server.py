"""MCP server bridging Claude Code to the Docker sandbox."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from mcp.server.mcpserver import MCPServer

from mcp_server.docker_manager import DockerManager
from mcp_server.tools import register_tools


@asynccontextmanager
async def lifespan(server: MCPServer) -> AsyncIterator[DockerManager]:
    """Start the sandbox container on startup, stop on shutdown."""
    manager = DockerManager()
    try:
        yield manager
    finally:
        await manager.stop()


mcp = MCPServer("rlm-sandbox", lifespan=lifespan)
register_tools(mcp)


if __name__ == "__main__":
    mcp.run(transport="stdio")
