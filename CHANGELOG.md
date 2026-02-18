# Changelog

## 1.2.0 - 2026-02-17

### Added
- Thread/namespace filtering on knowledge store — `thread` param on `rlm_search`, `rlm_ask`, `rlm_ingest`
- Deep reasoning DSPy signatures (`deep_reasoning`, `deep_reasoning_multi`) with 3-phase Recon/Filter/Aggregate strategy
- `llm_query_batch(prompts)` for concurrent sub-LLM calls from sandbox code (ThreadPoolExecutor, max 8 workers)
- Programmatic tool calling — sandbox code can call `search_knowledge()`, `ask_knowledge()`, `fetch_url()`, `load_file()`, `apple_search()` via `/tool_call` callback dispatch
- Session auto-capture script (`scripts/session_capture.py`) — JSONL transcript parser with tag stripping, message-boundary chunking, standalone memvid ingestion
- `rlm_usage` MCP tool — cumulative token stats, per-run diffs in sub-agent results, cost estimation (Haiku 4.5 pricing), reset support
- 350 tests (up from 209)

### Fixed
- `KnowledgeStore.ingest()` and `ingest_many()` now call `commit()` instead of `seal()` for incremental indexing

## 1.0.0 - 2026-02-13

### Added
- Plugin distribution structure (.claude-plugin, .mcp.json, agents, skills, hooks)
- Knowledge store: memvid-sdk backed hybrid search (.mv2 files)
  - `rlm_search`, `rlm_ask`, `rlm_timeline`, `rlm_ingest` tools
- Doc fetcher: URL fetching with .md variant detection, sitemap support, dual storage
  - `rlm_fetch`, `rlm_load_dir`, `rlm_fetch_sitemap` tools
- Research automation: compound research tool + knowledge management
  - `rlm_research`, `rlm_knowledge_status`, `rlm_knowledge_clear` tools
- Custom agents: `rlm-researcher` (doc research) and `rlm-sandbox` (code execution)
- Skills: `/rlm-sandbox:research` and `/rlm-sandbox:knowledge-status`
- Context7 routing hook (indexes Context7 fetches into knowledge store)
- Auto-setup script (venv + deps on first run)

### Core (from pre-plugin development)
- Docker sandbox with FastAPI + IPython kernel
- DSPy sub-agent support (host-side, Haiku 4.5)
- Session persistence via dill
- Three isolation tiers (process, Docker container, Docker Sandboxes)
- 209 tests
