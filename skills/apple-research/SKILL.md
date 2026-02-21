---
name: apple-research
description: "Research Apple frameworks against a spec/plan file using exported Dash docset docs. Produces a per-feature reference artifact with verbatim code examples from official guides and samples."
user-invocable: true
---

# Apple Docs Research Pipeline

Research Apple framework documentation against your app's spec or planning files.
Produces a structured reference artifact with verbatim code from official guides, samples, and API docs.

## When to Use

- Before implementing iOS/visionOS features that need official Apple patterns
- When you have a spec file and want to find relevant guides, samples, and APIs
- When you need code examples that will actually compile (not hallucinated APIs)

## Prerequisites

- Exported Apple docs in `DocSetQuery/docs/apple/*.md` (run batch_export.py)
- neo-research MCP server running
- (Optional) Docs ingested into .mv2 via `rlm_apple_bulk_ingest` for faster search

## Pipeline

### Phase 1: Parse the Spec

Read the user's spec/plan file and extract implementation features:

```
1. Read the spec file (user provides path)
2. Break into discrete features/components
3. For each feature, identify:
   - What Apple frameworks are involved
   - What specific capabilities are needed (gestures, 3D rendering, networking, etc.)
   - What platform constraints exist (visionOS only, iOS 17+, etc.)
```

### Phase 2: Discovery

For each feature, search the Apple docs:

```
# Via MCP tools (if docs are ingested into .mv2):
rlm_apple_lookup(query="<feature need>", framework="<fw>", top_k=5)

# Via extraction tool (for full sections with code):
rlm_apple_extract(query="<feature need>", frameworks="visionos,realitykit", role_filter="Sample Code")

# Via REPL (for deep programmatic search across all frameworks):
rlm_exec("""
from apple_extract import DocReader
reader = DocReader("/Users/quartershots/Source/DocSetQuery/docs/apple")

# Find relevant guides
guides = reader.find_by_role("Article", frameworks=["visionos", "arkit"])

# Find sample code
samples = reader.find_by_role("Sample Code", frameworks=["visionos", "realitykit"])

# Search for specific capability
hits = reader.find("immersive space", frameworks=["visionos", "swiftui"])

# Cross-reference a symbol
xrefs = reader.xref("ImmersiveSpace")
""")
```

### Phase 3: Extraction

For each discovery hit, extract the full section with code blocks preserved:

```
# Via MCP tool:
rlm_apple_extract(query="placing content on detected planes", frameworks="visionos", preserve_code=True)

# Via REPL for surgical extraction:
rlm_exec("""
from apple_extract import DocReader
reader = DocReader("/Users/quartershots/Source/DocSetQuery/docs/apple")

# Get full section text with code
section = reader.read_section("visionos", "Placing content on detected planes", include_children=True)
print(section)

# Or just the code blocks
blocks = reader.code_blocks("visionos", "Placing content on detected planes")
for b in blocks:
    print(f"--- {b['language']} ---")
    print(b['code'])
""")
```

### Phase 4: Write the Reference Artifact

Structure: one file per spec, organized by feature.

**Output path:** `~/.claude/research/apple-<project>/reference.md`

```markdown
# <Project> — Apple Docs Reference

> Generated: <date>
> Spec: <spec file path>
> Sources: <N> sections from <M> frameworks
> Docs root: /Users/quartershots/Source/DocSetQuery/docs/apple/

## Feature: <name from spec>

### Relevant Frameworks
- <framework>: <what it provides for this feature>

### Official Guide: <guide title> (Article)
_Source: docs/apple/<fw>.md, line <N>_

<verbatim extracted text with code blocks>

### Sample Code: <sample title> (Sample Code)
_Source: docs/apple/<fw>.md, line <N>_

<verbatim code blocks, full context>

### Key APIs
- `ClassName` (Class) — <one-line from overview>
  ```swift
  <declaration from doc>
  ```
- `methodName(_:)` (Instance Method) — <one-line>
  ```swift
  <declaration>
  ```

### Implementation Notes
Based on the guides above:
- <specific pattern to follow>
- <gotcha or constraint mentioned in the docs>

---

## Feature: <next feature>
...
```

### Phase 5: Verify

Read the artifact. For each feature, check:
1. Are there verbatim code examples? (not synthesized)
2. Do the APIs exist in the exported docs? (cross-ref with `reader.xref()`)
3. Are platform requirements noted?
4. Are there gaps? (features with no matching guides — flag them)

### Phase 6: Artifact Output

Report what was generated:
```
Apple docs research complete: <project>
- Features researched: N
- Sections extracted: M (from K frameworks)
- Reference: ~/.claude/research/apple-<project>/reference.md
- Code blocks preserved: Y verbatim examples
- Gaps: <list any features with no matching guides>

For coding: read the reference doc before implementing each feature.
For deep-dive: rlm_apple_extract(query="...", frameworks="...")
```

## REPL Helper Reference

The `DocReader` class (in `mcp_server/apple_extract.py`) provides these methods:

| Method | What it does |
|--------|-------------|
| `frameworks()` | List all exported framework files with sizes |
| `toc(fw)` | Table of contents for a framework |
| `find(query, frameworks?, role?)` | Search headings + content across frameworks |
| `find_by_role(role, frameworks?)` | Find all sections of a type (Article, Sample Code, Class, etc.) |
| `read_section(fw, heading_query)` | Full section text with code blocks |
| `code_blocks(fw, heading_query)` | Just the code blocks from a section |
| `xref(symbol)` | Which frameworks mention a symbol |

## Rules

1. **Preserve code verbatim.** Never paraphrase or summarize code blocks. Copy them exactly.
2. **Cite sources.** Every extracted section must have its framework file and line number.
3. **Feature-first organization.** Organize by spec features, not by framework.
4. **Flag gaps honestly.** If a feature has no matching guide or sample, say so.
5. **Prefer Sample Code over Articles.** Sample code has tested, runnable examples. Articles have conceptual explanations. Both are useful, but prioritize samples for implementation reference.
6. **Cross-reference APIs.** If a guide mentions `Entity`, check `realitykit.md` for the full `Entity (Class)` section. Combine guide context with API reference.
