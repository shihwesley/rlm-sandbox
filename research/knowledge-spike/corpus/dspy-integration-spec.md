---
name: dspy-integration
phase: 1
sprint: 2
parent: docker-sandbox
depends_on: [docker-sandbox]
status: draft
created: 2026-02-11
---

# DSPy RLM Integration

## Overview
Wraps DSPy's RLM pattern on the **host-side MCP server** so sub-agents can execute via sub_lm() calls without putting API keys in the container. The SandboxInterpreter routes code execution to the container's IPython kernel via HTTP, while LLM calls happen host-side using Claude Code's existing ANTHROPIC_API_KEY.

## Requirements
- [ ] REQ-1: SandboxInterpreter implementing DSPy's CodeInterpreter protocol (execute + __call__)
- [ ] REQ-2: SandboxInterpreter routes code to container's /exec endpoint via HTTP
- [ ] REQ-3: Sub-agent LM configured as Haiku 4.5 (claude-haiku-4-5-20251001), using host env ANTHROPIC_API_KEY
- [ ] REQ-4: Custom signature support — caller defines input/output fields
- [ ] REQ-5: Sub-agent results stored in sandbox variable space, not returned as raw text
- [ ] REQ-6: llm_query() callback stub injected into container namespace, routes to host endpoint
- [ ] REQ-7: Failure handling for rate limits, max_iterations exhausted, malformed signatures

## Acceptance Criteria
- [ ] AC-1: rlm.sub_agent MCP tool with a search signature returns structured results
- [ ] AC-2: Sub-agent results accessible via rlm.get after execution
- [ ] AC-3: Custom signatures with arbitrary output fields work correctly
- [ ] AC-4: Sub-agent uses Haiku 4.5 via host's ANTHROPIC_API_KEY (key never enters container)
- [ ] AC-5: max_iterations and max_llm_calls configurable per call
- [ ] AC-6: Rate limit errors return graceful error message, not crash
- [ ] AC-7: Malformed signature returns validation error

## Technical Approach
DSPy runs **host-side** in the MCP server process:
- `dspy.RLM(signature, sub_lm=sub_lm, interpreter=SandboxInterpreter(...))`
- SandboxInterpreter implements the CodeInterpreter protocol:
  - `execute(code, variables=None)` → HTTP POST to container's /exec
  - `__call__(code, variables=None)` → alias for execute()
  - Context manager support (__enter__/__exit__)
- Does NOT subclass PythonInterpreter (avoids Deno/Pyodide dependency)
- Sub-LM setup: `dspy.LM("anthropic/claude-haiku-4-5-20251001")` using host env
- llm_query callback: container has a stub function that POSTs to host's /llm_query endpoint

## Files
| File | Action | Purpose |
|------|--------|---------|
| mcp-server/sub_agent.py | create | DSPy RLM wrapper, SandboxInterpreter, sub_lm config |
| mcp-server/signatures.py | create | Custom signature builder (from rlmgrep's pattern) |
| mcp-server/tools.py | modify | Wire rlm.sub_agent tool to sub_agent.py |
| tests/test_sub_agent.py | create | Tests for sub-agent execution, variable storage, custom signatures, failures |

## Tasks
1. Implement SandboxInterpreter with CodeInterpreter protocol (execute → HTTP to /exec)
2. Implement sub_agent.py with DSPy RLM wrapper and Haiku 4.5 config (host-side)
3. Implement llm_query callback endpoint on host + stub injection into container
4. Port rlmgrep's custom signature builder (build_custom_signature)
5. Wire rlm.sub_agent MCP tool to sub_agent.py
6. Write tests for sub-agent execution, variable storage, custom signatures, failure modes

## Dependencies
- **Needs from docker-sandbox:** running container with /exec endpoint
- **Needs from mcp-server:** MCP server infrastructure, HTTP client to container
- **Provides to:** end user via rlm.sub_agent MCP tool

## Resolved Questions
- Interpreter: implement CodeInterpreter protocol directly (execute + __call__), NOT subclass PythonInterpreter
- API key: host-side via ANTHROPIC_API_KEY env var. Container never sees it.
- LLM callback: container gets injected `llm_query()` stub that POSTs to host
