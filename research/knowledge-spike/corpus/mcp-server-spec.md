---
name: mcp-server
phase: 1
sprint: 2
parent: docker-sandbox
depends_on: [docker-sandbox]
status: draft
created: 2026-02-11
---

# MCP Server (Host-Side)

## Overview
Python MCP server that runs on the host, manages the Docker container lifecycle, and bridges Claude Code tool calls to the sandbox's HTTP API. Uses stdio transport for Claude Code discovery.

## Requirements
- [ ] REQ-1: MCP server with stdio transport, auto-discovered by Claude Code
- [ ] REQ-2: Lazy container startup — first tool call starts the container, not session start
- [ ] REQ-3: Docker lifecycle management (start, stop, health-check, restart on crash)
- [ ] REQ-4: Six MCP tools: rlm.exec, rlm.load, rlm.get, rlm.vars, rlm.sub_agent, rlm.reset
- [ ] REQ-5: rlm.load reads a file from host filesystem and loads it into sandbox variable space
- [ ] REQ-6: rlm.get retrieves a variable, optionally filtering with a query (Python expression)

## Acceptance Criteria
- [ ] AC-1: Claude Code discovers rlm.* tools on startup via MCP config
- [ ] AC-2: First rlm.exec call starts container (within 5s), subsequent calls reuse it
- [ ] AC-3: rlm.load("/path/to/file.py", "src") loads file content into sandbox var "src"
- [ ] AC-4: rlm.get("src") returns the variable value; rlm.get("src", "len(src)") returns length
- [ ] AC-5: rlm.vars() lists all variables with types and summaries
- [ ] AC-6: rlm.sub_agent(signature, inputs) routes to container's /sub_agent
- [ ] AC-7: rlm.reset() wipes sandbox state (restarts kernel, clears vars)
- [ ] AC-8: Container health-check runs every 30s; auto-restart on failure

## Requirements (continued)
- [ ] REQ-7: --no-docker fallback mode: start srt-wrapped bare Python kernel (no Docker)
- [ ] REQ-8: srt wrapping for the MCP server process itself (defense-in-depth)

## Acceptance Criteria (continued)
- [ ] AC-9: When Docker unavailable, --no-docker starts srt-wrapped kernel, tools work
- [ ] AC-10: MCP server runs inside srt with denyRead for sensitive paths

## Technical Approach
Use the `mcp` Python SDK (`pip install "mcp[cli]"`) with the high-level `MCPServer` API.
Decorator-based tool registration with automatic schema generation from type hints.
`lifespan` parameter handles lazy container startup and graceful shutdown.
The server process starts when Claude Code launches it per mcp-config.json.
On first tool call, it starts the Docker container via docker-py.
All subsequent tool calls are HTTP requests to the container's FastAPI.

rlm.load is host-side only — it reads the file from disk, then POSTs the content
to /exec with code that assigns it to a variable. This way the file never enters
the context window.

rlm.sub_agent is host-side only — routes to mcp-server/sub_agent.py (DSPy runs
host-side, see dspy-integration spec). No API keys enter the container.

No glob support for rlm.load in v1 — single file paths only.

## Files
| File | Action | Purpose |
|------|--------|---------|
| mcp-server/server.py | create | MCP server via MCPServer class, stdio transport, tool registration, lifespan |
| mcp-server/docker_manager.py | create | Start/stop/health-check Docker containers, --no-docker fallback |
| mcp-server/tools.py | create | Tool implementations (exec, load, get, vars, sub_agent, reset) |
| mcp-server/srt-config.json | create | srt sandbox config for MCP server process |
| mcp-server/requirements.txt | create | mcp[cli], docker, httpx, dspy |
| tests/test_mcp_server.py | create | Tests for lazy startup, tool routing, health-check, --no-docker fallback |

## Tasks
1. Implement docker_manager.py with start/stop/health/restart + --no-docker fallback
2. Implement MCP server with MCPServer class, lifespan for lazy startup, stdio transport
3. Implement rlm.exec tool (proxy POST /exec to container)
4. Implement rlm.load tool (read host file, inject into sandbox via /exec)
5. Implement rlm.get, rlm.vars, rlm.reset tools
6. Wire rlm.sub_agent to mcp-server/sub_agent.py (from dspy-integration spec)
7. Create srt-config.json for MCP server wrapping
8. Write tests for lazy startup, tool routing, health-check recovery, --no-docker

## Dependencies
- **Needs from docker-sandbox:** container HTTP API to route calls to
- **Needs from dspy-integration:** sub_agent.py for rlm.sub_agent tool
- **Provides to claude-integration:** MCP server for Claude Code to discover
- **Provides to session-persistence:** server.py hooks for save/restore
- **Provides to dspy-integration:** llm_query callback endpoint for container

## Resolved Questions
- MCP SDK: use `mcp` Python SDK with high-level MCPServer API
- Globs: no glob support in v1, single file paths only
- srt wrapping: config at mcp-server/srt-config.json, denyRead for ~/.ssh, ~/.aws, etc.
- rlm.get filter: Python expression runs in sandbox kernel, not on host (documented)

## Research Spike Updates (2026-02-12)
- **srt wrapping:** MCP server should run inside `srt` sandbox for defense-in-depth.
  Config: allowLocalBinding=true, denyRead=[~/.ssh, ~/.aws, etc], allowWrite=[~/.rlm-sandbox].
  This prevents the MCP server from reading secrets or exfiltrating data even if compromised.
- **--no-docker flag:** Add fallback mode where MCP server starts the kernel as a bare
  srt-wrapped process instead of a Docker container. Uses research/srt-prototype/kernel.py pattern.
  Detected automatically if Docker is unavailable, or forced via --no-docker.
- **Prototype validated:** srt-wrapped process can reach Docker container on localhost (7/7 tests pass).
