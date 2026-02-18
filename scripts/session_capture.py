"""session_capture.py — Claude Code Stop hook for auto-indexing session transcripts.

Usage (Stop hook):
    python3 scripts/session_capture.py

    Claude Code passes the hook payload as JSON on stdin:
        {"transcript_path": "/path/to/session.jsonl", ...}

    Or pass the transcript path directly as an argument:
        python3 scripts/session_capture.py /path/to/session.jsonl

If no transcript path is found, the script exits cleanly (AC-5).
Standalone — does not require the MCP server to be running (REQ-7).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

log = logging.getLogger(__name__)

# Target chunk size in bytes (~4 KB). Chunks never split mid-message.
CHUNK_SIZE = 4096

# .mv2 storage directory — mirrors KnowledgeStore.KNOWLEDGE_DIR
KNOWLEDGE_DIR = os.path.expanduser("~/.rlm-sandbox/knowledge")

# Tags to strip from transcript content (REQ-2).
_STRIP_PATTERNS = [
    re.compile(r"<system-reminder>.*?</system-reminder>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<command-name>.*?</command-name>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<user-prompt-submit-hook>.*?</user-prompt-submit-hook>", re.DOTALL | re.IGNORECASE),
    re.compile(r"<system_warning>.*?</system_warning>", re.DOTALL | re.IGNORECASE),
    # Generic catch-all for remaining injected tags with known prefixes
    re.compile(r"</?system[^>]*>", re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_hash(project_path: str | None = None) -> str:
    """Replicate KnowledgeStore's hash logic for .mv2 path resolution."""
    path = project_path or os.getcwd()
    return hashlib.sha256(path.encode()).hexdigest()[:16]


def _mv2_path(project_path: str | None = None) -> str:
    ph = _project_hash(project_path)
    return os.path.join(KNOWLEDGE_DIR, f"{ph}.mv2")


def strip_injected_tags(text: str) -> str:
    """Remove injected XML tags that Claude Code inserts into transcripts (REQ-2)."""
    for pattern in _STRIP_PATTERNS:
        text = pattern.sub("", text)
    return text.strip()


def _git_info() -> dict[str, str]:
    """Collect git metadata via subprocess (REQ-3). Silently ignores errors."""
    info: dict[str, str] = {}
    try:
        info["git_user"] = subprocess.check_output(
            ["git", "config", "user.name"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        info["git_user"] = ""
    try:
        info["git_branch"] = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        info["git_branch"] = ""
    return info


def parse_transcript(path: str) -> list[dict[str, str]]:
    """Parse a JSONL transcript file. Returns list of {role, content} dicts (REQ-1).

    Lines that aren't valid JSON or lack role/content are skipped.
    """
    messages: list[dict[str, str]] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = obj.get("role") or obj.get("type", "")
                content = obj.get("content") or obj.get("message", "")
                if not role or not content:
                    continue
                if isinstance(content, list):
                    # Claude API format: content is a list of blocks
                    parts: list[str] = []
                    for block in content:
                        if isinstance(block, dict):
                            parts.append(block.get("text", "") or str(block))
                        else:
                            parts.append(str(block))
                    content = "\n".join(parts)
                messages.append({"role": str(role), "content": str(content)})
    except OSError as exc:
        log.error("Cannot read transcript %s: %s", path, exc)
    return messages


def chunk_messages(messages: list[dict[str, str]], chunk_size: int = CHUNK_SIZE) -> list[str]:
    """Group messages into ~chunk_size byte segments without splitting mid-message (REQ-4).

    Each chunk is a plaintext block of "ROLE: content" turns.
    """
    chunks: list[str] = []
    current_parts: list[str] = []
    current_size = 0

    for msg in messages:
        cleaned = strip_injected_tags(msg["content"])
        if not cleaned:
            continue
        line = f"{msg['role'].upper()}: {cleaned}\n"
        line_size = len(line.encode("utf-8"))
        if current_parts and current_size + line_size > chunk_size:
            chunks.append("".join(current_parts))
            current_parts = []
            current_size = 0
        current_parts.append(line)
        current_size += line_size

    if current_parts:
        chunks.append("".join(current_parts))

    return chunks


def _session_id(transcript_path: str) -> str:
    """Derive a session ID from the transcript filename."""
    basename = os.path.basename(transcript_path)
    # Remove extension for a cleaner ID
    return os.path.splitext(basename)[0]


def collect_metadata(transcript_path: str, project_path: str | None = None) -> dict[str, Any]:
    """Build per-session metadata dict (REQ-3)."""
    git = _git_info()
    return {
        "session_id": _session_id(transcript_path),
        "project_dir": project_path or os.getcwd(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_user": git.get("git_user", ""),
        "git_branch": git.get("git_branch", ""),
        "thread": "sessions",
    }


def ingest(transcript_path: str, project_path: str | None = None) -> int:
    """Main ingest pipeline. Returns number of chunks indexed (REQ-5, REQ-6).

    Opens the .mv2 file directly via memvid_sdk (REQ-7), calls put_many() once
    with all chunks, then seals once (REQ-6).
    """
    messages = parse_transcript(transcript_path)
    if not messages:
        log.info("No messages found in %s; skipping.", transcript_path)
        return 0

    chunks = chunk_messages(messages)
    if not chunks:
        log.info("No indexable chunks from %s; skipping.", transcript_path)
        return 0

    meta = collect_metadata(transcript_path, project_path)
    mv2_path = _mv2_path(project_path)
    session_id = meta["session_id"]

    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)

    # Build document list for put_many
    docs = []
    for i, text in enumerate(chunks, 1):
        docs.append(
            {
                "title": f"session:{session_id}:chunk-{i}",
                "label": "session",
                "text": text,
                "metadata": {**meta},
            }
        )

    # Open or create the .mv2 file directly (REQ-7)
    try:
        from memvid_sdk import create, use
        try:
            from memvid_sdk.embeddings import get_embedder
            embedder = get_embedder("huggingface", model="all-MiniLM-L6-v2")
        except Exception:
            embedder = None

        if os.path.exists(mv2_path):
            mem = use("basic", mv2_path)
        else:
            mem = create(mv2_path, enable_vec=True, enable_lex=True)

        mem.put_many(docs, embedder=embedder)
        mem.seal()  # Seal once (REQ-6)

        log.info("Indexed %d chunks from session %s into %s", len(docs), session_id, mv2_path)
        return len(docs)

    except ImportError as exc:
        log.error("memvid_sdk not available: %s", exc)
        return 0
    except Exception as exc:
        log.error("Failed to ingest session %s: %s", session_id, exc)
        return 0


def main() -> None:
    """Entry point. Called by Claude Code Stop hook or CLI."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    transcript_path: str | None = None

    if len(sys.argv) > 1:
        # Direct path argument
        transcript_path = sys.argv[1]
    else:
        # Claude Code Stop hook passes JSON on stdin
        try:
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw)
                transcript_path = payload.get("transcript_path")
        except Exception:
            pass

    if not transcript_path:
        # AC-5: exit cleanly when no transcript path provided
        sys.exit(0)

    if not os.path.exists(transcript_path):
        log.warning("Transcript not found: %s", transcript_path)
        sys.exit(0)

    count = ingest(transcript_path)
    print(f"session_capture: indexed {count} chunks from {transcript_path}", flush=True)


if __name__ == "__main__":
    main()
