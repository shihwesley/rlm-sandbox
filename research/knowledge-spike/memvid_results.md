# memvid-sdk Prototype Results

## Installation
- Package: memvid-sdk 2.0.156
- Python version: 3.14.2
- Install success: yes
- Wheel: cp38-abi3-macosx_11_0_arm64 (stable ABI, works on 3.14)
- Install size: 64.2 MB wheel

## Metrics
| Metric | Value |
|--------|-------|
| create() time | 0.070s |
| enable_vec() | enable_vec() succeeded in 0.000s |
| Local embeddings | NO — fastembed not available on macOS ARM64 |
| Index build time | 4.095s |
| mv2 file size | 785.6 KB |
| Avg query latency | 0.2ms |
| Peak RSS | 94.1 MB |
| Corpus size | 51,981 bytes / 15 files |
| commit() | skipped (broken in 2.0.156, WAL handles persistence) |

## Query Results — Natural Language (as specified)
| Query | Top Doc | Latency | Hits | Relevance (1-5) |
|-------|---------|---------|------|-----------------|
| How does the Docker sandbox execute Python code? | (none) | 0.4ms | 0 | 0 |
| What is DSPy and how does it optimize prompts? | (none) | 0.2ms | 0 | 0 |
| How does session persistence work with dill? | (none) | 0.2ms | 0 | 0 |
| What MCP tools are available for the sandbox? | (none) | 0.2ms | 0 | 0 |
| How to configure FastAPI with lifespan hooks? | (none) | 0.2ms | 0 | 0 |

## Query Results — Keyword-Stripped (stop words removed)
| Query (keywords only) | Top Doc | Latency | Hits | Relevance (1-5) |
|-----------------------|---------|---------|------|-----------------|
| Docker sandbox execute Python code | README.md (page 4/14) | 0.5ms | 1 | 2-3 |
| DSPy optimize prompts | (none) | 0.1ms | 0 | 0 |
| session persistence work dill | session-persistence-spec.md (page 5/5) | 0.6ms | 1 | 4-5 |
| MCP tools available sandbox | (none) | 0.1ms | 0 | 0 |
| configure FastAPI lifespan hooks | (none) | 0.1ms | 0 | 0 |

## Critical Findings

### 1. Natural Language Queries Return Zero Hits
Tantivy's query parser fails on natural language. Stop words ("How", "does", "What", "is")
cause the parser to return zero results. Keyword-stripped queries work — but this means
the caller must pre-process queries, removing the "just works" benefit.

### 2. Local Vector Search Unavailable on macOS ARM64
The `fastembed` feature (ONNX BGE-small, 384d) is **not compiled into the macOS ARM64 wheel**.
Attempting `enable_embedding=True` on `put()` fails with:
> MV015: Embedding failed: local embedding model 'bge-small' requires the 'fastembed' feature
> which is not available on this platform; use OpenAI embeddings instead

Semantic/hybrid search requires OpenAI API keys on this platform.
Only BM25 lexical search (tantivy engine) works without external dependencies.

### 3. API Differs Significantly from Cheat Sheet
The cheat sheet documents `from memvid import Memvid, PutOptions, SearchRequest` but the actual API:
- Module name: `memvid_sdk` (not `memvid`)
- `put()` takes keyword args (`title=`, `text=`, `uri=`), not raw bytes
- `find()` instead of `search()`, with `k=` instead of `top_k=`
- Results are plain dicts, not typed objects
- `commit()` broken in 2.0.156 (AttributeError on `_MemvidCore`)

### 4. Docker Implications
- In our Docker container (Linux x86_64), the `fastembed` feature **may** be available
- Need to verify: does the manylinux wheel include ONNX BGE-small?
- If not, we'd need OpenAI keys in the container (violates no-API-keys-in-container rule)
- Without semantic search, memvid is just a tantivy wrapper with extra overhead

## Notes
- Lexical search works for keyword queries but fails on natural language
- Single .mv2 file packaging is convenient (data + WAL + indexes)
- API is simple once you know the right module/method names
- 64.2 MB wheel is heavy for what amounts to BM25-only on this platform
- 4s index build for 52KB corpus is surprisingly slow (tantivy overhead?)
