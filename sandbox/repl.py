"""IPython kernel manager for the sandbox container."""

import io
import json
import contextlib
import threading
from IPython.core.interactiveshell import InteractiveShell


class Kernel:
    def __init__(self):
        self.shell = InteractiveShell.instance()

    def execute(self, code: str, timeout: int = 30) -> dict:
        """Run code in IPython, capture stdout/stderr, return results."""
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        result_container = [None]
        error_container = [None]

        def _run():
            try:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    result_container[0] = self.shell.run_cell(code, store_history=False)
            except Exception as e:
                error_container[0] = e

        thread = threading.Thread(target=_run)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            # Timeout — thread is stuck; we can't forcibly kill it,
            # but we report the timeout and move on.
            return {
                "output": stdout_buf.getvalue(),
                "stderr": f"Execution timed out after {timeout}s",
                "vars": [],
            }

        if error_container[0] is not None:
            return {
                "output": stdout_buf.getvalue(),
                "stderr": f"{type(error_container[0]).__name__}: {error_container[0]}",
                "vars": [],
            }

        result = result_container[0]
        output = stdout_buf.getvalue()

        # If the cell produced a result value (e.g. an expression), append its repr
        if result is not None and result.result is not None:
            output += repr(result.result)

        # Collect stderr — IPython may route tracebacks there
        stderr = stderr_buf.getvalue()
        if result is not None and not result.success and result.error_in_exec:
            exc = result.error_in_exec
            stderr += f"{type(exc).__name__}: {exc}"

        var_names = [k for k in self.shell.user_ns if not k.startswith("_") and k not in self.shell.user_ns_hidden]

        return {"output": output, "stderr": stderr, "vars": var_names}

    def get_vars(self) -> list[dict]:
        """Return metadata about all user-defined variables."""
        result = []
        for k, v in self.shell.user_ns.items():
            if k.startswith("_") or k in self.shell.user_ns_hidden:
                continue
            s = repr(v)
            if len(s) > 100:
                s = s[:97] + "..."
            result.append({"name": k, "type": type(v).__name__, "summary": s})
        return result

    def get_var(self, name: str) -> dict:
        """Return a single variable's value, JSON-safe when possible."""
        if name not in self.shell.user_ns or name in self.shell.user_ns_hidden:
            return {"error": "not found"}
        v = self.shell.user_ns[name]
        try:
            json.dumps(v)
            return {"value": v}
        except (TypeError, ValueError):
            return {"value": repr(v)}

    def reset(self):
        """Clear all state."""
        self.shell.reset(new_session=True)
