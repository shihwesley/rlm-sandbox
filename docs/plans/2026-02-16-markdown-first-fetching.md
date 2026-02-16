# Markdown-First Web Fetching Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make all web fetching prefer server-side markdown via `Accept: text/markdown` content negotiation, fall back through `markdown.new`, then existing `html2text`. Auto-index WebFetch results and Context7 docs into the `.mv2` knowledge store.

**Architecture:** Three-tier cascade in `fetcher.py` (negotiation → proxy → conversion). Two PostToolUse hooks: one for WebFetch auto-indexing, one for Context7→.mv2 ingestion.

**Tech Stack:** Python 3.12, httpx, FastMCP hooks, rlm-sandbox KnowledgeStore

---

### Task 1: Add markdown negotiation cascade to `fetch_url()`

**Files:**
- Modify: `mcp_server/fetcher.py:230-297` (the `fetch_url` function)
- Test: `tests/test_fetcher.py`

**Step 1: Write failing tests for the three-tier cascade**

Add to `tests/test_fetcher.py` in the `TestFetchUrl` class:

```python
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
        # Both Accept: text/markdown and .md variant return HTML
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
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/quartershots/Source/rlm-sandbox && python -m pytest tests/test_fetcher.py::TestFetchUrl::test_accept_markdown_negotiation tests/test_fetcher.py::TestFetchUrl::test_markdown_new_fallback tests/test_fetcher.py::TestFetchUrl::test_html2text_final_fallback -v`
Expected: FAIL — `markdown_source` key missing from meta, no `Accept` header sent

**Step 3: Implement the cascade in `fetch_url()`**

Replace the fetch logic in `fetch_url()` (lines ~259-293) with this cascade:

```python
# --- MARKDOWN NEGOTIATION CASCADE ---
# Tier 1: Try Accept: text/markdown content negotiation
markdown_source = "html2text"
markdown_tokens = None

if content is None:
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
MARKDOWN_NEW_BASE = "https://markdown.new/"
if content is None:
    try:
        proxy_url = f"{MARKDOWN_NEW_BASE}{url}"
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

# Tier 3: Fall back to original URL + html2text (existing logic)
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
        return {"content": None, "doc_path": doc_path, "meta": None,
                "from_cache": False, "error": f"Timeout fetching {url}"}
    except httpx.HTTPStatusError as exc:
        return {"content": None, "doc_path": doc_path, "meta": None,
                "from_cache": False, "error": f"HTTP {exc.response.status_code} fetching {url}"}
    except httpx.HTTPError as exc:
        return {"content": None, "doc_path": doc_path, "meta": None,
                "from_cache": False, "error": f"Connection error fetching {url}: {exc}"}
```

Also update `write_meta()` to accept and store `markdown_source` and `markdown_tokens`:

```python
def write_meta(doc_path: Path, url: str, content: str,
               markdown_source: str = "html2text",
               markdown_tokens: int | None = None) -> dict:
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
```

Update `_store_raw()` to pass through the new params:

```python
def _store_raw(doc_path: Path, content: str, url: str,
               markdown_source: str = "html2text",
               markdown_tokens: int | None = None) -> dict:
    doc_path.parent.mkdir(parents=True, exist_ok=True)
    doc_path.write_text(content)
    return write_meta(doc_path, url, content,
                      markdown_source=markdown_source,
                      markdown_tokens=markdown_tokens)
```

And the final storage call in `fetch_url()`:

```python
meta = _store_raw(doc_path, content, source_url,
                  markdown_source=markdown_source,
                  markdown_tokens=markdown_tokens)
return {"content": content, "doc_path": doc_path, "meta": meta,
        "from_cache": False, "error": None}
```

**Step 4: Run all fetcher tests**

Run: `cd /Users/quartershots/Source/rlm-sandbox && python -m pytest tests/test_fetcher.py -v`
Expected: ALL PASS

**Step 5: Commit**

```bash
git add mcp_server/fetcher.py tests/test_fetcher.py
git commit -m "feat(fetcher): add Accept: text/markdown negotiation + markdown.new fallback"
```

---

### Task 2: Create WebFetch PostToolUse hook

**Files:**
- Create: `scripts/webfetch-to-mv2.py`
- Modify: `hooks/hooks.json`

**Step 1: Write the hook script**

Create `scripts/webfetch-to-mv2.py`:

```python
#!/usr/bin/env python3
"""PostToolUse hook: auto-index WebFetch results into .mv2 knowledge store.

Reads tool input from stdin JSON, extracts the URL, re-fetches through
the enhanced fetcher (Accept: text/markdown cascade), and ingests into
the KnowledgeStore.

Exit 0 = allow (always), stdout = feedback to Claude.
"""

import json
import sys
import asyncio
from pathlib import Path

# Add parent so we can import mcp_server modules
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return

    tool_name = data.get("tool_name", "")
    if tool_name != "WebFetch":
        return

    tool_input = data.get("tool_input", {})
    url = tool_input.get("url", "")
    if not url:
        return

    # Skip blocked domains
    from urllib.parse import urlparse
    import re
    host = urlparse(url).hostname or ""
    base_host = re.sub(r"^(www|docs)\.", "", host)
    BLOCKED = {"medium.com", "substack.com"}
    if base_host in BLOCKED:
        return

    # Check freshness — skip if already indexed recently
    from mcp_server.fetcher import url_to_filepath, is_fresh
    doc_path = url_to_filepath(url)
    if is_fresh(doc_path):
        return

    # Re-fetch through enhanced fetcher
    asyncio.run(_fetch_and_index(url))


async def _fetch_and_index(url: str):
    import httpx
    from mcp_server.fetcher import fetch_url, extract_library_name

    async with httpx.AsyncClient() as client:
        result = await fetch_url(client, url, force=False)

    if result["error"] or not result["content"]:
        return

    # Try to ingest into knowledge store
    try:
        from mcp_server.knowledge import KnowledgeStore
        store = KnowledgeStore.default()
        store.ingest(
            title=url,
            label=f"webfetch-auto",
            text=result["content"],
            metadata=result["meta"] or {},
        )
        source = (result["meta"] or {}).get("markdown_source", "unknown")
        print(f"Auto-indexed {url} into knowledge store (via {source})")
    except Exception:
        # Silent failure — don't block the agent
        pass


if __name__ == "__main__":
    main()
```

**Step 2: Make it executable**

Run: `chmod +x /Users/quartershots/Source/rlm-sandbox/scripts/webfetch-to-mv2.py`

**Step 3: Register the hook in hooks.json**

Update `hooks/hooks.json` to add the WebFetch matcher:

```json
{
  "description": "rlm-sandbox hooks: auto-index WebFetch and Context7 content into knowledge store",
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "mcp__context7__query-docs",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/scripts/context7-to-mv2.sh",
            "timeout": 10
          }
        ]
      },
      {
        "matcher": "WebFetch",
        "hooks": [
          {
            "type": "command",
            "command": "python3 ${CLAUDE_PLUGIN_ROOT}/scripts/webfetch-to-mv2.py",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

**Step 4: Manual test**

Run: `echo '{"tool_name":"WebFetch","tool_input":{"url":"https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/","prompt":"test"}}' | python3 /Users/quartershots/Source/rlm-sandbox/scripts/webfetch-to-mv2.py`
Expected: "Auto-indexed ... into knowledge store (via negotiated)"

**Step 5: Commit**

```bash
git add scripts/webfetch-to-mv2.py hooks/hooks.json
git commit -m "feat(hooks): add WebFetch PostToolUse hook for auto-indexing to .mv2"
```

---

### Task 3: Wire up Context7 → .mv2 ingestion

**Files:**
- Modify: `scripts/context7-to-mv2.sh`

**Step 1: Review current script**

Current `context7-to-mv2.sh` only prints a suggestion. Replace it with actual ingestion.

**Step 2: Rewrite the script**

```bash
#!/usr/bin/env bash
# PostToolUse hook: ingest Context7 query-docs content into .mv2 knowledge store.
#
# Reads tool result from stdin JSON, extracts library name and content,
# calls a small Python helper to ingest into KnowledgeStore.
#
# Exit 0 = allow (always), stdout = feedback to Claude.

set -euo pipefail

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tool_name',''))" 2>/dev/null || echo "")

if [[ "$TOOL_NAME" != "mcp__context7__query-docs" ]]; then
    exit 0
fi

# Extract and ingest via Python
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "$INPUT" | python3 -c "
import sys, json
sys.path.insert(0, '${SCRIPT_DIR}/..')

data = json.load(sys.stdin)
params = data.get('tool_params', {})
result = data.get('tool_result', '')

lib_id = params.get('libraryId', 'unknown')
name = lib_id.strip('/').split('/')[-1] if '/' in lib_id else lib_id

if not result or len(result) < 50:
    sys.exit(0)

try:
    from mcp_server.knowledge import KnowledgeStore
    store = KnowledgeStore.default()
    store.ingest(
        title=f'context7:{name}',
        label=f'context7-{name}',
        text=result if isinstance(result, str) else str(result),
        metadata={'source': 'context7', 'library': name},
    )
    print(f'Context7 docs for \"{name}\" indexed into knowledge store.')
except Exception as e:
    print(f'Context7 indexing skipped: {e}')
" 2>/dev/null || true

exit 0
```

**Step 3: Verify the hook registration already exists**

The matcher in `hooks.json` already points to this script. No change needed.

**Step 4: Manual test**

Run: `echo '{"tool_name":"mcp__context7__query-docs","tool_params":{"libraryId":"/vercel/next.js"},"tool_result":"# Next.js Docs\n\nThis is sample content for testing the Context7 hook ingestion pipeline. It needs to be at least 50 characters."}' | bash /Users/quartershots/Source/rlm-sandbox/scripts/context7-to-mv2.sh`
Expected: `Context7 docs for "next.js" indexed into knowledge store.`

**Step 5: Commit**

```bash
git add scripts/context7-to-mv2.sh
git commit -m "feat(hooks): context7-to-mv2 now ingests docs into .mv2 knowledge store"
```

---

### Task 4: Verify end-to-end

**Step 1: Run full test suite**

Run: `cd /Users/quartershots/Source/rlm-sandbox && python -m pytest tests/test_fetcher.py -v`
Expected: ALL PASS

**Step 2: Integration smoke test**

Run: `cd /Users/quartershots/Source/rlm-sandbox && python3 -c "
import asyncio, httpx
from mcp_server.fetcher import fetch_url

async def test():
    async with httpx.AsyncClient() as c:
        r = await fetch_url(c, 'https://developers.cloudflare.com/fundamentals/reference/markdown-for-agents/', force=True)
        print(f'Source: {r[\"meta\"][\"markdown_source\"]}')
        print(f'Tokens: {r[\"meta\"].get(\"markdown_tokens\", \"N/A\")}')
        print(f'Size: {r[\"meta\"][\"size_bytes\"]} bytes')
        print(f'First 200 chars: {r[\"content\"][:200]}')

asyncio.run(test())
"`
Expected: `Source: negotiated` (Cloudflare site supports Accept: text/markdown)
