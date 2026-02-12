# faiss-cpu + onnxruntime Cheat Sheet

## Installation
```bash
pip install faiss-cpu onnxruntime
# For BGE-small embeddings via ONNX:
pip install fastembed  # wraps onnxruntime with model management
# Or manual:
pip install onnxruntime numpy
```

## FAISS Basics
```python
import numpy as np
import faiss

d = 384  # BGE-small dimension
index = faiss.IndexFlatL2(d)  # brute-force L2 (exact)
# or: index = faiss.IndexFlatIP(d)  # inner product (for cosine after L2-norm)

# Add vectors (numpy float32, shape [n, d])
vectors = np.random.random((1000, d)).astype('float32')
index.add(vectors)
print(index.ntotal)  # 1000

# Search k nearest neighbors
query = np.random.random((1, d)).astype('float32')
k = 5
D, I = index.search(query, k)
# D = distances, shape [nq, k]
# I = indices, shape [nq, k]
```

## Index Types (by dataset size)
| Index | Use Case | Training? |
|-------|----------|-----------|
| IndexFlatL2 | <100K vectors, exact | No |
| IndexIVFFlat | 100K-1M, approximate | Yes |
| IndexHNSWFlat | Any size, fast recall | No |

```python
# HNSW (comparable to memvid's approach)
index = faiss.IndexHNSWFlat(d, 16)  # 16 = M parameter
index.hnsw.efConstruction = 200
index.hnsw.efSearch = 64
index.add(vectors)
```

## BGE-small Embeddings (via fastembed)
```python
from fastembed import TextEmbedding

model = TextEmbedding("BAAI/bge-small-en-v1.5")  # 384d, ~50MB quantized
texts = ["Hello world", "Semantic search example"]
embeddings = list(model.embed(texts))
# Each embedding is numpy array of shape (384,)
```

## BGE-small Embeddings (manual ONNX)
```python
import onnxruntime as ort
from transformers import AutoTokenizer
import numpy as np

tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
session = ort.InferenceSession("model.onnx")

inputs = tokenizer(["Hello world"], padding=True, truncation=True, return_tensors="np")
outputs = session.run(None, dict(inputs))
embedding = outputs[0][0]  # shape (384,)
```

## Complete Pipeline
```python
import faiss
import numpy as np
from fastembed import TextEmbedding

# 1. Embed documents
model = TextEmbedding("BAAI/bge-small-en-v1.5")
docs = ["doc1 text...", "doc2 text...", ...]
doc_embeddings = np.array(list(model.embed(docs))).astype('float32')

# 2. Build index
d = 384
index = faiss.IndexFlatIP(d)  # inner product for cosine sim
faiss.normalize_L2(doc_embeddings)  # normalize for cosine
index.add(doc_embeddings)

# 3. Search
query_emb = np.array(list(model.embed(["search query"]))).astype('float32')
faiss.normalize_L2(query_emb)
D, I = index.search(query_emb, k=5)
```

## Pitfalls
- Vectors MUST be float32 numpy arrays (not float64)
- For cosine similarity: normalize vectors + use IndexFlatIP
- fastembed downloads model on first use (~50MB quantized, ~130MB full)
- faiss-cpu has no GPU support; faiss-gpu needs CUDA
- HNSW index is not serializable with `faiss.write_index` in older versions

## Sources
- https://github.com/facebookresearch/faiss/wiki/Getting-started
- https://qdrant.tech/articles/fastembed/
- https://bge-model.com/tutorial/3_Indexing/3.1.1.html
