# rlm-sandbox

A Docker sandbox for running Python and DSPy code in isolated containers, exposed to Claude Code through an MCP server.

Claude sends code via MCP tools. The MCP server (running on the host) forwards it to a FastAPI + IPython kernel inside a Docker container. Results come back the same way. DSPy optimization runs host-side so API keys never enter the container.

## Architecture

```
Claude Code
    |
    | stdio (MCP protocol)
    v
MCP Server (host process)
    |                \
    | HTTP             DSPy (host-side, talks to Haiku 4.5)
    v
Docker Container
    FastAPI + IPython kernel
    (no network, no API keys)
```

The MCP server is defined in `mcp_server/server.py`. The container runs `sandbox/server.py` (FastAPI) backed by `sandbox/repl.py` (IPython kernel).

## Isolation Tiers

The sandbox supports three levels of isolation depending on your environment:

**Tier 1 — Process isolation (`--no-docker`)**
Falls back to running the IPython kernel as a local subprocess. No Docker required. Startup is around 200ms. The `srt-config.json` file restricts filesystem access (denies `~/.ssh`, `~/.aws`, `~/.config/gcloud`). Good for quick iteration when you trust the code being executed.

**Tier 2 — Docker container (default)**
Runs the kernel inside a Docker container with null DNS (no outbound network), 2GB memory limit, and 2 CPU cap. Startup takes about 4 seconds. The container gets no API keys and no access to the host filesystem beyond the `./workspace` mount. This is the recommended mode.

**Tier 3 — Docker Sandboxes (future)**
Full Docker Desktop sandbox deployment with stronger isolation guarantees. Not yet implemented — requires a Docker Desktop version that supports the Sandboxes API.

When Docker is unavailable the MCP server automatically drops to Tier 1. The `srt-config.json` deny rules apply at every tier as defense-in-depth.

## Quick Start

**Prerequisites:** Python 3.12+, Docker (optional but recommended)

```bash
# Clone and install dependencies
pip install -r mcp_server/requirements.txt

# Run the automated setup
bash claude-integration/setup.sh

# Restart Claude Code to pick up the new MCP server
```

After setup, the `rlm` MCP server appears in Claude Code's tool list. Try it:

> "Use rlm_exec to calculate the first 20 Fibonacci numbers"

To start the sandbox manually (for development or testing):

```bash
docker compose up -d --build    # Tier 2: Docker
# or
uvicorn sandbox.server:app --host 127.0.0.1 --port 8080  # Tier 1: bare
```

## Tool Reference

| Tool | Description |
|------|-------------|
| `rlm_exec(code, timeout=30)` | Execute Python code in the sandbox. Returns stdout/stderr. |
| `rlm_load(path, var_name)` | Read a host file and inject its content into a sandbox variable. Denies access to `~/.ssh`, `~/.aws`, `~/.config/gcloud`, `~/.gnupg`. |
| `rlm_get(name, query=None)` | Retrieve a sandbox variable by name. If `query` is provided, evaluates it as a Python expression in the sandbox instead. |
| `rlm_vars()` | List all variables currently in the sandbox with types and value summaries. |
| `rlm_sub_agent(signature, inputs)` | Run a DSPy sub-agent with the given signature (e.g., `"question -> answer"`) and inputs dict. Results are stored in the sandbox as `_sub_agent_result`. |
| `rlm_reset()` | Clear all sandbox state (variables, imports, history). |

## Project Layout

```
mcp_server/          MCP server (runs on host)
  server.py          Entry point — stdio transport
  tools.py           Tool definitions (rlm_exec, rlm_load, etc.)
  docker_manager.py  Container lifecycle, health checks, fallback to bare mode
  sub_agent.py       DSPy sub-agent runner
  signatures.py      DSPy signature definitions
  srt-config.json    Filesystem deny rules (defense-in-depth)
sandbox/             Container payload
  server.py          FastAPI app with /exec, /var, /vars, /health
  repl.py            IPython kernel wrapper
claude-integration/  Claude Code setup files
  mcp-config.json    MCP server registration (has PROJECT_DIR placeholder)
  rlm-routing-rules.md  When to use sandbox vs. built-in tools
  setup.sh           Installer script
tests/               pytest test suite
workspace/           Mounted into container at /workspace
```

## Running Tests

```bash
# Unit/smoke tests (no Docker needed)
pytest tests/test_integration.py

# Full integration tests (requires Docker)
pytest tests/test_mcp_server.py tests/test_sandbox.py
```

## `/sandbox` Compatibility Note

Claude Code has a built-in `/sandbox` command that runs code in its own sandbox environment. `rlm-sandbox` is a separate system — it provides a persistent IPython kernel with variable state across calls, DSPy sub-agent support, and file loading from the host. Both can coexist. The routing rules in `.claude/rlm-routing-rules.md` tell Claude when to prefer one over the other.
