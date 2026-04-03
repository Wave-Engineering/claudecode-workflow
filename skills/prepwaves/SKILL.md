---
name: prepwaves
description: Analyze a master issue, validate sub-issue specs, compute dependency waves, and prepare for parallel agent execution
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-prepwaves does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-prepwaves
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# PrepWaves: Plan Parallel Execution Waves

Analyze epic issues and their sub-issues, validate they are ready for spec-driven parallel agent execution, compute dependency-ordered waves, and prepare everything for `/nextwave` to execute.

## Prerequisites

- One or more **epic issues** must exist, each referencing its sub-issues (stories)
- The user provides epic issue number(s): `/prepwaves #2` or `/prepwaves #2 #3 #4 #5 #6`
- Each epic becomes one **phase** in the plan. Multiple epics = multi-phase plan.

## Multi-Phase and Extend Mode

**First run (no existing plan):** Pass one or more epics. Each epic becomes a phase. All phases are initialized together.

**Adding phases later (existing plan):** If `.claude/status/phases-waves.json` already exists, `/prepwaves` automatically uses **extend mode** — new phases are appended to the existing plan without disturbing completed waves or issue state. The agent does NOT need to pass `--extend` manually; the skill detects the existing plan and does the right thing.

**This means it is safe to run `/prepwaves` per-phase.** Run it for Phase 1's epic first, execute those waves, then run it again for Phase 2's epic — the plan grows incrementally.

## Status Panel

This skill drives the `wave-status` CLI to initialize `.status-panel.html`.
The `init` command creates the state files and generates the first dashboard.
If `wave-status` is not installed, skip these calls — the wave executes normally without them.

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
- Branch naming convention: `feature/<issue-number>-<description>` (branches created at execution time by `/nextwave`)
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
2. **Do NOT create branches** — Branches are created by `/nextwave` at execution time, not at prep time. This ensures each branch starts from the current main/release branch with all prior waves' merged work included. Creating branches prematurely produces stale branches that require rebasing before every agent can start.
3. **Capture in task list** — One task per wave with descriptions listing the issues and dependencies. Set up `blockedBy` relationships between wave tasks.
4. **Update the plan file** — Write the wave execution plan to the active plan file so it survives compaction
5. **Initialize wave-status** — Build a plan JSON from the approved wave plan and initialize the status dashboard.

   Construct the plan JSON with this structure (one phase per epic):
   ```json
   {
     "project": "<Dev-Team from identity>",
     "base_branch": "main",
     "master_issue": <master-issue-number>,
     "phases": [
       {
         "name": "Phase 1",
         "waves": [
           {
             "id": "wave-1",
             "issues": [
               {"number": <issue-number>, "title": "<issue title>"},
               {"number": <issue-number>, "title": "<issue title>"}
             ]
           },
           {
             "id": "wave-2",
             "issues": [
               {"number": <issue-number>, "title": "<issue title>"}
             ]
           }
         ]
       }
     ]
   }
   ```

   **Check for an existing plan before initializing:**
   ```bash
   if [ -f .claude/status/phases-waves.json ]; then
     # Existing plan — use --extend to add new phases
     wave-status init --extend /tmp/wave-plan.json
   else
     # First run — initialize fresh
     wave-status init /tmp/wave-plan.json
   fi
   ```

   Verify the initialization succeeded:
   - `.claude/status/state.json` should exist
   - `.claude/status/phases-waves.json` should exist
   - `.claude/status/flights.json` should exist
   - `.status-panel.html` should exist at the project root

   If `wave-status` is not installed (command not found), skip this step and note it to the user.

   **Wave ID uniqueness:** When extending, wave IDs must not collide with existing waves. Use phase-prefixed IDs (e.g., `wave-2a`, `wave-2b` for Phase 2) to avoid collisions with Phase 1's `wave-1a`, `wave-1b`.

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
- `/nextwave` uses a **flight model** within each wave — it launches planning agents first to detect file-level conflicts, then partitions the wave into conflict-free flights. You do NOT need to account for file-level conflicts during `/prepwaves` — only dependency-level ordering matters here. Flight partitioning happens at execution time.
