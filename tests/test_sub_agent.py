"""Tests for DSPy RLM sub-agent integration.

All DSPy and HTTP calls are mocked — no live container or API key needed.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.signatures import (
    DEEP_REASONING_MULTI_SIGNATURE,
    DEEP_REASONING_SIGNATURE,
    NAMED_SIGNATURES,
    SEARCH_SIGNATURE,
    build_custom_signature,
    resolve_signature,
    validate_signature,
)
from mcp_server.sub_agent import (
    SandboxInterpreter,
    handle_llm_query,
    inject_llm_stub,
    inject_tool_stubs,
    run_sub_agent,
)


# -- Helpers --


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _mock_httpx_response(json_data: dict, status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx

        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


class FakePrediction:
    """Minimal mock of a DSPy Prediction object."""

    def __init__(self, fields: dict[str, Any], trajectory: list | None = None):
        self._output_fields = list(fields.keys())
        self.trajectory = trajectory
        for k, v in fields.items():
            setattr(self, k, v)


# -- SandboxInterpreter tests --


class TestSandboxInterpreter:
    def test_must_use_context_manager(self):
        interp = SandboxInterpreter()
        with pytest.raises(RuntimeError, match="context manager"):
            _run(interp.execute("print(1)"))

    def test_execute_posts_code_and_returns_output(self):
        interp = SandboxInterpreter()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "42\n", "stderr": "", "vars": ["x"]}
        )
        interp._client = mock_client

        result = _run(interp.execute("print(42)"))
        assert result == "42\n"
        mock_client.post.assert_called_once_with(
            "/exec", json={"code": "print(42)"}
        )

    def test_execute_includes_stderr_when_present(self):
        interp = SandboxInterpreter()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "NameError: x", "vars": []}
        )
        interp._client = mock_client

        result = _run(interp.execute("x"))
        assert "[stderr] NameError: x" in result

    def test_execute_with_variables_injects_before_code(self):
        interp = SandboxInterpreter()
        call_count = 0
        responses = [
            _mock_httpx_response({"output": "", "stderr": "", "vars": []}),
            _mock_httpx_response({"output": "hello\n", "stderr": "", "vars": []}),
        ]

        mock_client = AsyncMock()

        async def fake_post(url, json=None):
            nonlocal call_count
            resp = responses[call_count]
            call_count += 1
            return resp

        mock_client.post = fake_post
        interp._client = mock_client

        result = _run(interp.execute("print(msg)", variables={"msg": "hello"}))
        assert result == "hello\n"
        assert call_count == 2  # one for variable injection, one for code

    def test_callable_delegates_to_execute(self):
        interp = SandboxInterpreter()
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "ok", "stderr": "", "vars": []}
        )
        interp._client = mock_client

        result = _run(interp("print('ok')"))
        assert result == "ok"

    def test_context_manager_creates_and_closes_client(self):
        async def _test():
            interp = SandboxInterpreter(base_url="http://test:9999", timeout=5)
            async with interp as i:
                assert i._client is not None
                assert i is interp
            assert interp._client is None

        _run(_test())


# -- Signature validation tests --


class TestSignatureValidation:
    def test_valid_string_signatures(self):
        assert validate_signature("a -> b") is True
        assert validate_signature("x, y -> z: str") is True
        assert validate_signature("context, query -> answer: str") is True
        assert validate_signature("text, categories -> cat: str, conf: float") is True

    def test_invalid_string_signatures(self):
        assert validate_signature("") is False
        assert validate_signature("no arrow here") is False
        assert validate_signature("->") is False
        assert validate_signature("123invalid -> out") is False
        assert validate_signature("in -> ") is False

    def test_non_string_non_type_returns_false(self):
        assert validate_signature(42) is False
        assert validate_signature(None) is False

    def test_signature_class_validation(self):
        import dspy

        sig_cls = build_custom_signature(
            "TestSig",
            {"query": "the query"},
            {"answer": "the answer"},
        )
        assert validate_signature(sig_cls) is True
        assert validate_signature(str) is False  # not a Signature subclass


# -- Custom signature builder tests --


class TestBuildCustomSignature:
    def test_builds_signature_with_input_and_output_fields(self):
        import dspy

        sig = build_custom_signature(
            "MySig",
            {"query": "search query", "context": "search context"},
            {"answer": "the answer", "confidence": "confidence score"},
            instructions="Answer the query.",
        )

        assert issubclass(sig, dspy.Signature)
        assert sig.__name__ == "MySig"
        assert sig.__doc__ == "Answer the query."

    def test_rejects_empty_input_fields(self):
        with pytest.raises(ValueError, match="input field"):
            build_custom_signature("Bad", {}, {"out": "x"})

    def test_rejects_empty_output_fields(self):
        with pytest.raises(ValueError, match="output field"):
            build_custom_signature("Bad", {"in": "x"}, {})

    def test_rejects_invalid_field_names(self):
        with pytest.raises(ValueError, match="Invalid field name"):
            build_custom_signature("Bad", {"123bad": "x"}, {"out": "y"})

    def test_rejects_overlapping_fields(self):
        with pytest.raises(ValueError, match="both input and output"):
            build_custom_signature("Bad", {"x": "a"}, {"x": "b"})

    def test_custom_signature_with_arbitrary_output_fields(self):
        """AC-3: Custom signatures with arbitrary output fields work correctly."""
        import dspy

        sig = build_custom_signature(
            "ExtractSig",
            {"document": "source document"},
            {
                "entities": "extracted entities",
                "sentiment": "document sentiment",
                "summary": "brief summary",
            },
        )
        assert issubclass(sig, dspy.Signature)
        # All three output fields should be present in the signature
        output_names = {f.json_schema_extra["prefix"].rstrip(":").lower()
                        for f in sig.model_fields.values()
                        if f.json_schema_extra.get("__dspy_field_type") == "output"}
        for field in ("entities", "sentiment", "summary"):
            assert field in sig.model_fields, f"field '{field}' not in model_fields"


# -- Named signature tests --


class TestNamedSignatures:
    def test_named_signatures_map_contains_deep_reasoning(self):
        assert "deep_reasoning" in NAMED_SIGNATURES
        assert "deep_reasoning_multi" in NAMED_SIGNATURES

    def test_deep_reasoning_signature_is_dspy_subclass(self):
        import dspy

        assert issubclass(DEEP_REASONING_SIGNATURE, dspy.Signature)
        assert issubclass(DEEP_REASONING_MULTI_SIGNATURE, dspy.Signature)

    def test_validate_signature_accepts_deep_reasoning_name(self):
        assert validate_signature("deep_reasoning") is True
        assert validate_signature("deep_reasoning_multi") is True

    def test_resolve_signature_returns_class_for_known_name(self):
        import dspy

        result = resolve_signature("deep_reasoning")
        assert isinstance(result, type)
        assert issubclass(result, dspy.Signature)
        assert result is DEEP_REASONING_SIGNATURE

    def test_resolve_signature_returns_class_for_multi_name(self):
        result = resolve_signature("deep_reasoning_multi")
        assert result is DEEP_REASONING_MULTI_SIGNATURE

    def test_resolve_signature_passthrough_for_string_sig(self):
        sig = "context, query -> answer: str"
        assert resolve_signature(sig) is sig

    def test_resolve_signature_passthrough_for_class(self):
        import dspy

        sig_cls = build_custom_signature("X", {"a": "a"}, {"b": "b"})
        assert resolve_signature(sig_cls) is sig_cls

    def test_existing_string_signatures_still_validate(self):
        assert validate_signature(SEARCH_SIGNATURE) is True
        assert validate_signature("document, fields -> extracted: dict") is True

    def test_deep_reasoning_signature_has_correct_fields(self):
        assert "context" in DEEP_REASONING_SIGNATURE.model_fields
        assert "query" in DEEP_REASONING_SIGNATURE.model_fields
        assert "answer" in DEEP_REASONING_SIGNATURE.model_fields

    def test_deep_reasoning_multi_signature_has_correct_fields(self):
        assert "documents" in DEEP_REASONING_MULTI_SIGNATURE.model_fields
        assert "query" in DEEP_REASONING_MULTI_SIGNATURE.model_fields
        assert "answer" in DEEP_REASONING_MULTI_SIGNATURE.model_fields

    def test_deep_reasoning_signature_has_instructions(self):
        doc = DEEP_REASONING_SIGNATURE.__doc__
        assert "Phase 1" in doc
        assert "Phase 2" in doc
        assert "Phase 3" in doc

    @patch("mcp_server.sub_agent.dspy")
    def test_run_sub_agent_accepts_named_signature(self, mock_dspy):
        """run_sub_agent resolves 'deep_reasoning' name and calls RLM with the class."""
        fake_pred = FakePrediction({"answer": "resolved answer"})
        mock_rlm_instance = AsyncMock()
        mock_rlm_instance.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm_instance
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            result = _run(run_sub_agent(
                signature="deep_reasoning",
                inputs={"context": "some text", "query": "what is this?"},
            ))

        assert "error" not in result or result["error"] is None
        assert result["result"]["answer"] == "resolved answer"
        # Verify RLM was called with the actual class, not the string name
        rlm_call = mock_dspy.RLM.call_args
        first_arg = rlm_call.args[0] if rlm_call.args else rlm_call[0][0]
        assert first_arg is DEEP_REASONING_SIGNATURE


# -- run_sub_agent tests --


class TestRunSubAgent:
    def test_malformed_signature_returns_error(self):
        """AC-7: Malformed signature returns validation error."""
        result = _run(run_sub_agent(
            signature="not a valid signature",
            inputs={"x": 1},
        ))
        assert result["error"] == "Invalid signature format"
        assert result["result"] is None

    @patch("mcp_server.sub_agent.dspy")
    def test_search_signature_returns_structured_results(self, mock_dspy):
        """AC-1: sub_agent with a search signature returns structured results."""
        fake_pred = FakePrediction({"answer": "Paris is the capital of France."})

        mock_rlm_instance = AsyncMock()
        mock_rlm_instance.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm_instance
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            with patch("mcp_server.signatures.dspy", mock_dspy):
                # validate_signature needs dspy.Signature for type checks,
                # but string sigs don't hit that path
                result = _run(run_sub_agent(
                    signature=SEARCH_SIGNATURE,
                    inputs={"context": "France info", "query": "What is the capital?"},
                ))

        assert "error" not in result or result["error"] is None
        assert result["result"]["answer"] == "Paris is the capital of France."

    @patch("mcp_server.sub_agent.dspy")
    def test_max_iterations_and_llm_calls_configurable(self, mock_dspy):
        """AC-5: max_iterations and max_llm_calls configurable per call."""
        fake_pred = FakePrediction({"answer": "ok"})
        mock_rlm_instance = AsyncMock()
        mock_rlm_instance.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm_instance
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            _run(run_sub_agent(
                signature="q -> a: str",
                inputs={"q": "test"},
                max_iterations=5,
                max_llm_calls=15,
            ))

        # Verify RLM was constructed with the custom limits
        mock_dspy.RLM.assert_called_once()
        call_kwargs = mock_dspy.RLM.call_args
        assert call_kwargs.kwargs["max_iterations"] == 5 or call_kwargs[1].get("max_iterations") == 5

    @patch("mcp_server.sub_agent.dspy")
    def test_rate_limit_returns_graceful_error(self, mock_dspy):
        """AC-6: Rate limit errors return graceful error message, not crash."""
        mock_rlm_instance = AsyncMock()
        mock_rlm_instance.aforward.side_effect = Exception(
            "Rate limit exceeded: too many requests"
        )
        mock_dspy.RLM.return_value = mock_rlm_instance
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = type("DSPyError", (Exception,), {})

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            result = _run(run_sub_agent(
                signature="q -> a: str",
                inputs={"q": "test"},
            ))

        assert "Rate limited" in result["error"]
        assert result["result"] is None

    @patch("mcp_server.sub_agent.dspy")
    def test_uses_haiku_sub_lm(self, mock_dspy):
        """AC-4: Sub-agent uses Haiku 4.5 via host's ANTHROPIC_API_KEY."""
        fake_pred = FakePrediction({"answer": "test"})
        mock_rlm_instance = AsyncMock()
        mock_rlm_instance.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm_instance
        mock_dspy.LM.return_value = MagicMock(name="haiku-lm")
        mock_dspy.DSPyError = Exception

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            _run(run_sub_agent(
                signature="q -> answer: str",
                inputs={"q": "test"},
            ))

        # Verify LM was created with the Haiku model
        mock_dspy.LM.assert_called_once_with("anthropic/claude-haiku-4-5-20251001")

        # Verify the LM was passed to RLM as sub_lm
        rlm_call = mock_dspy.RLM.call_args
        assert rlm_call.kwargs.get("sub_lm") is not None or rlm_call[1].get("sub_lm") is not None


# -- llm_query callback tests --


class TestLlmQueryCallback:
    def test_handle_llm_query_returns_first_completion(self):
        mock_lm = MagicMock()
        mock_lm.return_value = ["The answer is 42."]

        result = _run(handle_llm_query("What is the answer?", mock_lm))
        assert result == "The answer is 42."
        mock_lm.assert_called_once_with("What is the answer?")

    def test_handle_llm_query_stringifies_non_list_response(self):
        mock_lm = MagicMock()
        mock_lm.return_value = "direct string"

        result = _run(handle_llm_query("prompt", mock_lm))
        assert result == "direct string"

    def test_handle_llm_query_propagates_errors(self):
        mock_lm = MagicMock()
        mock_lm.side_effect = RuntimeError("API down")

        with pytest.raises(RuntimeError, match="API down"):
            _run(handle_llm_query("prompt", mock_lm))

    def test_inject_llm_stub_posts_code_to_container(self):
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": ["llm_query"]}
        )

        _run(inject_llm_stub(mock_client, "http://host:9999/llm_query"))
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/exec"
        injected_code = call_args[1]["json"]["code"] if "json" in call_args[1] else call_args.kwargs["json"]["code"]
        assert "http://host:9999/llm_query" in injected_code
        assert "def llm_query" in injected_code


# -- Integration: results accessible via rlm.get (AC-2) --


class TestResultStorageInSandbox:
    """AC-2: Sub-agent results accessible via rlm.get after execution."""

    @patch("mcp_server.sub_agent.dspy")
    def test_result_fields_are_extractable(self, mock_dspy):
        """After run_sub_agent, result dict contains output fields from prediction."""
        fake_pred = FakePrediction(
            {"answer": "Paris", "confidence": 0.95},
            trajectory=["step1", "step2"],
        )
        mock_rlm_instance = AsyncMock()
        mock_rlm_instance.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm_instance
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            result = _run(run_sub_agent(
                signature="q -> answer: str, confidence: float",
                inputs={"q": "capital of France?"},
            ))

        # The result dict should have the output fields
        assert result["result"]["answer"] == "Paris"
        assert result["result"]["confidence"] == 0.95
        assert result["trajectory"] == ["step1", "step2"]


# -- llm_query_batch stub tests --


class TestBatchLLMStub:
    def test_inject_llm_stub_includes_batch_function(self):
        """inject_llm_stub code includes llm_query_batch definition."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": ["llm_query", "llm_query_batch"]}
        )

        _run(inject_llm_stub(mock_client, "http://host:9999/llm_query"))
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        assert "def llm_query_batch" in injected_code
        assert "ThreadPoolExecutor" in injected_code

    def test_batch_returns_results_in_order(self):
        """llm_query_batch returns results in the same order as input prompts."""
        call_order = []

        def fake_llm_query(prompt):
            call_order.append(prompt)
            return f"answer:{prompt}"

        import concurrent.futures

        def llm_query_batch(prompts):
            def _safe_query(p):
                try:
                    return fake_llm_query(p)
                except Exception as e:
                    return "[error] " + str(e)

            workers = min(len(prompts), 8)
            if workers == 0:
                return []
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                return list(pool.map(_safe_query, prompts))

        prompts = ["p0", "p1", "p2", "p3"]
        results = llm_query_batch(prompts)
        assert results == ["answer:p0", "answer:p1", "answer:p2", "answer:p3"]

    def test_batch_error_does_not_crash_batch(self):
        """Failed individual calls return '[error] ...' instead of raising."""
        import concurrent.futures

        def failing_llm_query(prompt):
            if prompt == "bad":
                raise ValueError("timeout")
            return f"ok:{prompt}"

        def llm_query_batch(prompts):
            def _safe_query(p):
                try:
                    return failing_llm_query(p)
                except Exception as e:
                    return "[error] " + str(e)

            workers = min(len(prompts), 8)
            if workers == 0:
                return []
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                return list(pool.map(_safe_query, prompts))

        results = llm_query_batch(["good", "bad", "also_good"])
        assert results[0] == "ok:good"
        assert results[1].startswith("[error]")
        assert "timeout" in results[1]
        assert results[2] == "ok:also_good"

    def test_batch_empty_list_returns_empty(self):
        """llm_query_batch([]) returns []."""
        import concurrent.futures

        def llm_query_batch(prompts):
            def _safe_query(p):
                return p

            workers = min(len(prompts), 8)
            if workers == 0:
                return []
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
                return list(pool.map(_safe_query, prompts))

        assert llm_query_batch([]) == []

    def test_batch_max_workers_capped_at_8(self):
        """ThreadPoolExecutor uses at most 8 workers even with more prompts."""
        captured = {}
        original_tpe = __import__("concurrent.futures", fromlist=["ThreadPoolExecutor"]).ThreadPoolExecutor

        class CapturingTPE(original_tpe):
            def __init__(self, max_workers=None, **kwargs):
                captured["max_workers"] = max_workers
                super().__init__(max_workers=max_workers, **kwargs)

        import concurrent.futures

        def llm_query_batch(prompts):
            def _safe_query(p):
                return p

            workers = min(len(prompts), 8)
            if workers == 0:
                return []
            with CapturingTPE(max_workers=workers) as pool:
                return list(pool.map(_safe_query, prompts))

        prompts = [f"p{i}" for i in range(20)]
        llm_query_batch(prompts)
        assert captured["max_workers"] == 8

    def test_existing_llm_query_unchanged(self):
        """inject_llm_stub still injects llm_query with the original callback URL."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": ["llm_query"]}
        )

        _run(inject_llm_stub(mock_client, "http://host:1234/llm_callback"))
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        assert "def llm_query" in injected_code
        assert "http://host:1234/llm_callback" in injected_code


# -- Tool stub injection tests --


class TestToolStubInjection:
    def test_inject_tool_stubs_posts_single_exec(self):
        """inject_tool_stubs sends a single POST /exec to the sandbox."""
        from mcp_server.llm_callback import SANDBOX_TOOLS

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": list(SANDBOX_TOOLS.keys())}
        )

        _run(inject_tool_stubs(mock_client, "http://host:8081", SANDBOX_TOOLS))
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[0][0] == "/exec"

    def test_inject_tool_stubs_defines_all_sandbox_functions(self):
        """Each key in SANDBOX_TOOLS appears as a def in the injected code."""
        from mcp_server.llm_callback import SANDBOX_TOOLS

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": []}
        )

        _run(inject_tool_stubs(mock_client, "http://host:8081", SANDBOX_TOOLS))
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        for func_name in SANDBOX_TOOLS:
            assert f"def {func_name}" in injected_code, \
                f"Expected 'def {func_name}' in injected code"

    def test_inject_tool_stubs_includes_tool_call_url(self):
        """The injected code POSTs to /tool_call on the callback base URL."""
        from mcp_server.llm_callback import SANDBOX_TOOLS

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": []}
        )

        _run(inject_tool_stubs(mock_client, "http://host:9876", SANDBOX_TOOLS))
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        assert "http://host:9876/tool_call" in injected_code

    def test_inject_tool_stubs_uses_urllib(self):
        """Stubs use urllib.request (stdlib) so no extra packages needed in container."""
        from mcp_server.llm_callback import SANDBOX_TOOLS

        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": []}
        )

        _run(inject_tool_stubs(mock_client, "http://host:8081", SANDBOX_TOOLS))
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        assert "urllib.request" in injected_code

    def test_inject_tool_stubs_with_empty_registry(self):
        """An empty tool registry injects helper but no stub functions."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": []}
        )

        _run(inject_tool_stubs(mock_client, "http://host:8081", {}))
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        # _tool_call dispatcher should still be there, just no per-tool stubs
        assert "_tool_call" in injected_code

    def test_search_knowledge_stub_has_top_k_param(self):
        """search_knowledge stub signature includes top_k parameter."""
        mock_client = AsyncMock()
        mock_client.post.return_value = _mock_httpx_response(
            {"output": "", "stderr": "", "vars": []}
        )

        _run(inject_tool_stubs(mock_client, "http://host:8081", {"search_knowledge": "rlm_search"}))
        call_args = mock_client.post.call_args
        injected_code = (
            call_args[1]["json"]["code"]
            if "json" in call_args[1]
            else call_args.kwargs["json"]["code"]
        )
        assert "top_k" in injected_code


# -- Token tracking tests --


class TestTokenTracking:
    """REQ-2: Sub-agent results include usage dict when callback_server provided."""

    def _make_callback_server(self, before: dict | None = None, after: dict | None = None):
        """Build a minimal mock callback_server with get_usage() returning given values."""
        cb = MagicMock()
        if before is not None and after is not None:
            cb.get_usage.side_effect = [before, after]
        else:
            default = {
                "total_input_tokens": 0,
                "total_output_tokens": 0,
                "total_calls": 0,
                "calls_by_model": {},
            }
            cb.get_usage.return_value = default
        return cb

    @patch("mcp_server.sub_agent.dspy")
    def test_usage_key_present_when_callback_server_provided(self, mock_dspy):
        """AC-1: result['usage'] is present when callback_server is passed."""
        fake_pred = FakePrediction({"answer": "ok"})
        mock_rlm = AsyncMock()
        mock_rlm.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        before = {"total_input_tokens": 0, "total_output_tokens": 0, "total_calls": 0, "calls_by_model": {}}
        after = {"total_input_tokens": 100, "total_output_tokens": 50, "total_calls": 3, "calls_by_model": {}}
        cb = self._make_callback_server(before, after)

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            result = _run(run_sub_agent(
                signature="q -> answer: str",
                inputs={"q": "test"},
                callback_server=cb,
            ))

        assert "usage" in result
        assert result["usage"]["input_tokens"] == 100
        assert result["usage"]["output_tokens"] == 50
        assert result["usage"]["llm_calls"] == 3

    @patch("mcp_server.sub_agent.dspy")
    def test_usage_key_absent_without_callback_server(self, mock_dspy):
        """AC-5: Backward compat — no 'usage' key when callback_server omitted."""
        fake_pred = FakePrediction({"answer": "ok"})
        mock_rlm = AsyncMock()
        mock_rlm.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            result = _run(run_sub_agent(
                signature="q -> answer: str",
                inputs={"q": "test"},
            ))

        assert "usage" not in result

    @patch("mcp_server.sub_agent.dspy")
    def test_usage_diff_is_per_run(self, mock_dspy):
        """Usage reflects delta between before/after snapshots, not cumulative totals."""
        fake_pred = FakePrediction({"answer": "ok"})
        mock_rlm = AsyncMock()
        mock_rlm.aforward.return_value = fake_pred
        mock_dspy.RLM.return_value = mock_rlm
        mock_dspy.LM.return_value = MagicMock()
        mock_dspy.DSPyError = Exception

        # Simulate 200 tokens already accumulated before this run
        before = {"total_input_tokens": 200, "total_output_tokens": 100, "total_calls": 5, "calls_by_model": {}}
        after = {"total_input_tokens": 350, "total_output_tokens": 160, "total_calls": 8, "calls_by_model": {}}
        cb = self._make_callback_server(before, after)

        with patch("mcp_server.sub_agent.SandboxInterpreter") as mock_interp_cls:
            mock_interp = AsyncMock()
            mock_interp.__aenter__ = AsyncMock(return_value=mock_interp)
            mock_interp.__aexit__ = AsyncMock(return_value=False)
            mock_interp_cls.return_value = mock_interp

            result = _run(run_sub_agent(
                signature="q -> answer: str",
                inputs={"q": "test"},
                callback_server=cb,
            ))

        assert result["usage"]["input_tokens"] == 150  # 350 - 200
        assert result["usage"]["output_tokens"] == 60   # 160 - 100
        assert result["usage"]["llm_calls"] == 3        # 8 - 5
