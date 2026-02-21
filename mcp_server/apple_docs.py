"""Apple documentation tools backed by DocSetQuery and Context7.

Wires local Apple framework docs (Dash docset) and Context7 library docs
into the neo-research knowledge store for hybrid search.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import Context

from mcp_server.knowledge import KnowledgeStore, get_store

log = logging.getLogger(__name__)

DOCSET_QUERY_ROOT = Path("/Users/quartershots/Source/DocSetQuery")
TOOLS_DIR = DOCSET_QUERY_ROOT / "tools"
DOCS_DIR = DOCSET_QUERY_ROOT / "docs" / "apple"

# Framework name -> docset root path
FRAMEWORK_PATHS: dict[str, str] = {
    "swiftui": "/documentation/swiftui",
    "foundation": "/documentation/foundation",
    "uikit": "/documentation/uikit",
    "realitykit": "/documentation/realitykit",
    "visionos": "/documentation/visionos",
    "vision": "/documentation/vision",
    "arkit": "/documentation/arkit",
    "avfoundation": "/documentation/avfoundation",
    "combine": "/documentation/combine",
    "swift": "/documentation/swift",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_store_from_ctx(ctx: Context) -> KnowledgeStore | None:
    """Pull the KnowledgeStore from the app context, if wired."""
    try:
        app = ctx.request_context.lifespan_context
        return getattr(app, "knowledge_store", None)
    except Exception:
        return None


async def _run_tool(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a DocSetQuery tool as a subprocess. Returns (returncode, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "python3", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd or TOOLS_DIR,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


def _parse_search_results(output: str) -> list[dict[str, str]]:
    """Parse docindex.py search output lines.

    Format: ``Title: Heading — path#anchor``
    Returns list of dicts with keys: title, heading, path, anchor.
    """
    results: list[dict[str, str]] = []
    for line in output.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("[docindex]"):
            continue
        # Split on " — " to separate label from path#anchor
        parts = line.split(" — ", 1)
        if len(parts) != 2:
            continue
        label, path_anchor = parts
        # Label is "Title: Heading"
        label_parts = label.split(": ", 1)
        title = label_parts[0] if label_parts else label
        heading = label_parts[1] if len(label_parts) > 1 else ""
        # path#anchor
        if "#" in path_anchor:
            path, anchor = path_anchor.rsplit("#", 1)
        else:
            path = path_anchor
            anchor = ""
        results.append({
            "title": title,
            "heading": heading,
            "path": path.strip(),
            "anchor": anchor.strip(),
        })
    return results


def _read_section(file_path: Path, anchor: str) -> str | None:
    """Read a section from a markdown file starting at the given anchor.

    Returns the section text from the anchor's heading up to the next
    heading of equal or higher level. Returns None if the anchor is not found.
    """
    if not file_path.exists():
        return None

    text = file_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Find the anchor — look for either an <a id="anchor"> tag or a heading
    # whose slug matches the anchor
    target_line: int | None = None
    target_level: int | None = None
    anchor_tag = f'<a id="{anchor}">'

    for i, line in enumerate(lines):
        if anchor_tag in line:
            # The heading is usually the next non-empty line
            for j in range(i + 1, min(i + 3, len(lines))):
                stripped = lines[j].lstrip()
                if stripped.startswith("#"):
                    level = len(stripped) - len(stripped.lstrip("#"))
                    target_line = j
                    target_level = level
                    break
            if target_line is None:
                target_line = i
                target_level = 2
            break
        # Also match heading text that slugifies to the anchor
        stripped = line.lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            heading_text = stripped[level:].strip()
            slug = _slugify(heading_text)
            if slug == anchor:
                target_line = i
                target_level = level
                break

    if target_line is None:
        return None

    # Collect lines until the next heading of same or higher level
    section_lines = [lines[target_line]]
    for i in range(target_line + 1, len(lines)):
        stripped = lines[i].lstrip()
        if stripped.startswith("#"):
            level = len(stripped) - len(stripped.lstrip("#"))
            if level <= target_level:
                break
        section_lines.append(lines[i])

    return "\n".join(section_lines).strip()


def _slugify(text: str) -> str:
    """Replicate DocSetQuery's slugify for anchor matching."""
    keep: list[str] = []
    for char in text:
        if char.isalnum():
            keep.append(char.lower())
        elif char in "/-_":
            keep.append("-")
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "section"


def _truncate_preserving_code(text: str, max_chars: int = 8000) -> str:
    """Truncate text but never cut inside a code block.

    If the text is under max_chars, return as-is. Otherwise, find a safe
    truncation point that doesn't split a ``` block.
    """
    if len(text) <= max_chars:
        return text

    # Find all code block boundaries
    in_code = False
    last_safe_point = 0
    for i, char in enumerate(text):
        if text[i:i + 3] == "```":
            in_code = not in_code
        if not in_code and i <= max_chars:
            # Track last point outside a code block near a newline
            if char == "\n":
                last_safe_point = i

    if last_safe_point > max_chars * 0.5:
        return text[:last_safe_point] + "\n...(truncated, code blocks preserved)"
    # Fallback: hard cut if no safe point found
    return text[:max_chars] + "\n...(truncated)"


def _chunk_markdown(text: str, framework: str) -> list[dict[str, Any]]:
    """Split markdown on ``## `` headings into chunks for ingestion.

    Each chunk gets title="{framework}/{heading}", label="apple-docs".
    """
    chunks: list[dict[str, Any]] = []
    current_heading = "preamble"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            # Flush previous chunk
            if current_lines:
                chunks.append({
                    "title": f"{framework}/{current_heading}",
                    "label": "apple-docs",
                    "text": "\n".join(current_lines).strip(),
                })
            current_heading = line[3:].strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Flush the last chunk
    if current_lines:
        body = "\n".join(current_lines).strip()
        if body:
            chunks.append({
                "title": f"{framework}/{current_heading}",
                "label": "apple-docs",
                "text": body,
            })

    return chunks


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register_apple_docs_tools(mcp) -> None:
    """Register Apple documentation tools on the MCP server instance."""

    @mcp.tool()
    async def rlm_apple_search(
        query: str,
        ctx: Context,
        framework: str | None = None,
    ) -> str:
        """Search local Apple framework docs via DocSetQuery's index.

        Returns matching headings with their section content from the
        pre-exported Markdown files.

        Args:
            query: Search term (case-insensitive substring match on headings)
            framework: Optional filter — only return results from this framework
        """
        rc, stdout, stderr = await _run_tool([
            str(TOOLS_DIR / "docindex.py"), "search", query,
        ])
        if rc != 0:
            return f"docindex search failed (rc={rc}): {stderr.strip()}"

        results = _parse_search_results(stdout)
        if not results:
            return f"No matches for '{query}' in Apple docs index."

        # Filter by framework if requested
        if framework:
            fw_lower = framework.lower()
            results = [
                r for r in results
                if fw_lower in r["path"].lower() or fw_lower in r["title"].lower()
            ]
            if not results:
                return f"No matches for '{query}' in framework '{framework}'."

        # Read actual section content for each match (cap at 10)
        parts: list[str] = []
        for hit in results[:10]:
            file_path = DOCSET_QUERY_ROOT / hit["path"]
            section = None
            if hit["anchor"]:
                section = await asyncio.to_thread(_read_section, file_path, hit["anchor"])

            parts.append(f"### {hit['title']}: {hit['heading']}")
            parts.append(f"_Source: {hit['path']}#{hit['anchor']}_")
            if section:
                # Truncate very long sections
                if len(section) > 3000:
                    section = section[:3000] + "\n...(truncated)"
                parts.append(section)
            else:
                parts.append("(section content not available)")
            parts.append("")

        header = f"Found {len(results)} matches for '{query}'"
        if len(results) > 10:
            header += f" (showing first 10 of {len(results)})"
        return header + "\n\n" + "\n".join(parts)

    @mcp.tool()
    async def rlm_apple_export(
        framework: str,
        ctx: Context,
        max_depth: int = 3,
    ) -> str:
        """Export an Apple framework's docs and index them into the knowledge store.

        Runs DocSetQuery's export + sanitize pipeline, then chunks the result
        by ## headings and ingests each chunk.

        Args:
            framework: Framework name (e.g. "swiftui", "foundation", "vision")
            max_depth: Export traversal depth (default 3, higher = more content)
        """
        fw_lower = framework.lower()
        doc_root = FRAMEWORK_PATHS.get(fw_lower)
        if not doc_root:
            known = ", ".join(sorted(FRAMEWORK_PATHS.keys()))
            return (
                f"Unknown framework '{framework}'. "
                f"Known frameworks: {known}. "
                f"You can also pass a custom path to docset_query.py directly."
            )

        output_path = Path(f"/tmp/neo-apple-{fw_lower}.md")

        # Step 1: export
        rc, stdout, stderr = await _run_tool([
            str(TOOLS_DIR / "docset_query.py"),
            "export",
            "--root", doc_root,
            "--output", str(output_path),
            "--max-depth", str(max_depth),
        ])
        if rc != 0:
            return f"Export failed (rc={rc}): {stderr.strip()[:500]}"

        # Step 2: sanitize
        rc, stdout, stderr = await _run_tool([
            str(TOOLS_DIR / "docset_sanitize.py"),
            "--input", str(output_path),
            "--in-place",
            "--toc-depth", "2",
        ])
        if rc != 0:
            log.warning("Sanitize had issues (rc=%d): %s", rc, stderr.strip()[:200])
            # Continue anyway — the export file still exists

        # Step 3: read and chunk
        if not output_path.exists():
            return f"Export file not found at {output_path} after pipeline."

        text = await asyncio.to_thread(output_path.read_text, "utf-8")
        chunks = _chunk_markdown(text, fw_lower)

        # Step 4: ingest into knowledge store
        store = _get_store_from_ctx(ctx)
        if store is None:
            return (
                f"Exported {fw_lower} to {output_path} "
                f"({len(chunks)} sections, {len(text)} bytes) "
                f"but knowledge store is not available for indexing."
            )

        try:
            store.ingest_many(chunks)
        except Exception as exc:
            log.exception("Batch ingest failed for %s", fw_lower)
            return f"Export succeeded but ingest failed: {exc}"

        return (
            f"Exported {fw_lower}, {len(chunks)} sections indexed "
            f"({len(text)} bytes)"
        )

    @mcp.tool()
    async def rlm_apple_read(
        path: str,
        ctx: Context,
        anchor: str | None = None,
    ) -> str:
        """Read a specific section from an exported Apple doc file.

        Use this for targeted reads instead of pulling entire framework
        files into context.

        Args:
            path: Path relative to DocSetQuery root (e.g. "docs/apple/swiftui.md")
            anchor: Optional heading anchor — returns just that section. Without
                    it, returns the first 200 lines.
        """
        file_path = DOCSET_QUERY_ROOT / path
        if not file_path.exists():
            return f"File not found: {path}"

        if anchor:
            section = await asyncio.to_thread(_read_section, file_path, anchor)
            if section is None:
                return f"Anchor '{anchor}' not found in {path}."
            if len(section) > 10000:
                section = section[:10000] + "\n...(truncated at 10k chars)"
            return section

        # No anchor — return first 200 lines with a length note
        text = await asyncio.to_thread(file_path.read_text, "utf-8")
        lines = text.splitlines()
        total = len(lines)
        preview = "\n".join(lines[:200])
        if total > 200:
            preview += f"\n\n... ({total} total lines, showing first 200)"
        return preview

    @mcp.tool()
    async def rlm_context7_ingest(
        library: str,
        content: str,
        ctx: Context,
    ) -> str:
        """Ingest Context7 docs content into the knowledge store.

        Call this after you've already fetched docs via Context7 MCP tools.
        Pass the library name and the raw content you received.

        Args:
            library: Library name (e.g. "swiftui", "react", "dspy")
            content: The documentation text to ingest (from Context7 output)
        """
        store = _get_store_from_ctx(ctx)
        if store is None:
            return "Knowledge store not available."

        if not content.strip():
            return "No content to ingest."

        # Split on ## headings, same as apple export
        chunks = _chunk_markdown(content, library)
        if not chunks:
            # No headings — ingest as a single chunk
            chunks = [{
                "title": library,
                "label": "context7",
                "text": content.strip(),
            }]
        else:
            # Override label to context7
            for c in chunks:
                c["label"] = "context7"

        try:
            frame_ids = store.ingest_many(chunks)
        except Exception as exc:
            log.exception("Context7 ingest failed for %s", library)
            return f"Ingest failed: {exc}"

        return (
            f"Ingested {library} docs "
            f"({len(content)} chars, {len(frame_ids)} frames)"
        )

    @mcp.tool()
    async def rlm_apple_bulk_ingest(
        ctx: Context,
        pattern: str = "*.md",
    ) -> str:
        """Ingest all exported Apple doc files from docs/apple/ into the knowledge store.

        Reads every .md file in DocSetQuery/docs/apple/, chunks on ## headings,
        and indexes into the .mv2 store for hybrid BM25+vector search.

        Run this once after a batch export to make all 317 frameworks searchable.

        Args:
            pattern: Glob pattern for files to ingest (default "*.md")
        """
        store = _get_store_from_ctx(ctx)
        if store is None:
            return "Knowledge store not available."

        files = sorted(DOCS_DIR.glob(pattern))
        if not files:
            return f"No files matching '{pattern}' in {DOCS_DIR}"

        total_chunks = 0
        total_bytes = 0
        succeeded = 0
        failed: list[str] = []

        for f in files:
            framework = f.stem
            try:
                text = await asyncio.to_thread(f.read_text, "utf-8")
                chunks = _chunk_markdown(text, framework)
                if chunks:
                    store.ingest_many(chunks)
                    total_chunks += len(chunks)
                    total_bytes += len(text)
                    succeeded += 1
                    log.info("Ingested %s: %d chunks", framework, len(chunks))
            except Exception as exc:
                log.warning("Failed to ingest %s: %s", framework, exc)
                failed.append(f"{framework}: {exc}")

        report = (
            f"Bulk ingest complete: {succeeded}/{len(files)} files, "
            f"{total_chunks} chunks, {total_bytes:,} bytes"
        )
        if failed:
            report += f"\nFailed ({len(failed)}):\n" + "\n".join(f"  - {e}" for e in failed)
        return report

    @mcp.tool()
    async def rlm_apple_extract(
        query: str,
        ctx: Context,
        frameworks: str | None = None,
        role_filter: str | None = None,
        max_results: int = 10,
        preserve_code: bool = True,
    ) -> str:
        """Deep extraction from exported Apple docs — finds and returns full sections.

        Two-stage: discovery via .mv2 search, then targeted file reads to get
        complete content with code blocks preserved verbatim. Use this when you
        need copy-paste-ready code examples and full API context, not just snippets.

        Args:
            query: What to find (e.g. "immersive space setup", "hand tracking gesture")
            frameworks: Comma-separated framework filter (e.g. "visionos,arkit,realitykit")
            role_filter: Filter by role tag (e.g. "Sample Code", "Article", "Class")
            max_results: Max sections to return (default 10)
            preserve_code: If True, never truncate code blocks (default True)
        """
        parts: list[str] = []

        # Stage 1: Discovery via knowledge store
        store = _get_store_from_ctx(ctx)
        discovery_hits: list[dict] = []
        if store is not None:
            try:
                search_q = query
                if frameworks:
                    search_q = f"{frameworks.replace(',', ' ')} {query}"
                raw_results = store.search(search_q, top_k=max_results * 2)
                for sr in raw_results:
                    title = sr.get("title", "")
                    text = sr.get("text", "")
                    # Apply role filter if specified
                    if role_filter and role_filter.lower() not in text[:200].lower():
                        continue
                    # Apply framework filter
                    if frameworks:
                        fw_list = [fw.strip().lower() for fw in frameworks.split(",")]
                        fw_from_title = title.split("/")[0].lower() if "/" in title else ""
                        if fw_from_title and fw_from_title not in fw_list:
                            continue
                    discovery_hits.append(sr)
                    if len(discovery_hits) >= max_results:
                        break
            except Exception as exc:
                log.warning("Knowledge store search failed: %s", exc)

        # Stage 2: Targeted file reads for full sections
        if not discovery_hits:
            # Fallback: direct file scan via grep-style heading search
            fw_files = sorted(DOCS_DIR.glob("*.md"))
            if frameworks:
                fw_list = [fw.strip().lower() for fw in frameworks.split(",")]
                fw_files = [f for f in fw_files if f.stem.lower() in fw_list]

            query_lower = query.lower()
            for f in fw_files:
                text = await asyncio.to_thread(f.read_text, "utf-8")
                lines = text.splitlines()
                for i, line in enumerate(lines):
                    if not line.startswith("## "):
                        continue
                    heading = line[3:].strip()
                    if query_lower not in heading.lower():
                        continue
                    if role_filter and f"({role_filter})" not in heading:
                        continue
                    # Extract this section
                    section_lines = [line]
                    for j in range(i + 1, len(lines)):
                        if lines[j].startswith("## "):
                            break
                        section_lines.append(lines[j])
                    section = "\n".join(section_lines).strip()
                    discovery_hits.append({
                        "title": f"{f.stem}/{heading}",
                        "text": section,
                    })
                    if len(discovery_hits) >= max_results:
                        break
                if len(discovery_hits) >= max_results:
                    break

        if not discovery_hits:
            return f"No results for '{query}' in Apple docs."

        # Stage 3: Format output with full code blocks preserved
        for hit in discovery_hits:
            title = hit.get("title", "untitled")
            text = hit.get("text", "")

            if preserve_code:
                # Never truncate inside a code block
                truncated = _truncate_preserving_code(text, max_chars=8000)
            else:
                truncated = text[:4000]
                if len(text) > 4000:
                    truncated += "\n...(truncated)"

            parts.append(f"### {title}")
            parts.append(truncated)
            parts.append("")

        header = f"Extracted {len(discovery_hits)} sections for '{query}'"
        if frameworks:
            header += f" (frameworks: {frameworks})"
        if role_filter:
            header += f" (role: {role_filter})"
        return header + "\n\n" + "\n".join(parts)

    @mcp.tool()
    async def rlm_apple_lookup(
        query: str,
        ctx: Context,
        framework: str | None = None,
        top_k: int = 5,
    ) -> str:
        """Combined Apple docs lookup: DocSetQuery first, then knowledge store.

        Checks the local Dash docset index for heading matches, then
        searches the knowledge store (which may contain Context7 and
        previously-exported Apple docs). Returns merged results from both.

        Args:
            query: Search term (e.g. "NavigationStack", "Entity Component")
            framework: Optional framework filter (e.g. "swiftui", "realitykit")
            top_k: Max results per source (default 5)
        """
        parts: list[str] = []
        found_local = 0
        found_store = 0

        # --- Source 1: DocSetQuery local index ---
        rc, stdout, stderr = await _run_tool([
            str(TOOLS_DIR / "docindex.py"), "search", query,
        ])
        if rc == 0:
            results = _parse_search_results(stdout)
            if framework:
                fw_lower = framework.lower()
                results = [
                    r for r in results
                    if fw_lower in r["path"].lower() or fw_lower in r["title"].lower()
                ]
            found_local = len(results)
            for hit in results[:top_k]:
                file_path = DOCSET_QUERY_ROOT / hit["path"]
                section = None
                if hit["anchor"]:
                    section = await asyncio.to_thread(
                        _read_section, file_path, hit["anchor"]
                    )
                parts.append(f"### [docset] {hit['title']}: {hit['heading']}")
                parts.append(f"_Source: {hit['path']}#{hit['anchor']}_")
                if section:
                    if len(section) > 2000:
                        section = section[:2000] + "\n...(truncated)"
                    parts.append(section)
                else:
                    parts.append("(section content not available)")
                parts.append("")

        # --- Source 2: Knowledge store (Context7 + indexed exports) ---
        store = _get_store_from_ctx(ctx)
        if store is not None:
            try:
                search_query = f"{framework} {query}" if framework else query
                store_results = store.search(search_query, top_k=top_k)
                found_store = len(store_results)
                for sr in store_results:
                    title = sr.get("title", "untitled")
                    label = sr.get("label", "unknown")
                    text = sr.get("text", "")
                    if len(text) > 2000:
                        text = text[:2000] + "\n...(truncated)"
                    parts.append(f"### [knowledge:{label}] {title}")
                    parts.append(text)
                    parts.append("")
            except Exception as exc:
                log.warning("Knowledge store search failed: %s", exc)

        if not parts:
            hint = ""
            if framework and framework.lower() in FRAMEWORK_PATHS:
                hint = (
                    f" Try rlm_apple_export('{framework}') to index "
                    f"those docs first."
                )
            return f"No results for '{query}'.{hint}"

        header = (
            f"Found {found_local} docset + {found_store} knowledge store "
            f"results for '{query}'"
        )
        if framework:
            header += f" (framework: {framework})"
        return header + "\n\n" + "\n".join(parts)
