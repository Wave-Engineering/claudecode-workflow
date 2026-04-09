---
name: nextwave
description: Execute the next pending wave of spec-driven sub-agents, using flight-based conflict avoidance for parallel flights and a streamlined fast-path for serial flights
---

# NextWave — Execute One Wave with Flight-Based Conflict Avoidance

Execute the next pending wave from a plan created by `/prepwaves`. Two modes, detected automatically: **parallel flights** (2+ issues, worktree isolation) and **serial flights** (1 issue, fast-path). Merges via PR/MR only — never direct-to-main.

## Tools Used

- Lifecycle: `wave_preflight`, `wave_planning`, `wave_flight`, `wave_flight_plan`, `wave_flight_done`, `wave_close_issue`, `wave_record_mr`, `wave_review`, `wave_complete`, `wave_waiting`, `wave_defer`
- Queries: `wave_next_pending`, `wave_previous_merged`, `wave_show`
- Flight partitioning: `flight_overlap`, `flight_partition`
- Drift: `drift_files_changed`, `drift_check_path_exists`, `drift_check_symbol_exists`
- Spec: `spec_validate_structure`
- Notifications: `mcp__disc-server__disc_send` — post wave status to `#wave-status` (`1487386934094462986`)

## Concepts

- **Wave**: issues whose deps are satisfied by prior waves (from `/prepwaves`).
- **Flight**: subset of a wave's issues that can execute in parallel without file conflicts. Single-issue flights take the fast-path.
- **Planning Agent**: read-only; reports what files/functions it would touch. Skipped for single-issue flights.
- **Execution Agent**: SPEC EXECUTOR — implements exactly what the issue says. No design decisions, no improvisation. Escalates on blockers.

Flow (parallel): `pre-flight → plan → flight 1 (exec+merge) → re-validate → flight 2 → ... → drift → complete`. Serial: skip the plan/re-validate steps.

## Step 1: Pre-Flight

`wave_preflight()` → `wave_next_pending()` identifies the wave → verify main clean → `wave_previous_merged()` confirms prior wave landed → `spec_validate_structure(N)` for each issue in the wave → create feature branches from current main (`git checkout main && git pull && git checkout -b feature/<N>-<desc> && git push -u origin`) → post to `#wave-status` (`1487386934094462986`): `"🏄 **Wave <id> started** — <project>, <N> issues in <M> flights. Agent: **<dev-name>** <dev-avatar>"`. Resolve identity from `/tmp/claude-agent-<md5>.json`. If `disc_send` fails, log and continue.

If any check fails: **stop and report.** Do not launch agents on a bad foundation.

## Step 2: Planning

**Serial fast-path** (1 issue, or topology is serial): `wave_planning()` → build a trivial one-issue-per-flight plan → `wave_flight_plan(plan)` → Step 3.

**Parallel path:** `wave_planning()` → launch one planning agent per issue **in a single message** (parallel tool calls). Each returns a target manifest: files to CREATE, files to MODIFY (with function/class names), test files, config/migration files. PRECISE paths and function names. → `flight_overlap(manifests)` + `flight_partition(manifests)` compute the flight plan (Flight 1 maximizes issue count; later flights resolve conflicts). → Present the plan; proceed without re-approval (the wave was approved during `/prepwaves`); flag unusual partitions. → `wave_flight_plan(plan)`.

**Default to safe:** when in doubt, sequence conflicting issues.

## Step 3: Execute Flight

`wave_flight(N)`. Serial flight: execute directly on the feature branch. Parallel flight: launch one execution agent per issue **in a single message** on isolated worktrees.

**Execution agent rules (preserve verbatim):**

- Implement EXACTLY what the issue specifies. If the spec is wrong or needs a design change, STOP and report — do NOT improvise.
- Do NOT commit. Leave changes uncommitted.
- CI/CD: no more than 5 lines in any `run:`/`script:` block — extract shell scripts to `scripts/ci/`. No hardcoded secrets.
- Tests exercise REAL code paths. Mocks only for true external boundaries (network/fs/APIs). Every new function needs coverage. Assert meaningful outcomes. >2 mocks in one test = wrong approach.
- Report: what was implemented, files, test results, review findings, AC status, concerns. Do NOT report success on failing tests or unmet AC.

**Parent quality review (you — not the sub-agent):** **Read the actual files in each worktree.** Do not trust self-reports.

- **CI/CD compliance**: for each modified workflow/CI file, check every `run:`/`script:` block (≤5 lines), hardcoded values, anti-patterns (missing `set -e`, `latest` tags). Fix in the worktree before the checklist.
- **Test quality**: read every new/modified test. Flag over-mocking (mocking the module under test), coverage gaps, trivial tests (only "not None" / "isinstance"), and whether tests actually ran. Re-run if suspicious. Fix in the worktree.
- Append `[parent-review]` to the checklist: CI, tests, coverage status.

**Pre-commit checklist (per agent):** present the full CLAUDE.md checklist — commit context (project, issue, branch, flight), checklist items, change summary, `[fixed]`/`[deferred]` findings, `[parent-review]`. **Wait for explicit user approval on each agent's work before committing.**

**Commit, push, merge:** commit with `type(scope): desc\n\nCloses #N` → push → create PR/MR (Summary / Changes / Test Results / `Closes #N`) → wait for CI green → merge via queue/train (`gh pr merge <N> --squash --delete-branch` or `glab mr merge <N> --squash --remove-source-branch --when-pipeline-succeeds`) or sequential fallback → `wave_close_issue(N)` + `wave_record_mr(N, url)` per issue → `wave_flight_done(N)` when all flight merges land → `git checkout main && git pull` → clean worktrees.

## Step 4: Inter-Flight Re-Validation (before each flight after Flight 1)

`drift_files_changed(prev_sha, HEAD)` → for each issue in the next flight, a re-validation agent re-reads only the intersecting files and reports `PLAN VALID` / `PLAN VALID (minor)` / `PLAN INVALIDATED` / `ESCALATE`. Process: VALID → proceed; INVALIDATED → re-plan that issue; new conflict → bump to a later flight; ESCALATE → stop and present. Rebase feature branches onto updated main before the next flight.

**Serial fast-path:** when both flights are single-issue, re-validation is optional — execution agents re-read fresh anyway. Judgment call: small/local changes → skip; structural → run.

## CRITICAL: Between-Wave Lifecycle Tasks

**After the last flight is merged, IMMEDIATELY create these tasks on the task list** — persistent memory across conversational interruptions:

1. Drift check for Wave N+1 (Step 5)
2. Close issues + record MRs (blocked by 1)
3. Fire `wave_complete` (blocked by 2)
4. Report results + deferrals (blocked by 3)
5. Fire `wave_waiting` for N+1 (blocked by 4)
6. Vox announcement (blocked by 5)
7. Wave N+1: awaiting user go-ahead (blocked by 6)

Without these, you WILL lose your place when the user asks questions between waves. @final-cut learned it the hard way.

## Step 5: Wave-Boundary Drift Check (not optional; every wave)

`wave_review()` → read the next wave's issue specs → for each issue, call `drift_check_path_exists(path)` on every file path referenced and `drift_check_symbol_exists(file, symbol)` on every function/class. Optionally launch a drift-check agent for deeper API-alignment / anti-pattern / scope-creep review.

- `SPEC CURRENT` → Step 6.
- `SPEC STALE` → mechanical fix: update the issue with corrected paths/names. Report changes. No per-fix approval.
- `SPEC BROKEN` → **stop and present.** Issue may need rewriting, descoping, or splitting.
- Hotspot / anti-pattern → create a chore issue for the refactor, recommend inserting it into the next wave, get user approval.

## Step 6: Wave Complete

`wave_complete()` → mark wave task done → verify main clean → confirm all wave issues closed (`wave_show()`) → report (issues closed vs. deferred, PR/MR URLs, flight breakdown, drift findings, next wave preview) → **deferred items report** (table: item / reason / risk / tracking-issue link; every deferral MUST be tracked via `work_item` as `type::chore` or `type::docs`) → **Discord + vox announcement** (resolve identity from `/tmp/claude-agent-<md5>.json`): post to `#wave-status` (`1487386934094462986`): `"✅ **Wave <id> complete** — <project>, <N> issues merged, <M> deferred. Agent: **<dev-name>** <dev-avatar>"` then vox (conversational, name/team/project/wave/counts) → prompt: "Wave N complete. Drift check for Wave N+1 is done. Run `/nextwave` for Wave N+1, or `/cryo` to preserve state."

## Non-Negotiables

EXECUTION skill — NO design decisions. Sub-agents are SPEC EXECUTORS. Default to safe: latency beats broken code. Flights prevent merge conflicts; planning is cheap, conflict resolution is expensive; single-issue flights take the fast-path. **NEVER merge directly to main.** NEVER skip the pre-commit checklist. NEVER commit without user approval, even on all-green. One wave per invocation — the user controls the pace. When waiting: `wave_waiting("<reason>")`. When deferring: `wave_defer(desc, risk)` then accept after user approval. If compaction is imminent: `/cryo` first — the task list survives. Pair: `/prepwaves` plans, `/nextwave` executes.
