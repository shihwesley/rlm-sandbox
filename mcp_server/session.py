"""Session persistence: save/restore sandbox kernel state across restarts."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path

import httpx

from mcp_server.docker_manager import BASE_URL

log = logging.getLogger(__name__)

SESSIONS_DIR = Path.home() / ".rlm-sandbox" / "sessions"
AUTO_SAVE_INTERVAL = 300  # 5 minutes
SNAPSHOT_EXPIRY_DAYS = 7


def _session_id(working_dir: str | None = None) -> str:
    """Deterministic session ID from the working directory path."""
    wd = working_dir or os.getcwd()
    return hashlib.sha256(wd.encode()).hexdigest()[:16]


def _snapshot_path(session_id: str) -> Path:
    return SESSIONS_DIR / f"{session_id}.pkl"


class SessionManager:
    """Orchestrates saving/restoring kernel snapshots via the sandbox HTTP API."""

    def __init__(self, working_dir: str | None = None):
        self.session_id = _session_id(working_dir)
        self._save_task: asyncio.Task | None = None

    async def save(self) -> bool:
        """Ask the sandbox to serialize its namespace, then write to disk."""
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(f"{BASE_URL}/snapshot/save", timeout=30)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("Snapshot save failed (HTTP): %s", e)
            return False

        snapshot_b64 = data.get("snapshot")
        if not snapshot_b64:
            log.warning("Snapshot save returned no data")
            return False

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        path = _snapshot_path(self.session_id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(snapshot_b64)
        tmp.rename(path)  # atomic on POSIX

        saved = data.get("saved", [])
        skipped = data.get("skipped", [])
        log.info("Saved session %s (%d vars, %d skipped)", self.session_id, len(saved), len(skipped))
        return True

    async def restore(self) -> bool:
        """Load snapshot from disk and send to sandbox for deserialization."""
        path = _snapshot_path(self.session_id)
        if not path.exists():
            log.info("No snapshot for session %s, starting fresh", self.session_id)
            return False

        # Check expiry
        age_days = (time.time() - path.stat().st_mtime) / 86400
        if age_days > SNAPSHOT_EXPIRY_DAYS:
            log.info("Snapshot for %s expired (%.1f days), removing", self.session_id, age_days)
            path.unlink(missing_ok=True)
            return False

        snapshot_b64 = path.read_text()
        try:
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{BASE_URL}/snapshot/restore",
                    json={"snapshot": snapshot_b64},
                    timeout=30,
                )
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            log.warning("Snapshot restore failed: %s — starting fresh", e)
            path.unlink(missing_ok=True)
            return False

        if "error" in data:
            log.warning("Corrupt snapshot for %s: %s — removed", self.session_id, data["error"])
            path.unlink(missing_ok=True)
            return False

        restored = data.get("restored", [])
        log.info("Restored session %s (%d vars)", self.session_id, len(restored))
        return True

    def start_auto_save(self) -> None:
        """Kick off a background loop that saves every AUTO_SAVE_INTERVAL seconds."""
        if self._save_task and not self._save_task.done():
            return
        self._save_task = asyncio.create_task(self._auto_save_loop())

    async def stop_auto_save(self) -> None:
        if self._save_task and not self._save_task.done():
            self._save_task.cancel()
            try:
                await self._save_task
            except asyncio.CancelledError:
                pass

    async def _auto_save_loop(self) -> None:
        while True:
            await asyncio.sleep(AUTO_SAVE_INTERVAL)
            try:
                await self.save()
            except Exception:
                log.exception("Auto-save failed")

    @staticmethod
    def cleanup_expired() -> int:
        """Remove snapshots older than SNAPSHOT_EXPIRY_DAYS. Returns count removed."""
        if not SESSIONS_DIR.exists():
            return 0
        removed = 0
        cutoff = time.time() - (SNAPSHOT_EXPIRY_DAYS * 86400)
        for f in SESSIONS_DIR.glob("*.pkl"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        return removed
