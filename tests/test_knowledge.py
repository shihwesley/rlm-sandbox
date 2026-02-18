"""Tests for the memvid-backed knowledge store and MCP tool registrations.

All memvid_sdk interactions are mocked -- these are unit/smoke tests,
not integration tests that require an actual memvid installation.
"""

from __future__ import annotations

import asyncio
import os
import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


def _run(coro):
    """Run an async coroutine synchronously. Avoids needing pytest-asyncio."""
    return asyncio.run(coro)

# We need to mock memvid_sdk before importing knowledge.py
# since it imports from memvid_sdk at method call time (lazy).


@pytest.fixture(autouse=True)
def _clear_store_cache():
    """Reset the singleton store cache between tests."""
    from mcp_server.knowledge import _stores
    _stores.clear()
    yield
    _stores.clear()


# -- Mock helpers --


def _make_mock_mem():
    """Create a mock memvid memory object with expected methods."""
    mem = MagicMock()
    mem.put_many.return_value = ["frame-1", "frame-2"]
    mem.commit.return_value = None
    mem.seal.return_value = None
    mem.find.return_value = {
        "hits": [
            {"title": "Doc A", "score": 0.92, "snippet": "relevant chunk from doc A"},
            {"title": "Doc B", "score": 0.78, "snippet": "another chunk from doc B"},
        ]
    }
    mem.ask.return_value = {
        "answer": "The answer is 42.",
        "hits": [
            {"title": "Doc A", "score": 0.92, "snippet": "relevant chunk"},
        ],
    }
    mem.timeline.return_value = [
        {"timestamp": 1700000000, "title": "First doc", "text": "first content"},
        {"timestamp": 1700003600, "title": "Second doc", "text": "second content"},
    ]
    mem.enrich.return_value = {"entities": [{"text": "Python", "type": "TECH"}]}
    return mem


def _make_mock_embedder():
    """Create a mock embedder object."""
    embedder = MagicMock()
    embedder.embed.return_value = [[0.1] * 384]
    return embedder


# -- KnowledgeStore unit tests --


class TestKnowledgeStoreInit:
    def test_path_is_correct(self):
        from mcp_server.knowledge import KnowledgeStore
        store = KnowledgeStore("abc123")
        expected = os.path.expanduser("~/.rlm-sandbox/knowledge/abc123.mv2")
        assert store.path == expected

    def test_mem_starts_none(self):
        from mcp_server.knowledge import KnowledgeStore
        store = KnowledgeStore("abc123")
        assert store.mem is None

    def test_embedder_starts_unchecked(self):
        from mcp_server.knowledge import KnowledgeStore
        store = KnowledgeStore("abc123")
        assert store._embedder is None
        assert store._embedder_checked is False


class TestEmbedderFallback:
    def test_embedder_loads_huggingface(self):
        from mcp_server.knowledge import KnowledgeStore

        mock_embedder = _make_mock_embedder()
        mock_get = MagicMock(return_value=mock_embedder)

        with patch.dict("sys.modules", {
            "memvid_sdk": MagicMock(),
            "memvid_sdk.embeddings": MagicMock(get_embedder=mock_get),
        }):
            store = KnowledgeStore("test")
            result = store.embedder

            mock_get.assert_called_once_with("huggingface", model="all-MiniLM-L6-v2")
            assert result is mock_embedder

    def test_embedder_falls_back_to_none_on_import_error(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        # Force re-check
        store._embedder_checked = False

        with patch.dict("sys.modules", {"memvid_sdk.embeddings": None}):
            # Simulate ImportError by making the import fail
            original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

            def fail_import(name, *args, **kwargs):
                if "memvid_sdk.embeddings" in name:
                    raise ImportError("no module")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=fail_import):
                result = store.embedder
                assert result is None

    def test_embedder_cached_after_first_check(self):
        from mcp_server.knowledge import KnowledgeStore

        mock_embedder = _make_mock_embedder()
        mock_get = MagicMock(return_value=mock_embedder)

        with patch.dict("sys.modules", {
            "memvid_sdk": MagicMock(),
            "memvid_sdk.embeddings": MagicMock(get_embedder=mock_get),
        }):
            store = KnowledgeStore("test")
            _ = store.embedder
            _ = store.embedder  # second access
            # Only called once despite two accesses
            mock_get.assert_called_once()


class TestKnowledgeStoreOpen:
    def test_open_creates_new_store(self, tmp_path):
        from mcp_server.knowledge import KnowledgeStore

        mock_mem = _make_mock_mem()
        mock_create = MagicMock(return_value=mock_mem)

        store = KnowledgeStore("new-project")
        store.path = str(tmp_path / "new.mv2")

        with patch("mcp_server.knowledge.create", mock_create, create=True), \
             patch.dict("sys.modules", {"memvid_sdk": MagicMock(create=mock_create)}):
            # Patch the import inside open()
            import mcp_server.knowledge as mod
            with patch.object(mod, "__builtins__", mod.__builtins__ if hasattr(mod, "__builtins__") else {}):
                pass
            # Simpler approach: just mock the import at the module level
            with patch("builtins.__import__") as mock_import:
                fake_sdk = types.ModuleType("memvid_sdk")
                fake_sdk.create = mock_create
                fake_sdk.use = MagicMock()

                def custom_import(name, *args, **kwargs):
                    if name == "memvid_sdk":
                        return fake_sdk
                    return __import__(name, *args, **kwargs)

                mock_import.side_effect = custom_import
                store.open()

                mock_create.assert_called_once_with(
                    store.path, enable_vec=True, enable_lex=True
                )
                assert store.mem is mock_mem

    def test_open_existing_store(self, tmp_path):
        from mcp_server.knowledge import KnowledgeStore

        mock_mem = _make_mock_mem()
        mock_use = MagicMock(return_value=mock_mem)

        store = KnowledgeStore("existing")
        mv2_path = tmp_path / "existing.mv2"
        mv2_path.touch()  # file exists
        store.path = str(mv2_path)

        with patch("builtins.__import__") as mock_import:
            fake_sdk = types.ModuleType("memvid_sdk")
            fake_sdk.use = mock_use
            fake_sdk.create = MagicMock()

            def custom_import(name, *args, **kwargs):
                if name == "memvid_sdk":
                    return fake_sdk
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = custom_import
            store.open()

            mock_use.assert_called_once_with("basic", store.path)
            assert store.mem is mock_mem

    def test_open_idempotent(self):
        """Calling open() twice doesn't re-create the mem object."""
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem  # pretend already opened

        store.open()  # should be a no-op
        assert store.mem is mock_mem


class TestIngest:
    def test_ingest_single_document(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = _make_mock_embedder()

        result = store.ingest("My Doc", "Some content here", label="notes")

        mock_mem.put_many.assert_called_once()
        call_args = mock_mem.put_many.call_args
        docs = call_args[0][0]
        assert len(docs) == 1
        assert docs[0]["title"] == "My Doc"
        assert docs[0]["text"] == "Some content here"
        assert docs[0]["label"] == "notes"
        assert call_args[1]["embedder"] is store._embedder
        mock_mem.commit.assert_called_once()
        assert result == ["frame-1", "frame-2"]

    def test_ingest_many_batch(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None  # lex-only

        docs = [
            {"title": "A", "text": "aaa"},
            {"title": "B", "text": "bbb", "label": "code"},
        ]
        result = store.ingest_many(docs)

        call_docs = mock_mem.put_many.call_args[0][0]
        assert len(call_docs) == 2
        assert call_docs[0]["label"] == "kb"  # default
        assert call_docs[1]["label"] == "code"
        mock_mem.commit.assert_called_once()

    def test_ingest_auto_opens(self, tmp_path):
        """Ingest calls _ensure_open if mem is None."""
        from mcp_server.knowledge import KnowledgeStore

        mock_mem = _make_mock_mem()
        store = KnowledgeStore("test")
        store.mem = None
        store._embedder_checked = True
        store._embedder = None

        with patch.object(store, "open") as mock_open:
            mock_open.side_effect = lambda: setattr(store, "mem", mock_mem)
            store.ingest("title", "text")
            mock_open.assert_called_once()


class TestSearch:
    def test_search_adaptive(self):
        from mcp_server.knowledge import KnowledgeStore, DEFAULT_MIN_RELEVANCY

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = _make_mock_embedder()

        results = store.search("test query", top_k=5)

        mock_mem.find.assert_called_once()
        call_kwargs = mock_mem.find.call_args[1]
        assert call_kwargs["adaptive"] is True
        assert call_kwargs["min_relevancy"] == DEFAULT_MIN_RELEVANCY
        assert call_kwargs["adaptive_strategy"] == "combined"
        assert call_kwargs["mode"] == "auto"
        # Results trimmed to top_k
        assert len(results["hits"]) <= 5

    def test_search_non_adaptive(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("query", top_k=3, adaptive=False)

        call_kwargs = mock_mem.find.call_args[1]
        assert "adaptive" not in call_kwargs
        assert call_kwargs["k"] == 3

    def test_search_mode_passthrough(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        store.search("q", mode="lex")
        assert mock_mem.find.call_args[1]["mode"] == "lex"

    def test_search_lex_only_without_embedder(self):
        """When embedder is None, search still works (lex-only)."""
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("query")
        assert mock_mem.find.call_args[1]["embedder"] is None
        assert "hits" in results


class TestAsk:
    def test_ask_with_answer(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = _make_mock_embedder()

        result = store.ask("What is X?")

        mock_mem.ask.assert_called_once_with(
            "What is X?",
            k=8,
            mode="auto",
            context_only=False,
            embedder=store._embedder,
        )
        assert result["answer"] == "The answer is 42."
        assert len(result["hits"]) == 1

    def test_ask_context_only(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        store.ask("question", context_only=True, top_k=5)

        assert mock_mem.ask.call_args[1]["context_only"] is True
        assert mock_mem.ask.call_args[1]["k"] == 5


class TestTimeline:
    def test_timeline_basic(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True

        entries = store.timeline(since=1700000000, until=1700003600, limit=10)

        mock_mem.timeline.assert_called_once_with(
            since=1700000000, until=1700003600, limit=10
        )
        assert len(entries) == 2
        assert entries[0]["title"] == "First doc"

    def test_timeline_no_bounds(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True

        store.timeline()
        mock_mem.timeline.assert_called_once_with(limit=20)

    def test_timeline_partial_bounds(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True

        store.timeline(since=1700000000)
        mock_mem.timeline.assert_called_once_with(since=1700000000, limit=20)


class TestEnrich:
    def test_enrich_default_engine(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True

        result = store.enrich()
        mock_mem.enrich.assert_called_once_with(engine="rules")
        assert result["entities"][0]["text"] == "Python"


class TestPersistence:
    def test_close_seals_store(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem

        store.close()
        mock_mem.seal.assert_called_once()
        assert store.mem is None

    def test_close_when_not_open_is_noop(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        store.close()  # should not raise

    def test_index_survives_reopen(self, tmp_path):
        """Simulates persistence: close and reopen uses 'use' (existing file)."""
        from mcp_server.knowledge import KnowledgeStore

        mock_mem_1 = _make_mock_mem()
        mock_mem_2 = _make_mock_mem()
        mock_use = MagicMock(return_value=mock_mem_2)

        store = KnowledgeStore("persist-test")
        mv2_path = tmp_path / "persist-test.mv2"
        store.path = str(mv2_path)

        # First open: create
        store.mem = mock_mem_1
        store.close()
        assert store.mem is None

        # Simulate .mv2 existing on disk after seal
        mv2_path.touch()

        # Second open: should use existing
        with patch("builtins.__import__") as mock_import:
            fake_sdk = types.ModuleType("memvid_sdk")
            fake_sdk.use = mock_use

            def custom_import(name, *args, **kwargs):
                if name == "memvid_sdk":
                    return fake_sdk
                return __import__(name, *args, **kwargs)

            mock_import.side_effect = custom_import
            store.open()
            mock_use.assert_called_once_with("basic", str(mv2_path))


class TestGetStore:
    def test_get_store_caches(self):
        from mcp_server.knowledge import get_store

        store1 = get_store("proj-a")
        store2 = get_store("proj-a")
        assert store1 is store2

    def test_different_hashes_different_stores(self):
        from mcp_server.knowledge import get_store

        store1 = get_store("proj-a")
        store2 = get_store("proj-b")
        assert store1 is not store2

    def test_get_store_default_hash(self):
        from mcp_server.knowledge import get_store, _project_hash

        store = get_store()
        expected_hash = _project_hash()
        assert store.project_hash == expected_hash


class TestFormatHits:
    def test_format_empty(self):
        from mcp_server.knowledge import _format_hits
        assert _format_hits([]) == "No results found."

    def test_format_with_scores(self):
        from mcp_server.knowledge import _format_hits
        hits = [
            {"title": "Test", "score": 0.95, "snippet": "hello world"},
        ]
        result = _format_hits(hits)
        assert "[1] Test (score: 0.950)" in result
        assert "hello world" in result

    def test_format_without_scores(self):
        from mcp_server.knowledge import _format_hits
        hits = [{"title": "Test", "score": 0.95, "snippet": "text"}]
        result = _format_hits(hits, include_score=False)
        assert "score" not in result
        assert "[1] Test" in result

    def test_format_truncates_long_snippets(self):
        from mcp_server.knowledge import _format_hits
        hits = [{"title": "Long", "score": 0.5, "snippet": "x" * 600}]
        result = _format_hits(hits)
        assert "..." in result
        # Snippet should be truncated to ~500 chars + "..."
        assert len(result) < 700


class TestProjectHash:
    def test_deterministic(self):
        from mcp_server.knowledge import _project_hash
        h1 = _project_hash("/some/path")
        h2 = _project_hash("/some/path")
        assert h1 == h2

    def test_different_paths(self):
        from mcp_server.knowledge import _project_hash
        h1 = _project_hash("/path/a")
        h2 = _project_hash("/path/b")
        assert h1 != h2

    def test_hash_length(self):
        from mcp_server.knowledge import _project_hash
        h = _project_hash("/test")
        assert len(h) == 16


# -- MCP tool registration tests --


class TestMCPToolRegistration:
    """Test that tools register correctly and produce expected output."""

    @pytest.fixture()
    def mock_mcp(self):
        """Create a mock FastMCP that captures tool registrations."""
        mcp = MagicMock()
        registered = {}

        def tool_decorator():
            def wrapper(fn):
                registered[fn.__name__] = fn
                return fn
            return wrapper

        mcp.tool = tool_decorator
        mcp._registered = registered
        return mcp

    def test_registers_all_tools(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools
        register_knowledge_tools(mock_mcp)

        expected = {"rlm_search", "rlm_ask", "rlm_timeline", "rlm_ingest"}
        assert set(mock_mcp._registered.keys()) == expected

    def test_tools_have_docstrings(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools
        register_knowledge_tools(mock_mcp)

        for name, fn in mock_mcp._registered.items():
            assert fn.__doc__ is not None, f"{name} missing docstring"

    def test_rlm_search_tool(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        store = get_store("test-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = mock_mcp._registered["rlm_search"]
        ctx = MagicMock()
        result = _run(fn("test query", ctx, project="test-proj"))

        assert "Doc A" in result
        assert "0.920" in result

    def test_rlm_search_empty_results(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {"hits": []}
        store = get_store("empty-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = mock_mcp._registered["rlm_search"]
        ctx = MagicMock()
        result = _run(fn("nothing", ctx, project="empty-proj"))
        assert "No results found" in result

    def test_rlm_ask_tool(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        store = get_store("ask-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = mock_mcp._registered["rlm_ask"]
        ctx = MagicMock()
        result = _run(fn("What is X?", ctx, project="ask-proj"))

        assert "The answer is 42." in result
        assert "Sources" in result

    def test_rlm_ask_context_only(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        mock_mem.ask.return_value = {
            "hits": [{"title": "C", "score": 0.8, "snippet": "chunk"}],
        }
        store = get_store("ctx-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = mock_mcp._registered["rlm_ask"]
        ctx = MagicMock()
        result = _run(fn("q", ctx, context_only=True, project="ctx-proj"))

        assert "chunk" in result
        # Should NOT have "Sources" header in context-only mode
        assert "Sources" not in result

    def test_rlm_timeline_tool(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        store = get_store("tl-proj")
        store.mem = mock_mem
        store._embedder_checked = True

        fn = mock_mcp._registered["rlm_timeline"]
        ctx = MagicMock()
        result = _run(fn(ctx, since=1700000000, project="tl-proj"))

        assert "First doc" in result
        assert "Second doc" in result

    def test_rlm_timeline_empty(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        mock_mem.timeline.return_value = []
        store = get_store("empty-tl")
        store.mem = mock_mem
        store._embedder_checked = True

        fn = mock_mcp._registered["rlm_timeline"]
        ctx = MagicMock()
        result = _run(fn(ctx, project="empty-tl"))
        assert "No entries" in result

    def test_rlm_ingest_tool(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        store = get_store("ingest-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = mock_mcp._registered["rlm_ingest"]
        ctx = MagicMock()
        result = _run(fn("My Title", "Some text content", ctx, project="ingest-proj"))

        assert "Ingested" in result
        assert "My Title" in result
        mock_mem.put_many.assert_called_once()
        mock_mem.commit.assert_called_once()

    def test_rlm_search_handles_exceptions(self, mock_mcp):
        from mcp_server.knowledge import register_knowledge_tools, get_store
        register_knowledge_tools(mock_mcp)

        mock_mem = _make_mock_mem()
        mock_mem.find.side_effect = RuntimeError("index corrupted")
        store = get_store("err-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = mock_mcp._registered["rlm_search"]
        ctx = MagicMock()
        result = _run(fn("query", ctx, project="err-proj"))
        assert "Error" in result
        assert "index corrupted" in result


class TestIncrementalIndexing:
    """Verify that ingest adds to the existing index without rebuilding."""

    def test_multiple_ingests_append(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        store.ingest("Doc 1", "first text")
        store.ingest("Doc 2", "second text")
        store.ingest("Doc 3", "third text")

        assert mock_mem.put_many.call_count == 3
        assert mock_mem.commit.call_count == 3

    def test_batch_ingest_is_single_call(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        docs = [
            {"title": f"Doc {i}", "text": f"text {i}"}
            for i in range(50)
        ]
        store.ingest_many(docs)

        # Single put_many call, single commit
        assert mock_mem.put_many.call_count == 1
        assert mock_mem.commit.call_count == 1
        assert len(mock_mem.put_many.call_args[0][0]) == 50


class TestThreadFilter:
    """Thread/namespace filtering for ingest, search, and ask."""

    # -- ingest --

    def test_ingest_stores_thread_in_metadata(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        store.ingest("Doc", "content", thread="alpha")

        docs = mock_mem.put_many.call_args[0][0]
        assert docs[0]["metadata"]["thread"] == "alpha"

    def test_ingest_no_thread_leaves_metadata_empty(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        store.ingest("Doc", "content")

        docs = mock_mem.put_many.call_args[0][0]
        assert "thread" not in docs[0]["metadata"]

    def test_ingest_thread_does_not_clobber_existing_metadata(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        store.ingest("Doc", "content", metadata={"source": "wiki"}, thread="beta")

        docs = mock_mem.put_many.call_args[0][0]
        assert docs[0]["metadata"]["thread"] == "beta"
        assert docs[0]["metadata"]["source"] == "wiki"

    def test_ingest_many_stores_thread_per_doc(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        docs = [
            {"title": "A", "text": "aaa", "thread": "t1"},
            {"title": "B", "text": "bbb"},
        ]
        store.ingest_many(docs)

        prepared = mock_mem.put_many.call_args[0][0]
        assert prepared[0]["metadata"]["thread"] == "t1"
        assert "thread" not in prepared[1]["metadata"]

    # -- search --

    def test_search_filters_by_thread(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {
            "hits": [
                {"title": "A", "score": 0.9, "snippet": "s", "metadata": {"thread": "t1"}},
                {"title": "B", "score": 0.8, "snippet": "s", "metadata": {"thread": "t2"}},
                {"title": "C", "score": 0.7, "snippet": "s", "metadata": {"thread": "t1"}},
            ]
        }
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("q", thread="t1")

        assert len(results["hits"]) == 2
        assert all(h["metadata"]["thread"] == "t1" for h in results["hits"])

    def test_search_no_thread_returns_all(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {
            "hits": [
                {"title": "A", "score": 0.9, "snippet": "s", "metadata": {"thread": "t1"}},
                {"title": "B", "score": 0.8, "snippet": "s", "metadata": {}},
            ]
        }
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("q")

        # No filter: both docs returned
        assert len(results["hits"]) == 2

    def test_search_thread_no_match_returns_empty(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {
            "hits": [
                {"title": "A", "score": 0.9, "snippet": "s", "metadata": {"thread": "other"}},
            ]
        }
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("q", thread="none")

        assert results["hits"] == []

    def test_search_old_docs_without_thread_field_excluded_when_filter_set(self):
        """Old docs without metadata.thread do not match when a thread filter is active."""
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {
            "hits": [
                # old doc: no thread field at all
                {"title": "Old", "score": 0.9, "snippet": "s", "metadata": {}},
                # new doc: has matching thread
                {"title": "New", "score": 0.8, "snippet": "s", "metadata": {"thread": "t1"}},
            ]
        }
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("q", thread="t1")

        titles = [h["title"] for h in results["hits"]]
        assert "New" in titles
        assert "Old" not in titles

    def test_search_old_docs_without_thread_returned_when_no_filter(self):
        """Old docs without metadata.thread still appear when no thread filter is set (REQ-4)."""
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {
            "hits": [
                {"title": "Old", "score": 0.9, "snippet": "s", "metadata": {}},
            ]
        }
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        results = store.search("q")

        assert len(results["hits"]) == 1
        assert results["hits"][0]["title"] == "Old"

    # -- ask --

    def test_ask_filters_hits_by_thread(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        mock_mem.ask.return_value = {
            "answer": "42",
            "hits": [
                {"title": "A", "score": 0.9, "snippet": "s", "metadata": {"thread": "t1"}},
                {"title": "B", "score": 0.8, "snippet": "s", "metadata": {"thread": "t2"}},
            ],
        }
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        result = store.ask("question", thread="t1")

        assert len(result["hits"]) == 1
        assert result["hits"][0]["title"] == "A"
        assert result["answer"] == "42"

    def test_ask_no_thread_returns_all_hits(self):
        from mcp_server.knowledge import KnowledgeStore

        store = KnowledgeStore("test")
        mock_mem = _make_mock_mem()
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        result = store.ask("question")

        # Default mock has 1 hit; no filtering applied
        assert len(result["hits"]) == 1

    # -- MCP tools --

    def test_mcp_rlm_search_passes_thread(self):
        from mcp_server.knowledge import register_knowledge_tools, get_store

        mcp = MagicMock()
        registered = {}

        def tool_decorator():
            def wrapper(fn):
                registered[fn.__name__] = fn
                return fn
            return wrapper

        mcp.tool = tool_decorator
        register_knowledge_tools(mcp)

        mock_mem = _make_mock_mem()
        mock_mem.find.return_value = {
            "hits": [
                {"title": "X", "score": 0.9, "snippet": "s", "metadata": {"thread": "proj"}},
            ]
        }
        store = get_store("thread-search-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = registered["rlm_search"]
        ctx = MagicMock()
        result = _run(fn("query", ctx, project="thread-search-proj", thread="proj"))

        assert "X" in result

    def test_mcp_rlm_ingest_passes_thread(self):
        from mcp_server.knowledge import register_knowledge_tools, get_store

        mcp = MagicMock()
        registered = {}

        def tool_decorator():
            def wrapper(fn):
                registered[fn.__name__] = fn
                return fn
            return wrapper

        mcp.tool = tool_decorator
        register_knowledge_tools(mcp)

        mock_mem = _make_mock_mem()
        store = get_store("thread-ingest-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = registered["rlm_ingest"]
        ctx = MagicMock()
        _run(fn("Title", "body text", ctx, project="thread-ingest-proj", thread="session-1"))

        docs = mock_mem.put_many.call_args[0][0]
        assert docs[0]["metadata"]["thread"] == "session-1"

    def test_mcp_rlm_ask_passes_thread(self):
        from mcp_server.knowledge import register_knowledge_tools, get_store

        mcp = MagicMock()
        registered = {}

        def tool_decorator():
            def wrapper(fn):
                registered[fn.__name__] = fn
                return fn
            return wrapper

        mcp.tool = tool_decorator
        register_knowledge_tools(mcp)

        mock_mem = _make_mock_mem()
        mock_mem.ask.return_value = {
            "answer": "yes",
            "hits": [
                {"title": "Z", "score": 0.9, "snippet": "s", "metadata": {"thread": "qa"}},
            ],
        }
        store = get_store("thread-ask-proj")
        store.mem = mock_mem
        store._embedder_checked = True
        store._embedder = None

        fn = registered["rlm_ask"]
        ctx = MagicMock()
        result = _run(fn("question", ctx, project="thread-ask-proj", thread="qa"))

        assert "yes" in result
        assert "Z" in result
