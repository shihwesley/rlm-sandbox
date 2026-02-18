"""Host-side callback server for llm_query() calls from the sandbox.

Runs a minimal asyncio HTTP server on CALLBACK_PORT. When sandbox code calls
llm_query(prompt), the injected stub POSTs here, and we route through dspy.LM
(Haiku 4.5) on the host side. API keys never enter the container.

Also handles POST /tool_call for sandbox-callable MCP tools (search_knowledge,
ask_knowledge, fetch_url, load_file, apple_search). Only idempotent/read tools
are exposed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Awaitable
from typing import Any

import dspy

log = logging.getLogger(__name__)

DEFAULT_SUB_LM = "anthropic/claude-haiku-4-5-20251001"
CALLBACK_PORT = 8081

# Registry of sandbox-callable tools: sandbox function name -> MCP tool name.
# Only idempotent/read tools are listed here.
SANDBOX_TOOLS: dict[str, str] = {
    "search_knowledge": "rlm_search",
    "ask_knowledge": "rlm_ask",
    "fetch_url": "rlm_fetch",
    "load_file": "rlm_load",
    "apple_search": "rlm_apple_search",
}


class LLMCallbackServer:
    """Async HTTP server that handles llm_query() and tool_call() callbacks from the sandbox."""

    def __init__(self, port: int = CALLBACK_PORT, model: str = DEFAULT_SUB_LM):
        self.port = port
        self.model = model
        self._sub_lm: dspy.LM | None = None
        self._server: asyncio.Server | None = None
        # Handlers for /tool_call dispatch; populated by register_tool_handler()
        self._tool_handlers: dict[str, Callable[[dict[str, Any]], Awaitable[Any]]] = {}
        # Token usage accumulator
        self._usage: dict[str, Any] = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_calls": 0,
            "calls_by_model": {},
        }

    @property
    def callback_url(self) -> str:
        """URL the sandbox stub should POST to."""
        return f"http://host.docker.internal:{self.port}/llm_query"

    @property
    def callback_url_local(self) -> str:
        """URL for bare-process mode (no Docker, everything on localhost)."""
        return f"http://127.0.0.1:{self.port}/llm_query"

    @property
    def base_url(self) -> str:
        """Base URL (without path) for constructing tool_call endpoint URLs."""
        return f"http://host.docker.internal:{self.port}"

    @property
    def base_url_local(self) -> str:
        """Base URL (without path) for bare-process mode."""
        return f"http://127.0.0.1:{self.port}"

    def register_tool_handler(
        self,
        tool_name: str,
        handler: Callable[[dict[str, Any]], Awaitable[Any]],
    ) -> None:
        """Register an async callable for a sandbox tool name."""
        self._tool_handlers[tool_name] = handler

    @property
    def sub_lm(self) -> dspy.LM:
        if self._sub_lm is None:
            self._sub_lm = dspy.LM(self.model)
        return self._sub_lm

    async def start(self) -> None:
        """Start listening for llm_query callbacks."""
        self._server = await asyncio.start_server(
            self._handle_connection, "0.0.0.0", self.port
        )
        log.info("LLM callback server listening on port %d", self.port)

    async def stop(self) -> None:
        """Shut down the callback server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            log.info("LLM callback server stopped")

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a single HTTP connection from the sandbox stub."""
        try:
            # Read request line
            request_line = await asyncio.wait_for(reader.readline(), timeout=5)
            if not request_line:
                return

            method, path, _ = request_line.decode().strip().split(" ", 2)

            # Read headers
            content_length = 0
            while True:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
                decoded = line.decode().strip()
                if not decoded:
                    break
                if decoded.lower().startswith("content-length:"):
                    content_length = int(decoded.split(":", 1)[1].strip())

            # Only accept POST to known routes
            if method != "POST" or path not in ("/llm_query", "/tool_call"):
                self._send_response(writer, 404, {"error": "not found"})
                return

            # Read body
            body = b""
            if content_length > 0:
                body = await asyncio.wait_for(
                    reader.readexactly(content_length), timeout=5
                )

            data = json.loads(body)

            if path == "/llm_query":
                prompt = data.get("prompt", "")
                if not prompt:
                    self._send_response(writer, 400, {"error": "missing prompt"})
                    return
                result = await self._query_lm(prompt)
                self._send_response(writer, 200, {"result": result})
            else:
                # /tool_call
                tool_name = data.get("tool_name", "")
                tool_input = data.get("input", {})
                if not tool_name:
                    self._send_response(writer, 400, {"error": "missing tool_name"})
                    return
                handler = self._tool_handlers.get(tool_name)
                if handler is None:
                    self._send_response(writer, 404, {"error": f"unknown tool: {tool_name}"})
                    return
                tool_result = await handler(tool_input)
                self._send_response(writer, 200, {"result": tool_result})

        except asyncio.TimeoutError:
            log.warning("Callback connection timed out")
            self._send_response(writer, 408, {"error": "timeout"})
        except Exception:
            log.exception("Error handling llm_query callback")
            self._send_response(writer, 500, {"error": "internal error"})
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _query_lm(self, prompt: str) -> str:
        """Run the prompt through dspy.LM in a thread (it's sync)."""
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(None, self.sub_lm, prompt)
        # Accumulate token usage from the most recent history entry
        self._accumulate_usage()
        # dspy.LM returns a list of completions
        if isinstance(response, list) and response:
            return response[0]
        return str(response)

    def _accumulate_usage(self) -> None:
        """Read the last history entry from sub_lm and add token counts to _usage."""
        try:
            history = self.sub_lm.history
            if not history:
                return
            entry = history[-1]
            usage = entry.get("usage") or {}
            input_tokens = int(usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0) or usage.get("output_tokens", 0))
            self._usage["total_input_tokens"] += input_tokens
            self._usage["total_output_tokens"] += output_tokens
            self._usage["total_calls"] += 1
            model_key = self.model
            if model_key not in self._usage["calls_by_model"]:
                self._usage["calls_by_model"][model_key] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "calls": 0,
                }
            self._usage["calls_by_model"][model_key]["input_tokens"] += input_tokens
            self._usage["calls_by_model"][model_key]["output_tokens"] += output_tokens
            self._usage["calls_by_model"][model_key]["calls"] += 1
        except Exception:
            log.debug("Could not read token usage from LM history", exc_info=True)

    def get_usage(self) -> dict[str, Any]:
        """Return a copy of the accumulated usage stats."""
        import copy
        return copy.deepcopy(self._usage)

    def reset_usage(self) -> None:
        """Zero all usage counters."""
        self._usage = {
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_calls": 0,
            "calls_by_model": {},
        }

    def setup_tool_handlers(self, knowledge_store, http_client) -> None:
        """Wire the sandbox-callable tool handlers using live service objects.

        Called from server.py lifespan after services are ready. Registers one
        async handler per entry in SANDBOX_TOOLS.
        """
        from mcp_server.knowledge import get_store
        from mcp_server.fetcher import fetch_url, extract_library_name

        async def _search_knowledge(inp: dict[str, Any]) -> Any:
            query = inp.get("query", "")
            top_k = int(inp.get("top_k", 10))
            store = knowledge_store if knowledge_store is not None else get_store()
            results = store.search(query, top_k=top_k)
            return results

        async def _ask_knowledge(inp: dict[str, Any]) -> Any:
            question = inp.get("question", "")
            store = knowledge_store if knowledge_store is not None else get_store()
            return store.ask(question)

        async def _fetch_url(inp: dict[str, Any]) -> Any:
            url = inp.get("url", "")
            result = await fetch_url(http_client, url)
            if result["error"]:
                return {"error": result["error"]}
            return {"content": result["content"], "from_cache": result["from_cache"]}

        async def _load_file(inp: dict[str, Any]) -> Any:
            import json as _json
            from pathlib import Path
            path = inp.get("path", "")
            var_name = inp.get("var_name", "")
            host_path = Path(path).expanduser().resolve()
            if not host_path.exists():
                return {"error": f"file not found: {host_path}"}
            content = host_path.read_text()
            return {"var_name": var_name, "content": content, "size": len(content)}

        async def _apple_search(inp: dict[str, Any]) -> Any:
            from mcp_server.apple_docs import _run_tool, _parse_search_results, TOOLS_DIR
            query = inp.get("query", "")
            framework = inp.get("framework", None)
            rc, stdout, stderr = await _run_tool([
                str(TOOLS_DIR / "docindex.py"), "search", query,
            ])
            if rc != 0:
                return {"error": f"docindex search failed: {stderr.strip()}"}
            results = _parse_search_results(stdout)
            if framework:
                fw_lower = framework.lower()
                results = [
                    r for r in results
                    if fw_lower in r["path"].lower() or fw_lower in r["title"].lower()
                ]
            return {"results": results[:10]}

        self.register_tool_handler("search_knowledge", _search_knowledge)
        self.register_tool_handler("ask_knowledge", _ask_knowledge)
        self.register_tool_handler("fetch_url", _fetch_url)
        self.register_tool_handler("load_file", _load_file)
        self.register_tool_handler("apple_search", _apple_search)
        log.info("Registered %d sandbox tool handlers", len(self._tool_handlers))

    @staticmethod
    def _send_response(
        writer: asyncio.StreamWriter, status: int, body: dict
    ) -> None:
        """Write a minimal HTTP/1.1 JSON response."""
        payload = json.dumps(body).encode()
        reason = {200: "OK", 400: "Bad Request", 404: "Not Found",
                  408: "Timeout", 500: "Internal Server Error"}.get(status, "Error")
        header = (
            f"HTTP/1.1 {status} {reason}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(payload)}\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        writer.write(header.encode() + payload)
