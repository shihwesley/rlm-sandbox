"""Memvid-backed knowledge store with MCP tool registrations.

Stores one .mv2 file per project. Supports hybrid search (BM25 + vector),
RAG Q&A, timeline retrieval, and incremental indexing.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any

from mcp.server.fastmcp import Context

log = logging.getLogger(__name__)

KNOWLEDGE_DIR = os.path.expanduser("~/.rlm-sandbox/knowledge")

# Minimum relevancy score for adaptive retrieval (score-cliff cutoff)
DEFAULT_MIN_RELEVANCY = 0.35
DEFAULT_ADAPTIVE_MAX_K = 30


def _project_hash(project_path: str | None = None) -> str:
    """Deterministic hash from the project path (or cwd)."""
    path = project_path or os.getcwd()
    return hashlib.sha256(path.encode()).hexdigest()[:16]


class KnowledgeStore:
    """Per-project knowledge index backed by a memvid .mv2 file.

    Wraps memvid_sdk's create/use API. Falls back to lex-only mode
    when sentence-transformers is unavailable.
    """

    def __init__(self, project_hash: str):
        self.project_hash = project_hash
        self.path = os.path.join(KNOWLEDGE_DIR, f"{project_hash}.mv2")
        self.mem = None
        self._embedder = None
        self._embedder_checked = False

    @property
    def embedder(self):
        """Lazy-load HuggingFace embedder. Returns None if unavailable (lex-only)."""
        if not self._embedder_checked:
            self._embedder_checked = True
            try:
                from memvid_sdk.embeddings import get_embedder
                self._embedder = get_embedder("huggingface", model="all-MiniLM-L6-v2")
            except (ImportError, Exception) as exc:
                log.warning("Embedder unavailable, lex-only mode: %s", exc)
                self._embedder = None
        return self._embedder

    def open(self) -> None:
        """Open existing .mv2 or create a new one."""
        if self.mem is not None:
            return

        if os.path.exists(self.path):
            from memvid_sdk import use
            self.mem = use("basic", self.path)
            log.info("Opened existing knowledge store: %s", self.path)
        else:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            from memvid_sdk import create
            self.mem = create(self.path, enable_vec=True, enable_lex=True)
            log.info("Created new knowledge store: %s", self.path)

    def close(self) -> None:
        """Commit and close the store."""
        if self.mem is not None:
            try:
                self.mem.seal()
            except Exception:
                log.exception("Failed to seal knowledge store")
            self.mem = None

    def _ensure_open(self) -> None:
        if self.mem is None:
            self.open()

    def ingest(
        self,
        title: str,
        text: str,
        label: str = "kb",
        metadata: dict[str, Any] | None = None,
    ) -> list:
        """Add a single document incrementally. Returns frame IDs."""
        self._ensure_open()
        doc = {
            "title": title,
            "label": label,
            "text": text,
            "metadata": metadata or {},
        }
        frame_ids = self.mem.put_many([doc], embedder=self.embedder)
        self.mem.commit()
        return frame_ids

    def ingest_many(
        self,
        docs: list[dict[str, Any]],
    ) -> list:
        """Batch-ingest documents. Each dict needs at least 'title' and 'text'."""
        self._ensure_open()
        prepared = []
        for d in docs:
            prepared.append({
                "title": d["title"],
                "label": d.get("label", "kb"),
                "text": d["text"],
                "metadata": d.get("metadata", {}),
            })
        frame_ids = self.mem.put_many(prepared, embedder=self.embedder)
        self.mem.commit()
        return frame_ids

    def search(
        self,
        query: str,
        top_k: int = 10,
        mode: str = "auto",
        adaptive: bool = True,
    ) -> dict[str, Any]:
        """Hybrid search with adaptive retrieval (score-cliff cutoff).

        Returns dict with 'hits' list. Each hit has title, score, snippet.
        """
        self._ensure_open()

        kwargs: dict[str, Any] = {
            "mode": mode,
            "embedder": self.embedder,
        }

        if adaptive:
            kwargs["adaptive"] = True
            kwargs["min_relevancy"] = DEFAULT_MIN_RELEVANCY
            kwargs["max_k"] = DEFAULT_ADAPTIVE_MAX_K
            kwargs["adaptive_strategy"] = "combined"
        else:
            kwargs["k"] = top_k

        results = self.mem.find(query, **kwargs)
        # Trim to top_k even with adaptive (adaptive may return up to max_k)
        if "hits" in results:
            results["hits"] = results["hits"][:top_k]
        return results

    def ask(
        self,
        question: str,
        context_only: bool = False,
        top_k: int = 8,
        mode: str = "auto",
    ) -> dict[str, Any]:
        """RAG Q&A or context-only chunk retrieval."""
        self._ensure_open()
        return self.mem.ask(
            question,
            k=top_k,
            mode=mode,
            context_only=context_only,
            embedder=self.embedder,
        )

    def timeline(
        self,
        since: int | None = None,
        until: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Chronological retrieval of indexed documents."""
        self._ensure_open()
        kwargs: dict[str, Any] = {"limit": limit}
        if since is not None:
            kwargs["since"] = since
        if until is not None:
            kwargs["until"] = until
        return self.mem.timeline(**kwargs)

    def enrich(self, engine: str = "rules") -> dict[str, Any]:
        """Entity extraction (opt-in). Uses regex-based rules by default."""
        self._ensure_open()
        return self.mem.enrich(engine=engine)


# -- Singleton cache: one store per project_hash --
_stores: dict[str, KnowledgeStore] = {}


def get_store(project_hash: str | None = None) -> KnowledgeStore:
    """Get or create a KnowledgeStore for the given project hash."""
    h = project_hash or _project_hash()
    if h not in _stores:
        _stores[h] = KnowledgeStore(h)
    return _stores[h]


def _format_hits(hits: list[dict], include_score: bool = True) -> str:
    """Format search hits into readable text."""
    if not hits:
        return "No results found."
    lines = []
    for i, hit in enumerate(hits, 1):
        title = hit.get("title", "(untitled)")
        snippet = hit.get("snippet", hit.get("text", ""))
        score = hit.get("score", 0)
        if include_score:
            lines.append(f"[{i}] {title} (score: {score:.3f})")
        else:
            lines.append(f"[{i}] {title}")
        if snippet:
            # Truncate long snippets
            if len(snippet) > 500:
                snippet = snippet[:500] + "..."
            lines.append(f"    {snippet}")
        lines.append("")
    return "\n".join(lines)


# -- MCP tool registration --


def register_knowledge_tools(mcp) -> None:
    """Register knowledge-store tools on the MCP server instance."""

    @mcp.tool()
    async def rlm_search(
        query: str,
        ctx: Context,
        top_k: int = 10,
        mode: str = "auto",
        project: str | None = None,
    ) -> str:
        """Search the knowledge store. Returns ranked chunks with source attribution.

        Args:
            query: Search query string
            top_k: Max results to return (default 10)
            mode: Search mode - 'auto' (hybrid), 'vec' (vector only), 'lex' (BM25 only)
            project: Project hash override (uses cwd-based hash if omitted)
        """
        try:
            store = get_store(project)
            results = store.search(query, top_k=top_k, mode=mode)
            hits = results.get("hits", [])
            if not hits:
                return "No results found."
            return _format_hits(hits)
        except Exception as exc:
            log.exception("rlm_search failed")
            return f"Error: {exc}"

    @mcp.tool()
    async def rlm_ask(
        question: str,
        ctx: Context,
        context_only: bool = False,
        top_k: int = 8,
        mode: str = "auto",
        project: str | None = None,
    ) -> str:
        """RAG Q&A over the knowledge store, or retrieve context chunks only.

        Args:
            question: The question to answer
            context_only: If True, return only retrieved chunks (no LLM answer)
            top_k: Number of context chunks to retrieve
            mode: Search mode - 'auto', 'vec', 'lex'
            project: Project hash override
        """
        try:
            store = get_store(project)
            result = store.ask(
                question,
                context_only=context_only,
                top_k=top_k,
                mode=mode,
            )

            parts = []
            if not context_only and result.get("answer"):
                parts.append(result["answer"])
                parts.append("")

            hits = result.get("hits", [])
            if hits:
                if not context_only:
                    parts.append("--- Sources ---")
                parts.append(_format_hits(hits, include_score=not context_only))

            return "\n".join(parts) if parts else "No relevant context found."
        except Exception as exc:
            log.exception("rlm_ask failed")
            return f"Error: {exc}"

    @mcp.tool()
    async def rlm_timeline(
        ctx: Context,
        since: int | None = None,
        until: int | None = None,
        limit: int = 20,
        project: str | None = None,
    ) -> str:
        """Chronological retrieval of indexed documents.

        Args:
            since: Unix timestamp lower bound (inclusive)
            until: Unix timestamp upper bound (inclusive)
            limit: Max entries to return (default 20)
            project: Project hash override
        """
        try:
            store = get_store(project)
            entries = store.timeline(since=since, until=until, limit=limit)

            if not entries:
                return "No entries in the requested time range."

            lines = []
            for entry in entries:
                ts = entry.get("timestamp", entry.get("ts", 0))
                title = entry.get("title", "(untitled)")
                text_preview = entry.get("text", entry.get("snippet", ""))
                if len(text_preview) > 200:
                    text_preview = text_preview[:200] + "..."
                lines.append(f"[{ts}] {title}")
                if text_preview:
                    lines.append(f"    {text_preview}")
                lines.append("")

            return "\n".join(lines)
        except Exception as exc:
            log.exception("rlm_timeline failed")
            return f"Error: {exc}"

    @mcp.tool()
    async def rlm_ingest(
        title: str,
        text: str,
        ctx: Context,
        label: str = "kb",
        project: str | None = None,
    ) -> str:
        """Ingest a document into the knowledge store.

        Args:
            title: Document title
            text: Document content
            label: Category label (default 'kb')
            project: Project hash override
        """
        try:
            store = get_store(project)
            frame_ids = store.ingest(title=title, text=text, label=label)
            return f"Ingested '{title}' ({len(text)} chars, {len(frame_ids)} frames)"
        except Exception as exc:
            log.exception("rlm_ingest failed")
            return f"Error: {exc}"
