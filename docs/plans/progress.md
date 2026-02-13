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
| dspy-integration | 1 | 2 | completed | af52b2f | 2026-02-12 |
| mcp-server | 1 | 2 | completed | af52b2f | 2026-02-12 |
| session-persistence | 2 | 1 | completed | d1ad217 | 2026-02-12 |
| claude-integration | 2 | 1 | completed | d1ad217 | 2026-02-12 |
| search-spike | 3 | 1 | completed | ebd8785 | 2026-02-12 |
| doc-fetcher | 4 | 1 | draft (rewritten for memvid) | -- | 2026-02-13 |
| search-engine | 4 | 1 | draft (rewritten for memvid) | -- | 2026-02-13 |
| orchestrator-integration | 4 | 2 | draft (rewritten for memvid) | -- | 2026-02-13 |

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
- **Status:** completed
- **Started:** 2026-02-12
- **Completed:** 2026-02-12
- **Tests:** 77/77 passed (35 new + 42 existing, zero regressions)
- **Commit:** d1ad217 (merge: 5bc3ab0)
- **Review:** 3 P0/P1 issues found and fixed (atomic writes, sed escaping, backup-before-merge)
- Actions taken:
  - session-persistence: dill-based /snapshot/save and /snapshot/restore endpoints, SessionManager with 5-min auto-save, lifespan hooks
  - claude-integration: mcp-config.json, routing rules, setup.sh installer, README with 3-tier isolation docs
  - Resolved merge conflict with in-flight FastMCP refactor (MCPServer → FastMCP + AppContext)
- Files created/modified:
  - sandbox/server.py (modified — snapshot endpoints)
  - mcp_server/session.py (created — SessionManager)
  - mcp_server/server.py (modified — lifespan wiring + FastMCP migration)
  - mcp_server/tools.py (modified — AppContext/shared httpx client refactor)
  - claude-integration/mcp-config.json (created)
  - claude-integration/rlm-routing-rules.md (created)
  - claude-integration/setup.sh (created)
  - README.md (created)
  - tests/test_persistence.py (created — 7 tests)
  - tests/test_integration.py (created — 28 tests)

## Test Results
| Test | Expected | Actual | Status |
|------|----------|--------|--------|
| srt-only prototype | 15 pass | 15 pass | PASS |
| hybrid prototype | 7 pass | 7 pass | PASS |

### Phase 3, Sprint 1: Search Engine Research Spike
- **Status:** completed
- **Started:** 2026-02-12
- **Completed:** 2026-02-12
- **Tests:** N/A (research spike — prototypes ran successfully)
- **Commit:** ebd8785
- **Review:** Skipped (research spike, no production code)
- Actions taken:
  - Prototyped memvid-sdk: installs on 3.14 but vec feature missing on macOS ARM64, 0/5 NL queries
  - Prototyped FAISS+fastembed: clean install, 5/5 NL queries, 2.4ms latency, 1.1GB peak RAM
  - Benchmarked both approaches with identical 15-file corpus and 5 queries
  - Analyzed host-side vs container-side: host-side wins (memory, model management, shared state)
  - Decision: FAISS + fastembed (BGE-small-en-v1.5), host-side in MCP server
- Files created/modified:
  - research/knowledge-spike/memvid_proto.py (created)
  - research/knowledge-spike/faiss_proto.py (created)
  - research/knowledge-spike/memvid_results.md (created)
  - research/knowledge-spike/faiss_results.md (created)
  - research/knowledge-spike/benchmark_results.md (created)
  - research/knowledge-spike/host_vs_container.md (created)
  - research/knowledge-spike/corpus/ (15 test files)
  - docs/plans/findings.md (modified — added search decision)
  - docs/plans/manifest.md (modified — search-spike → completed)
  - docs/plans/specs/search-spike-spec.md (modified — status → completed)

## Session: 2026-02-13
- Reversed search-spike decision: memvid-sdk replaces FAISS+fastembed
- Full memvid v2 docs fetched (89 pages) to .claude/docs/memvid/
- Rewrote Phase 4 specs for memvid integration:
  - search-engine: memvid .mv2 backend, hybrid search (lex+vec+reranker), adaptive retrieval, timeline
  - doc-fetcher: dual storage (raw .md files + .mv2 ingestion), sitemap support added
  - orchestrator-integration: rlm_research compound tool, Context7 routing, agent prompt templates
- Updated manifest and findings with memvid decision reversal

### Phase 4, Sprint 1: Doc Fetcher + Memvid Knowledge Engine (parallel)
- **Status:** completed
- **Started:** 2026-02-13
- **Completed:** 2026-02-13
- **Tests:** 174/174 passed (97 new: 47 knowledge + 50 fetcher)
- **Commit:** 0158cc0
- **Correction:** Spec called for fastembed-python (BGE-small) but built-in fastembed is broken on all wheels. Used memvid-sdk's get_embedder("huggingface", model="all-MiniLM-L6-v2") instead.
- Actions taken:
  - Implemented KnowledgeStore (mcp_server/knowledge.py) — memvid .mv2 wrapper, hybrid search, adaptive retrieval, timeline, entity extraction
  - Implemented doc-fetcher (mcp_server/fetcher.py) — URL fetching with .md variant detection, sitemap parsing, dual storage (raw + .mv2), freshness tracking
  - Wired both into server.py lifespan (KnowledgeStore on AppContext, register_knowledge_tools + register_fetcher_tools)
  - 6 new MCP tools: rlm_search, rlm_ask, rlm_timeline, rlm_ingest, rlm_fetch, rlm_load_dir, rlm_fetch_sitemap
- Files created/modified:
  - mcp_server/knowledge.py (created, 367 lines)
  - mcp_server/fetcher.py (created, 470 lines)
  - mcp_server/server.py (modified — imports, AppContext.knowledge_store, lifespan wiring)
  - mcp_server/requirements.txt (added html2text)
  - tests/test_knowledge.py (created, 771 lines, 47 tests)
  - tests/test_fetcher.py (created, 649 lines, 50 tests)

### Phase 4, Sprint 2: Orchestrator Integration
- **Status:** draft (blocked by Phase 4, Sprint 1)
- **Started:** --
- Actions taken:
  - Rewrote orchestrator-integration-spec.md (rlm_research, knowledge_status, agent prompts)
- Files created/modified:
  - docs/plans/specs/orchestrator-integration-spec.md (rewritten)

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Phases 0-3 complete. Phase 4 specs rewritten for memvid. Ready to implement |
| Where am I going? | 3 specs: search-engine + doc-fetcher (parallel), then orchestrator-integration |
| What's the goal? | Memvid knowledge store: fetch docs into .mv2, hybrid search, zero context cost |
| What have I learned? | memvid v2 has local fastembed (BGE-small), Ollama embeddings, hybrid search, adaptive retrieval. Spike's issues were likely a broken wheel |
| What have I done? | Core sandbox (77 tests) + search spike complete. Reversed to memvid, rewrote all Phase 4 specs |
