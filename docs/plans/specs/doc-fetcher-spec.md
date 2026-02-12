---
name: doc-fetcher
phase: 4
sprint: 1
parent: null
depends_on: [search-spike]
status: draft
created: 2026-02-12
---

# Document Fetcher

## Overview
Fetching layer that pulls documentation from web URLs, local files, and Context7 into the knowledge store. Handles blocked sites, prefers .md sources, tracks freshness metadata, and supports bulk ingestion of codebase docs.

## Requirements
- [ ] REQ-1: rlm_fetch(url, var_name) MCP tool — fetch URL content, convert to markdown, store in knowledge store
- [ ] REQ-2: Smart URL resolution — try .md variant first, fall back to HTML→markdown conversion
- [ ] REQ-3: rlm_load_dir(glob_pattern) MCP tool — bulk-load local .tech.md / cached docs
- [ ] REQ-4: Source metadata tracking — URL, fetch date, content hash, file size per document
- [ ] REQ-5: Cache freshness — skip re-fetch if content exists and is <7 days old, force refresh option
- [ ] REQ-6: Graceful degradation for blocked/unreachable sites — return clear error, suggest user paste

## Acceptance Criteria
- [ ] AC-1: rlm_fetch("https://docs.example.com/api") stores markdown content, returns confirmation (not the content itself)
- [ ] AC-2: For a URL with .md variant available, fetcher uses .md version (smaller, cleaner)
- [ ] AC-3: rlm_load_dir("**/*.tech.md") loads 20+ files in one call, returns count and total size
- [ ] AC-4: Re-fetching a cached URL within 7 days returns "already cached" without re-downloading
- [ ] AC-5: Fetching a blocked URL returns "fetch failed — paste content manually" within 5 seconds
- [ ] AC-6: All stored docs have source attribution metadata (URL or file path, fetch timestamp)

## Technical Approach
The fetcher is a host-side module in `mcp_server/` — it needs network access (container has none).

URL resolution strategy:
1. If URL ends in known doc path, try appending `.md` (e.g., `/docs/api` → `/docs/api.md`)
2. Fetch with standard HTTP headers (not browser-impersonating)
3. If HTML, convert to markdown via markdownify or html2text
4. If fetch fails (403, timeout, connection refused), return error immediately (one attempt only)

Bulk local loading:
- Glob pattern resolved against the project root
- Each file read as markdown, stored with its relative path as the key
- .tech.md files from .chronicler/ are first-class citizens

Metadata stored alongside content:
```python
{"url": "...", "fetched_at": "...", "content_hash": "sha256:...", "size_bytes": N}
```

## Files
| File | Action | Purpose |
|------|--------|---------|
| mcp_server/fetcher.py | create | URL fetching, .md detection, HTML→markdown, freshness tracking |
| mcp_server/tools.py | modify | Register rlm_fetch and rlm_load_dir tools |
| tests/test_fetcher.py | create | Tests for URL resolution, blocked site handling, bulk loading, freshness |

## Tasks
1. Implement URL fetching with .md variant detection and HTML→markdown fallback
2. Implement bulk local file loading with glob patterns
3. Add source metadata tracking and freshness checking
4. Register rlm_fetch and rlm_load_dir as MCP tools
5. Write tests for all fetching scenarios (success, .md fallback, blocked, cached, bulk)

## Dependencies
- **Needs from search-spike:** hosting decision (determines where fetched content is stored)
- **Provides to search-engine:** raw document content with metadata for indexing
- **Provides to orchestrator-integration:** rlm_fetch and rlm_load_dir tools for automated research

## Resolved Questions
- Fetcher runs host-side (needs network, container has none)
- One fetch attempt only — no retries, no workarounds for blocked sites
- HTML→markdown via html2text (lighter than markdownify, already common in Python)
