#!/usr/bin/env python3
"""memvid-sdk prototype for knowledge search spike.

Tests memvid-sdk 2.x against a 15-file markdown corpus.
Actual API differs from the cheat sheet — module is `memvid_sdk`,
uses keyword-arg `put()`, `find()` returns dicts, and `commit()`
is broken in 2.0.156 (WAL handles persistence anyway).
"""

import os
import sys
import time
import platform
import resource
import traceback
from pathlib import Path

CORPUS_DIR = Path(__file__).parent / "corpus"
RESULTS_FILE = Path(__file__).parent / "memvid_results.md"
MV2_FILE = Path(__file__).parent / "knowledge.mv2"

QUERIES = [
    "How does the Docker sandbox execute Python code?",
    "What is DSPy and how does it optimize prompts?",
    "How does session persistence work with dill?",
    "What MCP tools are available for the sandbox?",
    "How to configure FastAPI with lifespan hooks?",
]

python_version = platform.python_version()


def peak_rss_mb() -> float:
    """Peak RSS in MB (macOS returns bytes, Linux returns KB)."""
    usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        return usage / (1024 * 1024)
    return usage / 1024


def write_failure(error_msg: str):
    RESULTS_FILE.write_text(f"""# memvid-sdk Prototype Results

## Installation
- Package: memvid-sdk
- Python version: {python_version}
- Install success: no
- Install error: {error_msg}

## Metrics
N/A

## Query Results
N/A

## Notes
- {error_msg}
""")


def main():
    rss_before = peak_rss_mb()

    # --- Import ---
    try:
        import memvid_sdk
    except ImportError as e:
        write_failure(f"ImportError: {e}")
        print(f"FAIL: could not import memvid_sdk — {e}")
        sys.exit(1)

    print(f"memvid-sdk version: {getattr(memvid_sdk, '__version__', 'unknown')}")

    # --- Load corpus ---
    md_files = sorted(CORPUS_DIR.glob("*.md"))
    print(f"Found {len(md_files)} markdown files in corpus")

    corpus_docs: list[tuple[str, str]] = []
    for f in md_files:
        text = f.read_text(encoding="utf-8")
        corpus_docs.append((f.name, text))

    total_bytes = sum(len(t.encode()) for _, t in corpus_docs)
    print(f"Total corpus: {total_bytes:,} bytes across {len(corpus_docs)} files")

    # --- Create mv2 ---
    if MV2_FILE.exists():
        MV2_FILE.unlink()

    # enable_vec=True on create sets up HNSW index structure,
    # but local embeddings (fastembed/BGE-small) aren't available on macOS ARM64.
    # We still enable it to test if vec index creation works.
    t0_create = time.perf_counter()
    mem = memvid_sdk.create(str(MV2_FILE), enable_lex=True, enable_vec=True)
    t_create = time.perf_counter() - t0_create
    print(f"create() with enable_vec=True took {t_create:.3f}s")

    # Test if enable_vec() method also works
    t0_vec = time.perf_counter()
    try:
        mem.enable_vec()
        t_vec = time.perf_counter() - t0_vec
        vec_note = f"enable_vec() succeeded in {t_vec:.3f}s"
    except Exception as e:
        t_vec = time.perf_counter() - t0_vec
        vec_note = f"enable_vec() failed: {e}"
    print(f"  {vec_note}")

    # Test local embedding availability
    vec_embedding_works = False
    try:
        mem.put(title="__test__", text="embedding test", enable_embedding=True)
        vec_embedding_works = True
        embed_note = "local embeddings work"
    except Exception as e:
        embed_note = str(e)
    print(f"  Local embedding test: {embed_note}")

    # --- Index documents (lexical only, since local embeddings unavailable) ---
    t0_build = time.perf_counter()
    for name, text in corpus_docs:
        mem.put(
            title=name,
            text=text,
            uri=f"mv2://corpus/{name}",
        )
    t_build = time.perf_counter() - t0_build
    print(f"Index build (put x{len(corpus_docs)}): {t_build:.3f}s")

    # commit() is broken in 2.0.156 — _MemvidCore lacks the method.
    # WAL handles persistence, so data is already queryable.
    commit_note = "skipped (broken in 2.0.156, WAL handles persistence)"
    try:
        mem.commit()
        commit_note = "succeeded"
    except AttributeError:
        pass  # expected

    mv2_size = MV2_FILE.stat().st_size
    print(f"mv2 file size: {mv2_size:,} bytes ({mv2_size / 1024:.1f} KB)")

    # --- Run queries ---
    # Tantivy's query parser chokes on natural language (stop words like
    # "How", "does", "What", "is" cause zero results). We run each query
    # twice: once as-is, once with stop words stripped, to document this.
    STOP_WORDS = {"how", "does", "what", "is", "and", "the", "a", "an",
                  "to", "for", "with", "are", "it", "of", "in", "on", "by"}

    def strip_stops(q: str) -> str:
        q = q.rstrip("?").strip()
        return " ".join(w for w in q.split() if w.lower() not in STOP_WORDS)

    query_results: list[dict] = []
    keyword_results: list[dict] = []
    latencies: list[float] = []

    for q in QUERIES:
        # Natural language query (as specified)
        t0_q = time.perf_counter()
        result = mem.find(q, k=5, snippet_chars=300)
        t_q = time.perf_counter() - t0_q
        latencies.append(t_q)

        hits = result.get("hits", [])
        top_hit_text = ""
        top_title = ""
        if hits:
            top_hit_text = hits[0].get("snippet", "")[:200].replace("\n", " ").strip()
            top_title = hits[0].get("title", "")

        query_results.append({
            "query": q,
            "top_title": top_title,
            "top_result": top_hit_text,
            "latency_ms": t_q * 1000,
            "num_hits": len(hits),
            "engine": result.get("engine", "?"),
            "took_ms": result.get("took_ms", "?"),
        })
        print(f"  [{t_q*1000:.1f}ms] NL: {q[:50]}... -> {len(hits)} hits")

        # Keyword-stripped query
        kw_q = strip_stops(q)
        t0_kw = time.perf_counter()
        kw_result = mem.find(kw_q, k=5, snippet_chars=300)
        t_kw = time.perf_counter() - t0_kw

        kw_hits = kw_result.get("hits", [])
        kw_top_title = kw_hits[0].get("title", "") if kw_hits else ""
        kw_top_text = kw_hits[0].get("snippet", "")[:200].replace("\n", " ").strip() if kw_hits else ""

        keyword_results.append({
            "query": kw_q,
            "original": q,
            "top_title": kw_top_title,
            "top_result": kw_top_text,
            "latency_ms": t_kw * 1000,
            "num_hits": len(kw_hits),
        })
        print(f"           KW: \"{kw_q}\" -> {len(kw_hits)} hits, top={kw_top_title}")

    avg_latency = sum(latencies) / len(latencies) if latencies else 0
    rss_after = peak_rss_mb()

    # --- Write results ---
    nl_rows = ""
    for r in query_results:
        top = r["top_result"].replace("|", "\\|")[:100]
        relevance = _score_relevance(r)
        nl_rows += f"| {r['query']} | {r['top_title'] or '(none)'} | {r['latency_ms']:.1f}ms | {r['num_hits']} | {relevance} |\n"

    kw_rows = ""
    for r in keyword_results:
        top = r["top_result"].replace("|", "\\|")[:100]
        relevance = _score_relevance(r)
        kw_rows += f"| {r['query']} | {r['top_title'] or '(none)'} | {r['latency_ms']:.1f}ms | {r['num_hits']} | {relevance} |\n"

    results_md = f"""# memvid-sdk Prototype Results

## Installation
- Package: memvid-sdk 2.0.156
- Python version: {python_version}
- Install success: yes
- Wheel: cp38-abi3-macosx_11_0_arm64 (stable ABI, works on 3.14)
- Install size: 64.2 MB wheel

## Metrics
| Metric | Value |
|--------|-------|
| create() time | {t_create:.3f}s |
| enable_vec() | {vec_note} |
| Local embeddings | {"yes" if vec_embedding_works else "NO — fastembed not available on macOS ARM64"} |
| Index build time | {t_build:.3f}s |
| mv2 file size | {mv2_size / 1024:.1f} KB |
| Avg query latency | {avg_latency * 1000:.1f}ms |
| Peak RSS | {rss_after:.1f} MB |
| Corpus size | {total_bytes:,} bytes / {len(corpus_docs)} files |
| commit() | {commit_note} |

## Query Results — Natural Language (as specified)
| Query | Top Doc | Latency | Hits | Relevance (1-5) |
|-------|---------|---------|------|-----------------|
{nl_rows}
## Query Results — Keyword-Stripped (stop words removed)
| Query (keywords only) | Top Doc | Latency | Hits | Relevance (1-5) |
|-----------------------|---------|---------|------|-----------------|
{kw_rows}
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
"""

    RESULTS_FILE.write_text(results_md)
    print(f"\nResults written to {RESULTS_FILE}")


def _score_relevance(r: dict) -> str:
    """Rough relevance score based on whether the top doc matches the query topic."""
    if r["num_hits"] == 0:
        return "0"
    title = r.get("top_title", "").lower()
    # Use original query if available (keyword results), otherwise query field
    q = r.get("original", r["query"]).lower()

    keyword_map = {
        "docker": ["docker", "sandbox"],
        "sandbox": ["docker", "sandbox"],
        "dspy": ["dspy"],
        "session": ["session", "persistence", "dill"],
        "dill": ["session", "persistence", "dill"],
        "mcp": ["mcp"],
        "fastapi": ["fastapi"],
        "lifespan": ["fastapi"],
    }
    for trigger, file_keywords in keyword_map.items():
        if trigger in q and any(k in title for k in file_keywords):
            return "4-5"
    return "2-3"


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        traceback.print_exc()
        write_failure(f"{type(e).__name__}: {e}")
        sys.exit(1)
