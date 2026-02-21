#!/usr/bin/env python3
"""Ingest Apple docs into domain-grouped .mv2 knowledge stores.

Each domain gets its own store (apple-<domain>.mv2) to stay under the
50MB memvid capacity limit. Stores are created fresh — delete existing
ones before running.

Usage:
    python3 scripts/apple_domain_ingest.py [--domains spatial-computing,swiftui]
    python3 scripts/apple_domain_ingest.py --list
    python3 scripts/apple_domain_ingest.py --all
"""

import argparse
import os
import sys
import time
from pathlib import Path

DOCS_DIR = Path("/Users/quartershots/Source/DocSetQuery/docs/apple")
STORE_DIR = os.path.expanduser("~/.neo-research/knowledge")

# Domain groupings — each should produce < 2,500 chunks
DOMAINS = {
    "spatial-computing": [
        "realitykit", "arkit", "compositorservices", "shadergraph",
        "realitycomposerpro", "visionos", "phase", "roomplan", "modelio", "usd",
    ],
    "swiftui": [
        "swiftui", "observation", "widgetkit", "activitykit", "tipskit",
        "appintents", "sirikit",
    ],
    "uikit-appkit": [
        "uikit", "appkit", "watchkit", "tvuikit", "tvmlkit", "carplay",
    ],
    "foundation-core": [
        "foundation", "swift", "combine", "os", "dispatch",
        "uniformtypeidentifiers",
    ],
    "foundation-c": [
        "corefoundation",  # 1,306 chunks alone — needs its own store
    ],
    "media-audio": [
        "avfoundation", "avkit", "audiotoolbox", "audiounit", "avfaudio",
        "mediaplayer", "mediatoolbox", "mediaextension", "mediaaccessibility",
        "speech", "soundanalysis", "shazamkit", "replaykit", "cinematic",
        "screencapturekit", "photos", "photokit",
    ],
    "graphics": [
        "coreimage", "coregraphics", "imageio", "colorimetry",
        "spritekit", "quicklook", "quicklookthumbnailing",
    ],
    "metal": [
        "metal", "metalperformanceshaders", "metalperformanceshadersgraph",
    ],
    "ml-ai": [
        "coreml", "createml", "createmlcomponents", "vision",
        "naturallanguage", "foundationmodels", "sensitivecontentanalysis",
        "translation",
    ],
    "location-maps-weather": [
        "corelocation", "corelocationui", "mapkit", "weatherkit",
        "nearbyinteraction",
    ],
    "networking": [
        "network", "cloudkit", "multipeerconnectivity", "backgroundtasks",
        "linkpresentation",
    ],
    "security-auth": [
        "security", "authenticationservices", "cryptokit", "devicecheck",
        "identitylookup", "passkeys", "localauthentication",
    ],
    "hardware-sensors": [
        "coremotion", "corehaptics", "gamecontroller", "corebluetooth",
        "corenfc", "iobluetooth", "dockkit", "sensorkit", "pencilkit",
        "applepencil", "accessories",
    ],
    "health-home-data": [
        "healthkit", "homekit", "eventkit", "contacts", "addressbook",
    ],
    "system-misc": [
        "matter", "xcode", "accessibility", "accelerate",
        "usernotifications", "storekit",
    ],
}


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


def ingest_domain(domain: str, framework_names: list[str]) -> dict:
    """Ingest a single domain into its own .mv2 store."""
    from memvid_sdk import create

    store_path = os.path.join(STORE_DIR, f"apple-{domain}.mv2")

    # Skip if store already exists
    if os.path.exists(store_path):
        size_mb = os.path.getsize(store_path) / 1024 / 1024
        print(f"  SKIP {domain}: store exists ({size_mb:.1f} MB)")
        return {"domain": domain, "status": "skipped", "size_mb": size_mb}

    # Collect all chunks for this domain
    all_chunks = []
    file_count = 0
    total_bytes = 0
    missing = []

    for name in framework_names:
        f = DOCS_DIR / f"{name}.md"
        if not f.exists():
            missing.append(name)
            continue
        try:
            text = f.read_text(encoding="utf-8")
            chunks = chunk_markdown(text, name)
            all_chunks.extend(chunks)
            total_bytes += len(text)
            file_count += 1
        except Exception as exc:
            print(f"    WARN: {name}: {exc}")

    if not all_chunks:
        print(f"  SKIP {domain}: no chunks")
        return {"domain": domain, "status": "empty"}

    # Single put_many + seal (no batching within a domain)
    t0 = time.time()
    mem = create(store_path, enable_vec=False, enable_lex=True)
    ids = mem.put_many(all_chunks)
    mem.seal()
    mem.close()
    elapsed = time.time() - t0

    size_mb = os.path.getsize(store_path) / 1024 / 1024
    print(f"  OK {domain}: {len(ids)} chunks from {file_count} files "
          f"| {size_mb:.1f} MB | {elapsed:.0f}s"
          f"{f' (missing: {missing})' if missing else ''}")

    return {
        "domain": domain,
        "status": "ok",
        "chunks": len(ids),
        "files": file_count,
        "size_mb": size_mb,
        "seconds": elapsed,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--domains", help="Comma-separated domain names")
    parser.add_argument("--all", action="store_true", help="Ingest all domains")
    parser.add_argument("--list", action="store_true", help="List domains and exit")
    args = parser.parse_args()

    if args.list:
        for domain, names in DOMAINS.items():
            existing = [n for n in names if (DOCS_DIR / f"{n}.md").exists()]
            print(f"  {domain:25s} {len(existing):3d} files")
        return

    if args.domains:
        selected = [d.strip() for d in args.domains.split(",")]
        for d in selected:
            if d not in DOMAINS:
                print(f"ERROR: unknown domain '{d}'")
                print(f"Available: {', '.join(DOMAINS.keys())}")
                sys.exit(1)
    elif args.all:
        selected = list(DOMAINS.keys())
    else:
        print("Specify --domains or --all")
        sys.exit(1)

    os.makedirs(STORE_DIR, exist_ok=True)

    print(f"Ingesting {len(selected)} domains...")
    t0 = time.time()
    results = []

    for domain in selected:
        results.append(ingest_domain(domain, DOMAINS[domain]))

    elapsed = time.time() - t0
    ok = [r for r in results if r.get("status") == "ok"]
    total_chunks = sum(r.get("chunks", 0) for r in ok)
    total_mb = sum(r.get("size_mb", 0) for r in ok)
    print(f"\nDone in {elapsed:.0f}s")
    print(f"  Domains: {len(ok)}/{len(selected)}")
    print(f"  Chunks: {total_chunks:,}")
    print(f"  Storage: {total_mb:.1f} MB across {len(ok)} stores")


if __name__ == "__main__":
    main()
