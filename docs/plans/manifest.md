---
project: rlm-sandbox
created: 2026-02-11
updated: 2026-02-12
mode: spec-driven
priority: quality
---

# Plan Manifest

## Dependency Graph

```mermaid
graph TD
    R[sandbox-research] --> A[docker-sandbox]
    A --> B[dspy-integration]
    A --> C[mcp-server]
    B -.->|wires into| C
    C --> D[claude-integration]
    A --> E[session-persistence]
    C --> E

    SS[search-spike] --> DF[doc-fetcher]
    SS --> SE[search-engine]
    DF --> OI[orchestrator-integration]
    SE --> OI
```

## Phase / Sprint / Spec Map

| Phase | Sprint | Spec | Status | Depends On |
|-------|--------|------|--------|------------|
| 0 | 1 | sandbox-research | completed | -- |
| 1 | 1 | docker-sandbox | completed | sandbox-research |
| 1 | 2 | dspy-integration | completed | docker-sandbox |
| 1 | 2 | mcp-server | completed | docker-sandbox |
| 2 | 1 | session-persistence | completed | docker-sandbox, mcp-server |
| 2 | 1 | claude-integration | completed | mcp-server |
| 3 | 1 | search-spike | draft | -- |
| 4 | 1 | doc-fetcher | draft | search-spike |
| 4 | 1 | search-engine | draft | search-spike |
| 4 | 2 | orchestrator-integration | draft | doc-fetcher, search-engine |

## Spec Files

| Spec | Path | Lines | Description |
|------|------|-------|-------------|
| sandbox-research | docs/plans/specs/sandbox-research-spec.md | ~80 | Evaluate srt-only, hybrid, Docker Sandboxes paths |
| docker-sandbox | docs/plans/specs/docker-sandbox-spec.md | ~60 | Dockerfile, FastAPI server, IPython kernel |
| dspy-integration | docs/plans/specs/dspy-integration-spec.md | ~55 | DSPy RLM wrapper, sub_agent, Haiku 4.5 |
| mcp-server | docs/plans/specs/mcp-server-spec.md | ~60 | Host-side MCP, Docker lifecycle, stdio |
| session-persistence | docs/plans/specs/session-persistence-spec.md | ~45 | Save/restore sandbox state via dill |
| claude-integration | docs/plans/specs/claude-integration-spec.md | ~40 | mcp-config.json, CLAUDE.md rules |
| search-spike | docs/plans/specs/search-spike-spec.md | ~70 | Evaluate memvid-sdk vs FAISS+ONNX, host vs container |
| doc-fetcher | docs/plans/specs/doc-fetcher-spec.md | ~70 | URL fetching, .md detection, bulk local loading, freshness |
| search-engine | docs/plans/specs/search-engine-spec.md | ~80 | Semantic search, chunking, embedding, indexing, rlm_search |
| orchestrator-integration | docs/plans/specs/orchestrator-integration-spec.md | ~65 | Wire into /orchestrate Stage 4 and /interactive-planning |

## Findings
-> See findings.md

## Progress
-> See progress.md
