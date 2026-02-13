"""Compound research tool and knowledge management MCP tools.

Wires the memvid knowledge store into orchestration workflows:
- rlm_research(topic) — find docs, fetch, index
- rlm_knowledge_status() — show what's indexed
- rlm_knowledge_clear() — wipe the .mv2 index
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from mcp_server.fetcher import (
    extract_library_name,
    fetch_url,
    parse_sitemap_xml,
    DOCS_BASE,
)
from mcp_server.knowledge import KnowledgeStore, get_store, _project_hash, _stores

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Known doc URL mappings
# ---------------------------------------------------------------------------

KNOWN_DOCS: dict[str, str] = {
    "fastapi": "https://fastapi.tiangolo.com",
    "memvid": "https://docs.memvid.com",
    "dspy": "https://dspy.ai",
    "pydantic": "https://docs.pydantic.dev",
    "httpx": "https://www.python-httpx.org",
    "starlette": "https://www.starlette.io",
    "uvicorn": "https://www.uvicorn.org",
    "sqlmodel": "https://sqlmodel.tiangolo.com",
    "typer": "https://typer.tiangolo.com",
    "polars": "https://docs.pola.rs",
    "pytest": "https://docs.pytest.org",
    "click": "https://click.palletsprojects.com",
    "flask": "https://flask.palletsprojects.com",
    "django": "https://docs.djangoproject.com",
    "numpy": "https://numpy.org",
    "pandas": "https://pandas.pydata.org",
    "scikit-learn": "https://scikit-learn.org",
    "sklearn": "https://scikit-learn.org",
    "torch": "https://pytorch.org",
    "pytorch": "https://pytorch.org",
    "transformers": "https://huggingface.co/docs/transformers",
    "langchain": "https://python.langchain.com",
    "llamaindex": "https://docs.llamaindex.ai",
    "llama-index": "https://docs.llamaindex.ai",
    "openai": "https://platform.openai.com/docs",
    "anthropic": "https://docs.anthropic.com",
}


def _resolve_doc_urls(topic: str) -> list[str]:
    """Map a topic name to likely documentation URLs.

    Checks the known mapping first, then falls back to common patterns
    (docs.X.com, X.dev, X.readthedocs.io, docs.X.io).
    """
    topic_lower = topic.lower().strip()

    if topic_lower in KNOWN_DOCS:
        base = KNOWN_DOCS[topic_lower]
        return [f"{base}/sitemap.xml", base]

    return [
        f"https://docs.{topic_lower}.com/sitemap.xml",
        f"https://{topic_lower}.dev/sitemap.xml",
        f"https://{topic_lower}.readthedocs.io/sitemap.xml",
        f"https://docs.{topic_lower}.io/sitemap.xml",
    ]


# ---------------------------------------------------------------------------
# Internal fetch helpers
# ---------------------------------------------------------------------------


async def _fetch_sitemap(
    http_client: Any,
    sitemap_url: str,
    store: KnowledgeStore | None,
    *,
    force: bool = False,
) -> dict[str, int]:
    """Fetch a sitemap and all pages listed in it. Returns {fetched, failed}."""
    import asyncio

    try:
        resp = await http_client.get(sitemap_url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        log.warning("Sitemap fetch failed for %s: %s", sitemap_url, exc)
        return {"fetched": 0, "failed": 1}

    urls = parse_sitemap_xml(resp.text)
    if not urls:
        return {"fetched": 0, "failed": 0}

    library = extract_library_name(sitemap_url)
    fetched = 0
    failed = 0

    for page_url in urls:
        result = await fetch_url(http_client, page_url, force=force)
        if result.get("error"):
            failed += 1
        else:
            fetched += 1
            # Ingest into knowledge store if available
            if store is not None and result.get("content"):
                try:
                    store.ingest(
                        title=page_url,
                        text=result["content"],
                        label=library,
                        metadata=result.get("meta") or {},
                    )
                except Exception as exc:
                    log.warning("Ingest failed for %s: %s", page_url, exc)

        await asyncio.sleep(0.1)  # rate limit

    return {"fetched": fetched, "failed": failed}


async def _fetch_single(
    http_client: Any,
    url: str,
    store: KnowledgeStore | None,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch a single URL and optionally ingest it. Returns {ok, error}."""
    result = await fetch_url(http_client, url, force=force)
    if result.get("error"):
        return {"ok": False, "error": result["error"]}

    if store is not None and result.get("content"):
        library = extract_library_name(url)
        try:
            store.ingest(
                title=url,
                text=result["content"],
                label=library,
                metadata=result.get("meta") or {},
            )
        except Exception as exc:
            log.warning("Ingest failed for %s: %s", url, exc)

    return {"ok": True, "error": None}


# ---------------------------------------------------------------------------
# Helpers shared by tool functions
# ---------------------------------------------------------------------------


def _ctx(ctx: Context) -> Any:
    return ctx.request_context.lifespan_context


def _get_store_from_ctx(ctx: Context) -> KnowledgeStore | None:
    """Pull the KnowledgeStore from the app context, if wired."""
    try:
        app = _ctx(ctx)
        return getattr(app, "knowledge_store", None)
    except Exception:
        return None


def _count_doc_sources() -> dict[str, int]:
    """Count raw .md files per library under the docs base directory."""
    sources: dict[str, int] = {}
    docs_dir = Path(DOCS_BASE)
    if not docs_dir.exists():
        return sources
    for lib_dir in docs_dir.iterdir():
        if lib_dir.is_dir():
            files = list(lib_dir.glob("**/*.md"))
            if files:
                sources[lib_dir.name] = len(files)
    return sources


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_research_tools(mcp) -> None:
    """Register research and knowledge management tools on the MCP server."""

    @mcp.tool()
    async def rlm_research(topic: str, ctx: Context) -> str:
        """Research a topic: find docs, fetch them, index into the knowledge store.

        Tries known doc URLs first, then common patterns (sitemap.xml, direct pages).
        Results are indexed so you can query them with rlm_search afterwards.

        Args:
            topic: Library or topic name (e.g. "fastapi", "dspy", "memvid")
        """
        app = _ctx(ctx)
        store = _get_store_from_ctx(ctx)

        doc_urls = _resolve_doc_urls(topic)
        fetched = 0
        failed = 0

        for url in doc_urls:
            if url.endswith("sitemap.xml"):
                result = await _fetch_sitemap(
                    app.http, url, store, force=False
                )
                fetched += result.get("fetched", 0)
                failed += result.get("failed", 0)
                # If sitemap worked, skip remaining URLs
                if fetched > 0:
                    break
            else:
                result = await _fetch_single(
                    app.http, url, store, force=False
                )
                if result.get("ok"):
                    fetched += 1
                else:
                    failed += 1

        if fetched == 0:
            return (
                f"Could not fetch docs for '{topic}'. "
                f"Tried {len(doc_urls)} URL patterns, all failed. "
                f"You can manually fetch with rlm_fetch(url) if you know the doc URL."
            )

        return (
            f"Indexed {fetched} pages for '{topic}'. "
            f"{failed} failed. Use rlm_search to query."
        )

    @mcp.tool()
    async def rlm_knowledge_status(
        ctx: Context,
        project: str | None = None,
    ) -> str:
        """Show what's indexed in the knowledge store.

        Returns the store path, file size, and a breakdown of raw doc sources
        by library name.

        Args:
            project: Project hash override (uses cwd-based hash if omitted)
        """
        h = project or _project_hash()
        store = get_store(h)
        path = store.path
        exists = os.path.exists(path)
        size = os.path.getsize(path) if exists else 0

        sources = _count_doc_sources()

        lines = [f"Knowledge Store: {path}"]
        if exists:
            lines.append(f"Size: {size / 1024:.1f} KB")
        else:
            lines.append("Status: not created yet")

        lines.append(f"Sources ({len(sources)} libraries):")
        if sources:
            for name, count in sorted(sources.items()):
                lines.append(f"  - {name}: {count} files")
        else:
            lines.append("  (none)")

        return "\n".join(lines)

    @mcp.tool()
    async def rlm_knowledge_clear(
        ctx: Context,
        project: str | None = None,
    ) -> str:
        """Clear the knowledge store (.mv2 index) for a project.

        Closes the store, deletes the file, and resets the cache so the next
        access creates a fresh index.

        Args:
            project: Project hash override (uses cwd-based hash if omitted)
        """
        h = project or _project_hash()
        store = get_store(h)
        store.close()

        path = store.path
        removed = False
        if os.path.exists(path):
            os.remove(path)
            removed = True

        # Drop from singleton cache so next get_store() creates fresh
        _stores.pop(h, None)

        if removed:
            return f"Cleared knowledge store at {path}"
        return f"No knowledge store found at {path} (already clean)"
