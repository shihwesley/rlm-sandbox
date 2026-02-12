---
name: search-spike
phase: 3
sprint: 1
parent: null
depends_on: []
status: completed
created: 2026-02-12
---

# Search Engine Research Spike

## Overview
Evaluate memvid-sdk vs DIY FAISS+ONNX for semantic search over documentation. Prototype both approaches, benchmark them, and decide whether the search engine runs host-side (MCP server process) or inside the Docker container.

## Requirements
- [ ] REQ-1: Prototype memvid-sdk with `vec` feature (BGE-small ONNX embeddings + FAISS)
- [ ] REQ-2: Prototype DIY approach with faiss-cpu + onnxruntime + BGE-small
- [ ] REQ-3: Benchmark both on the same corpus: 10-20 markdown docs (~500KB total)
- [ ] REQ-4: Test both host-side and container-side execution
- [ ] REQ-5: Document the architectural decision with rationale

## Acceptance Criteria
- [ ] AC-1: Both prototypes can index 20 markdown files and return top-5 results for a query in <500ms
- [ ] AC-2: Benchmark table: model download size, peak RAM, index build time, query latency, result quality (manual spot-check)
- [ ] AC-3: Host vs container comparison: startup overhead, memory isolation, API complexity
- [ ] AC-4: Written decision in findings.md with clear "we chose X because Y" rationale

## Technical Approach
Create two small Python scripts in `research/knowledge-spike/`:
1. `memvid_proto.py` — install memvid-sdk, create .mv2 from test docs, run queries
2. `faiss_proto.py` — install faiss-cpu + onnxruntime, embed chunks, build index, query
3. `benchmark.py` — run both, collect metrics, output comparison table

Test corpus: use the existing `.claude/docs/` cached cheat sheets + a few markdown files from the project.

For host vs container: run each prototype both as a standalone script (simulating host) and inside the Docker sandbox via /exec (simulating container).

## Files
| File | Action | Purpose |
|------|--------|---------|
| research/knowledge-spike/memvid_proto.py | create | memvid-sdk prototype |
| research/knowledge-spike/faiss_proto.py | create | FAISS+ONNX prototype |
| research/knowledge-spike/benchmark.py | create | Comparison benchmarks |
| docs/plans/findings.md | modify | Record architectural decision |

## Tasks
1. Set up test corpus from existing cached docs
2. Prototype memvid-sdk approach (install, index, query)
3. Prototype FAISS+ONNX approach (embed, index, query)
4. Benchmark both approaches (metrics table)
5. Test host-side vs container-side execution for each
6. Write decision to findings.md

## Dependencies
- **Needs from:** nothing (standalone research)
- **Provides to search-engine:** architectural decision, chosen library, hosting model

## Open Questions
- Does memvid-sdk work on Python 3.14? (project uses 3.14)
- Is the ONNX BGE-small model quality good enough for doc chunks, or do we need BGE-base?
- Can the embedding model run inside the 2GB memory-limited container?
