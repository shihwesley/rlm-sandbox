# MCP Python SDK Cheat Sheet

## Installation
```bash
pip install "mcp[cli]"
```

## MCPServer (v2 — renamed from FastMCP)
```python
from mcp.server.mcpserver import MCPServer

mcp = MCPServer("server-name", version="1.0.0")
```

## Tool Registration (decorator)
```python
@mcp.tool()
def my_tool(arg1: str, arg2: int) -> str:
    """Tool description for Claude."""
    return f"result: {arg1} {arg2}"

# Async tools work too
@mcp.tool()
async def async_tool(code: str) -> str:
    """Async tool."""
    result = await do_something(code)
    return result
```
Schema auto-generated from type hints + docstring.

## Lifespan (startup/shutdown)
```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

@dataclass
class AppContext:
    db: Database
    container: DockerContainer

@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    # startup
    db = await Database.connect()
    container = start_container()
    try:
        yield AppContext(db=db, container=container)
    finally:
        # shutdown
        await db.disconnect()
        container.stop()

mcp = MCPServer("my-app", lifespan=app_lifespan)
```

## Accessing Context in Tools
```python
from mcp.server.mcpserver import Context

@mcp.tool()
async def my_tool(code: str, ctx: Context) -> str:
    app = ctx.request_context.lifespan_context  # your AppContext
    return app.container.exec(code)
```

## Running with stdio transport
```python
if __name__ == "__main__":
    mcp.run(transport="stdio")
```

## Claude Code mcp-config.json
```json
{
  "mcpServers": {
    "rlm": {
      "command": "python",
      "args": ["-m", "mcp_server.server"],
      "cwd": "/path/to/project"
    }
  }
}
```

## Resources (optional)
```python
@mcp.resource("data://{key}")
def get_data(key: str) -> str:
    return load_data(key)
```

## Key Points
- MCPServer replaces FastMCP in v2 (same API, just renamed)
- Import: `from mcp.server.mcpserver import MCPServer`
- Tools get schema from type hints — keep signatures clean
- Lifespan async context manager handles container lifecycle
- stdio transport is what Claude Code uses for local servers
- Context parameter injection gives tools access to lifespan state
