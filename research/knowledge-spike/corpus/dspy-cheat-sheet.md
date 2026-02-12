# DSPy RLM Cheat Sheet

## Installation
```bash
pip install dspy
```

## LM Configuration
```python
import dspy
lm = dspy.LM("anthropic/claude-haiku-4-5-20251001")
dspy.configure(lm=main_lm)
# or pass as sub_lm to RLM
```

## RLM Constructor
```python
dspy.RLM(
    signature,              # str or Signature class: "context, query -> answer"
    max_iterations=20,      # max REPL interaction loops
    max_llm_calls=50,       # max sub-LM calls per execution
    max_output_chars=10000, # truncate REPL output
    verbose=False,
    tools=None,             # list[Callable] accessible in sandbox
    sub_lm=None,            # separate LM for llm_query(); defaults to main LM
    interpreter=None,       # CodeInterpreter impl; defaults to PythonInterpreter (Deno/Pyodide)
)
```

## CodeInterpreter Protocol
The interface RLM expects from `interpreter=`. Default is PythonInterpreter (needs Deno).
Custom implementations must provide:
```python
class SandboxInterpreter:
    def execute(self, code: str, variables: dict | None = None) -> str:
        """Run code, return stdout/output as string."""
        ...

    def __call__(self, code: str, variables: dict | None = None) -> str:
        """Alias for execute()."""
        return self.execute(code, variables)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        ...
```

## Built-in REPL Tools (available inside the sandbox)
- `llm_query(prompt)` — query sub_lm for semantic extraction
- `llm_query_batched(prompts)` — concurrent multi-prompt queries
- `print()` — emit output visible to the LM
- `SUBMIT(output)` — terminate and return final answer

## Custom Signatures
```python
class SearchResult(dspy.Signature):
    """Extract search results from code output."""
    query: str = dspy.InputField()
    code_context: str = dspy.InputField()
    results: list[str] = dspy.OutputField()
```

String shorthand: `"query, code_context -> results: list[str]"`

## Usage
```python
rlm = dspy.RLM(
    "document, question -> answer",
    sub_lm=dspy.LM("anthropic/claude-haiku-4-5-20251001"),
    interpreter=my_interpreter,
    max_iterations=10,
)
result = rlm(document="...", question="...")
print(result.answer)
print(result.trajectory)  # step-by-step trace
```

## Key Points
- Not thread-safe with custom interpreters — one instance per concurrent use
- forward() is sync, aforward() is async
- llm_query() callback: container needs a stub that POSTs to host endpoint
- sub_lm defaults to the globally configured LM if not set
