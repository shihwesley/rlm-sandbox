---
name: deep-reasoning
phase: 6
sprint: 1
parent: null
depends_on: []
status: draft
created: 2026-02-17
---

# Deep Reasoning Signature

## Overview

Add pre-built DSPy signatures encoding a 3-phase reasoning strategy (Recon, Filter, Aggregate) adapted from Monolith's prompt engineering. Gives sub-agents explicit instructions for large-context tasks.

## Requirements

- [ ] REQ-1: Add DEEP_REASONING_SIGNATURE with phased instructions
- [ ] REQ-2: Add DEEP_REASONING_MULTI_SIGNATURE for multi-document contexts
- [ ] REQ-3: Add name-lookup map so rlm_sub_agent can accept names like "deep_reasoning"
- [ ] REQ-4: Existing string/class signatures still work unchanged

## Acceptance Criteria

- [ ] AC-1: `validate_signature("deep_reasoning")` returns True via name lookup
- [ ] AC-2: Signature instructions contain Recon/Filter/Aggregate phases
- [ ] AC-3: `run_sub_agent(signature="deep_reasoning", ...)` resolves and runs
- [ ] AC-4: Existing SEARCH/EXTRACT/CLASSIFY/SUMMARIZE signatures unaffected

## Technical Approach

Use `build_custom_signature()` to create signatures with rich instruction docstrings. Add `NAMED_SIGNATURES` dict mapping short names to signature objects. Update `validate_signature()` to check name map before string/class validation. Update `run_sub_agent()` to resolve names.

The 3-phase instructions:
- Phase 1 (Recon): Read context, check size, identify format and chunk boundaries
- Phase 2 (Filter): Split along boundaries, regex/keyword filter, call llm_query() on each relevant chunk
- Phase 3 (Aggregate): Synthesize sub-LLM results into final answer via llm_query()

Principle from Monolith: "Code filters, sub-LLMs reason." Deterministic Python narrows the search space, sub-LLMs handle semantic understanding.

## Files

| File | Action | Purpose |
|------|--------|---------|
| mcp_server/signatures.py | modify | Add signatures, name map, update validation |
| mcp_server/sub_agent.py | modify | Resolve signature names in run_sub_agent() |
| tests/test_sub_agent.py | modify | Add tests for named signature resolution |

## Tasks

1. Create DEEP_REASONING_SIGNATURE with 3-phase instructions
2. Create DEEP_REASONING_MULTI_SIGNATURE for multi-doc variant
3. Add NAMED_SIGNATURES lookup dict and update validate_signature()
4. Update run_sub_agent() to resolve names from the map
5. Add tests

## Dependencies

- **Needs from:** nothing
- **Provides to:** no downstream specs (standalone)
