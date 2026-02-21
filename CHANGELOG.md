# Changelog

## 2.1.0 - 2026-02-20

### Added
- **Apple docs domain stores** — split the monolithic apple-docs.mv2 into 15 domain-specific stores (spatial-computing, swiftui, ml-ai, foundation-core, networking, etc.). Each store stays under the memvid size limit and scopes search results to a single domain.
- `scripts/apple_domain_ingest.py` — batch ingestion script that splits 300+ Apple framework docs into domain stores
- `scripts/apple_bulk_ingest.py` — single-store bulk ingestion (for smaller domain sets)
- `mcp_server/apple_extract.py` — Apple docs extraction utilities
- `skills/apple-research/SKILL.md` — Apple API research skill
- **Coupling assessment** in research pipeline (Step 1b.5) — zero-cost structural check on the question tree that flags domains with high internal coupling. Recommends skill graph creation when sub-topics form a web rather than a list.
- **Skill graph gate** (Step 5b.5) — after artifact generation, suggests `/create-skill-graph` for high-coupling domains. Records recommendation in `sources.json`.
- Coupling score in research report output

### Changed
- `apple_docs.py` — expanded with domain-aware extraction and chunking
- Research report now includes coupling score (N/5) and graph recommendation

## 2.0.0 - 2026-02-18

### Changed — Research Pipeline Redesign
- Replaced 4 overlapping agents (neo-researcher, neo-research, research-sandbox, research-specialist) with single unified `research-agent` that runs the full pipeline
- New 5-phase pipeline: input parsing → question tree → source discovery → acquisition → distillation → expertise artifact
- Centralized storage at `~/.claude/research/<topic>/` — no scattered knowledge across projects
- Rewritten `/research` skill as thin orchestrator that spawns the research agent

### Added
- **Question tree methodology** — structured research design before searching, not blind Google queries. Each branch maps to source types and quality tiers.
- **Distillation phase** ("Matrix download") — systematic .mv2 querying per question tree branch, producing a 3-5K token expertise artifact. Agent becomes domain expert without reading raw content.
- **Expertise artifact format** — mental model, architecture, key APIs, common patterns, gotchas, quick reference. Compact enough to load in context.
- **Flexible input** — handles topic strings, rich paragraphs with context, seed URLs, or any combination
- **Resumption** — pipeline checks for existing artifacts and picks up where it left off
- `/research load <topic>` — reload existing expertise without re-fetching

### Removed
- `agents/research-sandbox.md` — absorbed into research-agent
- `agents/research-specialist.md` — absorbed into research-agent

## 1.3.0 - 2026-02-18

### Added
- research-sandbox and research-specialist agents (superseded by 2.0.0)

### Fixed
- `KnowledgeStore.open()` now passes `enable_vec=True, enable_lex=True` to `memvid_sdk.use()` so hybrid search works on reopened stores, not just newly created ones

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
- Custom agents: `neo-researcher` (doc research) and `neo-research` (code execution)
- Skills: `/neo-research:research` and `/neo-research:knowledge-status`
- Context7 routing hook (indexes Context7 fetches into knowledge store)
- Auto-setup script (venv + deps on first run)

### Core (from pre-plugin development)
- Docker sandbox with FastAPI + IPython kernel
- DSPy sub-agent support (host-side, Haiku 4.5)
- Session persistence via dill
- Three isolation tiers (process, Docker container, Docker Sandboxes)
- 209 tests
