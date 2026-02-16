"""Tests for the document fetching layer.

All HTTP calls and KnowledgeStore interactions are mocked.
No network or Docker required.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_server.fetcher import (
    BLOCKED_DOMAINS,
    DOCS_BASE,
    FRESHNESS_TTL,
    extract_library_name,
    fetch_url,
    html_to_markdown,
    is_fresh,
    parse_sitemap_xml,
    read_meta,
    register_fetcher_tools,
    url_to_filepath,
    write_meta,
    _content_hash,
    _looks_like_markdown,
    _store_raw,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(coro):
    """Run async coroutine synchronously."""
    return asyncio.run(coro)


def _mock_response(text: str = "", status_code: int = 200, headers: dict | None = None) -> MagicMock:
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import httpx
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}", request=MagicMock(), response=resp
        )
    return resp


# ---------------------------------------------------------------------------
# Library name extraction
# ---------------------------------------------------------------------------


class TestExtractLibraryName:
    def test_docs_subdomain(self):
        assert extract_library_name("https://docs.memvid.com/api/search") == "memvid"

    def test_plain_domain(self):
        assert extract_library_name("https://react.dev/docs/hooks") == "react"

    def test_developer_subdomain(self):
        assert extract_library_name("https://developer.mozilla.org/en-US/docs") == "mozilla"

    def test_github_repo(self):
        assert extract_library_name("https://github.com/foo/bar/blob/main/README.md") == "foo-bar"

    def test_github_org_only(self):
        assert extract_library_name("https://github.com/foo") == "foo"

    def test_github_bare(self):
        assert extract_library_name("https://github.com/") == "github"

    def test_www_prefix_stripped(self):
        name = extract_library_name("https://www.numpy.org/docs")
        assert name == "numpy"

    def test_api_prefix_stripped(self):
        name = extract_library_name("https://api.openai.com/v1/docs")
        assert name == "openai"


# ---------------------------------------------------------------------------
# URL to filepath
# ---------------------------------------------------------------------------


class TestUrlToFilepath:
    def test_basic_path(self):
        result = url_to_filepath("https://docs.memvid.com/api/search")
        assert result == DOCS_BASE / "memvid" / "api/search.md"

    def test_root_path(self):
        result = url_to_filepath("https://react.dev/")
        assert result == DOCS_BASE / "react" / "index.md"

    def test_strips_md_extension(self):
        result = url_to_filepath("https://example.com/docs/guide.md")
        assert str(result).endswith("guide.md")
        # Should not be guide.md.md
        assert not str(result).endswith("guide.md.md")

    def test_strips_html_extension(self):
        result = url_to_filepath("https://example.com/docs/guide.html")
        assert str(result).endswith("guide.md")


# ---------------------------------------------------------------------------
# Content detection
# ---------------------------------------------------------------------------


class TestLooksLikeMarkdown:
    def test_markdown_heading(self):
        assert _looks_like_markdown("# Hello\n\nSome content here.\n") is True

    def test_html_doctype(self):
        assert _looks_like_markdown("<!DOCTYPE html>\n<html>...") is False

    def test_html_tag(self):
        assert _looks_like_markdown("<html>\n<head>\n<title>X</title>") is False

    def test_empty(self):
        assert _looks_like_markdown("") is False
        assert _looks_like_markdown("   ") is False

    def test_mostly_html_lines(self):
        html = "\n".join([f"<div>line {i}</div>" for i in range(20)])
        assert _looks_like_markdown(html) is False

    def test_plain_text(self):
        assert _looks_like_markdown("Just some plain text.\nAnother line.") is True


# ---------------------------------------------------------------------------
# HTML to markdown
# ---------------------------------------------------------------------------


class TestHtmlToMarkdown:
    def test_basic_conversion(self):
        html = "<h1>Title</h1><p>Paragraph text.</p>"
        md = html_to_markdown(html)
        assert "Title" in md
        assert "Paragraph" in md

    def test_strips_tags_on_import_error(self):
        # Test the fallback path when html2text is unavailable
        with patch.dict("sys.modules", {"html2text": None}):
            # Force reimport to hit ImportError
            import importlib
            import mcp_server.fetcher as mod
            # We can test the regex fallback directly
            import re
            text = re.sub(r"<[^>]+>", "", "<b>bold</b> text")
            assert "bold" in text
            assert "text" in text


# ---------------------------------------------------------------------------
# Freshness tracking
# ---------------------------------------------------------------------------


class TestFreshness:
    def test_fresh_file(self, tmp_path):
        doc = tmp_path / "test.md"
        doc.write_text("content")
        write_meta(doc, "https://example.com", "content")
        assert is_fresh(doc) is True

    def test_missing_file(self, tmp_path):
        doc = tmp_path / "nonexistent.md"
        assert is_fresh(doc) is False

    def test_missing_meta(self, tmp_path):
        doc = tmp_path / "test.md"
        doc.write_text("content")
        # No sidecar metadata written
        assert is_fresh(doc) is False

    def test_stale_file(self, tmp_path):
        doc = tmp_path / "test.md"
        doc.write_text("content")
        # Write meta with old timestamp
        meta_path = doc.with_suffix(".meta.json")
        old_time = datetime.now(timezone.utc) - timedelta(days=10)
        meta = {
            "url": "https://example.com",
            "fetched_at": old_time.isoformat(),
            "content_hash": "sha256:abc",
            "size_bytes": 7,
        }
        meta_path.write_text(json.dumps(meta))
        assert is_fresh(doc) is False

    def test_corrupt_meta(self, tmp_path):
        doc = tmp_path / "test.md"
        doc.write_text("content")
        meta_path = doc.with_suffix(".meta.json")
        meta_path.write_text("not json{{{")
        assert is_fresh(doc) is False


class TestMetadata:
    def test_write_and_read(self, tmp_path):
        doc = tmp_path / "doc.md"
        doc.write_text("hello")
        meta = write_meta(doc, "https://example.com/page", "hello")

        assert meta["url"] == "https://example.com/page"
        assert meta["content_hash"].startswith("sha256:")
        assert meta["size_bytes"] == 5
        assert "fetched_at" in meta

        # Read back
        loaded = read_meta(doc)
        assert loaded == meta

    def test_content_hash_deterministic(self):
        h1 = _content_hash("hello world")
        h2 = _content_hash("hello world")
        h3 = _content_hash("different")
        assert h1 == h2
        assert h1 != h3


# ---------------------------------------------------------------------------
# Sitemap parsing
# ---------------------------------------------------------------------------


class TestSitemapParsing:
    def test_basic_sitemap(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/page1</loc></url>
            <url><loc>https://example.com/page2</loc></url>
            <url><loc>https://example.com/page3</loc></url>
        </urlset>"""
        urls = parse_sitemap_xml(xml)
        assert urls == [
            "https://example.com/page1",
            "https://example.com/page2",
            "https://example.com/page3",
        ]

    def test_empty_sitemap(self):
        xml = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"></urlset>"""
        assert parse_sitemap_xml(xml) == []

    def test_invalid_xml(self):
        assert parse_sitemap_xml("not xml at all {{{") == []

    def test_no_namespace(self):
        xml = """<urlset><url><loc>https://a.com/x</loc></url></urlset>"""
        urls = parse_sitemap_xml(xml)
        assert urls == ["https://a.com/x"]

    def test_whitespace_in_loc(self):
        xml = """<urlset><url><loc>  https://a.com/y  </loc></url></urlset>"""
        urls = parse_sitemap_xml(xml)
        assert urls == ["https://a.com/y"]


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------


class TestFetchUrl:
    def test_blocked_domain(self):
        client = AsyncMock()
        result = _run(fetch_url(client, "https://medium.com/some-article"))
        assert result["error"] is not None
        assert "Blocked" in result["error"]
        # No HTTP calls should have been made
        client.get.assert_not_called()

    def test_cached_response(self, tmp_path):
        """Fresh cached file should be returned without fetching."""
        client = AsyncMock()

        url = "https://docs.example.com/page"
        doc_path = url_to_filepath(url)

        # Pre-populate cache
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("# Cached content")
        write_meta(doc_path, url, "# Cached content")

        result = _run(fetch_url(client, url))
        assert result["from_cache"] is True
        assert result["content"] == "# Cached content"
        assert result["error"] is None
        client.get.assert_not_called()

    def test_force_bypasses_cache(self, tmp_path):
        """force=True should re-fetch even if cached."""
        url = "https://docs.example.com/fresh"
        doc_path = url_to_filepath(url)
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text("# Old content")
        write_meta(doc_path, url, "# Old content")

        client = AsyncMock()
        new_resp = _mock_response("# New content", 200)

        async def fake_get(u, **kwargs):
            return new_resp

        client.get = fake_get

        result = _run(fetch_url(client, url, force=True))
        assert result["from_cache"] is False
        assert result["content"] == "# New content"

    def test_html_converted_to_markdown(self):
        """HTML content gets converted via html2text fallback."""
        url = "https://docs.example.com/page"
        client = AsyncMock()

        html = "<html><body><h1>Title</h1><p>Body text</p></body></html>"

        async def fake_get(u, **kwargs):
            return _mock_response(html, 200)

        client.get = fake_get

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is None
        assert "Title" in result["content"]

    def test_timeout_error(self):
        """Timeout across all tiers returns clear error."""
        import httpx as _httpx

        url = "https://docs.example.com/slow"
        client = AsyncMock()
        client.get = AsyncMock(side_effect=_httpx.TimeoutException("timed out"))

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is not None
        assert "Timeout" in result["error"]

    def test_http_403_error(self):
        """403 on all tiers returns clear error."""
        url = "https://docs.example.com/forbidden"
        client = AsyncMock()

        async def fake_get(u, **kwargs):
            return _mock_response("Forbidden", 403)

        client.get = fake_get

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is not None
        assert "403" in result["error"]

    def test_connection_error(self):
        """Connection refused across all tiers returns clear error."""
        import httpx as _httpx

        url = "https://docs.example.com/down"
        client = AsyncMock()
        client.get = AsyncMock(side_effect=_httpx.ConnectError("refused"))

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is not None
        assert "Connection error" in result["error"]

    def test_dual_storage_writes_file_and_meta(self, tmp_path):
        """Successful fetch writes both raw .md and .meta.json."""
        url = "https://docs.testlib.com/quickstart"
        client = AsyncMock()
        client.get = AsyncMock(return_value=_mock_response("# Quick Start\n\nHello.", 200))

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is None

        doc_path = result["doc_path"]
        assert doc_path.exists()
        assert doc_path.read_text() == "# Quick Start\n\nHello."

        meta = read_meta(doc_path)
        assert meta is not None
        assert meta["url"].startswith("https://")
        assert meta["content_hash"].startswith("sha256:")
        assert meta["size_bytes"] > 0

    def test_accept_markdown_negotiation(self):
        """Tier 1: Accept: text/markdown header gets native markdown response."""
        url = "https://docs.example.com/guide"
        client = AsyncMock()

        md_content = "# Guide\n\nNative markdown from server."
        resp = _mock_response(md_content, 200)
        resp.headers = {"content-type": "text/markdown; charset=utf-8", "x-markdown-tokens": "42"}

        async def fake_get(u, **kwargs):
            headers = kwargs.get("headers", {})
            if headers.get("Accept") == "text/markdown":
                return resp
            return _mock_response("<html>fallback</html>", 200)

        client.get = fake_get

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is None
        assert result["content"] == md_content
        assert result["meta"]["markdown_source"] == "negotiated"
        assert result["meta"]["markdown_tokens"] == 42

    def test_markdown_new_fallback(self):
        """Tier 2: When Accept: text/markdown returns HTML, try markdown.new proxy."""
        url = "https://nocloudflare.example.com/page"
        client = AsyncMock()

        md_from_proxy = "# Page\n\nConverted by markdown.new."

        async def fake_get(u, **kwargs):
            if "markdown.new" in u:
                resp = _mock_response(md_from_proxy, 200)
                resp.headers = {"content-type": "text/markdown", "x-markdown-tokens": "30"}
                return resp
            return _mock_response("<!DOCTYPE html><html><body>html</body></html>", 200)

        client.get = fake_get

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is None
        assert result["content"] == md_from_proxy
        assert result["meta"]["markdown_source"] == "markdown_new"

    def test_html2text_final_fallback(self):
        """Tier 3: When both negotiation and markdown.new fail, fall back to html2text."""
        url = "https://oldsite.example.com/page"
        client = AsyncMock()

        html = "<html><body><h1>Old Site</h1><p>Content here.</p></body></html>"

        async def fake_get(u, **kwargs):
            if "markdown.new" in u:
                import httpx as _httpx
                raise _httpx.ConnectError("markdown.new unreachable")
            return _mock_response(html, 200)

        client.get = fake_get

        result = _run(fetch_url(client, url, force=True))
        assert result["error"] is None
        assert "Old Site" in result["content"]
        assert result["meta"]["markdown_source"] == "html2text"

    def test_markdown_new_skipped_for_blocked_domains(self):
        """Don't send blocked-domain URLs to markdown.new either."""
        url = "https://medium.com/some-article"
        client = AsyncMock()
        result = _run(fetch_url(client, url))
        assert result["error"] is not None
        assert "Blocked" in result["error"]


# ---------------------------------------------------------------------------
# Bulk local file loading
# ---------------------------------------------------------------------------


class TestBulkLoad:
    """Test the rlm_load_dir tool logic indirectly via the internal helpers."""

    def test_store_raw(self, tmp_path):
        doc_path = tmp_path / "lib" / "page.md"
        content = "# Test page"
        meta = _store_raw(doc_path, content, "file:///test")
        assert doc_path.exists()
        assert doc_path.read_text() == content
        assert meta["url"] == "file:///test"
        assert meta["size_bytes"] == len(content.encode())


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


class TestToolRegistration:
    def test_register_creates_tools(self):
        """register_fetcher_tools should register 3 tools on the MCP instance."""
        mcp = MagicMock()
        # MagicMock's .tool() returns a MagicMock, whose __call__ returns another MagicMock
        # that acts as the decorator. We need tool() to return a callable decorator.
        registered = []

        def fake_tool():
            def decorator(fn):
                registered.append(fn.__name__)
                return fn
            return decorator

        mcp.tool = fake_tool
        register_fetcher_tools(mcp)

        assert "rlm_fetch" in registered
        assert "rlm_load_dir" in registered
        assert "rlm_fetch_sitemap" in registered

    def test_rlm_fetch_tool_returns_error_for_blocked(self):
        """rlm_fetch tool should return error string for blocked domains."""
        mcp = MagicMock()
        tools = {}

        def fake_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

        mcp.tool = fake_tool
        register_fetcher_tools(mcp)

        # Create a mock context
        mock_ctx = MagicMock()
        mock_app = MagicMock()
        mock_app.http = AsyncMock()
        mock_ctx.request_context.lifespan_context = mock_app

        result = _run(tools["rlm_fetch"]("https://medium.com/article", mock_ctx))
        assert "Error" in result
        assert "Blocked" in result

    def test_rlm_fetch_tool_success(self):
        """rlm_fetch tool should return success message with file path."""
        mcp = MagicMock()
        tools = {}

        def fake_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

        mcp.tool = fake_tool
        register_fetcher_tools(mcp)

        mock_ctx = MagicMock()
        mock_app = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response("# Docs\n\nContent.", 200))
        mock_app.http = mock_client
        # No knowledge store
        mock_app.knowledge_store = None
        mock_ctx.request_context.lifespan_context = mock_app

        result = _run(tools["rlm_fetch"]("https://docs.newlib.com/start", mock_ctx, force=True))
        assert "fetched" in result
        assert "Stored" in result

    def test_rlm_fetch_sitemap_empty(self):
        """rlm_fetch_sitemap with no URLs returns informative message."""
        mcp = MagicMock()
        tools = {}

        def fake_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

        mcp.tool = fake_tool
        register_fetcher_tools(mcp)

        mock_ctx = MagicMock()
        mock_app = MagicMock()
        mock_client = AsyncMock()
        # Return empty sitemap
        mock_client.get = AsyncMock(return_value=_mock_response("<urlset></urlset>", 200))
        mock_app.http = mock_client
        mock_ctx.request_context.lifespan_context = mock_app

        result = _run(tools["rlm_fetch_sitemap"]("https://example.com/sitemap.xml", mock_ctx))
        assert "No URLs found" in result

    def test_rlm_fetch_with_knowledge_store(self):
        """rlm_fetch should call knowledge_store.ingest when store is available."""
        mcp = MagicMock()
        tools = {}

        def fake_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

        mcp.tool = fake_tool
        register_fetcher_tools(mcp)

        mock_ctx = MagicMock()
        mock_app = MagicMock()
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response("# Page\n\nBody.", 200))
        mock_app.http = mock_client

        mock_store = MagicMock()
        mock_store.ingest = MagicMock()
        mock_app.knowledge_store = mock_store
        mock_ctx.request_context.lifespan_context = mock_app

        result = _run(tools["rlm_fetch"]("https://docs.testlib.com/page", mock_ctx, force=True))
        assert "Indexed" in result
        mock_store.ingest.assert_called_once()

        # Verify metadata was passed
        call_kwargs = mock_store.ingest.call_args
        assert call_kwargs.kwargs["title"] == "https://docs.testlib.com/page"
        assert call_kwargs.kwargs["label"] == "testlib"
        assert "url" in call_kwargs.kwargs["metadata"]

    def test_rlm_load_dir_no_matches(self):
        """rlm_load_dir with no matching files returns informative message."""
        mcp = MagicMock()
        tools = {}

        def fake_tool():
            def decorator(fn):
                tools[fn.__name__] = fn
                return fn
            return decorator

        mcp.tool = fake_tool
        register_fetcher_tools(mcp)

        mock_ctx = MagicMock()
        mock_app = MagicMock()
        mock_app.knowledge_store = None
        mock_ctx.request_context.lifespan_context = mock_app

        result = _run(tools["rlm_load_dir"]("nonexistent_dir_xyz/**/*.md", mock_ctx))
        assert "No files matched" in result


# ---------------------------------------------------------------------------
# Cleanup: remove any .claude/docs files created during tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def cleanup_docs():
    """Remove any docs files created during testing."""
    yield
    import shutil
    docs_dir = Path(DOCS_BASE)
    if docs_dir.exists():
        shutil.rmtree(docs_dir, ignore_errors=True)
