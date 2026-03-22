---
name: cryo
description: Cryogenically preserve session state before context compaction — curate plan file and task list
---

# Cryo: Pre-Compaction State Preservation

Compaction is coming. Freeze everything that matters into durable storage so `/engage` can thaw it later.

## What Gets Preserved

1. **Plan file** — The plan file from plan mode context (path shown in system messages)
2. **Task list** — The TaskCreate/TaskUpdate task list

If no plan file path exists in the system context, warn the user — there's nowhere to write state.

## Step 1: Audit Current State

Before writing anything, gather:

- `git branch --show-current` and `git log --oneline -5` for each working directory with changes
- `git status` for uncommitted work
- Read the existing plan file (if any) to understand its current structure
- Check TaskList for any active tasks

## Step 2: Curate the Plan File

Rewrite the plan file as a **session state document** — not a plan for future work, but a snapshot of where things stand RIGHT NOW. The audience is a future version of yourself with zero context.

Structure it as:

```markdown
# Session State — [project/feature name]

## Working Directory
[path]

## Current Branch
[branch name and repo]

## Git Config
[any repo-local config that matters — user.name, user.email]

## Commits (pushed)
[numbered list of commits on this branch, with SHAs and messages]

## MR / PR
[URL, source→target, pipeline status]

## What Was Built
[Organized by component — what exists in the codebase NOW, not what's planned]

## Key Design Decisions
[Numbered list of non-obvious choices and WHY they were made]

## Validation Results
[What passed, what failed, what was verified]

## PENDING
[What still needs to happen — be specific]

## Related Projects
[Paths, branches, cross-references]

## Lessons Learned
[Anything that caused pain — CI quirks, API gotchas, workarounds]
```

### Writing Rules

- **Be factual, not aspirational** — Document what IS, not what SHOULD BE
- **Include paths** — Future-you needs to find files without searching
- **Include SHAs** — Commits are the ground truth
- **Include URLs** — MRs, pipelines, issues
- **Include error context** — If something failed and was fixed, say what the error was and what fixed it
- **Prune stale content** — Remove sections about completed work that's already merged and irrelevant
- **Keep active context** — Anything the next session needs to pick up where you left off

## Step 3: Curate the Task List

- **Delete completed tasks** — They're done, they don't need to survive compaction
- **Delete stale/irrelevant tasks** — If the work shifted, clean up
- **Keep pending and in-progress tasks** — These are the "what's next"
- **Update descriptions** — Make sure each surviving task has enough context to be actionable without the full conversation history

## Step 4: Confirm

Tell the user:
- What was written to the plan file (brief summary)
- How many tasks survived vs. were pruned
- "Cryo complete. Ready for compaction."

## Important

- This is a WRITE operation, not a read. You are actively curating, not just summarizing.
- Do NOT ask for approval to write the plan file — the user invoked `/cryo`, that IS the approval.
- DO be thorough. The plan file is the ONLY thing that survives compaction intact. Everything else becomes a lossy summary.
- Pair with `/engage` for the thaw cycle: `/cryo` freezes, `/engage` thaws.
