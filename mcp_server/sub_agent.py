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
    """Inject llm_query() stub into container that POSTs to host.

    The stub uses 'requests' (available in the container) to call back to the
    host-side callback endpoint. This keeps API keys out of the container.
    """
    stub_code = (
        "import requests as _llm_requests\n"
        "def llm_query(prompt):\n"
        "    _resp = _llm_requests.post(\n"
        f'        "{callback_url}",\n'
        '        json={"prompt": prompt},\n'
        "        timeout=120,\n"
        "    )\n"
        "    _resp.raise_for_status()\n"
        '    return _resp.json()["result"]\n'
    )
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
) -> dict[str, Any]:
    """Execute a DSPy RLM sub-agent.

    Returns dict with 'result' (output fields) and 'trajectory' (step trace).
    """
    from mcp_server.signatures import validate_signature

    if not validate_signature(signature):
        return {"error": "Invalid signature format", "result": None, "trajectory": None}

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

    return {"result": result, "trajectory": trajectory}
