---
name: nextwave
description: Execute the next pending wave of spec-driven sub-agents, using flight-based conflict avoidance for parallel flights and a streamlined fast-path for serial flights
---

# NextWave — Execute One Wave with the Orchestrator/Prime/Flight Protocol

Execute the next pending wave created by `/prepwaves`. Single-wave primitive. The top-level session is the **Orchestrator**; it spawns a **Prime** sub-agent for planning and post-flight merge work, and N **Flight** sub-agents in parallel for per-issue implementation. All inter-agent data flows through a filesystem message bus under `/tmp/wavemachine/{repo-slug}/wave-{N}/` — Orchestrator context holds only paths and status tokens.

Two modes:

- `/nextwave` — **interactive**. Approval gate fires after Flights return and before Prime(post-flight) pushes anything to remote.
- `/nextwave auto` — **auto**. Skips the approval gate. Called by `/wavemachine`. `wave_ci_trust_level` stands in for human judgement.

Merges always go through PR/MR — never direct-to-main.

## Why this shape

CC sub-agents do not have the `Agent`/`Task` tool. Only the top-level session can spawn parallel sub-agents. That means the Orchestrator *must* own the parallel Flight spawn; Prime cannot do it. Prime is a sequential planner and merge-driver; Flights are the workers. Filesystem bus keeps Orchestrator tokens O(1) per flight regardless of flight content size. See `lesson_cc_subagent_tools.md` and `decision_wavemachine_v2.md`.

## Tools Used

- Lifecycle: `wave_preflight`, `wave_next_pending`, `wave_previous_merged`, `wave_flight_plan`, `wave_flight`, `wave_flight_done`, `wave_close_issue`, `wave_record_mr`, `wave_reconcile_mrs`, `wave_review`, `wave_complete`, `wave_waiting`, `wave_defer`, `wave_show`
- Flight partitioning (used by Prime): `flight_overlap`, `flight_partition`
- Drift (used by Prime post-wave): `drift_files_changed`, `drift_check_path_exists`, `drift_check_symbol_exists`
- Spec: `spec_validate_structure`, `spec_get`, `spec_acceptance_criteria`
- Commutativity + merge (used by Prime post-flight): `commutativity_verify`, `pr_create`, `pr_wait_ci`, `pr_merge`
- CI trust (auto mode): `wave_ci_trust_level`
- Bus primitives (bash): `scripts/wavebus/wave-init`, `scripts/wavebus/flight-finalize`, `scripts/wavebus/wave-cleanup`
- Notifications: `mcp__disc-server__disc_send` — post wave status to `#wave-status` (`1487386934094462986`)

## Concepts

- **Orchestrator** — this session. Has `Agent`. Drives the Step 1–6 loop below. Parses canonical status lines. Owns the approval gate in interactive mode.
- **Prime** — `general-purpose` sub-agent. One per wave (re-spawned per role: pre-wave / post-flight / post-wave). Reads/writes bus files; runs MCP tools. Does NOT commit. Does NOT have `Agent`.
- **Flight** — `general-purpose` sub-agent. One per issue in a flight. Reads `prompt.md` from the bus, works in an assigned worktree, runs mechanical precheck, commits in the worktree, writes `results.md.partial`, calls `flight-finalize`, returns the canonical line as its last message.
- **Canonical Flight return regex:** `^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$`. Anything else → Orchestrator treats as FAIL (malformed).
- **Bus path scheme:**

  ```
  /tmp/wavemachine/{repo-slug}/wave-{N}/
  ├── plan.md                                 # Prime(pre-wave) writes
  ├── merge-report.md                         # Prime(post-wave) writes
  ├── flight-{M}/
  │   ├── merge-report.md                     # Prime(post-flight) writes
  │   └── issue-{X}/
  │       ├── prompt.md                       # Prime(pre-wave) writes
  │       ├── results.md.partial              # Flight writes first
  │       ├── results.md                      # atomic rename target
  │       └── DONE                            # "PASS" or "FAIL"
  ```

## Step 1 — Orchestrator pre-flight

1. `wave_preflight()` → `wave_next_pending()` → resolve wave id `N`. If none, report and exit.
2. Resolve **target repo slug** for the bus path. Same-repo waves: use the current repo's slug. Cross-repo waves (wave plan lives in this repo, stories live elsewhere): use the target repo's slug per `lesson_cross_repo_wave_orchestration.md`.
3. Verify main is clean in the target repo; `wave_previous_merged()` confirms prior wave landed; `spec_validate_structure(issue)` for each issue in the wave.
4. Call `scripts/wavebus/wave-init <repo-slug> <N> 1`. Flight count is `1` initially — Prime may re-invoke it with the real count (script is idempotent). Capture the printed wave root.
5. Pre-create worktrees per issue. Same-repo: `Agent` calls in Step 3 can use `isolation: "worktree"`. Cross-repo: create them now via `git -C <target-repo> worktree add /tmp/wt-<slug>-<issue> -b feature/<issue>-<desc>` (one per issue).
6. Resolve identity from `/tmp/claude-agent-<md5>.json`; post to `#wave-status` (`1487386934094462986`): `"🏄 **Wave <N> started** — <project>, <issue-count> issues. Agent: **<dev-name>** <dev-avatar>"`. If `disc_send` fails, log and continue.
7. Spawn **Prime(pre-wave)** — single `Agent` call, `subagent_type: general-purpose`. Prompt template below.

## Step 2 — Prime(pre-wave) prompt contract

Prime(pre-wave) is a sub-agent. It does NOT have `Agent`; it cannot spawn Flights. Its job is to plan the wave into the bus.

Prompt template (fill in `<repo-slug>`, `<N>`, `<wave-root>`, and the issue list):

> You are the Prime agent for wave `<N>` of `<repo-slug>`. You plan the wave into the filesystem bus at `<wave-root>`.
>
> Inputs:
> - Wave id: `<N>`
> - Issues in this wave: `<list-of-issue-numbers>`
> - Wave root: `<wave-root>`
> - Target repo: `<target-repo>`
>
> Steps:
> 1. For each issue, fetch the spec via `spec_get` and acceptance criteria via `spec_acceptance_criteria`. Summarize files-to-create / files-to-modify / test files per issue.
> 2. Run `flight_overlap` + `flight_partition` on the per-issue manifests to determine flight structure. Flight 1 maximizes issue count; later flights resolve file-level conflicts. When in doubt, sequence.
> 3. If the partition needs more flights than the bus was pre-created for, call `scripts/wavebus/wave-init <repo-slug> <N> <final-flight-count>` (idempotent).
> 4. Write `<wave-root>/plan.md` summarizing the flight structure (flight M → issues, per-issue file manifest, rationale).
> 5. For each flight M and each issue X in it, write `<wave-root>/flight-<M>/issue-<X>/prompt.md` containing the full Flight instructions (see "Flight stub prompt" in the caller's skill body — reproduce verbatim, fill placeholders).
> 6. Register the plan via `wave_flight_plan`.
> 7. If any issue's spec is unbuildable (missing AC, structural contradiction, etc.), mark the plan `BLOCKED` and name the failing issue + reason in `plan.md`.
>
> Final message — exactly one line, no prose, no fences:
>
> ```
> {"plan_path":"<absolute-path-to-plan.md>","status":"READY|BLOCKED","flights":[{"flight":1,"issues":[N,N,N]},{"flight":2,"issues":[N]}]}
> ```

Orchestrator parses that JSON. If `status=BLOCKED`, print the blocker from `plan.md`, post a BLOCKED notice to `#wave-status`, exit (leave bus in place for forensics). In **auto mode**, emit the canonical status line (see "Step 6 — Final status emission") before returning control. Else continue.

## Step 3 — Per-flight execution loop

For each flight M in the plan, in order:

### 3a. `wave_flight(flight_number=M)` — register flight start.

### 3b. Spawn parallel Flights in ONE tool-use block.

The Orchestrator issues one `Agent` tool-use block containing N `Agent` calls — one per issue in flight M — **in the same assistant message**. This is the only place in the skill where parallelism actually happens. Do NOT issue the calls in separate messages; do NOT use `run_in_background`; do NOT shell out.

Each Agent call: `subagent_type: general-purpose`, prompt = the Flight stub below (filled in), and for same-repo waves `isolation: "worktree"` (for cross-repo, omit — worktrees were pre-created in Step 1.5 and are referenced by path in the prompt).

### 3c. Collect returns.

Each Flight's last message is exactly one line matching `^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$`. Orchestrator:

- Parses each line. Malformed → record as FAIL, note "malformed return".
- Verifies the `DONE` sentinel (`/tmp/wavemachine/.../issue-<X>/DONE`) exists and contains `PASS` or `FAIL` matching the returned line. Mismatch → FAIL.
- Reads each `results.md` into context (small, summary + checklist).

### 3d. Approval gate (interactive mode only — SKIP in auto mode).

Present a per-Flight summary table (issue, worktree, PASS/FAIL, results.md excerpt). Wait for explicit user approval before Step 3e. If rejected: leave the bus in place, report the wave root path, exit. Nothing touches remote.

In **auto mode**: call `wave_ci_trust_level`; if trust is sufficient, skip the gate and proceed directly to Step 3e. If trust drops below threshold (e.g. recent CI instability), pause and surface to the parent `/wavemachine` caller.

### 3e. Spawn Prime(post-flight).

One `Agent` call, `subagent_type: general-purpose`. Prompt template:

> You are the Prime(post-flight) agent for wave `<N>`, flight `<M>` of `<repo-slug>`. Flights have already committed in their worktrees. You push, PR, wait CI, verify commutativity, and merge.
>
> Inputs:
> - Wave root: `<wave-root>`
> - Flight: `<M>`
> - Issues in this flight: `<list>`
> - Target repo: `<target-repo>`
>
> Steps:
> 1. For each issue X in this flight, read `<wave-root>/flight-<M>/issue-<X>/results.md` and verify `DONE` contains `PASS`. If any FAIL, stop and write a `BLOCKED` report naming the failing issues.
> 2. For each issue, push the Flight's commit from its worktree (`git -C <worktree> push -u origin <branch>`), create a PR via `pr_create`, wait for CI via `pr_wait_ci`.
> 3. If this flight has multiple issues, run `commutativity_verify` on the changesets `{id, head_ref}`. Interpret the group verdict:
>    - `STRONG` / `MEDIUM` → `pr_merge(skip_train=true)` for all.
>    - `WEAK` / `ORACLE_REQUIRED` → sequential merge via the merge queue (no skip).
>    Single-issue flights skip commutativity entirely.
> 4. Merge all flight PRs via `pr_merge`. On merge, call `wave_close_issue(X)` and `wave_record_mr(X, url)` per issue. Call `wave_flight_done(M)` after all merges land.
> 5. `git checkout main && git pull` in the target repo.
> 6. Write `<wave-root>/flight-<M>/merge-report.md` (per-issue PR URL, CI status, merge strategy, anomalies).
>
> Final message — exactly one line:
>
> ```
> {"report_path":"<absolute-path-to-merge-report.md>","status":"PASS|FAIL|BLOCKED"}
> ```

### 3f. Parse Prime(post-flight) return.

- `PASS` → continue to the next flight. If the next flight exists, perform the inter-flight re-validation step 3g before spawning its Flights.
- `FAIL` / `BLOCKED` → stop the per-flight loop. Leave the bus in place. Surface to user with the `report_path`. In **auto mode**, emit the canonical status line (see "Step 6 — Final status emission") before returning control.

### 3g. Inter-flight re-validation (before flight M+1, M ≥ 1).

`drift_files_changed(prev_sha, HEAD)` on the target repo. If the changeset intersects any file in flight M+1's manifest, spawn a small re-validation Flight per affected issue (same mechanism as Step 3b, one `Agent` call per issue in a single tool-use block). Each returns `PLAN VALID` / `PLAN VALID (minor)` / `PLAN INVALIDATED` / `ESCALATE`. INVALIDATED → re-plan via a fresh Prime(pre-wave) narrowed to the affected issues; ESCALATE → stop and surface. Rebase feature branches onto updated main before the next flight.

Serial fast-path: when both flights are single-issue and the changed file set is small/local, skip the re-validation Flight spawn. Judgment call — the next Flight will re-read fresh anyway.

## Step 4 — Post-wave Prime (terminal)

After every flight has merged:

1. Spawn **Prime(post-wave)** — one `Agent` call, `subagent_type: general-purpose`. Prompt:

   > You are the Prime(post-wave) agent for wave `<N>` of `<repo-slug>`. The wave is fully merged. You reconcile state and emit the terminal report.
   >
   > Steps:
   > 1. `wave_review()` — confirm every wave issue is closed.
   > 2. `wave_reconcile_mrs()` — reconcile recorded MRs against actual PR state.
   > 3. Drift check against wave N+1: read the next wave's issue specs; for each file path referenced call `drift_check_path_exists`, for each symbol call `drift_check_symbol_exists`, and `drift_files_changed(prev_sha, HEAD)` for summary.
   >    - `SPEC CURRENT` → note in report; move on.
   >    - `SPEC STALE` → mechanical fix: update the issue with corrected paths/names; list changes in the report.
   >    - `SPEC BROKEN` → leave the issue alone; flag for user attention in the report.
   > 4. `wave_complete()` (marks the current wave complete — takes no args; the server uses the active wave from state).
   > 5. Write `<wave-root>/merge-report.md` (issues closed, PR URLs, flight breakdown, drift findings, deferred items, next-wave preview).
   >
   > Final message — exactly one line:
   >
   > ```
   > {"report_path":"<absolute-path-to-merge-report.md>","status":"PASS|FAIL|BLOCKED"}
   > ```

2. Orchestrator reads the report, surfaces a human-readable summary, and — in interactive mode — prompts: "Wave N complete. Run `/nextwave` for Wave N+1, or `/cryo` to preserve state."
3. Post to `#wave-status` (`1487386934094462986`): `"✅ **Wave <N> complete** — <project>, <merged> merged, <deferred> deferred. Agent: **<dev-name>** <dev-avatar>"`, then vox announcement (conversational: name, team, project, wave, counts).
4. In **auto mode**, emit the canonical status line (see "Step 6 — Final status emission") as the final assistant message. If Prime(post-wave) returned FAIL/BLOCKED, emit that status; otherwise emit OK.

## Step 5 — Cleanup

- **Success path** (Prime(post-wave) returned `PASS`): call `scripts/wavebus/wave-cleanup <wave-root>`. Report "bus cleaned" in the final summary.
- **Failure / abort path**: DO NOT cleanup. Leave the bus in place. Tell the user the exact wave root path so they can inspect `plan.md`, each `prompt.md`, each `results.md`, and each flight's `merge-report.md`.

## Step 6 — Final status emission (auto mode only)

When `/nextwave auto` is invoked by `/wavemachine`, the Orchestrator's **last assistant message** must be exactly one line of JSON — nothing else, no prose, no fences. `/wavemachine`'s loop parses this line to decide whether to iterate or abort.

Mapping from Prime's terminal `status` to the wavemachine-facing status:

| Prime return | Exit path | Emitted line |
|---|---|---|
| Step 4 Prime(post-wave) `PASS` | Wave merged cleanly | `{"status":"OK","wave_id":"<N>"}` |
| Step 2 Prime(pre-wave) `BLOCKED` | Wave cannot start | `{"status":"BLOCKED","wave_id":"<N>","reason":"<one-line from plan.md>"}` |
| Step 3f Prime(post-flight) `BLOCKED` | A flight rejected merge on policy grounds | `{"status":"BLOCKED","wave_id":"<N>","reason":"<one-line from merge-report.md>"}` |
| Step 3f Prime(post-flight) `FAIL` | A flight hit an unrecoverable failure (CI red, merge conflict, etc.) | `{"status":"FAIL","wave_id":"<N>","reason":"<one-line from merge-report.md>"}` |
| Step 4 Prime(post-wave) `FAIL` / `BLOCKED` | Drift / reconciliation failed after all flights merged | `{"status":"FAIL","wave_id":"<N>","reason":"<one-line from merge-report.md>"}` / `{"status":"BLOCKED","wave_id":"<N>","reason":"..."}` |

`<N>` is the wave id (e.g. `W-4`). The `reason` field is required on BLOCKED and FAIL; OK never carries a reason.

**Auto-mode approval gate fallback:** Step 3d says auto mode pauses and surfaces to the caller if `wave_ci_trust_level` drops below threshold. Treat that as BLOCKED: emit `{"status":"BLOCKED","wave_id":"<N>","reason":"ci_trust_level below threshold — manual approval required"}`.

**Interactive mode:** Do NOT emit the JSON line. Interactive `/nextwave` ends with the human-readable prompt described in Step 4 — emitting a machine-parseable line would pollute the user-facing flow.

**Ordering:** the JSON line comes AFTER the Discord announcement and the cleanup step, as the **final** assistant message of the auto-mode run. If any later output would follow (a summary table, a vox call), move it BEFORE the JSON emission.

## Flight stub prompt (template — Prime writes this into each `prompt.md`)

This prompt is what each Flight sub-agent receives. Preserve the SPEC EXECUTOR block verbatim; it is load-bearing policy from v1.

> You are a Flight agent for wave `<N>`, flight `<M>`, issue `<X>` of `<repo-slug>`.
>
> Your working directory is `<worktree-path>` (use absolute paths or `cd` into it before any git/file operations).
> Your branch is `<branch-name>` (already checked out in the worktree).
> Full instructions for this issue are at `<wave-root>/flight-<M>/issue-<X>/prompt.md` — re-read that file now; this block is only the contract for your return.
>
> **SPEC EXECUTOR rules (preserve verbatim):**
>
> - Implement EXACTLY what the issue specifies. If the spec is wrong or needs a design change, STOP and report — do NOT improvise.
> - Do NOT commit. Leave changes uncommitted.
> - CI/CD: no more than 5 lines in any `run:`/`script:` block — extract shell scripts to `scripts/ci/`. No hardcoded secrets.
> - Tests exercise REAL code paths. Mocks only for true external boundaries (network/fs/APIs). Every new function needs coverage. Assert meaningful outcomes. >2 mocks in one test = wrong approach.
> - Report: what was implemented, files, test results, review findings, AC status, concerns. Do NOT report success on failing tests or unmet AC.
>
> **After implementation, run the mechanical half of `/precheck` in the worktree:**
>
> 1. `./scripts/ci/validate.sh` (or the project's equivalent)
> 2. Project test suite
> 3. Code-reviewer agent review of your diff
> 4. AC verification — re-read the issue, walk every acceptance criterion, confirm each is met
>
> **If all mechanical checks pass, commit in your worktree:**
>
> ```
> git -C <worktree-path> add <files>
> git -C <worktree-path> commit -m "type(scope): description\n\nCloses #<X>"
> ```
>
> (Do NOT push. Prime(post-flight) pushes after Orchestrator's approval gate.)
>
> **Write your results file:**
>
> 1. Write `<wave-root>/flight-<M>/issue-<X>/results.md.partial` with: commit SHA, files changed, test results, code-reviewer findings, AC checklist status, any deferred items, any concerns.
> 2. Call `scripts/wavebus/flight-finalize <wave-root>/flight-<M>/issue-<X>/results.md.partial <PASS|FAIL>`.
>    - `PASS` if every AC is met and all mechanical checks are green.
>    - `FAIL` otherwise. `results.md.partial` must still be non-empty — explain the failure.
>
> **Your LAST message must be exactly one line — the stdout of `flight-finalize` — nothing else. No prose, no fences.** The line must match `^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$`. Anything else is a protocol violation and the Orchestrator will record this Flight as FAIL.

## Non-Negotiables

EXECUTION skill — NO design decisions. Flight sub-agents are SPEC EXECUTORS. Default to safe: latency beats broken code. Flights prevent merge conflicts; planning is cheap, conflict resolution is expensive; single-issue flights take the fast-path. **NEVER merge directly to main.** NEVER skip the pre-commit checklist. **Interactive mode: NEVER commit or push without user approval** — the approval gate in Step 3d is the one human checkpoint; do not bypass it. One wave per invocation — the user controls the pace in interactive mode; `/wavemachine` controls it in auto mode. When waiting: `wave_waiting("<reason>")`. When deferring: `wave_defer(desc, risk)` then accept after user approval. If compaction is imminent: `/cryo` first — the task list survives. Pair: `/prepwaves` plans, `/nextwave` executes, `/wavemachine` drives the loop.
