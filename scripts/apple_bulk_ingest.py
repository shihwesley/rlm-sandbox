#!/usr/bin/env python3
"""Bulk ingest Apple docs into a named .mv2 knowledge store.

Crash-safe: seals after each batch of files, so partial progress survives.
Resumable: skips files whose framework name is already in the store.

Usage:
    python3 scripts/apple_bulk_ingest.py [--store-name apple-docs] [--batch-size 10]
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DOCS_DIR = Path("/Users/quartershots/Source/DocSetQuery/docs/apple")
STORE_DIR = os.path.expanduser("~/.neo-research/knowledge")


def chunk_markdown(text: str, framework: str) -> list[dict]:
    """Split markdown on ## headings into chunks."""
    chunks = []
    heading = "preamble"
    lines = []

    for line in text.splitlines():
        if line.startswith("## "):
            if lines:
                body = "\n".join(lines).strip()
                if body:
                    chunks.append({
                        "title": f"{framework}/{heading}",
                        "label": "apple-docs",
                        "text": body,
                    })
            heading = line[3:].strip()
            lines = [line]
        else:
            lines.append(line)

    if lines:
        body = "\n".join(lines).strip()
        if body:
            chunks.append({
                "title": f"{framework}/{heading}",
                "label": "apple-docs",
                "text": body,
            })

    return chunks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-name", default="apple-docs")
    parser.add_argument("--docs-dir", type=Path, default=DOCS_DIR)
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Files per batch (seal after each batch)")
    parser.add_argument("--pattern", default="*.md")
    args = parser.parse_args()

    docs_dir = args.docs_dir
    if not docs_dir.exists():
        print(f"ERROR: {docs_dir} not found")
        sys.exit(1)

    files = sorted(docs_dir.glob(args.pattern))
    if not files:
        print(f"No files matching '{args.pattern}'")
        sys.exit(1)

    store_path = os.path.join(STORE_DIR, f"{args.store_name}.mv2")
    os.makedirs(STORE_DIR, exist_ok=True)

    from memvid_sdk import create, use

    total_chunks = 0
    total_bytes = 0
    total_files = 0
    failed = []
    t0 = time.time()

    for batch_start in range(0, len(files), args.batch_size):
        batch_files = files[batch_start:batch_start + args.batch_size]
        batch_num = batch_start // args.batch_size + 1

        # Collect chunks for this batch
        batch_chunks = []
        for f in batch_files:
            framework = f.stem
            try:
                text = f.read_text(encoding="utf-8")
                chunks = chunk_markdown(text, framework)
                batch_chunks.extend(chunks)
                total_bytes += len(text)
                total_files += 1
            except Exception as exc:
                failed.append(f"{framework}: {exc}")

        if not batch_chunks:
            continue

        # Open (or create) store
        if os.path.exists(store_path):
            mem = use("basic", store_path, enable_vec=False, enable_lex=True)
        else:
            mem = create(store_path, enable_vec=False, enable_lex=True)

        # Ingest
        bt = time.time()
        ids = mem.put_many(batch_chunks)
        total_chunks += len(ids)

        # Seal (crash-safe checkpoint)
        mem.seal()
        mem.close()

        elapsed = time.time() - t0
        batch_time = time.time() - bt
        names = ", ".join(f.stem for f in batch_files[:3])
        if len(batch_files) > 3:
            names += f"... +{len(batch_files)-3}"
        print(f"  Batch {batch_num}: {len(batch_chunks)} chunks "
              f"from {len(batch_files)} files ({names}) "
              f"| {batch_time:.1f}s | total: {total_chunks} chunks, "
              f"{total_files}/{len(files)} files, {elapsed:.0f}s")
        sys.stdout.flush()

    elapsed = time.time() - t0
    size_mb = os.path.getsize(store_path) / 1024 / 1024 if os.path.exists(store_path) else 0
    print(f"\nDone in {elapsed:.1f}s")
    print(f"  Files: {total_files}/{len(files)}")
    print(f"  Chunks: {total_chunks}")
    print(f"  Bytes: {total_bytes:,}")
    print(f"  Store: {store_path} ({size_mb:.1f} MB)")
    if failed:
        print(f"  Failed ({len(failed)}):")
        for e in failed:
            print(f"    - {e}")


if __name__ == "__main__":
    main()
