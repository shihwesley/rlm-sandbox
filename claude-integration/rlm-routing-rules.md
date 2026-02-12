# RLM Sandbox Routing Rules

When the `rlm` MCP server is available, follow these rules to decide when to use it vs. built-in tools.

## File Loading

- Files **over 200 lines**: use `rlm_load` to bring the file into the sandbox as a variable, then process it there. This keeps large content out of the context window.
- Files under 200 lines: use `Read` as usual.

## Code Execution

- **Multi-file analysis** (comparing files, aggregating data across sources): use `rlm_exec` to run Python in the sandbox. Store intermediate results as sandbox variables rather than printing everything back.
- **Large data processing** (CSV parsing, JSON transformation, text manipulation over big inputs): always use the sandbox. Do not attempt inline code blocks for anything over a few hundred lines of data.
- **Quick one-liners** (simple calculations, string formatting): either inline or sandbox is fine.

## Sub-Agent Tasks

- Use `rlm_sub_agent` when the task benefits from DSPy optimization — multi-step reasoning, structured extraction, or tasks that improve with few-shot examples.
- Provide a clear `signature` string (e.g., `"question -> answer"`) and matching `inputs` dict.

## Variable Management

- After running computations, store meaningful results in named sandbox variables.
- Retrieve results with `rlm_get` — use the `query` parameter to run expressions against stored data without pulling everything back.
- Use `rlm_vars` to check what's currently in the sandbox before running new code.

## When NOT to Use the Sandbox

- Reading small config files or source code for understanding — use `Read`.
- Simple file edits — use `Edit`.
- Git operations — use `Bash`.
- The sandbox is for computation, not for replacing standard file operations.
