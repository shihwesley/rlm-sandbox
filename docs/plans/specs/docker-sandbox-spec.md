---
name: docker-sandbox
phase: 1
sprint: 1
parent: null
depends_on: []
status: completed
created: 2026-02-11
---

# Docker Sandbox

## Overview
The foundation container that runs a persistent Python 3.12 environment with an IPython kernel and FastAPI server. Everything else builds on this.

## Requirements
- [ ] REQ-1: Dockerfile with Python 3.12, DSPy, FastAPI, uvicorn, IPython, dill
- [ ] REQ-2: FastAPI server on :8080 with /exec, /vars, /var/:name endpoints
- [ ] REQ-3: Persistent IPython kernel that maintains state across /exec calls
- [ ] REQ-4: docker-compose.yml with --dns 0.0.0.0 (bridge network), 2GB memory limit, 2 CPU cores
- [ ] REQ-6: Configurable execution timeout per /exec call (default 30s)
- [ ] REQ-5: Mounted volume at /workspace for shared files with host

## Acceptance Criteria
- [ ] AC-1: `docker compose up` starts container, healthcheck passes within 10s
- [ ] AC-2: POST /exec {code: "x = 42"} returns {output: "", stderr: "", vars: ["x"]}
- [ ] AC-3: GET /vars returns [{name: "x", type: "int", summary: "42"}]
- [ ] AC-4: GET /var/x returns {value: 42}
- [ ] AC-5: State persists across multiple /exec calls (set x=1, then read x)
- [ ] AC-6: DNS resolution fails inside container (curl to domain fails; raw IP on bridge still works)
- [ ] AC-7: Container respects memory limit (allocation >2GB fails gracefully)
- [ ] AC-8: /exec with timeout=5 kills execution after 5s and returns error

## Technical Approach
Based on rlmgrep's interpreter pattern but replacing Deno with a persistent IPython kernel.
The kernel runs as a long-lived process inside the container, and FastAPI routes requests to it.
Variables live in the kernel's namespace — inspectable via /vars and /var/:name.

## Files
| File | Action | Purpose |
|------|--------|---------|
| Dockerfile | create | Python 3.12 base, install deps, expose 8080 |
| docker-compose.yml | create | Container config with --dns 0.0.0.0, volume mounts, resource limits |
| sandbox/server.py | create | FastAPI app with /exec, /vars, /var/:name routes |
| sandbox/repl.py | create | IPython kernel manager (start, execute, inspect, capture output) |
| sandbox/requirements.txt | create | fastapi, uvicorn, ipython, dill, rich (no dspy — DSPy runs host-side) |
| tests/test_sandbox.py | create | Integration tests for container, exec, vars, persistence, isolation |

## Tasks
1. Create Dockerfile with Python 3.12 base and dependency installation
2. Create docker-compose.yml with security constraints and volume mounts
3. Implement sandbox/repl.py IPython kernel manager
4. Implement sandbox/server.py FastAPI routes
5. Write integration tests (container up, exec, vars, persistence, isolation)

## Dependencies
- **Needs from:** nothing (foundation spec)
- **Provides to dspy-integration:** running container with /exec endpoint
- **Provides to mcp-server:** HTTP API to route MCP tool calls to
- **Provides to session-persistence:** kernel state to serialize

## Resolved Questions
- stdout/stderr: combined output + separate stderr field. Response: `{output, stderr, vars}`
- Exec timeout: 30s default, configurable per call via `timeout` param
- DSPy removed from container deps — DSPy runs host-side in MCP server

## Research Spike Updates (2026-02-12)
- **--network=none changed to --dns 0.0.0.0:** Port mapping requires bridge network.
  --dns 0.0.0.0 blocks DNS resolution while allowing localhost port forwarding.
  Future hardening: Unix socket on mounted volume (no network at all).
- **srt-only fallback:** The kernel.py from research/srt-prototype/ can run without Docker,
  wrapped by `srt`. The MCP server should support a `--no-docker` flag that uses this path.
- **Prototype validated:** research/srt-prototype/kernel.py passes 15/15 tests.
  research/hybrid-prototype/ passes 7/7 tests with Docker + srt.
