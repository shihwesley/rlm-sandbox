---
name: session-capture
phase: 6
sprint: 2
parent: null
depends_on: [thread-support]
status: draft
created: 2026-02-17
---

# Session Auto-Capture

## Overview

Add a Claude Code Stop hook that auto-indexes session transcripts into the project's knowledge store. Uses a CLI bridge script (no MCP server dependency). Every session becomes searchable.

## Requirements

- [ ] REQ-1: Python script parses JSONL session transcripts
- [ ] REQ-2: Strips system-reminder, command-name, and other injected tags
- [ ] REQ-3: Collects metadata: git user, branch, project dir, timestamp, session ID
- [ ] REQ-4: Chunks transcript by message boundaries (~4KB segments)
- [ ] REQ-5: Ingests into project's .mv2 file with label="session", thread="sessions"
- [ ] REQ-6: Seals once at the end (not per-chunk)
- [ ] REQ-7: Works standalone — does not require MCP server to be running

## Acceptance Criteria

- [ ] AC-1: Running script on a JSONL transcript file produces indexed chunks
- [ ] AC-2: `rlm_search("query", thread="sessions")` finds session content
- [ ] AC-3: Metadata includes git branch and session timestamp
- [ ] AC-4: System-reminder tags stripped from indexed text
- [ ] AC-5: Script exits cleanly if no transcript path provided (no-op)

## Technical Approach

**`scripts/session_capture.py`:**
- Reads transcript JSONL from path (arg or stdin JSON with `transcript_path`)
- Parses each line as JSON, extracts role + content
- Regex-strips `<system-reminder>...</system-reminder>`, `<command-name>...</command-name>`, etc.
- Collects git metadata via subprocess (git config user.name, git rev-parse --abbrev-ref HEAD)
- Chunks into ~4KB segments at message boundaries
- Opens .mv2 directly via `memvid_sdk` using same project hash logic as knowledge.py
- Calls `put_many()` with all chunks, seals once

**Hook config** (documented, user-installed):
```json
{"hooks": {"Stop": [{"type": "command", "command": "python3 scripts/session_capture.py"}]}}
```

## Files

| File | Action | Purpose |
|------|--------|---------|
| scripts/session_capture.py | create | Main capture script |
| tests/test_session_capture.py | create | Test parsing, chunking, tag stripping |

## Tasks

1. Create JSONL parser that extracts user/assistant turns
2. Implement system-tag stripping via regex
3. Implement metadata collection (git user, branch, timestamp)
4. Implement message-boundary chunking (~4KB)
5. Wire memvid_sdk direct ingestion with thread="sessions"
6. Add tests for parsing, stripping, chunking

## Dependencies

- **Needs from thread-support:** thread parameter on ingest for label="session", thread="sessions"
- **Provides to:** no downstream specs
