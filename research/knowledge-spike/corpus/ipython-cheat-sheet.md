# IPython InteractiveShell Cheat Sheet

## Create persistent shell instance
```python
from IPython.core.interactiveshell import InteractiveShell

shell = InteractiveShell.instance()
```

## Execute code
```python
result = shell.run_cell(
    raw_cell="x = 42\nprint(x)",
    store_history=False,  # False for programmatic use
    silent=False,          # True suppresses output
)
```

## ExecutionResult
```python
result.success        # bool - True if no error
result.error_before_exec  # SyntaxError etc.
result.error_in_exec      # Runtime error
result.result         # repr of last expression (if any)
result.raise_error()  # re-raise if success is False
```

## Capture stdout/stderr
```python
import io
from contextlib import redirect_stdout, redirect_stderr

stdout_buf = io.StringIO()
stderr_buf = io.StringIO()

with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
    result = shell.run_cell(code, store_history=False)

output = stdout_buf.getvalue()
errors = stderr_buf.getvalue()
```

## Inspect namespace variables
```python
# All user-defined variables
user_ns = shell.user_ns
# Filter out builtins/internals
user_vars = {k: v for k, v in user_ns.items()
             if not k.startswith("_") and k not in shell.user_ns_hidden}
```

## Reset kernel state
```python
shell.reset(new_session=True)
```

## Key points
- Single `InteractiveShell.instance()` persists state across calls
- Variables live in `shell.user_ns` dict
- `run_cell` handles both expressions and statements
- Use `store_history=False` when embedding
- `silent=True` suppresses all output display
