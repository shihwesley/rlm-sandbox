---
name: research
description: "Research any topic — builds question tree, discovers sources, fetches to disk (zero context cost), indexes into .mv2, distills into expertise artifact. Agent becomes domain expert. Use when you need to learn about a technology, protocol, framework, or domain before working with it."
---

# Research: $ARGUMENTS

Turn "$ARGUMENTS" into genuine expertise using the unified research pipeline.

## What This Does

1. Parses your input (topic, paragraph, URLs, or any mix)
2. Builds a structured question tree (research methodology before searching)
3. Discovers and fetches sources (content never enters context — goes to disk → .mv2)
4. Distills indexed knowledge into a compact expertise artifact via systematic querying
5. Loads the expertise into your context — you now know the topic

Output lives at `~/.claude/research/<topic-slug>/`.

## When This Skill Triggers

- "research X", "learn about X", "look up X before we start"
- "I need to understand X" (with or without URLs/context)
- Pasting a paragraph of context about something to learn
- "/research <topic>" explicitly

## Step 1: Check for Existing Research

```bash
HOME_DIR=$(echo ~)
ls "$HOME_DIR/.claude/research/" 2>/dev/null
```

If the topic (or something close) already has a directory with `expertise.md`:
- Read and present the existing expertise doc
- Ask: "I have existing research on this. Load it, or re-research with fresh sources?"
- If load → read expertise.md, done
- If re-research → continue to Step 2

## Step 2: Spawn the Research Agent

The research agent handles the full pipeline. Spawn it with the user's input:

```python
Task(
  subagent_type="general-purpose",
  name="researcher",
  description="Research pipeline for topic",
  model="sonnet",
  prompt="""
You are the research-agent. Follow the pipeline in agents/research-agent.md exactly.

## Input
$ARGUMENTS

## Instructions
Run all 5 phases:
1. Parse input → build question tree
2. Discover sources (WebSearch per branch)
3. Fetch → disk → index into .mv2 (zero context cost)
4. Distill: query .mv2 systematically → write expertise.md
5. Report results

Write all artifacts to ~/.claude/research/<slug>/.
Return the expertise.md content and a summary report when done.

## MCP Tools Available
Use ToolSearch to load: rlm_search, rlm_ask, rlm_ingest, rlm_exec, rlm_knowledge_status

## Rules
- Never read fetched content. Files go disk → knowledge store.
- Never use WebFetch. Use curl via Bash for fetching, WebSearch for discovery.
- Question tree before searching. Structure first.
- Be honest about gaps.
"""
)
```

## Step 3: Load Expertise

When the agent returns:

1. Read `~/.claude/research/<slug>/expertise.md`
2. Present it to the user
3. The agent (you) now has the expertise loaded in context

## Step 4: Report

```
Research complete: <topic>
- Expertise: ~/.claude/research/<slug>/expertise.md
- Knowledge store: ~/.claude/research/<slug>/knowledge.mv2
- Deep-dive: rlm_search(query="...", project="<slug>")
- Reload later: /research load <topic>
```

After the agent returns, check `sources.json` for a coupling assessment. If `coupling.recommendation == "skill-graph"`, append to your report:

```
Domain coupling: high (score N/5)
→ Create navigable skill graph: /create-skill-graph <slug>
```

## Loading Existing Research

If the user says `/research load <topic>`:

1. Find the matching directory in `~/.claude/research/`
2. Read `expertise.md`
3. Present it — agent now has the expertise

No need to re-fetch or re-index. The knowledge store is also available for `rlm_search` queries.

## Listing Available Research

If the user says `/research` with no arguments or `/research list`:

```bash
HOME_DIR=$(echo ~)
ls -1 "$HOME_DIR/.claude/research/" 2>/dev/null
```

List what topics have been researched with their dates and sizes.

## Rules

- **One fetch attempt per URL.** Fail → skip → move on.
- **Don't paste full doc content.** The expertise doc is the output, not raw pages.
- **Check before re-fetching.** Existing research is reusable.
- **Stay on topic.** Research what was asked. Don't branch into related topics uninvited.
- **Quality over quantity.** 10 good sources beat 50 mediocre ones.
