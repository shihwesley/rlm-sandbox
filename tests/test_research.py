"""Tests for the compound research tool and knowledge management MCP tools.

All HTTP and KnowledgeStore interactions are mocked.
No network, Docker, or memvid installation required.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.research import (
    KNOWN_DOCS,
    _count_doc_sources,
    _fetch_single,
    _fetch_sitemap,
    _resolve_doc_urls,
    register_research_tools,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run async coroutine synchronously."""
    return asyncio.run(coro)


def _mock_response(text: str = "", status_code: int = 200) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


@pytest.fixture(autouse=True)
def _clear_store_cache():
    """Reset the singleton store cache between tests."""
    from mcp_server.knowledge import _stores
    _stores.clear()
    yield
    _stores.clear()


@pytest.fixture()
def mock_mcp():
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


# ---------------------------------------------------------------------------
# _resolve_doc_urls tests
# ---------------------------------------------------------------------------


class TestResolveDocUrls:
    def test_known_topic_returns_sitemap_and_base(self):
        urls = _resolve_doc_urls("fastapi")
        assert urls == [
            "https://fastapi.tiangolo.com/sitemap.xml",
            "https://fastapi.tiangolo.com",
        ]

    def test_known_topic_case_insensitive(self):
        urls = _resolve_doc_urls("  FastAPI  ")
        assert urls[0] == "https://fastapi.tiangolo.com/sitemap.xml"

    def test_known_topic_memvid(self):
        urls = _resolve_doc_urls("memvid")
        assert "https://docs.memvid.com/sitemap.xml" in urls

    def test_known_topic_dspy(self):
        urls = _resolve_doc_urls("dspy")
        assert urls[0] == "https://dspy.ai/sitemap.xml"

    def test_unknown_topic_returns_fallback_patterns(self):
        urls = _resolve_doc_urls("somelib")
        assert len(urls) == 4
        assert "https://docs.somelib.com/sitemap.xml" in urls
        assert "https://somelib.dev/sitemap.xml" in urls
        assert "https://somelib.readthedocs.io/sitemap.xml" in urls
        assert "https://docs.somelib.io/sitemap.xml" in urls

    def test_all_known_docs_have_valid_base_urls(self):
        for topic, base in KNOWN_DOCS.items():
            assert base.startswith("https://"), f"{topic} has invalid base: {base}"

    def test_sklearn_alias(self):
        urls = _resolve_doc_urls("sklearn")
        assert urls[0] == "https://scikit-learn.org/sitemap.xml"


# ---------------------------------------------------------------------------
# _fetch_sitemap tests
# ---------------------------------------------------------------------------


class TestFetchSitemap:
    def test_successful_sitemap(self):
        sitemap_xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
        </urlset>"""

        client = AsyncMock()

        # First call returns sitemap, subsequent calls return page content
        sitemap_resp = _mock_response(sitemap_xml)
        page_resp = _mock_response("# Page content")

        call_count = 0

        async def fake_get(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "sitemap.xml" in url:
                return sitemap_resp
            return page_resp

        client.get = fake_get

        mock_store = MagicMock()

        result = _run(_fetch_sitemap(
            client, "https://example.com/sitemap.xml", mock_store
        ))

        assert result["fetched"] == 2
        assert result["failed"] == 0
        # Two pages ingested
        assert mock_store.ingest.call_count == 2

    def test_sitemap_fetch_failure(self):
        """When the sitemap itself can't be fetched, return 0 fetched, 1 failed."""
        import httpx

        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        result = _run(_fetch_sitemap(
            client, "https://down.example.com/sitemap.xml", None
        ))

        assert result["fetched"] == 0
        assert result["failed"] == 1

    def test_empty_sitemap(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=_mock_response("<urlset></urlset>"))

        result = _run(_fetch_sitemap(
            client, "https://example.com/sitemap.xml", None
        ))

        assert result["fetched"] == 0
        assert result["failed"] == 0

    def test_no_store_still_fetches(self):
        """Fetching works even without a knowledge store (store=None)."""
        sitemap_xml = """<urlset>
            <url><loc>https://example.com/p</loc></url>
        </urlset>"""

        client = AsyncMock()

        async def fake_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(sitemap_xml)
            return _mock_response("# Content")

        client.get = fake_get

        result = _run(_fetch_sitemap(
            client, "https://example.com/sitemap.xml", None
        ))

        assert result["fetched"] == 1

    def test_ingest_failure_does_not_block_fetching(self):
        """If store.ingest raises, the page is still counted as fetched."""
        sitemap_xml = """<urlset>
            <url><loc>https://example.com/ok</loc></url>
        </urlset>"""

        client = AsyncMock()

        async def fake_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(sitemap_xml)
            return _mock_response("# Works")

        client.get = fake_get

        mock_store = MagicMock()
        mock_store.ingest.side_effect = RuntimeError("store broken")

        result = _run(_fetch_sitemap(
            client, "https://example.com/sitemap.xml", mock_store
        ))

        # Page fetched successfully even though ingest failed
        assert result["fetched"] == 1


# ---------------------------------------------------------------------------
# _fetch_single tests
# ---------------------------------------------------------------------------


class TestFetchSingle:
    def test_success(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=_mock_response("# Hello"))

        result = _run(_fetch_single(
            client, "https://example.com/page", None, force=True
        ))

        assert result["ok"] is True
        assert result["error"] is None

    def test_success_with_store(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=_mock_response("# Data"))

        mock_store = MagicMock()

        result = _run(_fetch_single(
            client, "https://docs.testlib.com/guide", mock_store, force=True
        ))

        assert result["ok"] is True
        mock_store.ingest.assert_called_once()

    def test_failure(self):
        import httpx

        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("nope"))

        result = _run(_fetch_single(
            client, "https://down.example.com/x", None, force=True
        ))

        assert result["ok"] is False
        assert result["error"] is not None

    def test_ingest_error_still_ok(self):
        """If ingest fails, the fetch itself is still considered successful."""
        client = AsyncMock()
        client.get = AsyncMock(return_value=_mock_response("# Stuff"))

        mock_store = MagicMock()
        mock_store.ingest.side_effect = RuntimeError("boom")

        result = _run(_fetch_single(
            client, "https://example.com/x", mock_store, force=True
        ))

        assert result["ok"] is True


# ---------------------------------------------------------------------------
# _count_doc_sources tests
# ---------------------------------------------------------------------------


class TestCountDocSources:
    def test_no_docs_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.research.DOCS_BASE", tmp_path / "nope")
        assert _count_doc_sources() == {}

    def test_with_libraries(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.research.DOCS_BASE", tmp_path)

        (tmp_path / "fastapi").mkdir()
        (tmp_path / "fastapi" / "index.md").write_text("# Index")
        (tmp_path / "fastapi" / "tutorial.md").write_text("# Tutorial")
        (tmp_path / "dspy").mkdir()
        (tmp_path / "dspy" / "api.md").write_text("# API")

        sources = _count_doc_sources()
        assert sources == {"fastapi": 2, "dspy": 1}

    def test_empty_library_dir_excluded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("mcp_server.research.DOCS_BASE", tmp_path)

        (tmp_path / "empty_lib").mkdir()
        # No .md files inside

        sources = _count_doc_sources()
        assert sources == {}


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_registers_all_tools(self, mock_mcp):
        register_research_tools(mock_mcp)
        expected = {"rlm_research", "rlm_knowledge_status", "rlm_knowledge_clear"}
        assert set(mock_mcp._registered.keys()) == expected

    def test_tools_have_docstrings(self, mock_mcp):
        register_research_tools(mock_mcp)
        for name, fn in mock_mcp._registered.items():
            assert fn.__doc__ is not None, f"{name} missing docstring"


# ---------------------------------------------------------------------------
# rlm_research tool
# ---------------------------------------------------------------------------


class TestRlmResearch:
    @pytest.fixture()
    def tools(self, mock_mcp):
        register_research_tools(mock_mcp)
        return mock_mcp._registered

    def _make_ctx(self, http_client=None, store=None):
        ctx = MagicMock()
        app = MagicMock()
        app.http = http_client or AsyncMock()
        app.knowledge_store = store
        ctx.request_context.lifespan_context = app
        return ctx

    def test_known_topic_sitemap_success(self, tools):
        """Known topic with working sitemap indexes pages."""
        sitemap_xml = """<urlset>
            <url><loc>https://fastapi.tiangolo.com/tutorial/</loc></url>
            <url><loc>https://fastapi.tiangolo.com/advanced/</loc></url>
        </urlset>"""

        client = AsyncMock()

        async def fake_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(sitemap_xml)
            return _mock_response("# Page content here")

        client.get = fake_get
        ctx = self._make_ctx(http_client=client)

        result = _run(tools["rlm_research"]("fastapi", ctx))

        assert "Indexed 2 pages" in result
        assert "fastapi" in result
        assert "rlm_search" in result

    def test_known_topic_sitemap_fails_fallback_to_base(self, tools):
        """If sitemap fails, fall back to base URL fetch."""
        import httpx

        client = AsyncMock()

        call_urls = []

        async def fake_get(url, **kwargs):
            call_urls.append(url)
            if "sitemap" in url:
                raise httpx.ConnectError("nope")
            return _mock_response("# Docs homepage")

        client.get = fake_get
        ctx = self._make_ctx(http_client=client)

        result = _run(tools["rlm_research"]("memvid", ctx))

        assert "Indexed 1 pages" in result

    def test_unknown_topic_all_fail(self, tools):
        """Unknown topic where all URL patterns fail."""
        import httpx

        client = AsyncMock()
        client.get = AsyncMock(side_effect=httpx.ConnectError("all down"))

        ctx = self._make_ctx(http_client=client)

        result = _run(tools["rlm_research"]("nonexistent_obscure_lib", ctx))

        assert "Could not fetch" in result
        assert "nonexistent_obscure_lib" in result
        assert "rlm_fetch" in result

    def test_unknown_topic_first_sitemap_works(self, tools):
        """Unknown topic where the first fallback pattern returns a sitemap."""
        sitemap_xml = """<urlset>
            <url><loc>https://docs.newlib.com/intro</loc></url>
        </urlset>"""

        client = AsyncMock()

        async def fake_get(url, **kwargs):
            if url == "https://docs.newlib.com/sitemap.xml":
                return _mock_response(sitemap_xml)
            if "sitemap" in url:
                raise Exception("other sitemaps fail")
            return _mock_response("# intro page")

        client.get = fake_get
        ctx = self._make_ctx(http_client=client)

        result = _run(tools["rlm_research"]("newlib", ctx))

        assert "Indexed 1 pages" in result

    def test_research_with_knowledge_store(self, tools):
        """rlm_research uses the knowledge store from the app context."""
        sitemap_xml = """<urlset>
            <url><loc>https://dspy.ai/getting-started</loc></url>
        </urlset>"""

        client = AsyncMock()

        async def fake_get(url, **kwargs):
            if "sitemap" in url:
                return _mock_response(sitemap_xml)
            return _mock_response("# Getting Started with DSPy")

        client.get = fake_get

        mock_store = MagicMock()
        ctx = self._make_ctx(http_client=client, store=mock_store)

        result = _run(tools["rlm_research"]("dspy", ctx))

        assert "Indexed 1 pages" in result
        mock_store.ingest.assert_called_once()


# ---------------------------------------------------------------------------
# rlm_knowledge_status tool
# ---------------------------------------------------------------------------


class TestRlmKnowledgeStatus:
    @pytest.fixture()
    def tools(self, mock_mcp):
        register_research_tools(mock_mcp)
        return mock_mcp._registered

    def test_status_no_store_file(self, tools, tmp_path):
        """Status when the .mv2 file doesn't exist yet."""
        from mcp_server.knowledge import get_store

        store = get_store("status-test")
        store.path = str(tmp_path / "nonexistent.mv2")

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="status-test"):
            result = _run(tools["rlm_knowledge_status"](ctx))

        assert "not created yet" in result
        assert "Knowledge Store" in result

    def test_status_with_existing_store(self, tools, tmp_path):
        """Status when the .mv2 file exists."""
        from mcp_server.knowledge import get_store

        store = get_store("exists-test")
        mv2 = tmp_path / "exists.mv2"
        mv2.write_bytes(b"x" * 2048)
        store.path = str(mv2)

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="exists-test"), \
             patch("mcp_server.research._count_doc_sources", return_value={"fastapi": 15, "dspy": 8}):
            result = _run(tools["rlm_knowledge_status"](ctx))

        assert "2.0 KB" in result
        assert "fastapi: 15" in result
        assert "dspy: 8" in result
        assert "2 libraries" in result

    def test_status_no_sources(self, tools, tmp_path):
        """Status when no doc sources exist."""
        from mcp_server.knowledge import get_store

        store = get_store("nosrc-test")
        mv2 = tmp_path / "nosrc.mv2"
        mv2.write_bytes(b"x" * 512)
        store.path = str(mv2)

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="nosrc-test"), \
             patch("mcp_server.research._count_doc_sources", return_value={}):
            result = _run(tools["rlm_knowledge_status"](ctx))

        assert "0 libraries" in result
        assert "(none)" in result

    def test_status_with_project_override(self, tools, tmp_path):
        """Explicit project hash overrides the cwd-based default."""
        from mcp_server.knowledge import get_store

        store = get_store("override-proj")
        mv2 = tmp_path / "override.mv2"
        mv2.write_bytes(b"data")
        store.path = str(mv2)

        ctx = MagicMock()

        with patch("mcp_server.research._count_doc_sources", return_value={}):
            result = _run(tools["rlm_knowledge_status"](ctx, project="override-proj"))

        assert str(mv2) in result or "override" in result.lower()


# ---------------------------------------------------------------------------
# rlm_knowledge_clear tool
# ---------------------------------------------------------------------------


class TestRlmKnowledgeClear:
    @pytest.fixture()
    def tools(self, mock_mcp):
        register_research_tools(mock_mcp)
        return mock_mcp._registered

    def test_clear_existing_store(self, tools, tmp_path):
        """Clearing an existing store removes the file and resets the cache."""
        from mcp_server.knowledge import get_store, _stores

        store = get_store("clear-test")
        mv2 = tmp_path / "clear.mv2"
        mv2.write_bytes(b"indexed data")
        store.path = str(mv2)
        store.mem = MagicMock()

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="clear-test"):
            result = _run(tools["rlm_knowledge_clear"](ctx))

        assert "Cleared" in result
        assert not mv2.exists()
        assert "clear-test" not in _stores

    def test_clear_nonexistent_store(self, tools, tmp_path):
        """Clearing when no .mv2 file exists still works (no error)."""
        from mcp_server.knowledge import get_store

        store = get_store("ghost-test")
        store.path = str(tmp_path / "ghost.mv2")

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="ghost-test"):
            result = _run(tools["rlm_knowledge_clear"](ctx))

        assert "already clean" in result

    def test_clear_calls_store_close(self, tools, tmp_path):
        """Clearing calls close() on the store before deleting."""
        from mcp_server.knowledge import get_store

        store = get_store("close-test")
        mv2 = tmp_path / "close.mv2"
        mv2.write_bytes(b"data")
        store.path = str(mv2)
        mock_mem = MagicMock()
        store.mem = mock_mem

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="close-test"):
            _run(tools["rlm_knowledge_clear"](ctx))

        # seal should have been called via close()
        mock_mem.seal.assert_called_once()

    def test_clear_with_project_override(self, tools, tmp_path):
        """Explicit project hash clears the right store."""
        from mcp_server.knowledge import get_store, _stores

        store = get_store("specific-proj")
        mv2 = tmp_path / "specific.mv2"
        mv2.write_bytes(b"data")
        store.path = str(mv2)
        store.mem = MagicMock()

        ctx = MagicMock()
        result = _run(tools["rlm_knowledge_clear"](ctx, project="specific-proj"))

        assert "Cleared" in result
        assert not mv2.exists()
        assert "specific-proj" not in _stores

    def test_clear_resets_cache_for_fresh_access(self, tools, tmp_path):
        """After clear, get_store() returns a new instance."""
        from mcp_server.knowledge import get_store, _stores

        store_before = get_store("recycle-test")
        mv2 = tmp_path / "recycle.mv2"
        mv2.write_bytes(b"old")
        store_before.path = str(mv2)
        store_before.mem = MagicMock()

        ctx = MagicMock()

        with patch("mcp_server.research._project_hash", return_value="recycle-test"):
            _run(tools["rlm_knowledge_clear"](ctx))

        # New get_store call should create a fresh instance
        store_after = get_store("recycle-test")
        assert store_after is not store_before
        assert store_after.mem is None


# ---------------------------------------------------------------------------
# Cleanup: remove any .claude/docs files created during tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_docs():
    """Remove any docs files created during testing."""
    yield
    import shutil
    from mcp_server.fetcher import DOCS_BASE
    docs_dir = Path(DOCS_BASE)
    if docs_dir.exists():
        shutil.rmtree(docs_dir, ignore_errors=True)
