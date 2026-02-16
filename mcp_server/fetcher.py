"""Document fetching layer with dual storage (raw .md + .mv2 ingestion).

Fetches documentation URLs, stores raw markdown files for human-readable cache,
and ingests content into the KnowledgeStore for vector search.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree

import httpx
from mcp.server.fastmcp import Context

log = logging.getLogger(__name__)

# Raw docs land here: .claude/docs/{library}/{path}.md
DOCS_BASE = Path(".claude/docs")

# How long cached files stay fresh (seconds)
FRESHNESS_TTL = 7 * 24 * 3600  # 7 days

# Rate limit delay between sitemap fetches (seconds)
SITEMAP_RATE_LIMIT = 0.2

# Sites known to block automated fetching
BLOCKED_DOMAINS = frozenset({
    "medium.com",
    "substack.com",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def extract_library_name(url: str) -> str:
    """Pull a library/project name from a URL's domain.

    Examples:
        docs.memvid.com      -> memvid
        react.dev             -> react
        developer.mozilla.org -> mozilla
        github.com/foo/bar    -> foo-bar
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # GitHub: use org/repo as library name
    if host in ("github.com", "raw.githubusercontent.com"):
        parts = parsed.path.strip("/").split("/")
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        if parts and parts[0]:
            return parts[0]
        return "github"

    # Strip common prefixes
    host = re.sub(r"^(www|docs|api|developer)\.", "", host)

    # Take the first meaningful segment
    segments = host.split(".")
    # Filter out TLDs and short noise
    meaningful = [s for s in segments if len(s) > 2 and s not in ("com", "org", "io", "dev", "net", "co")]
    if meaningful:
        return meaningful[0]

    # Fallback: use the full host minus dots
    return host.replace(".", "-") or "unknown"


def url_to_filepath(url: str) -> Path:
    """Convert a URL into a relative file path under the library's doc dir.

    e.g. https://docs.memvid.com/api/search -> memvid/api/search.md
    """
    parsed = urlparse(url)
    library = extract_library_name(url)
    path = parsed.path.strip("/")

    # Remove trailing .md/.html extensions before re-adding .md
    path = re.sub(r"\.(md|html|htm)$", "", path)

    if not path:
        path = "index"

    return DOCS_BASE / library / f"{path}.md"


def _meta_path(doc_path: Path) -> Path:
    """Sidecar metadata path for a doc file."""
    return doc_path.with_suffix(".meta.json")


def _content_hash(text: str) -> str:
    return f"sha256:{hashlib.sha256(text.encode()).hexdigest()}"


def read_meta(doc_path: Path) -> dict | None:
    """Read the sidecar .meta.json, or None if missing/corrupt."""
    mp = _meta_path(doc_path)
    if not mp.exists():
        return None
    try:
        return json.loads(mp.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def write_meta(doc_path: Path, url: str, content: str,
               markdown_source: str = "html2text",
               markdown_tokens: int | None = None) -> dict:
    """Write sidecar metadata and return the metadata dict."""
    meta = {
        "url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "content_hash": _content_hash(content),
        "size_bytes": len(content.encode()),
        "markdown_source": markdown_source,
    }
    if markdown_tokens is not None:
        meta["markdown_tokens"] = markdown_tokens
    mp = _meta_path(doc_path)
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(json.dumps(meta, indent=2))
    return meta


def is_fresh(doc_path: Path, ttl: float = FRESHNESS_TTL) -> bool:
    """Check if a cached doc file exists and its metadata is younger than ttl."""
    if not doc_path.exists():
        return False
    meta = read_meta(doc_path)
    if meta is None:
        return False
    try:
        fetched = datetime.fromisoformat(meta["fetched_at"])
        age = (datetime.now(timezone.utc) - fetched).total_seconds()
        return age < ttl
    except (KeyError, ValueError):
        return False


def _looks_like_markdown(text: str) -> bool:
    """Heuristic: does this text look like markdown rather than HTML?"""
    if not text.strip():
        return False
    # If it starts with an HTML doctype or <html tag, it's HTML
    stripped = text.strip()[:200].lower()
    if stripped.startswith("<!doctype") or stripped.startswith("<html"):
        return False
    # If more than 30% of lines start with HTML tags, probably HTML
    lines = text.split("\n")[:50]
    html_lines = sum(1 for l in lines if re.match(r"^\s*<[a-z]", l.strip().lower()))
    if lines and html_lines / len(lines) > 0.3:
        return False
    return True


def html_to_markdown(html: str) -> str:
    """Convert HTML to markdown using html2text."""
    try:
        import html2text
        h = html2text.HTML2Text()
        h.ignore_links = False
        h.ignore_images = False
        h.body_width = 0  # no wrapping
        return h.handle(html)
    except ImportError:
        # Fallback: strip tags crudely
        text = re.sub(r"<[^>]+>", "", html)
        return text.strip()


def parse_sitemap_xml(xml_text: str) -> list[str]:
    """Extract all <loc> URLs from a sitemap XML string."""
    urls: list[str] = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return urls

    # Handle namespace (sitemaps usually have xmlns)
    # Match any namespace prefix
    for elem in root.iter():
        tag = elem.tag
        # Strip namespace
        local = tag.split("}")[-1] if "}" in tag else tag
        if local == "loc" and elem.text:
            urls.append(elem.text.strip())
    return urls


def _get_store(ctx: Context) -> Any:
    """Get the KnowledgeStore from the app context. Returns None if not wired yet."""
    try:
        app = ctx.request_context.lifespan_context
        return getattr(app, "knowledge_store", None)
    except Exception:
        return None


async def _ingest_to_store(store: Any, title: str, label: str, text: str, metadata: dict) -> bool:
    """Ingest content into the KnowledgeStore if available. Returns True on success."""
    if store is None:
        return False
    try:
        store.ingest(title=title, label=label, text=text, metadata=metadata)
        return True
    except Exception as exc:
        log.warning("KnowledgeStore ingest failed: %s", exc)
        return False


def _store_raw(doc_path: Path, content: str, url: str,
               markdown_source: str = "html2text",
               markdown_tokens: int | None = None) -> dict:
    """Write raw markdown file and sidecar metadata. Returns metadata dict."""
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(content)
    return write_meta(doc_path, url, content,
                      markdown_source=markdown_source,
                      markdown_tokens=markdown_tokens)


# ---------------------------------------------------------------------------
# Core fetch logic
# ---------------------------------------------------------------------------


async def fetch_url(
    client: httpx.AsyncClient,
    url: str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Fetch a single URL with markdown negotiation cascade and caching.

    Cascade order:
      1. Accept: text/markdown content negotiation
      2. markdown.new proxy
      3. Original URL + html2text conversion

    Returns dict with keys: content, doc_path, meta, from_cache, error
    """
    parsed = urlparse(url)
    host = parsed.hostname or ""

    # Check blocked domains
    base_host = re.sub(r"^(www|docs)\.", "", host)
    if base_host in BLOCKED_DOMAINS:
        return {"content": None, "doc_path": None, "meta": None, "from_cache": False,
                "error": f"Blocked domain: {base_host}. These sites block automated fetching."}

    doc_path = url_to_filepath(url)

    # Freshness check
    if not force and is_fresh(doc_path):
        cached_content = doc_path.read_text()
        cached_meta = read_meta(doc_path)
        return {"content": cached_content, "doc_path": doc_path, "meta": cached_meta,
                "from_cache": True, "error": None}

    # --- MARKDOWN NEGOTIATION CASCADE ---
    content = None
    source_url = url
    markdown_source = "html2text"
    markdown_tokens = None

    # Tier 1: Try Accept: text/markdown content negotiation
    try:
        resp = await client.get(
            url, timeout=15, follow_redirects=True,
            headers={"Accept": "text/markdown"},
        )
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "text/markdown" in ct:
            content = resp.text
            markdown_source = "negotiated"
            tok = resp.headers.get("x-markdown-tokens")
            if tok:
                markdown_tokens = int(tok)
            source_url = url
        elif _looks_like_markdown(resp.text):
            content = resp.text
            markdown_source = "negotiated"
            source_url = url
    except (httpx.HTTPError, httpx.TimeoutException, ValueError):
        pass

    # Tier 2: Try markdown.new proxy
    if content is None:
        try:
            proxy_url = f"https://markdown.new/{url}"
            resp = await client.get(proxy_url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            proxy_text = resp.text
            if proxy_text and _looks_like_markdown(proxy_text):
                content = proxy_text
                markdown_source = "markdown_new"
                tok = resp.headers.get("x-markdown-tokens")
                if tok:
                    markdown_tokens = int(tok)
                source_url = url
        except (httpx.HTTPError, httpx.TimeoutException, ValueError):
            pass

    # Tier 3: Fall back to original URL + html2text
    if content is None:
        try:
            resp = await client.get(url, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            text = resp.text
            if _looks_like_markdown(text):
                content = text
            else:
                content = html_to_markdown(text)
            markdown_source = "html2text"
            source_url = url
        except httpx.TimeoutException:
            return {"content": None, "doc_path": doc_path, "meta": None, "from_cache": False,
                    "error": f"Timeout fetching {url}"}
        except httpx.HTTPStatusError as exc:
            return {"content": None, "doc_path": doc_path, "meta": None, "from_cache": False,
                    "error": f"HTTP {exc.response.status_code} fetching {url}"}
        except httpx.HTTPError as exc:
            return {"content": None, "doc_path": doc_path, "meta": None, "from_cache": False,
                    "error": f"Connection error fetching {url}: {exc}"}

    # Dual storage: raw file + metadata
    meta = _store_raw(doc_path, content, source_url,
                      markdown_source=markdown_source,
                      markdown_tokens=markdown_tokens)
    return {"content": content, "doc_path": doc_path, "meta": meta,
            "from_cache": False, "error": None}


# ---------------------------------------------------------------------------
# MCP tool registrations
# ---------------------------------------------------------------------------


def register_fetcher_tools(mcp) -> None:
    """Register document fetching tools on the MCP server instance."""

    @mcp.tool()
    async def rlm_fetch(url: str, ctx: Context, force: bool = False) -> str:
        """Fetch a URL and store as docs + index into knowledge store.

        Uses a three-tier cascade: Accept: text/markdown negotiation, markdown.new
        proxy, then HTML->markdown. Cached files younger than 7 days are returned
        without re-fetching unless force=True.
        """
        app = ctx.request_context.lifespan_context
        result = await fetch_url(app.http, url, force=force)

        if result["error"]:
            return f"Error: {result['error']}"

        # Ingest into knowledge store
        store = _get_store(ctx)
        library = extract_library_name(url)
        meta = result["meta"] or {}
        ingested = await _ingest_to_store(
            store,
            title=url,
            label=library,
            text=result["content"],
            metadata=meta,
        )

        status = "cached" if result["from_cache"] else "fetched"
        size = meta.get("size_bytes", len(result["content"].encode()))
        parts = [
            f"[{status}] {url}",
            f"  Stored: {result['doc_path']}",
            f"  Size: {size} bytes",
        ]
        if ingested:
            parts.append("  Indexed in knowledge store")
        else:
            parts.append("  Knowledge store not available (raw file only)")
        return "\n".join(parts)

    @mcp.tool()
    async def rlm_load_dir(glob_pattern: str, ctx: Context) -> str:
        """Bulk-load local files matching a glob pattern into raw docs + knowledge store.

        Example: rlm_load_dir("./docs/**/*.md")
        """
        base = Path.cwd()
        matches = sorted(base.glob(glob_pattern))

        if not matches:
            return f"No files matched pattern: {glob_pattern}"

        store = _get_store(ctx)
        loaded = 0
        errors = []
        total_bytes = 0

        for fpath in matches:
            if not fpath.is_file():
                continue
            try:
                content = fpath.read_text()
            except (OSError, UnicodeDecodeError) as exc:
                errors.append(f"{fpath}: {exc}")
                continue

            # Store as raw doc
            # Use relative path as the "URL" for local files
            rel = str(fpath.relative_to(base))
            doc_path = DOCS_BASE / "local" / f"{rel}"
            if not doc_path.suffix:
                doc_path = doc_path.with_suffix(".md")
            doc_path.parent.mkdir(parents=True, exist_ok=True)
            doc_path.write_text(content)
            meta = write_meta(doc_path, f"file://{fpath}", content)

            # Ingest into knowledge store
            await _ingest_to_store(
                store,
                title=str(fpath.name),
                label="local",
                text=content,
                metadata=meta,
            )

            loaded += 1
            total_bytes += len(content.encode())

        parts = [f"Loaded {loaded} files ({total_bytes} bytes)"]
        if errors:
            parts.append(f"{len(errors)} errors:")
            for e in errors[:5]:
                parts.append(f"  - {e}")
            if len(errors) > 5:
                parts.append(f"  ... and {len(errors) - 5} more")
        return "\n".join(parts)

    @mcp.tool()
    async def rlm_fetch_sitemap(sitemap_url: str, ctx: Context, force: bool = False) -> str:
        """Parse a sitemap.xml and fetch all listed pages.

        Each page is stored as raw markdown + indexed in the knowledge store.
        Rate-limited to ~5 requests/second.
        """
        app = ctx.request_context.lifespan_context

        # Fetch the sitemap itself
        try:
            resp = await app.http.get(sitemap_url, timeout=30, follow_redirects=True)
            resp.raise_for_status()
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            return f"Error fetching sitemap: {exc}"

        urls = parse_sitemap_xml(resp.text)
        if not urls:
            return f"No URLs found in sitemap at {sitemap_url}"

        store = _get_store(ctx)
        library = extract_library_name(sitemap_url)
        fetched = 0
        failed = 0
        total_bytes = 0
        errors: list[str] = []

        for page_url in urls:
            result = await fetch_url(app.http, page_url, force=force)

            if result["error"]:
                failed += 1
                errors.append(f"{page_url}: {result['error']}")
            else:
                fetched += 1
                size = (result["meta"] or {}).get("size_bytes", 0)
                total_bytes += size

                # Ingest into knowledge store
                await _ingest_to_store(
                    store,
                    title=page_url,
                    label=library,
                    text=result["content"],
                    metadata=result["meta"] or {},
                )

            # Rate limit between requests
            await asyncio.sleep(SITEMAP_RATE_LIMIT)

        parts = [
            f"Sitemap: {sitemap_url}",
            f"  Pages fetched: {fetched}",
            f"  Pages failed: {failed}",
            f"  Total size: {total_bytes} bytes",
        ]
        if errors:
            parts.append("  Errors:")
            for e in errors[:10]:
                parts.append(f"    - {e}")
            if len(errors) > 10:
                parts.append(f"    ... and {len(errors) - 10} more")
        return "\n".join(parts)
