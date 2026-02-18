---
name: parallel-llm
phase: 6
sprint: 1
parent: null
depends_on: []
status: draft
created: 2026-02-17
---

# Parallel Sub-LLM Calls

## Overview

Add `llm_query_batch(prompts)` to the sandbox stub so code in the container can fire multiple sub-LLM calls concurrently. Uses ThreadPoolExecutor (stdlib) — no new container dependencies.

## Requirements

- [ ] REQ-1: Inject `llm_query_batch(prompts)` alongside existing `llm_query(prompt)`
- [ ] REQ-2: Uses concurrent.futures.ThreadPoolExecutor, max 8 workers
- [ ] REQ-3: Returns results in input order
- [ ] REQ-4: Failed individual calls return error string instead of crashing batch
- [ ] REQ-5: Existing `llm_query()` unchanged

## Acceptance Criteria

- [ ] AC-1: Sandbox code can call `results = llm_query_batch(["p1", "p2", "p3"])`
- [ ] AC-2: Results list length matches prompts list length
- [ ] AC-3: One failed prompt doesn't prevent other results from returning
- [ ] AC-4: `llm_query("single prompt")` still works after batch injection

## Technical Approach

Extend `inject_llm_stub()` in `sub_agent.py` to inject a second function alongside `llm_query`. The batch function:
1. Creates `ThreadPoolExecutor(max_workers=min(len(prompts), 8))`
2. Submits each prompt via `executor.map()` wrapping `llm_query`
3. Wraps each call in try/except, replacing failures with `"[error] {message}"`
4. Returns list of results in input order

Callback server handles concurrent connections already (asyncio). No changes needed there.

## Files

| File | Action | Purpose |
|------|--------|---------|
| mcp_server/sub_agent.py | modify | Extend inject_llm_stub() with batch function |
| tests/test_sub_agent.py | modify | Add batch injection test |

## Tasks

1. Write the `llm_query_batch` stub code string
2. Append to `inject_llm_stub()`
3. Add test verifying batch stub gets injected
4. Add test verifying error handling per-slot

## Dependencies

- **Needs from:** nothing
- **Provides to token-tracking:** callback server changes must not conflict
