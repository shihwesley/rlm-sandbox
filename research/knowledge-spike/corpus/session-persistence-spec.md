---
name: session-persistence
phase: 2
sprint: 1
parent: null
depends_on: [docker-sandbox, mcp-server]
status: draft
created: 2026-02-11
---

# Session Persistence

## Overview
Save and restore sandbox state so it survives across Claude Code sessions, /clear, and context compactions. Uses dill for Python object serialization and stores snapshots on the host.

## Requirements
- [ ] REQ-1: Save sandbox state (all kernel variables) to a host-side snapshot file
- [ ] REQ-2: Restore sandbox state from a snapshot on container restart
- [ ] REQ-3: Auto-save on MCP server shutdown (SessionEnd hook or graceful stop)
- [ ] REQ-4: Manual save/restore via rlm.save() and rlm.restore() MCP tools (optional)
- [ ] REQ-5: Snapshot format is portable across container rebuilds

## Acceptance Criteria
- [ ] AC-1: After rlm.exec("x = 42"), stopping and restarting the container, rlm.get("x") returns 42
- [ ] AC-2: Snapshot files stored at ~/.rlm-sandbox/sessions/{session-id}.pkl
- [ ] AC-3: Auto-save fires on container stop (not crash — crash loses unsaved state)
- [ ] AC-4: Restore handles missing/corrupt snapshots gracefully (starts fresh, warns)
- [ ] AC-5: Non-serializable variables (open files, connections) are skipped with a warning

## Technical Approach
Dedicated /snapshot/save and /snapshot/restore endpoints on the container's FastAPI server.
On save: container serializes kernel globals via dill to mounted volume.
On restore: container loads dill snapshot into kernel namespace.
MCP server orchestrates: calls /snapshot/save before shutdown, /snapshot/restore on startup.

Auto-save: periodic (every 5 min via MCP server timer) + on graceful shutdown (SIGTERM).
Crash recovery: last periodic save is the recovery point.

dill handles more types than pickle (lambdas, closures, partial functions)
which matters since the sandbox accumulates computed values.

Session ID: hash of the working directory (project root Claude Code operates in).
Per-project isolation by default.

## Files
| File | Action | Purpose |
|------|--------|---------|
| mcp-server/session.py | create | Save/restore orchestration, periodic timer, snapshot management |
| sandbox/server.py | modify | Add /snapshot/save and /snapshot/restore endpoints |
| mcp-server/server.py | modify | Hook session save into lifespan shutdown, periodic timer |
| tests/test_persistence.py | create | Tests for save/restore cycle, corrupt snapshot, non-serializable vars |

## Tasks
1. Add /snapshot/save and /snapshot/restore endpoints to sandbox server (dill-based)
2. Implement mcp-server/session.py with save/restore orchestration and periodic timer
3. Wire auto-save into MCP server lifespan shutdown + 5-min periodic save
4. Write tests for save/restore cycle, corrupt snapshot handling, non-serializable vars

## Dependencies
- **Needs from docker-sandbox:** kernel state to serialize, mounted volume for snapshots
- **Needs from mcp-server:** server lifecycle hooks for auto-save, lifespan context
- **Provides to claude-integration:** session persistence that survives /clear

## Resolved Questions
- Session ID: hash of working directory (per-project isolation by default)
- Save mechanism: dedicated /snapshot/save and /snapshot/restore endpoints (not POST /exec with dill code)
- Auto-save: periodic (5 min) + graceful shutdown. Crash loses only last 5 min.
- rlm.save/rlm.restore: deferred to v2 (auto-save covers the core use case)
- Snapshot expiry: 7 days default, configurable
