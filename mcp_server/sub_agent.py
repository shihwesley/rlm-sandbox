"""DSPy RLM wrapper with SandboxInterpreter for container-based code execution."""

from __future__ import annotations

import logging
from typing import Any

import dspy
import httpx

log = logging.getLogger(__name__)

# Default sub-LM — Haiku 4.5, uses host's ANTHROPIC_API_KEY
DEFAULT_SUB_LM = "anthropic/claude-haiku-4-5-20251001"


# -- SandboxInterpreter --


class SandboxInterpreter:
    """CodeInterpreter that routes code to the sandbox container's /exec endpoint."""

    def __init__(self, base_url: str = "http://localhost:8080", timeout: float = 60):
        self.base_url = base_url
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def execute(self, code: str, variables: dict[str, Any] | None = None) -> str:
        """Run code in sandbox via HTTP POST to /exec. Return stdout output."""
        client = self._ensure_client()

        # Inject variables into the sandbox namespace before running the code
        if variables:
            inject_lines = []
            for name, value in variables.items():
                inject_lines.append(f"{name} = {value!r}")
            inject_code = "\n".join(inject_lines)
            await self._post_exec(client, inject_code)

        return await self._post_exec(client, code)

    async def _post_exec(self, client: httpx.AsyncClient, code: str) -> str:
        """POST code to /exec and return the output string."""
        resp = await client.post("/exec", json={"code": code})
        resp.raise_for_status()
        data = resp.json()

        # Combine stdout and stderr for DSPy to see errors
        output = data.get("output", "")
        stderr = data.get("stderr", "")
        if stderr:
            output = f"{output}\n[stderr] {stderr}" if output else f"[stderr] {stderr}"
        return output

    async def __call__(self, code: str, variables: dict[str, Any] | None = None) -> str:
        return await self.execute(code, variables)

    async def __aenter__(self) -> SandboxInterpreter:
        self._client = httpx.AsyncClient(
            base_url=self.base_url, timeout=self.timeout
        )
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError(
                "SandboxInterpreter must be used as an async context manager"
            )
        return self._client


# -- llm_query injection --


async def inject_llm_stub(client: httpx.AsyncClient, callback_url: str) -> None:
    """Inject llm_query() and llm_query_batch() stubs into container that POST to host.

    Uses urllib.request (stdlib, always available) to call back to the
    host-side callback endpoint. API keys never enter the container.
    """
    stub_code = (
        "import urllib.request as _llm_urllib\n"
        "import json as _llm_json\n"
        "import concurrent.futures as _llm_futures\n"
        "def llm_query(prompt):\n"
        "    _data = _llm_json.dumps({'prompt': prompt}).encode()\n"
        "    _req = _llm_urllib.Request(\n"
        f'        "{callback_url}",\n'
        "        data=_data,\n"
        "        headers={'Content-Type': 'application/json'},\n"
        "        method='POST',\n"
        "    )\n"
        "    with _llm_urllib.urlopen(_req, timeout=120) as _resp:\n"
        "        return _llm_json.loads(_resp.read())['result']\n"
        "def llm_query_batch(prompts):\n"
        "    def _safe_query(p):\n"
        "        try:\n"
        "            return llm_query(p)\n"
        "        except Exception as _e:\n"
        "            return '[error] ' + str(_e)\n"
        "    _workers = min(len(prompts), 8)\n"
        "    if _workers == 0:\n"
        "        return []\n"
        "    with _llm_futures.ThreadPoolExecutor(max_workers=_workers) as _pool:\n"
        "        return list(_pool.map(_safe_query, prompts))\n"
    )
    resp = await client.post("/exec", json={"code": stub_code})
    resp.raise_for_status()


async def inject_tool_stubs(
    client: httpx.AsyncClient,
    callback_base_url: str,
    tools: dict[str, str],
) -> None:
    """Inject sandbox stub functions for each tool in the registry.

    Each stub POSTs to {callback_base_url}/tool_call with tool_name + input,
    then returns the JSON result. Uses urllib.request (stdlib) so no extra
    packages are needed inside the container.

    Args:
        client: httpx client pointed at the sandbox /exec endpoint
        callback_base_url: Base URL of the host callback server (no trailing /)
        tools: Mapping of sandbox function name -> MCP tool name (from SANDBOX_TOOLS)
    """
    tool_call_url = f"{callback_base_url}/tool_call"

    # Build one stub per tool and emit them in a single /exec call
    stub_lines: list[str] = [
        "import urllib.request as _tc_urllib",
        "import json as _tc_json",
        "",
        "def _tool_call(tool_name, **kwargs):",
        "    _data = _tc_json.dumps({'tool_name': tool_name, 'input': kwargs}).encode()",
        "    _req = _tc_urllib.Request(",
        f'        "{tool_call_url}",',
        "        data=_data,",
        "        headers={'Content-Type': 'application/json'},",
        "        method='POST',",
        "    )",
        "    with _tc_urllib.urlopen(_req, timeout=60) as _resp:",
        "        return _tc_json.loads(_resp.read())['result']",
        "",
    ]

    # Per-tool wrapper with named parameters
    _TOOL_SIGNATURES: dict[str, str] = {
        "search_knowledge": "query, top_k=10",
        "ask_knowledge": "question",
        "fetch_url": "url",
        "load_file": "path, var_name",
        "apple_search": "query, framework=None",
    }

    for func_name in tools:
        sig = _TOOL_SIGNATURES.get(func_name, "**kwargs")
        # Build a forwarding call that maps positional/keyword args to the dict
        if sig == "**kwargs":
            call_args = "**kwargs"
        else:
            # Extract param names (strip defaults) for the call-through
            param_names = [p.split("=")[0].strip() for p in sig.split(",")]
            call_args = ", ".join(f"{p}={p}" for p in param_names)
        stub_lines += [
            f"def {func_name}({sig}):",
            f"    return _tool_call('{func_name}', {call_args})",
            "",
        ]

    stub_code = "\n".join(stub_lines)
    resp = await client.post("/exec", json={"code": stub_code})
    resp.raise_for_status()


async def handle_llm_query(prompt: str, sub_lm: dspy.LM) -> str:
    """Handle llm_query() calls from the container. Routes to host-side sub_lm."""
    try:
        response = sub_lm(prompt)
        # dspy.LM returns a list of completions; take the first
        if isinstance(response, list) and response:
            return response[0]
        return str(response)
    except Exception as e:
        log.error("llm_query failed: %s", e)
        raise


# -- Main entry point --


async def run_sub_agent(
    signature: str | type,
    inputs: dict[str, Any],
    max_iterations: int = 10,
    max_llm_calls: int = 30,
    sandbox_url: str = "http://localhost:8080",
    sub_lm_model: str = DEFAULT_SUB_LM,
    callback_server: Any = None,
) -> dict[str, Any]:
    """Execute a DSPy RLM sub-agent.

    Returns dict with 'result' (output fields) and 'trajectory' (step trace).
    If callback_server is provided, a 'usage' key is added with per-run token stats.
    """
    from mcp_server.signatures import validate_signature, resolve_signature

    signature = resolve_signature(signature)
    if not validate_signature(signature):
        return {"error": "Invalid signature format", "result": None, "trajectory": None}

    # Snapshot usage before the run so we can compute the diff
    usage_before = callback_server.get_usage() if callback_server is not None else None

    sub_lm = dspy.LM(sub_lm_model)

    async with SandboxInterpreter(sandbox_url) as interpreter:
        try:
            rlm = dspy.RLM(
                signature,
                sub_lm=sub_lm,
                interpreter=interpreter,
                max_iterations=max_iterations,
                max_llm_calls=max_llm_calls,
            )
            prediction = await rlm.aforward(**inputs)
        except dspy.DSPyError as e:
            log.error("DSPy error in sub-agent: %s", e)
            return {"error": str(e), "result": None, "trajectory": None}
        except httpx.HTTPStatusError as e:
            log.error("Sandbox HTTP error: %s", e)
            return {"error": f"Sandbox error: {e}", "result": None, "trajectory": None}
        except Exception as e:
            # Catch rate limits and other transient failures
            err_str = str(e).lower()
            if "rate" in err_str and "limit" in err_str:
                log.warning("Rate limited during sub-agent execution: %s", e)
                return {
                    "error": "Rate limited — try again in a few seconds",
                    "result": None,
                    "trajectory": None,
                }
            log.error("Unexpected error in sub-agent: %s", e)
            return {"error": str(e), "result": None, "trajectory": None}

    # Extract output fields from the prediction
    result = {}
    if hasattr(prediction, "_output_fields"):
        for field_name in prediction._output_fields:
            result[field_name] = getattr(prediction, field_name, None)
    elif hasattr(prediction, "keys"):
        result = dict(prediction)
    else:
        result = {"output": str(prediction)}

    trajectory = getattr(prediction, "trajectory", None)

    ret: dict[str, Any] = {"result": result, "trajectory": trajectory}

    if callback_server is not None:
        usage_after = callback_server.get_usage()
        ret["usage"] = {
            "input_tokens": usage_after["total_input_tokens"] - usage_before["total_input_tokens"],
            "output_tokens": usage_after["total_output_tokens"] - usage_before["total_output_tokens"],
            "llm_calls": usage_after["total_calls"] - usage_before["total_calls"],
        }

    return ret
