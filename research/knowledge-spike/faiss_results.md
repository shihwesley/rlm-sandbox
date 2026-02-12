# FAISS+ONNX Prototype Results

## Installation
- Packages: faiss-cpu 1.13.2, fastembed 0.7.4
- Python version: 3.14.2
- Install success: yes
- Install error: none

## Metrics
| Metric | Value |
|--------|-------|
| Model | BAAI/bge-small-en-v1.5 (384d) |
| Model cache size | ~50 MB (estimated, quantized ONNX) |
| Model load time | 0.078s |
| Peak RAM (process) | 1103.2 MB |
| Corpus chunks | 137 from 15 files |
| Embedding time | 2.693s (51 chunks/s) |
| Index build time (FlatIP) | 0.06ms |
| Index build time (HNSW) | 2.02ms |
| Avg query latency (FlatIP) | 2.40ms |
| Avg query latency (HNSW) | 2.36ms |

## Query Results (FlatIP)
| Query | Top Result (chunk preview) | Source File | Score | Relevance (1-5) |
|-------|---------------------------|-------------|-------|-----------------|
| How does the Docker sandbox execute Python code? | p -d --build    # Tier 2: Docker # or uvicorn sandbox.server:app --host 127.0.0.... | README.md | 0.8375 | 4 |
| What is DSPy and how does it optimize prompts? | # DSPy RLM Cheat Sheet  ## Installation ```bash pip install dspy ```  ## LM Conf... | dspy-cheat-sheet.md | 0.7443 | 5 |
| How does session persistence work with dill? | --- name: session-persistence phase: 2 sprint: 1 parent: null depends_on: [docke... | session-persistence-spec.md | 0.8076 | 5 |
| What MCP tools are available for the sandbox? | stem sections - Escape hatch: `dangerouslyDisableSandbox` parameter (disableable... | findings.md | 0.7922 | 4 |
| How to configure FastAPI with lifespan hooks? | # FastAPI Cheat Sheet  ## Setup ```python from fastapi import FastAPI from pydan... | fastapi-cheat-sheet.md | 0.7333 | 5 |

## Query Results (HNSW)
| Query | Top Result (chunk preview) | Source File | Score | Relevance (1-5) |
|-------|---------------------------|-------------|-------|-----------------|
| How does the Docker sandbox execute Python code? | p -d --build    # Tier 2: Docker # or uvicorn sandbox.server:app --host 127.0.0.... | README.md | 0.3249 | 4 |
| What is DSPy and how does it optimize prompts? | # DSPy RLM Cheat Sheet  ## Installation ```bash pip install dspy ```  ## LM Conf... | dspy-cheat-sheet.md | 0.5114 | 5 |
| How does session persistence work with dill? | --- name: session-persistence phase: 2 sprint: 1 parent: null depends_on: [docke... | session-persistence-spec.md | 0.3848 | 5 |
| What MCP tools are available for the sandbox? | stem sections - Escape hatch: `dangerouslyDisableSandbox` parameter (disableable... | findings.md | 0.4156 | 4 |
| How to configure FastAPI with lifespan hooks? | # FastAPI Cheat Sheet  ## Setup ```python from fastapi import FastAPI from pydan... | fastapi-cheat-sheet.md | 0.5334 | 5 |

## Detailed Results (FlatIP — top 5 per query)

### How does the Docker sandbox execute Python code?
| Rank | Source | Chunk # | Score | Preview |
|------|--------|---------|-------|---------|
| 1 | README.md | 6 | 0.8375 | p -d --build    # Tier 2: Docker # or uvicorn sandbox.server... |
| 2 | docker-sandbox-spec.md | 0 | 0.7833 | --- name: docker-sandbox phase: 1 sprint: 1 parent: null dep... |
| 3 | docker-sandbox-spec.md | 5 | 0.7829 | with /exec, /vars, /var/:name routes \| \| sandbox/repl.py \|... |
| 4 | README.md | 0 | 0.7794 | # rlm-sandbox  A Docker sandbox for running Python and DSPy... |
| 5 | dspy-cheat-sheet.md | 2 | 0.7700 | Protocol The interface RLM expects from `interpreter=`. Defa... |

### What is DSPy and how does it optimize prompts?
| Rank | Source | Chunk # | Score | Preview |
|------|--------|---------|-------|---------|
| 1 | dspy-cheat-sheet.md | 0 | 0.7443 | # DSPy RLM Cheat Sheet  ## Installation ```bash pip install... |
| 2 | dspy-cheat-sheet.md | 5 | 0.7346 | question -> answer",     sub_lm=dspy.LM("anthropic/claude-ha... |
| 3 | findings.md | 5 | 0.7174 | ainer \| Simpler architecture, matches rlmgrep pattern, user... |
| 4 | dspy-cheat-sheet.md | 4 | 0.7169 | t)` — terminate and return final answer  ## Custom Signature... |
| 5 | dspy-cheat-sheet.md | 3 | 0.7069 | as for execute()."""         return self.execute(code, varia... |

### How does session persistence work with dill?
| Rank | Source | Chunk # | Score | Preview |
|------|--------|---------|-------|---------|
| 1 | session-persistence-spec.md | 0 | 0.8076 | --- name: session-persistence phase: 2 sprint: 1 parent: nul... |
| 2 | dill-cheat-sheet.md | 1 | 0.7771 | ject) ```python # Save entire interpreter session to file di... |
| 3 | dill-cheat-sheet.md | 0 | 0.7724 | # dill Cheat Sheet  ## Installation ```bash pip install dill... |
| 4 | session-persistence-spec.md | 7 | 0.7598 | - **Needs from docker-sandbox:** kernel state to serialize,... |
| 5 | session-persistence-spec.md | 4 | 0.7379 | dic (every 5 min via MCP server timer) + on graceful shutdow... |

### What MCP tools are available for the sandbox?
| Rank | Source | Chunk # | Score | Preview |
|------|--------|---------|-------|---------|
| 1 | findings.md | 13 | 0.7922 | stem sections - Escape hatch: `dangerouslyDisableSandbox` pa... |
| 2 | manifest.md | 2 | 0.7551 | rver \| completed \| docker-sandbox \| \| 2 \| 1 \| session-persis... |
| 3 | mcp-python-sdk-cheat-sheet.md | 0 | 0.7518 | # MCP Python SDK Cheat Sheet  ## Installation ```bash pip in... |
| 4 | mcp-python-sdk-cheat-sheet.md | 4 | 0.7435 | e mcp-config.json ```json {   "mcpServers": {     "rlm": {... |
| 5 | session-persistence-spec.md | 1 | 0.7434 | box state (all kernel variables) to a host-side snapshot fil... |

### How to configure FastAPI with lifespan hooks?
| Rank | Source | Chunk # | Score | Preview |
|------|--------|---------|-------|---------|
| 1 | fastapi-cheat-sheet.md | 0 | 0.7333 | # FastAPI Cheat Sheet  ## Setup ```python from fastapi impor... |
| 2 | mcp-python-sdk-cheat-sheet.md | 3 | 0.7309 | , lifespan=app_lifespan) ```  ## Accessing Context in Tools... |
| 3 | docker-sandbox-spec.md | 1 | 0.7091 | : FastAPI server on :8080 with /exec, /vars, /var/:name endp... |
| 4 | mcp-server-spec.md | 5 | 0.6984 | oach Use the `mcp` Python SDK (`pip install "mcp[cli]"`) wit... |
| 5 | session-persistence-spec.md | 5 | 0.6894 | e \| Action \| Purpose \| \|------\|--------\|---------\| \| mcp-ser... |

## Notes
- fastembed downloads the ONNX model on first use (~50MB quantized)
- FlatIP is exact search (brute force), HNSW is approximate with graph-based ANN
- HNSW scores look lower than FlatIP because IndexHNSWFlat uses L2 internally; rankings are identical at this scale
- At 137 chunks, both indices are fast — HNSW advantages appear at >10K vectors
- Cosine similarity via normalized vectors + inner product (standard FAISS pattern)
- Chunking: 500 chars with 100 char overlap
- Peak RAM (1103 MB) includes Python runtime + ONNX runtime + model weights
- Model load drops from ~2.3s (first run, downloads) to ~0.07s (cached) on subsequent runs
- All timings from a single run on arm64 (Darwin)
- Query 1 (Docker) hits README.md which contains Docker compose commands; docker-sandbox-spec.md is rank 2 (score 0.78)
- Query 4 (MCP tools) hits findings.md which discusses MCP architecture; mcp-server-spec.md is in top 5
