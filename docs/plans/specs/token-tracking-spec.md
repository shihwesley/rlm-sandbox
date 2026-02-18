---
name: token-tracking
phase: 6
sprint: 2
parent: null
depends_on: [parallel-llm]
status: draft
created: 2026-02-17
---

# Token Usage Tracking

## Overview

Instrument LLM calls to track token usage. Surface per-run stats in sub-agent results and cumulative session stats via a new rlm_usage MCP tool.

## Requirements

- [ ] REQ-1: LLMCallbackServer accumulates input/output tokens per call
- [ ] REQ-2: Sub-agent results include usage dict (input_tokens, output_tokens, llm_calls)
- [ ] REQ-3: New rlm_usage MCP tool returns cumulative session stats
- [ ] REQ-4: Usage can be reset via rlm_usage(reset=True)
- [ ] REQ-5: Cost estimation for known models (Haiku 4.5 pricing)

## Acceptance Criteria

- [ ] AC-1: After a sub-agent run, result["usage"] contains token counts
- [ ] AC-2: rlm_usage() returns cumulative stats across all calls in session
- [ ] AC-3: rlm_usage(reset=True) zeroes the counters
- [ ] AC-4: Cost estimate present in output
- [ ] AC-5: Existing sub-agent behavior unchanged (usage is additive, not breaking)

## Technical Approach

**A. LLMCallbackServer accumulator (`llm_callback.py`):**
Add `_usage` dict: `{total_input_tokens, total_output_tokens, total_calls, calls_by_model}`. After each `_query_lm()`, inspect `self.sub_lm.history[-1]` for token usage. Add `get_usage()` and `reset_usage()` methods.

**B. Per-run stats in `run_sub_agent()` (`sub_agent.py`):**
Accept optional `callback_server` param. Snapshot usage before run, diff after. Add `"usage"` key to return dict. MCP tool in tools.py passes `ctx.app.callback_server`.

**C. rlm_usage MCP tool (`tools.py`):**
Reads `ctx.app.callback_server.get_usage()`. Formats with call count, tokens, estimated cost. Pricing table: `{model: ($/1M_input, $/1M_output)}` for known models.

## Files

| File | Action | Purpose |
|------|--------|---------|
| mcp_server/llm_callback.py | modify | Add _usage accumulator, get_usage(), reset_usage() |
| mcp_server/sub_agent.py | modify | Accept callback_server param, add usage to result |
| mcp_server/tools.py | modify | Pass callback_server to run_sub_agent, add rlm_usage tool |
| tests/test_llm_callback.py | modify | Test accumulation and reset |
| tests/test_sub_agent.py | modify | Test usage in result dict |

## Tasks

1. Add _usage dict and accumulation logic to LLMCallbackServer
2. Add get_usage() and reset_usage() methods
3. Update run_sub_agent() to accept callback_server and return usage
4. Update rlm_sub_agent MCP tool to pass callback_server from AppContext
5. Add rlm_usage MCP tool with cost estimation
6. Add tests

## Dependencies

- **Needs from parallel-llm:** callback server changes done first to avoid conflicts
- **Provides to:** no downstream specs
