---
name: orchestrator-integration
phase: 4
sprint: 2
parent: null
depends_on: [doc-fetcher, search-engine]
status: draft
created: 2026-02-12
---

# Orchestrator & Planning Integration

## Overview
Wire the knowledge store into existing workflows: /orchestrate Stage 4 (RESEARCH) auto-loads docs, /interactive-planning research phases use rlm_search instead of flooding context, and users can manually trigger research loading. Also adds cleanup after phases complete.

## Requirements
- [ ] REQ-1: /orchestrate Stage 4 uses rlm_fetch + rlm_load_dir to populate knowledge store before agent dispatch
- [ ] REQ-2: /interactive-planning research phases use rlm_search to query docs without context bloat
- [ ] REQ-3: Manual rlm_research(topic) trigger — fetches official docs for a topic and indexes them
- [ ] REQ-4: Knowledge cleanup option — clear indexed docs after all phases complete (configurable)
- [ ] REQ-5: Context7 integration — route Context7 results through the knowledge store instead of context

## Acceptance Criteria
- [ ] AC-1: /orchestrate --resume on a new phase auto-loads tech docs from Stage 4 into knowledge store
- [ ] AC-2: Agent prompts include "use rlm_search for docs" instead of receiving full doc content
- [ ] AC-3: rlm_research("fastapi lifespan") fetches FastAPI docs and indexes them, returns confirmation
- [ ] AC-4: After all phases complete, knowledge index can be optionally cleared via rlm_knowledge_clear
- [ ] AC-5: Context7 fetches get cached in knowledge store for future rlm_search queries

## Technical Approach
Modify existing orchestrator skills and planning skill to use rlm_* tools:

Stage 4 (RESEARCH) changes:
- Replace "Write cheat sheet to .claude/docs/" with "rlm_fetch + rlm_load_dir"
- Agent prompts say "query docs via rlm_search, don't read full files"
- Cheat sheets still created as fallback for offline/degraded mode

Interactive-planning changes:
- Research gates use rlm_fetch for web sources
- Findings written to findings.md AND indexed in knowledge store
- rlm_search available during brainstorming phases

Manual trigger:
- rlm_research(topic) = Context7 resolve + fetch + index, all in one call
- Returns: "Indexed N chunks from M sources for {topic}"

Cleanup:
- rlm_knowledge_clear() removes index + cached docs for current project
- Called optionally at end of orchestration or manually

## Files
| File | Action | Purpose |
|------|--------|---------|
| mcp_server/tools.py | modify | Register rlm_research and rlm_knowledge_clear tools |
| .claude/skills/orchestrator/tech-researcher.md | modify | Route Stage 4 through knowledge store |
| .claude/skills/interactive-planning.md | modify | Use rlm_search in research phases |
| tests/test_orchestrator_knowledge.py | create | Integration tests for orchestrator + knowledge store |

## Tasks
1. Implement rlm_research(topic) tool (Context7 + web fetch + index)
2. Implement rlm_knowledge_clear() tool
3. Modify orchestrator tech-researcher to use knowledge store
4. Modify interactive-planning to use rlm_search in research phases
5. Add Context7 → knowledge store routing
6. Write integration tests

## Dependencies
- **Needs from doc-fetcher:** rlm_fetch and rlm_load_dir tools
- **Needs from search-engine:** rlm_search tool and indexing API
- **Provides to:** end user (research workflow that doesn't eat context)

## Open Questions
- Should the orchestrator still create .claude/docs/ cheat sheets as a fallback? (probably yes, for offline use)
- How to handle Context7 rate limits when fetching multiple libs?
- Should rlm_research accept a list of topics? (e.g., rlm_research(["fastapi", "dill", "docker-py"]))
