---
name: thread-support
phase: 6
sprint: 1
parent: null
depends_on: []
status: draft
created: 2026-02-17
---

# Thread/Namespace Support in Knowledge Store

## Overview

Add optional thread filtering to the knowledge store so documents can be organized by topic, session type, or workflow. Thread is a metadata convention — no schema change needed.

## Requirements

- [ ] REQ-1: `ingest()` and `ingest_many()` accept optional `thread` param, stored in metadata
- [ ] REQ-2: `search()` post-filters results by thread when specified
- [ ] REQ-3: MCP tools `rlm_search`, `rlm_ingest`, `rlm_ask` expose thread param
- [ ] REQ-4: Old documents without thread field still match when no filter is applied

## Acceptance Criteria

- [ ] AC-1: `ingest(title="x", text="y", thread="sessions")` stores thread in metadata
- [ ] AC-2: `search("query", thread="sessions")` returns only session-labeled docs
- [ ] AC-3: `search("query")` with no thread returns all docs (backward compat)
- [ ] AC-4: Existing tests still pass

## Technical Approach

Thread stored as `metadata["thread"]` on each document. Search post-filters hits after memvid returns results (memvid has no native pre-filter). Filter is simple string equality on `hit["metadata"].get("thread")`.

## Files

| File | Action | Purpose |
|------|--------|---------|
| mcp_server/knowledge.py | modify | Add thread param to ingest/search/ask, post-filter logic |
| tests/test_knowledge.py | modify | Add thread filter tests |

## Tasks

1. Add `thread` parameter to `ingest()` and `ingest_many()`
2. Add thread post-filtering to `search()` and `ask()`
3. Update MCP tool registrations with thread parameter
4. Add tests for thread filtering

## Dependencies

- **Needs from:** nothing
- **Provides to session-capture:** thread parameter for labeling session documents
