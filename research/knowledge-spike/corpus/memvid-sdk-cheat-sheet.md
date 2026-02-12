# memvid-sdk Cheat Sheet

## Installation
```bash
pip install memvid-sdk
```

## Core Concepts
- Single `.mv2` file = data + WAL + indexes (no external DB)
- `vec` feature: HNSW index with BGE-small ONNX embeddings (384d, cosine similarity)
- HNSW params: M=16, ef_construction=200
- Hybrid search: BM25 lexical + semantic vector
- Rust core with Python/Node/Rust bindings

## Python API (mirrors Rust core)
```python
from memvid import Memvid, PutOptions, SearchRequest

# Create memory
mem = Memvid.create("knowledge.mv2")

# Enable vector search (ONNX BGE-small embeddings)
mem.enable_vec()

# Add documents
mem.put(b"some text content")

# Add with metadata
opts = PutOptions.builder() \
    .title("Meeting Notes") \
    .uri("mv2://meetings/2024-01-15") \
    .tag("project", "alpha") \
    .build()
mem.put_with_options(b"Q4 planning discussion...", opts)

# Add with explicit embedding
embedding = [0.1, 0.2, ...]  # 384-dim float list
mem.put_with_embedding(b"Neural networks for NLP", embedding)

# Commit (persist to file)
mem.commit()

# Search (lexical)
response = mem.search(SearchRequest(query="planning", top_k=10, snippet_chars=200))
for hit in response.hits:
    print(hit.text)

# Vector similarity search
hits = mem.search_vec(query_embedding, top_k=5)
for hit in hits:
    print(f"Frame: {hit.frame_id}, Distance: {hit.distance}")
```

## CLI (Docker)
```bash
docker run --rm -v $(pwd):/data memvid/cli create my-memory.mv2
docker run --rm -v $(pwd):/data memvid/cli put my-memory.mv2 --input doc.pdf
docker run --rm -v $(pwd):/data memvid/cli find my-memory.mv2 --query "search"
docker run --rm -v $(pwd):/data memvid/cli stats my-memory.mv2
```

## Vec Model Selection
```python
mem.set_vec_model("bge-small-en-v1.5")  # default, 384d
mem.set_vec_model("bge-base-en-v1.5")   # 768d, higher quality
```

## Pitfalls
- Must call `mem.commit()` to persist changes
- `vec` feature downloads ONNX model on first use (~130MB for BGE-small)
- Python 3.14 compatibility: UNKNOWN (open question for spike)
- Memory footprint with HNSW index grows with document count

## Sources
- https://github.com/memvid/memvid
- https://docs.memvid.com
- MV2_SPEC.md (HNSW params, file format)
