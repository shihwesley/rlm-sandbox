"""Tests for scripts/session_capture.py.

Covers: JSONL parsing, tag stripping, message-boundary chunking,
metadata collection, and the ingest pipeline (memvid_sdk mocked).
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import types
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import subprocess

import pytest

# ---------------------------------------------------------------------------
# Insert scripts/ onto path so we can import session_capture directly
# ---------------------------------------------------------------------------

SCRIPTS_DIR = str(Path(__file__).parent.parent / "scripts")
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_mem():
    """Mock memvid memory object."""
    mem = MagicMock()
    mem.put_many.return_value = ["f1", "f2"]
    mem.seal.return_value = None
    return mem


@pytest.fixture()
def mock_memvid_sdk(mock_mem):
    """Patch memvid_sdk in sys.modules so session_capture picks it up."""
    sdk = types.ModuleType("memvid_sdk")
    sdk.create = MagicMock(return_value=mock_mem)
    sdk.use = MagicMock(return_value=mock_mem)

    embeddings_mod = types.ModuleType("memvid_sdk.embeddings")
    embeddings_mod.get_embedder = MagicMock(return_value=None)

    with patch.dict(sys.modules, {"memvid_sdk": sdk, "memvid_sdk.embeddings": embeddings_mod}):
        yield sdk, mock_mem


@pytest.fixture()
def sample_jsonl(tmp_path) -> Path:
    """Write a sample JSONL transcript and return its path."""
    lines = [
        {"role": "user", "content": "Hello, world!"},
        {"role": "assistant", "content": "Hi there!"},
        {"role": "user", "content": "What is 2+2?"},
        {"role": "assistant", "content": "4"},
    ]
    p = tmp_path / "session-abc123.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines))
    return p


@pytest.fixture()
def transcript_with_tags(tmp_path) -> Path:
    """Transcript that contains system-reminder and command-name tags."""
    lines = [
        {
            "role": "user",
            "content": (
                "<system-reminder>You are Claude.</system-reminder>"
                "Can you help me?"
            ),
        },
        {
            "role": "assistant",
            "content": (
                "<command-name>bash</command-name>"
                "Sure, running the command now."
            ),
        },
        {
            "role": "user",
            "content": "Normal message without tags.",
        },
    ]
    p = tmp_path / "session-tags.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines))
    return p


# ---------------------------------------------------------------------------
# Import the module under test (after fixtures declared)
# ---------------------------------------------------------------------------

import importlib
import session_capture  # noqa: E402  (imported after sys.path update)


# ---------------------------------------------------------------------------
# REQ-1 / AC-1: JSONL parsing
# ---------------------------------------------------------------------------


class TestParseTranscript:
    def test_basic_parse(self, sample_jsonl):
        msgs = session_capture.parse_transcript(str(sample_jsonl))
        assert len(msgs) == 4
        assert msgs[0] == {"role": "user", "content": "Hello, world!"}
        assert msgs[1] == {"role": "assistant", "content": "Hi there!"}

    def test_skips_invalid_json_lines(self, tmp_path):
        p = tmp_path / "bad.jsonl"
        p.write_text('{"role": "user", "content": "ok"}\nNOT JSON\n{"role": "assistant", "content": "yes"}\n')
        msgs = session_capture.parse_transcript(str(p))
        assert len(msgs) == 2

    def test_skips_lines_without_role(self, tmp_path):
        p = tmp_path / "norole.jsonl"
        p.write_text('{"content": "no role here"}\n{"role": "user", "content": "has role"}\n')
        msgs = session_capture.parse_transcript(str(p))
        assert len(msgs) == 1
        assert msgs[0]["role"] == "user"

    def test_skips_lines_without_content(self, tmp_path):
        p = tmp_path / "nocontent.jsonl"
        p.write_text('{"role": "user"}\n{"role": "user", "content": "present"}\n')
        msgs = session_capture.parse_transcript(str(p))
        assert len(msgs) == 1

    def test_handles_missing_file(self, tmp_path):
        msgs = session_capture.parse_transcript(str(tmp_path / "nonexistent.jsonl"))
        assert msgs == []

    def test_list_content_blocks(self, tmp_path):
        """Claude API format where content is a list of blocks."""
        line = json.dumps({
            "role": "assistant",
            "content": [{"type": "text", "text": "Part A"}, {"type": "text", "text": "Part B"}],
        })
        p = tmp_path / "blocks.jsonl"
        p.write_text(line + "\n")
        msgs = session_capture.parse_transcript(str(p))
        assert len(msgs) == 1
        assert "Part A" in msgs[0]["content"]
        assert "Part B" in msgs[0]["content"]

    def test_empty_file(self, tmp_path):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        assert session_capture.parse_transcript(str(p)) == []

    def test_blank_lines_skipped(self, tmp_path):
        p = tmp_path / "blanks.jsonl"
        p.write_text('\n\n{"role": "user", "content": "hi"}\n\n')
        msgs = session_capture.parse_transcript(str(p))
        assert len(msgs) == 1


# ---------------------------------------------------------------------------
# REQ-2: Tag stripping
# ---------------------------------------------------------------------------


class TestStripInjectedTags:
    def test_strips_system_reminder(self):
        text = "<system-reminder>Secret instructions.</system-reminder>User message."
        result = session_capture.strip_injected_tags(text)
        assert "<system-reminder>" not in result
        assert "Secret instructions." not in result
        assert "User message." in result

    def test_strips_command_name(self):
        text = "<command-name>bash</command-name>Run now."
        result = session_capture.strip_injected_tags(text)
        assert "<command-name>" not in result
        assert "bash" not in result
        assert "Run now." in result

    def test_strips_user_prompt_submit_hook(self):
        text = "<user-prompt-submit-hook>hook data</user-prompt-submit-hook>actual content"
        result = session_capture.strip_injected_tags(text)
        assert "hook data" not in result
        assert "actual content" in result

    def test_strips_system_warning(self):
        text = "<system_warning>Token usage: 1000/5000</system_warning>Normal text."
        result = session_capture.strip_injected_tags(text)
        assert "Token usage" not in result
        assert "Normal text." in result

    def test_multiline_tag(self):
        text = "<system-reminder>\nLine 1\nLine 2\n</system-reminder>After."
        result = session_capture.strip_injected_tags(text)
        assert "Line 1" not in result
        assert "After." in result

    def test_no_tags_unchanged(self):
        text = "Plain text without any tags."
        assert session_capture.strip_injected_tags(text) == text

    def test_empty_string(self):
        assert session_capture.strip_injected_tags("") == ""

    def test_strips_from_parsed_transcript(self, transcript_with_tags):
        msgs = session_capture.parse_transcript(str(transcript_with_tags))
        chunks = session_capture.chunk_messages(msgs)
        combined = " ".join(chunks)
        assert "<system-reminder>" not in combined
        assert "<command-name>" not in combined
        assert "You are Claude." not in combined
        assert "Can you help me?" in combined
        assert "Sure, running the command now." in combined


# ---------------------------------------------------------------------------
# REQ-4: Chunking
# ---------------------------------------------------------------------------


class TestChunkMessages:
    def test_basic_chunking(self, sample_jsonl):
        msgs = session_capture.parse_transcript(str(sample_jsonl))
        chunks = session_capture.chunk_messages(msgs)
        assert len(chunks) >= 1
        # All messages should appear somewhere in the chunks
        combined = " ".join(chunks)
        assert "Hello, world!" in combined
        assert "Hi there!" in combined

    def test_respects_chunk_boundary(self):
        """Messages that together exceed chunk_size should split into multiple chunks."""
        big_content = "A" * 3000
        messages = [
            {"role": "user", "content": big_content},
            {"role": "assistant", "content": big_content},
        ]
        chunks = session_capture.chunk_messages(messages, chunk_size=4096)
        # Each message is ~3000 bytes; combined ~6000 > 4096, so should split
        assert len(chunks) == 2

    def test_does_not_split_single_large_message(self):
        """A single message larger than chunk_size must not be split mid-message."""
        big = "X" * 6000
        messages = [{"role": "user", "content": big}]
        chunks = session_capture.chunk_messages(messages, chunk_size=4096)
        assert len(chunks) == 1
        assert big in chunks[0]

    def test_empty_messages(self):
        assert session_capture.chunk_messages([]) == []

    def test_messages_with_only_tags_produce_no_chunks(self):
        """After stripping, if content is empty the message is skipped."""
        messages = [{"role": "user", "content": "<system-reminder>only tags</system-reminder>"}]
        chunks = session_capture.chunk_messages(messages)
        assert chunks == []

    def test_chunk_contains_role_prefix(self):
        messages = [{"role": "user", "content": "test content"}]
        chunks = session_capture.chunk_messages(messages)
        assert "USER:" in chunks[0]

    def test_multiple_small_messages_grouped(self):
        """Many small messages should be grouped into fewer chunks."""
        messages = [{"role": "user", "content": "hi"} for _ in range(10)]
        chunks = session_capture.chunk_messages(messages, chunk_size=4096)
        assert len(chunks) == 1  # all tiny, should be one chunk


# ---------------------------------------------------------------------------
# REQ-3: Metadata collection
# ---------------------------------------------------------------------------


class TestCollectMetadata:
    def test_metadata_fields_present(self, sample_jsonl):
        with patch("subprocess.check_output") as mock_sub:
            mock_sub.side_effect = ["Test User\n", "main\n"]
            meta = session_capture.collect_metadata(str(sample_jsonl))
        assert "session_id" in meta
        assert "project_dir" in meta
        assert "timestamp" in meta
        assert "git_user" in meta
        assert "git_branch" in meta
        assert meta["thread"] == "sessions"

    def test_session_id_from_filename(self, sample_jsonl):
        meta = session_capture.collect_metadata(str(sample_jsonl))
        # session id should be derived from the filename without extension
        assert "session-abc123" in meta["session_id"]

    def test_git_user_collected(self, sample_jsonl):
        with patch("subprocess.check_output") as mock_sub:
            mock_sub.side_effect = ["Jane Doe\n", "feature/x\n"]
            meta = session_capture.collect_metadata(str(sample_jsonl))
        assert meta["git_user"] == "Jane Doe"
        assert meta["git_branch"] == "feature/x"

    def test_git_failure_does_not_crash(self, sample_jsonl):
        with patch("subprocess.check_output", side_effect=subprocess.CalledProcessError(1, "git")):
            meta = session_capture.collect_metadata(str(sample_jsonl))
        assert meta["git_user"] == ""
        assert meta["git_branch"] == ""

    def test_project_path_override(self, sample_jsonl):
        meta = session_capture.collect_metadata(str(sample_jsonl), project_path="/custom/path")
        assert meta["project_dir"] == "/custom/path"

    def test_thread_is_sessions(self, sample_jsonl):
        meta = session_capture.collect_metadata(str(sample_jsonl))
        assert meta["thread"] == "sessions"


# ---------------------------------------------------------------------------
# REQ-5, REQ-6, REQ-7: Ingest pipeline
# ---------------------------------------------------------------------------


class TestIngest:
    def test_ingest_calls_put_many_and_seal(self, sample_jsonl, mock_memvid_sdk, tmp_path):
        sdk, mock_mem = mock_memvid_sdk
        project_path = str(tmp_path)

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.path.exists", side_effect=lambda p: p == str(sample_jsonl)), \
             patch("os.makedirs"):
            count = session_capture.ingest(str(sample_jsonl), project_path=project_path)

        assert sdk.create.called or sdk.use.called
        mock_mem.put_many.assert_called_once()
        mock_mem.seal.assert_called_once()  # REQ-6: sealed exactly once
        assert count > 0

    def test_ingest_uses_label_session(self, sample_jsonl, mock_memvid_sdk, tmp_path):
        sdk, mock_mem = mock_memvid_sdk
        project_path = str(tmp_path)

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.path.exists", side_effect=lambda p: p == str(sample_jsonl)), \
             patch("os.makedirs"):
            session_capture.ingest(str(sample_jsonl), project_path=project_path)

        docs = mock_mem.put_many.call_args[0][0]
        assert all(d["label"] == "session" for d in docs)

    def test_ingest_includes_thread_sessions(self, sample_jsonl, mock_memvid_sdk, tmp_path):
        sdk, mock_mem = mock_memvid_sdk
        project_path = str(tmp_path)

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.path.exists", side_effect=lambda p: p == str(sample_jsonl)), \
             patch("os.makedirs"):
            session_capture.ingest(str(sample_jsonl), project_path=project_path)

        docs = mock_mem.put_many.call_args[0][0]
        assert all(d["metadata"].get("thread") == "sessions" for d in docs)

    def test_ingest_returns_zero_for_empty_transcript(self, tmp_path, mock_memvid_sdk):
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        count = session_capture.ingest(str(p), project_path=str(tmp_path))
        assert count == 0

    def test_ingest_returns_zero_when_memvid_unavailable(self, sample_jsonl, tmp_path):
        with patch.dict(sys.modules, {"memvid_sdk": None}):
            # Force ImportError by removing from sys.modules
            saved = sys.modules.pop("memvid_sdk", None)
            try:
                count = session_capture.ingest(str(sample_jsonl), project_path=str(tmp_path))
                assert count == 0
            finally:
                if saved is not None:
                    sys.modules["memvid_sdk"] = saved

    def test_ingest_uses_existing_mv2_when_present(self, sample_jsonl, mock_memvid_sdk, tmp_path):
        sdk, mock_mem = mock_memvid_sdk
        project_path = str(tmp_path)
        mv2_path = session_capture._mv2_path(project_path)

        def exists_side_effect(path):
            if path == str(sample_jsonl):
                return True
            if path == mv2_path:
                return True
            return os.path.exists.__wrapped__(path) if hasattr(os.path.exists, "__wrapped__") else False

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.path.exists", side_effect=exists_side_effect), \
             patch("os.makedirs"):
            session_capture.ingest(str(sample_jsonl), project_path=project_path)

        # use() should be called (not create()) since mv2 "exists"
        sdk.use.assert_called_once()
        sdk.create.assert_not_called()

    def test_ingest_creates_mv2_when_missing(self, sample_jsonl, mock_memvid_sdk, tmp_path):
        sdk, mock_mem = mock_memvid_sdk
        project_path = str(tmp_path)

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.path.exists", side_effect=lambda p: p == str(sample_jsonl)), \
             patch("os.makedirs"):
            session_capture.ingest(str(sample_jsonl), project_path=project_path)

        sdk.create.assert_called_once()
        sdk.use.assert_not_called()


# ---------------------------------------------------------------------------
# REQ-7: Standalone — project hash logic matches knowledge.py
# ---------------------------------------------------------------------------


class TestProjectHash:
    def test_hash_matches_knowledge_py_logic(self):
        """Verify _project_hash replicates KnowledgeStore's hash exactly."""
        test_path = "/Users/test/myproject"
        expected = hashlib.sha256(test_path.encode()).hexdigest()[:16]
        assert session_capture._project_hash(test_path) == expected

    def test_hash_uses_cwd_when_no_path(self):
        expected = hashlib.sha256(os.getcwd().encode()).hexdigest()[:16]
        assert session_capture._project_hash() == expected

    def test_mv2_path_format(self):
        path = session_capture._mv2_path("/my/project")
        assert path.endswith(".mv2")
        assert "/.rlm-sandbox/knowledge/" in path


# ---------------------------------------------------------------------------
# AC-5: main() exits cleanly with no transcript
# ---------------------------------------------------------------------------


class TestMain:
    def test_exits_cleanly_with_no_args(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["session_capture.py"])
        monkeypatch.setattr(sys, "stdin", StringIO(""))
        with pytest.raises(SystemExit) as exc_info:
            session_capture.main()
        assert exc_info.value.code == 0

    def test_exits_cleanly_with_empty_stdin(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["session_capture.py"])
        monkeypatch.setattr(sys, "stdin", StringIO("{}"))
        with pytest.raises(SystemExit) as exc_info:
            session_capture.main()
        assert exc_info.value.code == 0

    def test_exits_cleanly_with_nonexistent_path(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["session_capture.py", "/nonexistent/path.jsonl"])
        with pytest.raises(SystemExit) as exc_info:
            session_capture.main()
        assert exc_info.value.code == 0

    def test_reads_transcript_path_from_stdin_json(self, monkeypatch, tmp_path, mock_memvid_sdk):
        sdk, mock_mem = mock_memvid_sdk
        p = tmp_path / "sess.jsonl"
        p.write_text(json.dumps({"role": "user", "content": "hi"}) + "\n")

        payload = json.dumps({"transcript_path": str(p)})
        monkeypatch.setattr(sys, "argv", ["session_capture.py"])
        monkeypatch.setattr(sys, "stdin", StringIO(payload))

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.makedirs"):
            # Should not raise
            try:
                session_capture.main()
            except SystemExit:
                pass

        mock_mem.put_many.assert_called_once()

    def test_reads_transcript_path_from_argv(self, monkeypatch, tmp_path, mock_memvid_sdk):
        sdk, mock_mem = mock_memvid_sdk
        p = tmp_path / "sess.jsonl"
        p.write_text(json.dumps({"role": "user", "content": "hello"}) + "\n")

        monkeypatch.setattr(sys, "argv", ["session_capture.py", str(p)])

        with patch("subprocess.check_output", return_value="user\n"), \
             patch("os.makedirs"):
            session_capture.main()

        mock_mem.put_many.assert_called_once()
