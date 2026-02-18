"""MCP tool definitions for the sandbox."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
from mcp.server.fastmcp import Context

from mcp_server.docker_manager import BASE_URL

if TYPE_CHECKING:
    from mcp_server.server import AppContext


def _ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context


async def _post_exec(app: AppContext, code: str, timeout: int = 30) -> dict:
    """POST /exec to the sandbox container using the shared HTTP client."""
    await app.manager.ensure_running()
    r = await app.http.post(
        f"{BASE_URL}/exec",
        json={"code": code, "timeout": timeout},
        timeout=timeout + 5,
    )
    r.raise_for_status()
    return r.json()


def register_tools(mcp) -> None:
    """Register all sandbox tools on the MCP server instance."""

    @mcp.tool()
    async def rlm_exec(code: str, ctx: Context, timeout: int = 30) -> str:
        """Execute Python code in the sandbox and return output."""
        app = _ctx(ctx)
        data = await _post_exec(app, code, timeout)
        parts = []
        if data.get("output"):
            parts.append(data["output"])
        if data.get("stderr"):
            parts.append(f"[stderr] {data['stderr']}")
        return "\n".join(parts) if parts else "(no output)"

    # Paths the srt sandbox also blocks — defense-in-depth
    DENY_PATHS = [
        Path.home() / ".ssh",
        Path.home() / ".aws",
        Path.home() / ".config" / "gcloud",
        Path.home() / ".gnupg",
    ]

    @mcp.tool()
    async def rlm_load(path: str, var_name: str, ctx: Context) -> str:
        """Read a file from the host filesystem and inject it into the sandbox."""
        host_path = Path(path).expanduser().resolve()
        if any(host_path.is_relative_to(d) for d in DENY_PATHS):
            return f"Error: access denied — {host_path} is in a restricted directory"
        if not host_path.exists():
            return f"Error: file not found: {host_path}"
        content = host_path.read_text()
        escaped = json.dumps(content)
        code = f"{var_name} = {escaped}"
        app = _ctx(ctx)
        data = await _post_exec(app, code)
        if data.get("stderr"):
            return f"Error loading: {data['stderr']}"
        return f"Loaded {host_path.name} into `{var_name}` ({len(content)} chars)"

    @mcp.tool()
    async def rlm_get(name: str, ctx: Context, query: str | None = None) -> str:
        """Get a variable's value from the sandbox. Optionally run a query expression."""
        app = _ctx(ctx)
        await app.manager.ensure_running()

        if query:
            data = await _post_exec(app, query)
            output = data.get("output", "")
            if data.get("stderr"):
                output += f"\n[stderr] {data['stderr']}"
            return output or "(no output)"

        r = await app.http.get(f"{BASE_URL}/var/{name}", timeout=10)
        r.raise_for_status()
        data = r.json()

        if data.get("error"):
            return f"Error: {data['error']}"
        return json.dumps(data.get("value"), indent=2, default=str)

    @mcp.tool()
    async def rlm_vars(ctx: Context) -> str:
        """List all variables in the sandbox."""
        app = _ctx(ctx)
        await app.manager.ensure_running()
        r = await app.http.get(f"{BASE_URL}/vars", timeout=10)
        r.raise_for_status()
        var_list = r.json()

        if not var_list:
            return "(no variables)"
        lines = [f"  {v['name']}: {v['type']} = {v['summary']}" for v in var_list]
        return "\n".join(lines)

    @mcp.tool()
    async def rlm_sub_agent(
        signature: str,
        inputs: dict,
        ctx: Context,
        max_iterations: int = 10,
        max_llm_calls: int = 30,
    ) -> str:
        """Run a DSPy RLM sub-agent with the given signature and inputs."""
        from mcp_server.sub_agent import run_sub_agent

        app = _ctx(ctx)
        await app.manager.ensure_running()

        result = await run_sub_agent(
            signature=signature,
            inputs=inputs,
            max_iterations=max_iterations,
            max_llm_calls=max_llm_calls,
            sandbox_url=BASE_URL,
            callback_server=app.llm_callback,
        )

        if result.get("error"):
            return f"Error: {result['error']}"

        # Store results in sandbox so they're accessible via rlm.get
        if result.get("result"):
            store_code = f"_sub_agent_result = {result['result']!r}"
            await _post_exec(app, store_code)

        return json.dumps(result, indent=2, default=str)

    # Pricing table: model -> ($/1M input tokens, $/1M output tokens)
    _PRICING: dict[str, tuple[float, float]] = {
        "anthropic/claude-haiku-4-5-20251001": (0.80, 4.00),
    }

    @mcp.tool()
    async def rlm_usage(ctx: Context, reset: bool = False) -> str:
        """Return cumulative LLM token usage stats for this session.

        Set reset=True to zero all counters after reading.
        """
        app = _ctx(ctx)
        cb = app.llm_callback
        if reset:
            cb.reset_usage()
            return "Usage counters reset."

        usage = cb.get_usage()
        total_in = usage["total_input_tokens"]
        total_out = usage["total_output_tokens"]
        total_calls = usage["total_calls"]

        # Estimate cost using known pricing; sum across models present in session
        total_cost = 0.0
        for model, stats in usage.get("calls_by_model", {}).items():
            price_in, price_out = _PRICING.get(model, (0.0, 0.0))
            total_cost += stats["input_tokens"] * price_in / 1_000_000
            total_cost += stats["output_tokens"] * price_out / 1_000_000

        lines = [
            f"LLM calls: {total_calls}",
            f"Input tokens: {total_in:,}",
            f"Output tokens: {total_out:,}",
            f"Estimated cost: ${total_cost:.4f}",
        ]
        if usage["calls_by_model"]:
            lines.append("By model:")
            for model, stats in usage["calls_by_model"].items():
                lines.append(
                    f"  {model}: {stats['calls']} calls, "
                    f"{stats['input_tokens']:,} in, {stats['output_tokens']:,} out"
                )
        return "\n".join(lines)

    @mcp.tool()
    async def rlm_reset(ctx: Context) -> str:
        """Reset the sandbox kernel, clearing all state."""
        from mcp_server.sub_agent import inject_llm_stub

        app = _ctx(ctx)
        data = await _post_exec(app, "get_ipython().reset(new_session=True)")

        # Re-inject llm_query() since reset clears the namespace
        cb = app.llm_callback
        cb_url = cb.callback_url_local if app.manager._no_docker else cb.callback_url
        inject_client = httpx.AsyncClient(base_url=BASE_URL, timeout=10)
        try:
            await inject_llm_stub(inject_client, cb_url)
        finally:
            await inject_client.aclose()

        if data.get("stderr"):
            return f"Reset with warnings: {data['stderr']}"
        return "Sandbox reset."
