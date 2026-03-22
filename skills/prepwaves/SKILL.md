---
name: prepwaves
description: Analyze a master issue, validate sub-issue specs, compute dependency waves, and prepare for parallel agent execution
---

# PrepWaves: Plan Parallel Execution Waves

Analyze a master issue and its sub-issues, validate they are ready for spec-driven parallel agent execution, compute dependency-ordered waves, and prepare everything for `/nextwave` to execute.

## Prerequisites

- A "master issue" must exist — an epic or parent issue that references sub-issues
- The user must provide the master issue number (or it must be identifiable from context)

## Platform Detection

Before starting, detect the platform from the git remote:
- **GitHub** (`github.com` in remote URL) — use `gh` CLI for issue/PR operations
- **GitLab** (`gitlab` in remote URL) — use `glab` CLI for issue/MR operations

Use the correct CLI throughout. All steps below use generic terms ("issue", "merge request/PR") — substitute the platform-specific command.

## Step 1: Validate the Master Issue

Read the master issue via the platform CLI (e.g., `gh issue view` or `glab issue view`).

Check for:
- **Sub-issue references** — The master issue must reference child issues (by number, checklist, or table)
- **Dependency information** — Either explicit in the master issue or derivable from the sub-issues themselves
- **Scope clarity** — The master issue should make clear what "done" looks like

If the master issue is missing any of these, **stop and tell the user what's missing**. Do NOT proceed with a half-baked plan.

## Step 2: Validate Each Sub-Issue

For each sub-issue referenced by the master issue, read it and verify it has the minimum structure for spec-driven agent execution:

### Required Sections (all must be present)
- **Changes** — What files/functions to create or modify
- **Tests** — Specific test names and what they verify
- **Acceptance criteria** — Checkboxes defining "done"

### Required Properties
- **Dependencies stated** — Which other sub-issues must be completed first (or "none")
- **Scope is bounded** — An agent can implement this without making design decisions

### Pre-Flight Report

Present a table:

| Issue | Title | Deps | Changes | Tests | AC | Ready? |
|-------|-------|------|---------|-------|----|--------|

Mark each column with a checkmark or X. If ANY issue is not ready, **list what's missing and ask the user how to proceed** — fix the issues now, or exclude them from the wave plan.

## Step 3: Compute Waves

Using the dependency graph from the sub-issues:

1. **Topological sort** — Group issues into waves where all dependencies are satisfied by prior waves
2. **Maximize parallelism** — Within each wave, all issues are independent and can run concurrently
3. **Identify the critical path** — The longest chain of sequential waves

Present the wave plan:

```
Wave 1 (parallel — no dependencies)
├── #N  Title  [branch: feature/N-description]
└── #M  Title  [branch: feature/M-description]

Wave 2 (parallel — depends on Wave 1)
├── #P  Title  [needs #N]
└── #Q  Title  [needs #N, #M]

...
```

Include:
- Which issues are in each wave
- Which branches they map to (verify branches exist, create if needed)
- The dependency chain for each
- Total number of waves and estimated parallelism

## Step 4: Get Approval

Present the full plan to the user:
1. Pre-flight report (sub-issue readiness)
2. Wave plan (dependency order)
3. Any concerns or risks identified

**Wait for explicit approval before proceeding to Step 5.**

## Step 5: Persist the Plan

Once approved:

1. **Create/update issues** — If any sub-issues need to be created (not just validated), create them now with full specs
2. **Create branches** — For any sub-issues that don't have branches yet, create them from `main`
3. **Capture in task list** — One task per wave with descriptions listing the issues and dependencies. Set up `blockedBy` relationships between wave tasks.
4. **Update the plan file** — Write the wave execution plan to the active plan file so it survives compaction

## Step 6: Confirm

Tell the user:
- How many waves, how many issues total
- Which issues were ready vs. needed fixes
- "Prep complete. Run `/nextwave` to begin execution."

## Important

- This is a PLANNING skill — it does NOT execute any implementation code
- Push back hard on vague sub-issues. A vague issue produces an agent that guesses. A precise issue produces an agent that executes.
- If the user wants to change the wave plan, iterate here — not during `/nextwave`
- The quality of the issue specs directly determines the quality of agent output
- Pair with `/nextwave` for execution: `/prepwaves` plans, `/nextwave` executes one wave at a time
