---
name: search-engine
phase: 4
sprint: 1
parent: null
depends_on: [search-spike]
status: draft
created: 2026-02-12
---

# Semantic Search Engine

## Overview
Embedding-based semantic search over loaded documentation. Chunks documents by markdown sections, builds a vector index, and provides a query API that returns relevant snippets with source attribution. Approach (memvid-sdk vs FAISS+ONNX) and hosting (host vs container) determined by search-spike.

## Requirements
- [ ] REQ-1: Chunk markdown documents by heading sections (## level)
- [ ] REQ-2: Embed chunks using ONNX model (BGE-small or as determined by spike)
- [ ] REQ-3: Build FAISS (or memvid) index over all embedded chunks
- [ ] REQ-4: rlm_search(query, top_k) MCP tool — semantic search, returns ranked chunks
- [ ] REQ-5: Source attribution — each result includes document name, section heading, source URL/path
- [ ] REQ-6: Incremental indexing — adding new docs re-indexes only the new content, not everything
- [ ] REQ-7: Index persistence — index survives across MCP server restarts (not just /clear)

## Acceptance Criteria
- [ ] AC-1: rlm_search("async lifespan pattern") returns relevant FastAPI docs chunks when FastAPI docs are loaded
- [ ] AC-2: Each result includes: chunk text (50-200 lines), source doc name, section heading, relevance score
- [ ] AC-3: Adding a new doc and searching immediately finds content from that doc
- [ ] AC-4: Cold query latency <500ms for 50 indexed documents
- [ ] AC-5: Index persists in ~/.rlm-sandbox/knowledge/ and reloads on server restart

## Technical Approach
**Determined by search-spike.** Two possible paths:

Path A (memvid-sdk):
- Create .mv2 file per project (keyed by project root hash)
- Chunk docs → memvid.add() with metadata tags
- Query via memvid.search() → results with source info
- .mv2 file stored at ~/.rlm-sandbox/knowledge/{project-id}.mv2

Path B (FAISS+ONNX):
- Embed chunks with ONNX BGE-small model
- FAISS IndexFlatIP (inner product) for similarity search
- Metadata sidecar JSON for source attribution
- Persist index + metadata at ~/.rlm-sandbox/knowledge/{project-id}/

Markdown chunking strategy:
- Split on ## headings (keep heading in chunk for context)
- Chunks >500 tokens get further split on paragraph boundaries
- Chunks <50 tokens get merged with the next chunk
- Track: doc_name, section_heading, source_url, char_offset

## Files
| File | Action | Purpose |
|------|--------|---------|
| mcp_server/knowledge.py | create | Chunking, embedding, indexing, search, persistence |
| mcp_server/tools.py | modify | Register rlm_search tool |
| tests/test_knowledge.py | create | Tests for chunking, indexing, search quality, incremental updates |

## Tasks
1. Implement markdown chunker (heading-based, with size limits)
2. Implement embedding + index building (chosen approach from spike)
3. Implement rlm_search with source attribution in results
4. Add incremental indexing (diff new docs against existing index)
5. Add index persistence (save/load from ~/.rlm-sandbox/knowledge/)
6. Register rlm_search as MCP tool
7. Write tests for chunking, search quality, incremental updates, persistence

## Dependencies
- **Needs from search-spike:** chosen approach (memvid-sdk or FAISS+ONNX), hosting model
- **Needs from doc-fetcher:** raw document content with metadata to index
- **Provides to orchestrator-integration:** rlm_search tool for research queries

## Open Questions
- Optimal chunk size for doc search? (500 tokens seems right, spike should validate)
- Should search results include surrounding context (1-2 paragraphs around the match)?
- How to handle code blocks in chunks? (keep intact, don't split mid-block)
