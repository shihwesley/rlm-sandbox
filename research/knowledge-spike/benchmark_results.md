# Search Engine Benchmark: memvid-sdk vs FAISS+ONNX

## Test Setup
- Corpus: 15 markdown files (~52KB total) from project docs and cached cheat sheets
- Chunks: 137 (FAISS, ~500 char with overlap) / whole-file (memvid)
- Queries: 5 natural language questions about project components
- Platform: macOS ARM64, Python 3.14

## Head-to-Head Comparison

| Metric | memvid-sdk | FAISS+fastembed |
|--------|-----------|-----------------|
| Install size | 64.2 MB wheel | ~21 MB (faiss 3.5 + onnxruntime 17 + fastembed 0.1) |
| Index build time | 4.1s | 2.69s (embed) + <0.01s (index) |
| Avg query latency | 0.2ms | 2.4ms |
| Peak RAM | 94 MB | 1.1 GB |
| NL query recall | 0/5 (0%) | 5/5 (100%) |
| Result relevance | N/A | 3/5 rank-1 perfect, 2/5 in top-3 |
| Python 3.14 | Installs, but vec broken | Works cleanly |
| Semantic search | Not available (macOS ARM64) | Full ONNX BGE-small, 384d |
| Search type | BM25 lexical only | Cosine similarity (semantic) |

## Analysis

memvid-sdk's query latency is lower (0.2ms vs 2.4ms), but it returns zero results for natural language queries. Tantivy's BM25 parser can't handle stop words in conversational questions. The vec feature (HNSW + ONNX embeddings) is compiled out of the macOS ARM64 wheel. Without semantic search, memvid is a lexical-only search over .mv2 files — not what we need.

FAISS+fastembed handles natural language queries correctly because it does semantic similarity rather than keyword matching. The 2.4ms latency is well under the 500ms acceptance criterion. The 1.1GB RAM footprint is the main concern for container deployment.

HNSW vs FlatIP showed no difference at 137 chunks. HNSW's advantage appears at >10K vectors.

## Decision

**FAISS + fastembed (BGE-small-en-v1.5) wins.** memvid-sdk is not viable for this use case.
