---
name: programmatic-tools
phase: 6
sprint: 1
parent: null
depends_on: []
status: draft
created: 2026-02-17
---

# Programmatic Tool Calling (Multi-Tool Sandbox)

## Overview

Generalize the sandbox callback mechanism from a single `llm_query()` function to a multi-tool dispatcher. Any MCP tool marked as sandbox-callable gets an auto-generated stub injected into the container. Code in the sandbox can call knowledge search, doc fetch, Apple docs, etc. — processing results programmatically without those intermediates entering Claude Code's context window.

Inspired by Anthropic's programmatic tool calling API pattern (code_execution + allowed_callers). Our implementation is the "self-managed sandboxed execution" variant they describe.

## Requirements

- [ ] REQ-1: Callback server handles `POST /tool_call` with `tool_name` + `input` dispatch
- [ ] REQ-2: Tool registry marks which MCP tools are sandbox-callable
- [ ] REQ-3: Auto-generate Python stub functions from the registry and inject into sandbox
- [ ] REQ-4: Each stub POSTs to host callback, receives JSON result, returns to sandbox code
- [ ] REQ-5: Existing `llm_query()` remains as-is (backward compat)
- [ ] REQ-6: Only idempotent/read tools are sandbox-callable (not rlm_exec, rlm_reset)

## Acceptance Criteria

- [ ] AC-1: Sandbox code can call `search_knowledge("auth patterns")` and get search results
- [ ] AC-2: Sandbox code can call `fetch_url("https://...")` and get markdown content
- [ ] AC-3: `llm_query("prompt")` still works unchanged
- [ ] AC-4: Calling an unregistered tool name returns a clear error
- [ ] AC-5: Tools not marked sandbox-callable are not injectable

## Technical Approach

### A. Generalize callback server (`llm_callback.py`)

Add a second route: `POST /tool_call` alongside existing `POST /llm_query`.

```
POST /tool_call
Body: {"tool": "search_knowledge", "input": {"query": "auth", "top_k": 5}}
Response: {"result": "...formatted string..."}
```

Add a `_tool_handlers` dict mapping tool names to async callables. Each handler wraps the corresponding MCP tool function, stripping the `ctx` parameter (sandbox calls don't have MCP context).

Existing `/llm_query` stays untouched — it's a fast path that doesn't need the dispatch overhead.

### B. Tool registry and sandbox-callable marking

Add a `SANDBOX_TOOLS` dict in a new section of `llm_callback.py` (or a small `sandbox_tools.py` module). Each entry maps a sandbox function name to:
- The host-side handler function
- Input parameter schema (for validation)
- A description (injected as a docstring in the stub)

Initial sandbox-callable tools:
| Sandbox Function | MCP Tool | Why |
|---|---|---|
| `search_knowledge(query, top_k=10)` | `rlm_search` | Search indexed docs |
| `ask_knowledge(question)` | `rlm_ask` | RAG Q&A over knowledge store |
| `fetch_url(url)` | `rlm_fetch` | Fetch and convert a URL to markdown |
| `load_file(path, var_name)` | `rlm_load` | Load a host file into sandbox |
| `apple_search(query, framework)` | `rlm_apple_search` | Search Apple docs |

NOT sandbox-callable: `rlm_exec`, `rlm_reset`, `rlm_sub_agent`, `rlm_ingest`, `rlm_load_dir`, `rlm_fetch_sitemap`, `rlm_knowledge_clear`.

### C. Auto-generate and inject stubs (`sub_agent.py`)

New function `inject_tool_stubs(client, callback_url, tools)`:
- Iterates the SANDBOX_TOOLS registry
- For each tool, generates a Python function that:
  - Takes the declared parameters
  - POSTs to `{callback_url}` (reuses existing callback URL routing for Docker vs local)
  - Returns the parsed JSON result
- Injects via `POST /exec` to the sandbox

Called from `server.py` lifespan after `inject_llm_stub()` — same pattern, additive.

### D. Callback URL routing

The callback server already has `callback_url` (Docker) and `callback_url_local` (bare process). The new `/tool_call` endpoint uses the same host:port, just a different path. Stubs POST to `http://host.docker.internal:8081/tool_call` (Docker) or `http://127.0.0.1:8081/tool_call` (local).

## Files

| File | Action | Purpose |
|------|--------|---------|
| mcp_server/llm_callback.py | modify | Add /tool_call route, _tool_handlers registry |
| mcp_server/sub_agent.py | modify | Add inject_tool_stubs() function |
| mcp_server/server.py | modify | Call inject_tool_stubs() in lifespan after llm_stub |
| tests/test_llm_callback.py | modify | Test /tool_call dispatch and error handling |
| tests/test_sub_agent.py | modify | Test stub injection for registered tools |

## Tasks

1. Add SANDBOX_TOOLS registry with initial 5 tools
2. Add /tool_call route to LLMCallbackServer with dispatch logic
3. Add handler wrappers for each sandbox-callable tool
4. Implement inject_tool_stubs() in sub_agent.py
5. Wire inject_tool_stubs() into server.py lifespan
6. Add tests for dispatch, stub injection, error on unknown tool

## Dependencies

- **Needs from:** nothing (uses existing MCP tool functions directly)
- **Provides to:** no downstream specs. Complements parallel-llm (batch + multi-tool = powerful combo)

## Open Questions

- Should sandbox-callable tools support async batch calls too (like llm_query_batch)? Defer to a follow-up if needed.
