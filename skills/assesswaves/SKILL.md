---
name: assesswaves
description: Quick assessment of whether a piece of work is suitable for wave-pattern parallel execution. Lighter than /prepwaves — helps decide decomposition before (or after) issues are created.
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/skill-intro-assesswaves does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/skill-intro-assesswaves
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# AssessWaves: Is This Work Wave-Patternable?

Quickly assess whether a set of work items can benefit from parallel agent execution via the wave pattern. This is a **decision tool**, not a planning tool — it recommends a decomposition and verdict, but does not create issues, flight plans, or execute anything.

Use this **before** `/prepwaves` to decide whether wave-pattern execution is worth it.

## Platform Detection

Before starting, detect the platform from the git remote:
- **GitHub** (`github.com` in remote URL) — use `gh` CLI for issue operations
- **GitLab** (`gitlab` in remote URL) — use `glab` CLI for issue operations

Use the correct CLI throughout.

## Input Modes

Detect the input mode from arguments:

- **Issue numbers** (`/assesswaves #50 #51 #52` or `/assesswaves 50 51 52`) — read the issues and analyze them
- **No arguments** (`/assesswaves`) — ask the user to describe the work items, or derive them from current conversation context

## Step 1: Gather Work Items

**If issue numbers were provided:**
- Read each issue via the platform CLI (`gh issue view` / `glab issue view`)
- Extract: title, description, and acceptance criteria

**If no issue numbers:**
- Ask the user to list the discrete pieces of work, or identify them from the conversation
- Each item needs at least a one-line description of what it changes

Produce a numbered list of work items before proceeding.

## Step 2: File Impact Analysis

**Use sub-agents for this step.** Launch one Explore agent per work item to keep the main context clean and to run the analysis in parallel. Each agent should:

1. Take the work item's description/acceptance criteria as input
2. Search the codebase (grep, glob, read) to identify which files and directories the item would likely touch
3. Return a concise list: files to create, files to modify, directories affected

Collect the results from all agents before proceeding.

## Step 3: Conflict Matrix

Compare the file impact lists across all work items:

| | Item 1 | Item 2 | Item 3 |
|---|--------|--------|--------|
| **Item 1** | — | overlap? | overlap? |
| **Item 2** | | — | overlap? |
| **Item 3** | | | — |

For each pair, note:
- **File overlap** — do they modify the same files? Which ones?
- **Logical dependency** — does one item need another's output? Does ordering matter?
- **Shared state** — do they write to the same config, schema, or data store?

## Step 4: Verdict Card

Present the assessment in this format:

```
### Wave Assessment

| Field | Value |
|-------|-------|
| **Work items** | N items assessed |
| **Wave-able** | yes / no / maybe |
| **Suggested waves** | N waves (rough sketch) |
| **Risk level** | low / medium / high |

### Items

1. **<item summary>** — touches: `file1.py`, `file2.py`, `dir/`
2. **<item summary>** — touches: `file3.py`, `dir/`
3. ...

### Conflict Matrix

(the matrix from Step 3)

### Wave Sketch

- **Wave 1** (parallel): Items 1, 3 — no file overlap, independent
- **Wave 2** (sequential after wave 1): Item 2 — depends on Item 1's output

### Risk Flags

- (any tight coupling, shared schema changes, ordering constraints, etc.)
- (if none: "No significant risks identified.")

### Recommendation

(one of:)
- "Wave-able. Create issues for each item and run `/prepwaves` for full planning."
- "Wave-able. Issues already exist — ready for `/prepwaves`."
- "Not wave-able. These items have too much file overlap / are logically sequential. Execute them in series."
- "Maybe wave-able with restructuring. Consider splitting <item> into <X> and <Y> to reduce overlap."
```

## What This Skill Does NOT Do

- Create issues (recommend them, let the user decide)
- Produce flight plans (that's `/prepwaves`)
- Execute waves (that's `/nextwave`)
- Deep target-file mapping with line-level analysis (that's `/prepwaves` territory)
