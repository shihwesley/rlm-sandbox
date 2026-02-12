# Progress Log

## Session: 2026-02-11
- Created spec-driven plan with 5 specs across 2 phases
- Researched rlmgrep for DSPy RLM reference patterns
- All planning files written (manifest, findings, progress, 5 spec files)

## Session: 2026-02-12
- Researched Anthropic's official sandbox infrastructure (native /sandbox, srt, Docker Sandboxes)
- Added sandbox-research spec as Phase 0 blocker
- Updated manifest DAG: sandbox-research -> docker-sandbox -> (everything else)
- DSPy stays in-container per user decision
- Installed @anthropic-ai/sandbox-runtime (srt) globally
- Built srt-only prototype: research/srt-prototype/ — 15/15 tests pass
- Built hybrid prototype: research/hybrid-prototype/ — 7/7 tests pass
- Found --network=none breaks port mapping → use --dns 0.0.0.0 on bridge
- Docker Sandboxes unavailable in Docker Desktop 28.0.1
- Wrote comparison matrix: research/comparison.md
- Recommendation: Hybrid (Docker+srt) primary, srt-only as --no-docker fallback
- Updated docker-sandbox, mcp-server, claude-integration specs with research findings

## Spec Status
| Spec | Phase | Sprint | Status | Commit | Last Updated |
|------|-------|--------|--------|--------|-------------|
| sandbox-research | 0 | 1 | completed | -- | 2026-02-12 |
| docker-sandbox | 1 | 1 | completed | 4b01edc | 2026-02-12 |
| dspy-integration | 1 | 2 | ready | -- | 2026-02-12 |
| mcp-server | 1 | 2 | ready | -- | 2026-02-12 |
| session-persistence | 2 | 1 | ready | -- | 2026-02-12 |
| claude-integration | 2 | 1 | ready | -- | 2026-02-12 |

### Phase 0, Sprint 1: Sandbox Research Spike
- **Status:** completed
- **Started:** 2026-02-12
- **Completed:** 2026-02-12
- Actions taken:
  - Installed srt, tested basic execution, port binding, filesystem/network isolation
  - Built srt-only prototype (kernel.py + test_kernel.sh) — 15/15
  - Built hybrid prototype (Dockerfile + kernel.py + test_hybrid.sh) — 7/7
  - Tested Docker Sandboxes — unavailable in current Docker Desktop
  - Wrote comparison matrix and recommendation
  - Updated downstream specs with findings
- Files created/modified:
  - research/srt-test-config.json
  - research/srt-prototype/srt-config.json
  - research/srt-prototype/kernel.py
  - research/srt-prototype/test_kernel.sh
  - research/hybrid-prototype/Dockerfile
  - research/hybrid-prototype/kernel.py
  - research/hybrid-prototype/mcp-srt-config.json
  - research/hybrid-prototype/test_hybrid.sh
  - research/comparison.md
  - docs/plans/findings.md (updated with results)
  - docs/plans/specs/docker-sandbox-spec.md (updated)
  - docs/plans/specs/mcp-server-spec.md (updated)
  - docs/plans/specs/claude-integration-spec.md (updated)

### Phase 1, Sprint 1: Docker Sandbox
- **Status:** completed
- **Started:** 2026-02-12
- **Completed:** 2026-02-12
- **Tests:** 8/8 passed
- **Commit:** 4b01edc
- Actions taken:
  - Created Dockerfile (python:3.12-slim + curl, uvicorn CMD)
  - Created docker-compose.yml (dns 0.0.0.0, 2GB mem, 2 CPU, /workspace volume, healthcheck)
  - Implemented sandbox/repl.py (IPython kernel manager with timeout via threading)
  - Implemented sandbox/server.py (FastAPI routes: /exec, /vars, /var/:name, /health)
  - Wrote 8 integration tests covering all acceptance criteria
  - Fixed test ordering: timeout before memory (OOM may kill container)
  - Memory test accepts both MemoryError and OOM-killed connection reset
- Files created/modified:
  - Dockerfile
  - docker-compose.yml
  - pyproject.toml
  - sandbox/__init__.py, sandbox/repl.py, sandbox/requirements.txt, sandbox/server.py
  - tests/__init__.py, tests/test_sandbox.py
  - workspace/.gitkeep, .gitignore

### Phase 1, Sprint 2: DSPy (host-side) + MCP Server (parallel)
- **Status:** completed
- **Started:** 2026-02-12
- **Completed:** 2026-02-12
- **Tests:** 42/42 passed (8 sandbox + 8 MCP integration + 26 DSPy mock-based)
- **Commit:** af52b2f
- **Architecture change:** DSPy moved host-side to MCP server (no API key in container)
- Actions taken:
  - Created mcp_server/ package (renamed from mcp-server/ — hyphens aren't valid Python package names)
  - Implemented DockerManager with lazy startup, health loop, --no-docker fallback
  - Implemented MCPServer with lifespan, stdio transport, 6 tools (exec, load, get, vars, sub_agent, reset)
  - Implemented SandboxInterpreter (CodeInterpreter protocol: execute + __call__)
  - Implemented run_sub_agent() with DSPy RLM, Haiku 4.5 sub_lm, configurable limits
  - Built custom signature builder (build_custom_signature) and pre-built signatures
  - Added llm_query callback (container stub POSTs to host, API keys stay host-side)
  - Added path denylist on rlm_load (defense-in-depth, matches srt-config)
  - Fixed reset to use get_ipython().reset() (kernel object not in IPython namespace)
  - Fixed asyncio test helper for Python 3.14 (asyncio.run() not get_event_loop())
  - Fixed test assertions (DSPy Signature field access, ternary precedence)
  - Port corrected from 8000 to 8080 (matching docker-compose.yml)
- Files created/modified:
  - mcp_server/__init__.py, docker_manager.py, server.py, tools.py, sub_agent.py, signatures.py
  - mcp_server/requirements.txt, srt-config.json
  - tests/test_mcp_server.py, tests/test_sub_agent.py
  - .gitignore (fixed __pycache__ pattern)

### Phase 2, Sprint 1: Persistence + Claude Integration (parallel)
- **Status:** ready (blocked by Phase 1, all decisions resolved)
- **Started:** --
- Actions taken:
- Files created/modified:

## Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| srt-only prototype | 15 pass | 15 pass | PASS |
| hybrid prototype | 7 pass | 7 pass | PASS |

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phase 0 complete, Phase 1 Sprint 1 next |
| Where am I going? | 5 remaining specs across 2 phases |
| What's the goal? | MCP-bridged sandbox for Claude Code (RLM pattern) with tiered isolation |
| What have I learned? | Hybrid (Docker+srt) is best for prod, srt-only for dev; --network=none doesn't work |
| What have I done? | Research spike complete with prototypes, comparison, and spec updates |
