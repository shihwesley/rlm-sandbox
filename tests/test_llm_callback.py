"""Tests for mcp_server/llm_callback.py — LLMCallbackServer."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from mcp_server.llm_callback import CALLBACK_PORT, DEFAULT_SUB_LM, LLMCallbackServer, SANDBOX_TOOLS


class TestLLMCallbackServerProperties:
    def test_default_port(self):
        server = LLMCallbackServer()
        assert server.port == CALLBACK_PORT

    def test_callback_url(self):
        server = LLMCallbackServer(port=9999)
        assert server.callback_url == "http://host.docker.internal:9999/llm_query"

    def test_callback_url_local(self):
        server = LLMCallbackServer(port=9999)
        assert server.callback_url_local == "http://127.0.0.1:9999/llm_query"

    def test_default_model(self):
        server = LLMCallbackServer()
        assert server.model == DEFAULT_SUB_LM


class TestLLMCallbackServerLifecycle:
    @pytest.mark.anyio
    async def test_start_and_stop(self):
        # Use a high port to avoid conflicts
        server = LLMCallbackServer(port=18081)
        await server.start()
        assert server._server is not None
        await server.stop()
        assert server._server is None

    @pytest.mark.anyio
    async def test_stop_without_start(self):
        server = LLMCallbackServer(port=18082)
        # should not raise
        await server.stop()


class TestLLMCallbackServerHTTP:
    """Test the actual HTTP handling by sending raw TCP requests."""

    @pytest.mark.anyio
    async def test_post_llm_query_returns_result(self):
        server = LLMCallbackServer(port=18083)

        # Mock the sub_lm property to avoid real API calls
        mock_lm = MagicMock(return_value=["mocked response"])
        server._sub_lm = mock_lm

        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18083)
            body = json.dumps({"prompt": "hello"}).encode()
            request = (
                f"POST /llm_query HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=10)
            writer.close()

            response_text = response.decode()
            # Parse status line
            status_line = response_text.split("\r\n")[0]
            assert "200" in status_line

            # Parse body (after double CRLF)
            resp_body = response_text.split("\r\n\r\n", 1)[1]
            data = json.loads(resp_body)
            assert data["result"] == "mocked response"

        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_wrong_path_returns_404(self):
        server = LLMCallbackServer(port=18084)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18084)
            request = (
                "GET /wrong HTTP/1.1\r\n"
                "Host: 127.0.0.1\r\n"
                "\r\n"
            ).encode()

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5)
            writer.close()

            assert b"404" in response

        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_missing_prompt_returns_400(self):
        server = LLMCallbackServer(port=18085)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18085)
            body = json.dumps({"prompt": ""}).encode()
            request = (
                f"POST /llm_query HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5)
            writer.close()

            assert b"400" in response

        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_lm_error_returns_500(self):
        server = LLMCallbackServer(port=18086)
        mock_lm = MagicMock(side_effect=RuntimeError("API error"))
        server._sub_lm = mock_lm

        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18086)
            body = json.dumps({"prompt": "will fail"}).encode()
            request = (
                f"POST /llm_query HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5)
            writer.close()

            assert b"500" in response

        finally:
            await server.stop()


class TestQueryLM:
    @pytest.mark.anyio
    async def test_returns_first_from_list(self):
        server = LLMCallbackServer(port=18087)
        mock_lm = MagicMock(return_value=["first", "second"])
        server._sub_lm = mock_lm
        result = await server._query_lm("test prompt")
        assert result == "first"
        mock_lm.assert_called_once_with("test prompt")

    @pytest.mark.anyio
    async def test_stringifies_non_list(self):
        server = LLMCallbackServer(port=18088)
        mock_lm = MagicMock(return_value=42)
        server._sub_lm = mock_lm
        result = await server._query_lm("test")
        assert result == "42"


class TestSandboxToolsRegistry:
    def test_sandbox_tools_contains_expected_keys(self):
        expected = {"search_knowledge", "ask_knowledge", "fetch_url", "load_file", "apple_search"}
        assert set(SANDBOX_TOOLS.keys()) == expected

    def test_sandbox_tools_maps_to_correct_mcp_names(self):
        assert SANDBOX_TOOLS["search_knowledge"] == "rlm_search"
        assert SANDBOX_TOOLS["ask_knowledge"] == "rlm_ask"
        assert SANDBOX_TOOLS["fetch_url"] == "rlm_fetch"
        assert SANDBOX_TOOLS["load_file"] == "rlm_load"
        assert SANDBOX_TOOLS["apple_search"] == "rlm_apple_search"

    def test_register_tool_handler_stores_handler(self):
        server = LLMCallbackServer(port=19000)

        async def my_handler(inp):
            return "ok"

        server.register_tool_handler("search_knowledge", my_handler)
        assert "search_knowledge" in server._tool_handlers
        assert server._tool_handlers["search_knowledge"] is my_handler

    def test_server_starts_with_empty_tool_handlers(self):
        server = LLMCallbackServer(port=19001)
        assert server._tool_handlers == {}

    def test_base_url_properties(self):
        server = LLMCallbackServer(port=19002)
        assert server.base_url == "http://host.docker.internal:19002"
        assert server.base_url_local == "http://127.0.0.1:19002"


class TestToolCallHTTP:
    """Test the /tool_call HTTP route dispatch."""

    @pytest.mark.anyio
    async def test_tool_call_dispatches_to_handler(self):
        server = LLMCallbackServer(port=18090)

        async def fake_search(inp):
            return {"hits": [{"title": inp.get("query", "")}]}

        server.register_tool_handler("search_knowledge", fake_search)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18090)
            body = json.dumps({"tool_name": "search_knowledge", "input": {"query": "test"}}).encode()
            request = (
                f"POST /tool_call HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=10)
            writer.close()

            response_text = response.decode()
            assert "200" in response_text.split("\r\n")[0]
            resp_body = json.loads(response_text.split("\r\n\r\n", 1)[1])
            assert resp_body["result"]["hits"][0]["title"] == "test"
        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_tool_call_missing_tool_name_returns_400(self):
        server = LLMCallbackServer(port=18091)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18091)
            body = json.dumps({"input": {}}).encode()
            request = (
                f"POST /tool_call HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5)
            writer.close()

            assert b"400" in response
        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_tool_call_unknown_tool_returns_404(self):
        server = LLMCallbackServer(port=18092)
        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18092)
            body = json.dumps({"tool_name": "nonexistent_tool", "input": {}}).encode()
            request = (
                f"POST /tool_call HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=5)
            writer.close()

            assert b"404" in response
        finally:
            await server.stop()

    @pytest.mark.anyio
    async def test_llm_query_still_works_alongside_tool_call(self):
        """REQ-5: existing llm_query() remains as-is (backward compat)."""
        server = LLMCallbackServer(port=18093)
        mock_lm = MagicMock(return_value=["mocked"])
        server._sub_lm = mock_lm

        await server.start()
        try:
            reader, writer = await asyncio.open_connection("127.0.0.1", 18093)
            body = json.dumps({"prompt": "hello"}).encode()
            request = (
                f"POST /llm_query HTTP/1.1\r\n"
                f"Host: 127.0.0.1\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"\r\n"
            ).encode() + body

            writer.write(request)
            await writer.drain()

            response = await asyncio.wait_for(reader.read(4096), timeout=10)
            writer.close()

            assert b"200" in response
            resp_body = json.loads(response.decode().split("\r\n\r\n", 1)[1])
            assert resp_body["result"] == "mocked"
        finally:
            await server.stop()


class TestUsageTracking:
    """REQ-1: LLMCallbackServer accumulates token usage per call."""

    def test_initial_usage_is_zero(self):
        server = LLMCallbackServer(port=19100)
        usage = server.get_usage()
        assert usage["total_input_tokens"] == 0
        assert usage["total_output_tokens"] == 0
        assert usage["total_calls"] == 0
        assert usage["calls_by_model"] == {}

    def test_get_usage_returns_copy(self):
        server = LLMCallbackServer(port=19101)
        usage = server.get_usage()
        usage["total_calls"] = 99
        assert server.get_usage()["total_calls"] == 0

    def test_reset_usage_zeroes_counters(self):
        server = LLMCallbackServer(port=19102)
        server._usage["total_calls"] = 5
        server._usage["total_input_tokens"] = 1000
        server._usage["total_output_tokens"] = 500
        server._usage["calls_by_model"]["some-model"] = {"input_tokens": 1000, "output_tokens": 500, "calls": 5}
        server.reset_usage()
        usage = server.get_usage()
        assert usage["total_calls"] == 0
        assert usage["total_input_tokens"] == 0
        assert usage["total_output_tokens"] == 0
        assert usage["calls_by_model"] == {}

    def test_accumulate_usage_reads_history(self):
        server = LLMCallbackServer(port=19103)
        mock_lm = MagicMock()
        mock_lm.history = [{"usage": {"prompt_tokens": 100, "completion_tokens": 50}}]
        server._sub_lm = mock_lm
        server._accumulate_usage()
        usage = server.get_usage()
        assert usage["total_input_tokens"] == 100
        assert usage["total_output_tokens"] == 50
        assert usage["total_calls"] == 1

    def test_accumulate_usage_uses_input_output_token_keys(self):
        """Some APIs return input_tokens/output_tokens instead of prompt/completion."""
        server = LLMCallbackServer(port=19104)
        mock_lm = MagicMock()
        mock_lm.history = [{"usage": {"input_tokens": 200, "output_tokens": 80}}]
        server._sub_lm = mock_lm
        server._accumulate_usage()
        usage = server.get_usage()
        assert usage["total_input_tokens"] == 200
        assert usage["total_output_tokens"] == 80

    def test_accumulate_usage_accumulates_across_calls(self):
        server = LLMCallbackServer(port=19105)
        mock_lm = MagicMock()
        mock_lm.history = [{"usage": {"prompt_tokens": 10, "completion_tokens": 5}}]
        server._sub_lm = mock_lm
        server._accumulate_usage()
        server._accumulate_usage()
        usage = server.get_usage()
        assert usage["total_input_tokens"] == 20
        assert usage["total_output_tokens"] == 10
        assert usage["total_calls"] == 2

    def test_accumulate_usage_tracks_per_model(self):
        server = LLMCallbackServer(port=19106)
        mock_lm = MagicMock()
        mock_lm.history = [{"usage": {"prompt_tokens": 50, "completion_tokens": 25}}]
        server._sub_lm = mock_lm
        server._accumulate_usage()
        usage = server.get_usage()
        model_stats = usage["calls_by_model"][server.model]
        assert model_stats["input_tokens"] == 50
        assert model_stats["output_tokens"] == 25
        assert model_stats["calls"] == 1

    def test_accumulate_usage_empty_history_is_noop(self):
        server = LLMCallbackServer(port=19107)
        mock_lm = MagicMock()
        mock_lm.history = []
        server._sub_lm = mock_lm
        server._accumulate_usage()
        usage = server.get_usage()
        assert usage["total_calls"] == 0

    def test_accumulate_usage_missing_usage_key_is_noop(self):
        server = LLMCallbackServer(port=19108)
        mock_lm = MagicMock()
        mock_lm.history = [{"response": "no usage key here"}]
        server._sub_lm = mock_lm
        server._accumulate_usage()
        usage = server.get_usage()
        assert usage["total_calls"] == 1
        assert usage["total_input_tokens"] == 0

    @pytest.mark.anyio
    async def test_query_lm_accumulates_after_call(self):
        """After _query_lm(), usage counters should be incremented."""
        server = LLMCallbackServer(port=19109)
        mock_lm = MagicMock(return_value=["result"])
        mock_lm.history = [{"usage": {"prompt_tokens": 30, "completion_tokens": 15}}]
        server._sub_lm = mock_lm
        await server._query_lm("test prompt")
        usage = server.get_usage()
        assert usage["total_calls"] == 1
        assert usage["total_input_tokens"] == 30
        assert usage["total_output_tokens"] == 15
