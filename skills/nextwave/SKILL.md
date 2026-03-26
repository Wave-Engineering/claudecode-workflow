---
name: nextwave
description: Execute the next pending wave of parallel spec-driven sub-agents on isolated worktrees, using flight-based conflict avoidance
---

# NextWave: Execute One Wave with Flight-Based Conflict Avoidance

Execute the next pending wave from a plan created by `/prepwaves`. Uses a two-phase approach: **planning agents** identify file targets, then issues are partitioned into **flights** (conflict-free groups) for safe parallel execution. Merges via PR/MR — never directly to main.

## Core Concepts

- **Wave**: A group of issues whose dependencies are all satisfied by prior waves. Defined by `/prepwaves`.
- **Flight**: A subset of a wave's issues that can execute in parallel without file-level conflicts. Determined at runtime by analyzing planning agent output.
- **Planning Agent**: A lightweight, read-only agent that reads an issue and the codebase, then reports which files/functions it would modify — without writing any code.
- **Execution Agent**: A full agent that implements the issue on an isolated worktree.

Flow: `Pre-Flight Checks → Planning Phase → Flight 1 (execute + merge) → Re-Validate → Flight 2 (execute + merge) → ... → Design Review → Wave Complete`

## Status Panel

This skill drives the `wave-status` CLI to keep `.status-panel.html` current.
Every lifecycle transition triggers a dashboard regeneration via a `wave-status`
command. If `wave-status` is not installed, skip these calls — the wave executes
normally without them.

## Prerequisites

- `/prepwaves` must have been run — wave plan must exist in the task list
- Previous waves (if any) must be merged to the main branch

## Platform Detection

Before starting, detect the platform from the git remote:
- **GitHub** (`github.com` in remote URL) — use `gh` CLI, create **pull requests** (PRs)
- **GitLab** (`gitlab` in remote URL) — use `glab` CLI, create **merge requests** (MRs)

Use the correct CLI and terminology throughout. The rest of this document uses "PR/MR" to mean whichever applies.

---

## Step 1: Pre-Flight Checks

Before launching any agents:

1. **Update status panel** — Signal that pre-flight checks are underway:
   ```bash
   wave-status preflight
   ```
2. **Identify the next pending wave** — Read the task list, find the first wave task that is not completed
3. **Verify the main branch is clean** — `git status` shows no uncommitted changes, `git log` confirms previous wave's commits are present
4. **Verify previous wave is merged** — If this is not Wave 1, confirm that all issues from the prior wave have their code on the main branch
5. **Verify issue specs** — For each issue in this wave, read it via the platform CLI and confirm it has: Changes, Tests, Acceptance Criteria
6. **Create feature branches** — For each issue in this wave, create a branch from the current main/release branch. This ensures each branch includes all prior waves' merged work.
   ```bash
   git checkout main && git pull
   git checkout -b feature/<issue-number>-<description>
   git push -u origin feature/<issue-number>-<description>
   ```
   Repeat for each issue in the wave. Branches are created at execution time (not during `/prepwaves`) to avoid stale branches that need rebasing.

If any check fails, **stop and report** — do not launch agents on a bad foundation.

---

## Step 2: Planning Phase — Target Analysis

Signal the transition to the planning phase:
```bash
wave-status planning
```

Launch **planning agents** for every issue in the wave. These are lightweight, read-only agents that analyze the codebase and report what they would change — without writing any code.

**All planning agents MUST be launched in a single message** (parallel tool calls) to maximize concurrency.

### Planning Agent Prompt Template

```
You are a PLANNING AGENT. Your job is to read an issue and the codebase, then report exactly which files and code blocks you would modify. Do NOT write any code. Do NOT make changes.

## Your Issue
Read issue #N from this repo using the platform CLI (gh issue view N, or glab issue view N).

## Your Task
1. Read the issue thoroughly — understand every acceptance criterion
2. Read the existing codebase files relevant to this issue
3. Identify EVERY file you would create or modify to implement this issue
4. For each file, identify the specific functions/classes/blocks you would change

## Report Format
Return a structured target manifest:

### Target Manifest for Issue #N

**Files to CREATE:**
- `path/to/new_file.py` — brief description of what it contains

**Files to MODIFY:**
- `path/to/existing.py`
  - Function/method: `function_name()` (lines ~X-Y) — what changes
  - Function/method: `other_function()` (lines ~X-Y) — what changes
- `path/to/another.py`
  - Class: `ClassName` — what changes
  - Import block (lines ~1-10) — new imports needed

**Test files to CREATE:**
- `tests/test_feature.py` — brief description

**Test files to MODIFY:**
- `tests/test_existing.py` — what changes and why

**Config/Migration files:**
- `alembic/versions/NNNN_description.py` — new migration
- Other config changes

Be PRECISE about file paths and function names. The orchestrator uses this to detect conflicts between parallel agents.
```

### Conflict Detection

Once all planning agents report back:

1. **Build a target map** — For each file, list which issues want to modify it
2. **Detect conflicts** — A conflict exists when two or more issues target the **same file**. Be more granular where possible:
   - Same function in the same file = **hard conflict** (must be sequenced)
   - Different functions in the same file = **soft conflict** (may be safe, but sequence to be safe)
   - Same file but one creates and one modifies = **hard conflict**
   - Different files entirely = **no conflict**
3. **Default to safe** — When in doubt, treat it as a conflict and sequence the agents

### Flight Partitioning

Partition the wave's issues into flights:

1. **Flight 1** — All issues with no conflicts (or one issue from each conflict group). Maximize the number of issues in Flight 1.
2. **Flight 2** — Issues that conflicted with Flight 1 issues, now safe to run (Flight 1 will be merged first). May also include issues that conflict with each other — apply the same partitioning recursively.
3. **Flight N** — Continue until all issues are assigned to a flight.

**Partitioning rules:**
- Within a flight, no two issues may target the same file
- Prefer putting the issue with the MOST file changes into an earlier flight (it establishes the new baseline for later flights)
- If only one conflict exists between two issues, put the simpler/smaller one in Flight 1 (less disruption to later flights)

Present the flight plan to the user:

```
## Flight Plan for Wave N

### Flight 1 (parallel — no file conflicts)
- #A — Title
- #B — Title

### Flight 2 (after Flight 1 merges — resolves conflicts with #A)
- #C — Title (conflicts with #A on sync.py)
- #D — Title

### Conflict Analysis
- sync.py: #A (handle_rename) vs #C (handle_deleted_file) → sequenced
- models.py: #A (ChangedFile) only → no conflict
```

Proceed to execute Flight 1 without waiting for additional approval (the user approved the wave plan during `/prepwaves`). If the flight plan looks unusual (e.g., all issues in separate flights due to heavy conflicts), flag it to the user.

**Store the flight plan in the status dashboard:**

Build a JSON array of flights (one object per flight, with issue numbers and initial status):
```bash
cat > /tmp/flight-plan.json << 'FLIGHTS'
[
  {"issues": [<issue-numbers-in-flight-1>], "status": "pending"},
  {"issues": [<issue-numbers-in-flight-2>], "status": "pending"}
]
FLIGHTS
wave-status flight-plan /tmp/flight-plan.json
```

---

## Step 3: Execute Flight

Signal the flight is starting:
```bash
wave-status flight <N>
```

For the current flight, launch **execution agents** — one per issue, all in parallel on isolated worktrees.

**All agents in a flight MUST be launched in a single message** (parallel tool calls) to maximize concurrency.

### Execution Agent Prompt Template

Each agent receives this prompt (filled in per-issue):

```
You are implementing a specific issue. You are a SPEC EXECUTOR — implement exactly what the issue describes. Do NOT make design decisions or change scope.

## Your Issue
Read issue #N from this repo using the platform CLI (gh issue view N, or glab issue view N).

## Rules
1. IMPLEMENT EXACTLY what the issue specifies — changes, tests, acceptance criteria
2. Do NOT make design changes. If something in the issue doesn't work as described or needs a design change, STOP and report back with what's wrong and why. Do NOT improvise.
3. Do NOT commit. Leave all changes uncommitted in the worktree.
4. Work on branch: feature/N-description

## CI/CD Rules
- If you create or modify CI workflow files (`.github/workflows/*.yml`, `.gitlab-ci.yml`): **NO MORE THAN 5 LINES in any `run:` or `script:` block.** If the logic exceeds 5 lines, create a shell script in `scripts/ci/` and call it instead.
- Do NOT hardcode secrets or environment-specific values in CI files.

## Test Quality Rules
- Tests must exercise REAL code paths. Do NOT mock the module under test.
- Mocks are ONLY acceptable for true external boundaries: network calls, filesystem I/O, external APIs, third-party services.
- Every new function or module you create must have corresponding test coverage.
- Tests must assert meaningful outcomes — not just "didn't throw" or "returned something."
- If you find yourself mocking more than 2 things in a single test, you are probably testing the wrong way. Step back and test the real behavior.

## Implementation Steps
1. Read the issue thoroughly — understand every acceptance criterion
2. Read the existing codebase files you'll be modifying
3. Implement the changes described in the issue
4. Write ALL tests listed in the issue
5. Run the test suite and fix any failures
6. Run the code-reviewer agent over your changes — fix any high+ risk findings

## When You're Done
Report back with:
- **What was implemented** — brief summary of changes made
- **Files modified/created** — list with brief descriptions
- **Test results** — which tests pass, any failures
- **Code review findings** — what was found, what was fixed, what remains (with risk levels)
- **Acceptance criteria status** — check each criterion, mark as done or explain what's missing
- **Concerns or blockers** — anything that didn't go as the issue described

Do NOT report success if tests fail or acceptance criteria are unmet. Be honest about the state.
```

### Collect Results

As agents complete, collect their reports. For each agent:

1. **Read the agent's report** — what was built, test results, review findings, concerns
2. **Check for escalations** — did any agent flag a design issue or blocker?
3. **Note the worktree path** — where the agent's changes live

If any agent escalated a design concern:
- **Stop the flight** — present the concern to the user before proceeding
- The user may need to update the issue spec and re-run that agent

### Parent Agent Quality Review

Before presenting checklists to the user, the parent agent (you) must review each sub-agent's work for quality issues that sub-agents commonly miss. **Read the actual files in the worktree** — do not rely solely on the sub-agent's self-report.

#### CI/CD Compliance Review

If any CI/CD files were created or modified (`.github/workflows/*.yml`, `.gitlab-ci.yml`):

1. **Read every modified workflow/CI file** in the worktree
2. **Check each `run:` / `script:` block** — if any exceeds 5 lines of procedural logic, flag it. The fix is to extract into a shell script in `scripts/ci/`.
3. **Check for hardcoded values** — secrets, environment-specific URLs, account numbers should be parameterized via secrets/variables, not inline.
4. **Check for anti-patterns** — `set -e` missing in shell scripts called from CI, missing error handling on critical steps, `latest` tags on Docker images.

If violations are found: **fix them in the worktree before presenting to the user.** Note the fixes in the Change Summary.

#### Test Quality Review

For ALL new or modified test files:

1. **Read the test files** in the worktree — do not trust the sub-agent's "all tests pass" at face value
2. **Check for over-mocking** — If a test mocks the module it's supposed to be testing, it proves nothing. Mocks are only acceptable for true external boundaries (network, filesystem, external APIs, third-party services). Flag any test that mocks internal project code.
3. **Check for coverage gaps** — Every new function, class, or module introduced by the story should have at least one test that exercises its real behavior. List any untested code paths.
4. **Check for trivial tests** — Tests that only assert "not None", "isinstance", or "didn't raise" without checking actual behavior are insufficient. Tests must verify correct *outcomes*.
5. **Check that tests actually ran** — Verify the sub-agent's reported test output. If tests weren't run or results look suspicious, re-run them yourself in the worktree.

If issues are found: **fix them in the worktree before presenting to the user.** Note the fixes in the Change Summary under a `[test-quality]` category.

#### Review Summary

After completing both reviews, add a section to the pre-commit checklist:

**[parent-review]** — Summary of what was checked and any fixes applied:
- CI compliance: (clean / N issues fixed)
- Test quality: (clean / N issues fixed)
- Coverage: (all new code covered / gaps noted)

### Present Pre-Commit Checklists

For EACH agent's work in this flight, present the full pre-commit checklist as defined in CLAUDE.md:

#### Commit Context

| Field | Value |
|-------|-------|
| **Project** | (from Dev-Team identity) |
| **Issue** | #N — issue title |
| **Branch** | `feature/N-description` → `main` |
| **Flight** | Flight X of Y in Wave Z |

#### Checklist
(The full CLAUDE.md checklist — Implementation Complete, TODOs, Docs, Pre-commit, Tests, Scripts, Code Review)

#### Change Summary
(Categorized by codebase/docs/tests/config)

#### Review Findings
**[fixed]** — high+ risk items resolved by the agent
**[deferred]** — medium and below for user assessment

**Wait for explicit user approval on EACH agent's work before committing.**

### Commit, Push, and Create PR/MR

For each approved agent:

1. **Commit** on the feature branch in the worktree with proper commit message format:
   ```
   type(scope): description

   Closes #N   (GitHub)
   Closes #N   (GitLab — or use "Resolves #N" if project prefers)
   ```

2. **Push the feature branch** to the remote:
   ```bash
   git push -u origin feature/N-description
   ```

3. **Create a PR/MR** targeting the main branch:

   **GitHub:**
   ```bash
   gh pr create --title "feat(scope): description" --body "$(cat <<'EOF'
   ## Summary
   <brief description of changes>

   ## Changes
   <bullet list of what was modified>

   ## Test Results
   <paste test output summary>

   Closes #N

   Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

   **GitLab:**
   ```bash
   glab mr create --title "feat(scope): description" --description "$(cat <<'EOF'
   ## Summary
   <brief description of changes>

   ## Changes
   <bullet list of what was modified>

   ## Test Results
   <paste test output summary>

   Closes #N

   Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )" --source-branch feature/N-description --target-branch main
   ```

4. **Wait for CI** — If CI is configured, check that tests pass before merging:
   - GitHub: `gh pr checks <number>` (poll until tests pass; builds may be non-blocking)
   - GitLab: `glab mr view <number>` to check pipeline status

5. **Merge the flight's PR/MRs** — use the appropriate strategy:

   **Option A: Merge queue / merge train (preferred when available)**

   - GitHub (merge queue enabled): `gh pr merge <number> --squash --delete-branch --merge-queue`
   - GitLab (merge train enabled): `glab mr merge <number> --squash --remove-source-branch --when-pipeline-succeeds`

   **Option B: Sequential merge (fallback when queues/trains not available)**

   1. Merge the first PR/MR
   2. Pull to local main: `git checkout main && git pull`
   3. Verify remaining PR/MR branches are still clean (rebase if needed)
   4. Repeat for the next PR/MR

6. **Update status dashboard** — after each PR/MR is merged, record the closure and PR/MR reference:
   ```bash
   wave-status close-issue <issue-number>
   wave-status record-mr <issue-number> "<PR/MR-number-or-URL>"
   ```
   After ALL PR/MRs in the flight are merged, mark the flight complete:
   ```bash
   wave-status flight-done <N>
   ```

7. **Pull merged changes** to local main after all flight PR/MRs are merged:
   ```bash
   git checkout main && git pull
   ```

8. **Clean up worktrees** — remove temporary worktrees for this flight

---

## Step 4: Inter-Flight Transition (Targeted Re-Validation)

**This step runs before each flight after Flight 1.** Its purpose is to ensure that the previous flight's merged changes haven't invalidated the next flight's plans.

### 4a: Identify Changed Files

Determine which files were modified by the previous flight:
```bash
git diff --name-only <pre-flight-sha>..HEAD
```

### 4b: Launch Targeted Re-Validation Agents

For each issue in the next flight, launch a **lightweight re-validation agent**:

```
You are a RE-VALIDATION AGENT. A previous flight of changes has been merged. Your job is to confirm that your implementation plan for issue #N is still valid.

## Context
The following files were modified by the previous flight:
<list of changed files>

## Your Task
1. Read the issue: #N
2. Re-read ONLY the files from the changed list that overlap with your planned targets
3. Assess impact:
   - **No impact**: The changes don't affect your planned work. Report "PLAN VALID".
   - **Minor impact**: Line numbers shifted or imports changed, but your approach is the same. Report "PLAN VALID — minor adjustments needed" with details.
   - **Major impact**: A function you planned to extend was refactored, moved, or deleted. Your plan needs revision. Report "PLAN INVALIDATED" with details of what changed and why your plan breaks.
   - **Impossible**: The previous flight's changes make your issue nonsensical or harmful to implement. Report "ESCALATE" with a clear explanation.

## Report Format
### Re-Validation for Issue #N
- **Status**: PLAN VALID | PLAN VALID (minor adjustments) | PLAN INVALIDATED | ESCALATE
- **Changed files reviewed**: list
- **Impact assessment**: brief explanation
- **Revised targets** (if PLAN INVALIDATED): updated file/function targets
```

### 4c: Process Re-Validation Results

- **All PLAN VALID** → Proceed to execute the next flight (Step 3)
- **PLAN VALID (minor adjustments)** → Proceed; the execution agent will adapt naturally since it reads the codebase fresh
- **PLAN INVALIDATED** → Re-run the planning phase for just the affected issue(s). If the revised plan creates a NEW conflict with another issue in this flight, bump one of them to a later flight.
- **ESCALATE** → Stop and present the concern to the user. The issue spec may need updating. Do NOT proceed with an agent that says its task is impossible or harmful.

### 4d: Rebase Feature Branches

Before executing the next flight, rebase its feature branches onto the updated main/release branch so execution agents start from the latest code:
```bash
git checkout feature/N-description
git rebase main  # or release/X.Y.Z
git push --force-with-lease
```

Then return to Step 3 for the next flight.

---

## Step 5: Wave-Boundary Design Review

**This step runs after all flights are merged but BEFORE prompting for the next wave.** Its purpose is to catch spec drift — issue specs for later waves were written before earlier waves were implemented, so file paths, function signatures, and API surfaces may no longer match reality.

This is NOT optional. It runs for every wave, regardless of size. Rules with exceptions get ignored.

Signal the transition to design review:
```bash
wave-status review
```

### 5a: Read Next Wave's Issue Specs

Identify the next wave from the task list. For each issue in that wave, read its full spec via the platform CLI.

### 5b: Launch Design Review Agents

For each issue in the NEXT wave, launch a lightweight review agent:

```
You are a DESIGN REVIEW AGENT. The previous wave has just been merged. Your job is to check whether the spec for issue #N still matches the actual codebase.

## Your Task
1. Read issue #N via the platform CLI
2. For each file path mentioned in the issue's "Changes" section, verify it exists and the referenced functions/classes/structures are present and match the spec's assumptions
3. For each API or interface the issue depends on, verify the signatures and behaviors match what the spec expects

## Check Categories

### Spec Freshness
- Do file paths referenced in the issue still exist at those locations?
- Do function/class names referenced in the issue match what's actually in the code?
- Do API signatures (parameters, return types) match what the spec assumes?
- Has any dependency listed in the issue been moved, renamed, or refactored?

### API Surface Alignment
- Did the previous wave create or modify APIs that this issue references?
- If so, do the actual APIs match what this issue's spec expects?

### Emerging Anti-Patterns
- Are there files that have been modified by many prior issues (conflict magnets)?
- Are there patterns emerging that suggest a refactor would reduce risk for this issue (e.g., a module doing too many things, a "god file" accumulating subcommands)?
- If you detect a hotspot file: note it and suggest whether a structural refactor should be done BEFORE this issue runs, or whether the issue can proceed safely.

### Scope Creep Detection
- Did any previous wave add functionality not in its spec that this issue's spec might conflict with?
- Are there new files, functions, or patterns that this issue should know about but its spec doesn't mention?

## Report Format
### Design Review for Issue #N

- **Status**: SPEC CURRENT | SPEC STALE | SPEC BROKEN
- **File path checks**: list of paths checked and whether they're still accurate
- **API alignment**: any mismatches between spec assumptions and actual code
- **Anti-patterns detected**: any hotspot files or structural concerns
- **Scope creep risks**: anything unexpected from prior waves
- **Recommended spec updates**: specific changes to make to the issue before execution (if any)
```

### 5c: Process Design Review Results

- **All SPEC CURRENT** → Report findings and proceed to Wave Complete (Step 6). No spec updates needed.
- **SPEC STALE** → The spec references outdated file paths, function names, or APIs that have been renamed or restructured. **Update the issue on the platform** with corrected paths/names before proceeding. These are mechanical fixes — don't wait for user approval on each one, but report what was changed.
- **SPEC BROKEN** → The spec makes assumptions that are fundamentally wrong given the current codebase state. **Stop and present to the user.** The issue may need significant rewriting, descoping, or splitting. Do NOT proceed to the next wave until resolved.
- **Anti-pattern detected** → If a structural refactor is recommended (e.g., extracting a plugin registry from a conflict-magnet file), **create a chore issue** for the refactor and recommend inserting it into the next wave. Present to the user for approval. The refactor issue should follow the same spec format as any other issue (Changes, Tests, AC).

### 5d: Update Status Panel

If `.claude/status/state.json` exists, update it to reflect any spec changes, new chore issues, or anti-pattern findings from this review.

---

## Step 6: Wave Complete

After ALL flights in the wave have been executed, merged, and the design review is done:

1. **Mark the wave complete in status dashboard:**
   ```bash
   wave-status complete
   ```
2. **Mark the wave task as completed** in the task list
3. **Verify the main branch is clean** — all merges successful, no conflicts
4. **Close issues** if not auto-closed by the PR/MR merge keywords — verify closure via the platform CLI
5. **Report wave status:**
   - How many issues completed vs. deferred
   - PR/MR URLs for the record
   - Flight breakdown (how many flights, what was sequenced and why)
   - Any issues that need re-work
   - Design review findings for the next wave
   - What the next wave contains (with any spec updates noted)

### Deferred Items Report

At wave completion, report ALL items that were deferred during this wave:

```
## Deferred Items from Wave N

| Item | Deferred From | Reason | Risk of Deferral |
|------|---------------|--------|------------------|
| Update rules config docs with delete policy section | #18 | Internal behavior, no user-facing impact yet | Low — docs needed before release |
| README retry configuration section | #19 | Config is env-var based, discoverable | Low — docs needed before release |
```

For each deferred item:
- Explain WHY it is acceptable to defer
- Assess the RISK of deferral (low/medium/high)
- **Create a tracking issue** on the platform for each approved deferral, labeled `type::chore` or `type::docs`

Do NOT let deferred items disappear into the void. Every deferral must be tracked.

6. **Prompt:** "Wave N complete. Design review for Wave N+1 is done. Run `/nextwave` for Wave N+1, or `/cryo` to preserve state."

---

## Important

- This is an EXECUTION skill — it does NOT make design decisions
- Sub-agents are SPEC EXECUTORS — they implement what the issue says, nothing more
- If an agent needs to deviate from the spec, it escalates — it does NOT improvise
- **Default to safe** — latency is always preferable to broken code or merge conflicts
- **Flights exist to prevent merge conflicts** — the planning phase is cheap, conflict resolution is expensive
- Worktrees provide isolation — agents cannot interfere with each other or with `main`
- **NEVER merge directly to main** — always go through a PR/MR for audit trail and CI
- NEVER skip the pre-commit checklist — it exists because compaction has caused skipped reviews before
- NEVER commit without user approval — even if the agent reports all green
- When waiting on user input (approvals, decisions), update the dashboard: `wave-status waiting "<reason>"`
- When deferring items, track them: `wave-status defer "<description>" "<risk>"` and `wave-status defer-accept <index>` after user approval
- One wave per invocation — the user controls the pace
- If compaction is imminent, run `/cryo` before it hits — the task list tracks wave progress
- Pair with `/prepwaves` for planning: `/prepwaves` plans, `/nextwave` executes
