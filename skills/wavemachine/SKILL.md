---
name: wavemachine
description: Autopilot for wave-pattern execution. Spawns a background sub-agent that runs /nextwave in a loop, using wave_health_check as a circuit breaker. Stops at the first sniff of trouble. One plan at a time.
---

# Wavemachine — Autopilot for Wave-Pattern Execution

Wavemachine is a **dumb repeater with a circuit breaker**. It runs the `/nextwave` loop autonomously in a background sub-agent, advancing through a multi-wave plan on the happy path, and aborts cleanly at the first sniff of trouble. The sophistication lives in the tools it calls — `/nextwave` does the real work, `wave_health_check()` decides whether to continue.

**Mental model (compiling natural language):** issue specs are source; planning/execution sub-agents are the compiler; MCP tools are the runtime; **wavemachine is `make all` for the wave-pattern compiler.** It exists so the human can work on the next epic while the current epic grinds through the happy path in the background.

## Tools Used

- `mcp__sdlc-server__wave_show` — read current wave state (pre-flight checks, progress monitoring)
- `mcp__sdlc-server__wave_previous_merged` — verify prior wave's work is on main
- `mcp__sdlc-server__wave_next_pending` — identify what remains
- `mcp__sdlc-server__wave_health_check` — the circuit breaker; structured blocker report between iterations
- `mcp__sdlc-server__wave_ci_trust_level` — detect whether the platform guarantees pre-merge CI equals post-merge CI
- `mcp__sdlc-server__wave_waiting` — mark the plan as paused with a reason on abort
- `mcp__disc-server__disc_send` — post status updates to `#wave-status` (`1487386934094462986`)
- The Agent tool with `run_in_background: true` — spawn the background loop worker

## Pre-Flight Checks (refuse to start on failure)

Before spawning anything:

1. **Plan exists.** Call `wave_show()`. If it returns no state / empty state, refuse: "No wave plan exists. Run `/prepwaves <epic>` first."
2. **No other wave active.** Inspect `wave_show()`'s output — if `action` is `in-flight`, `planning`, or any active state, refuse: "Wave <id> is already active (action: <X>). Let it finish or clear state before starting wavemachine."
3. **Base branch clean.** `git status --porcelain` returns nothing on the configured base branch. Any untracked/modified files → refuse and list them.
4. **Previous wave merged.** Call `wave_previous_merged()`. If the prior wave's work is not on main, refuse.
5. **At least one pending wave remains.** Call `wave_next_pending()`. If null, refuse: "No pending waves. Plan is complete — run `/dod` to verify."
6. **No concurrent wavemachine.** Read `.claude/status/state.json` — if `wavemachine_active` is already `true`, refuse: "Wavemachine is already running in this project. Wait for it to complete or abort first."

On any refusal: explain the failure, suggest the remediation, **do not spawn**.

## Launch Sequence

Once pre-flight passes:

1. **Set the active flag.** Run `python3 -m wave_status wavemachine-start --launcher main` to stamp `wavemachine_active: true` into `state.json` (plus `wavemachine_started_at` and `wavemachine_launcher`). This is the signal the statusline 🌊 indicator reads, and the CLI guarantees atomic writes via `save_json`. Do **not** `Edit` `state.json` directly — the harness denies direct writes to `.claude/status/**` from background sub-agents, so all flag transitions must flow through this CLI for parity.
2. **Regenerate and open the status panel.** Run `./scripts/generate-status-panel` then open `.status-panel.html` with `xdg-open` (Linux) or `open` (macOS). This happens here — not inside the background worker — so it costs zero sub-agent tokens and guarantees the panel is visible before work begins.
3. **Detect CI trust.** Call `wave_ci_trust_level()` once and cache the result for the background worker. Drives whether `wave_health_check()` treats post-merge main CI as a separate gate.
4. **Post to Discord.** `disc_send` to `#wave-status` (`1487386934094462986`): `"🌊 **Wavemachine started** — <project>, <N> waves pending. Agent: **<dev-name>** <dev-avatar>"`. Resolve identity from `/tmp/claude-agent-<md5>.json`. If `disc_send` fails, log and continue — Discord is informational, not a gate.
5. **Spawn the background worker** via the Agent tool with `run_in_background: true` and the prompt template below. Capture the returned task ID.
6. **Report to the user:** "Wavemachine launched (task `<task_id>`). Background agent will run the wave loop until the plan completes or a blocker is hit. Statusline 🌊 indicator is live. Status panel is open in your browser. Main session stays conversational — ask me anything or `wave_show()` to monitor."
7. **Return control to the main session.** You do NOT poll the background agent. It reports back when it finishes or aborts.

## Background Worker Prompt Template

```
You are a WAVEMACHINE WORKER. Your job is to run the wave-pattern execution loop
autonomously and stop at the first problem.

## The Loop

Repeat until exit condition:

1. Run `/nextwave` for the current pending wave. This handles pre-flight, planning,
   flight execution, commit/push/merge, drift check, and wave_complete internally.
   Follow the /nextwave skill as written — do not skip its pre-commit checklist.

2. After /nextwave reports the wave is complete, call `wave_health_check()`.

3. Evaluate the response:
   - `safe_to_proceed: true` and another wave is pending → go to step 1
   - `safe_to_proceed: true` and no more waves → exit cleanly (plan complete)
   - `safe_to_proceed: false` → abort, report blockers, exit

## Commit Approval

For the pre-commit checklist /nextwave presents per agent:
- Present the full checklist (mandatory — do not skip)
- If the checklist is clean (no high+ review findings, no test failures, no CI issues,
  no deferrals), auto-approve and proceed
- If ANY item on the checklist is failing, STOP and abort (do not commit)

This is Option B from the design: the checklist IS the approval gate; auto-approval
is just "nothing in the report is above the abort threshold."

## CI Wait Policy

Block on green CI before merging each PR. The merge queue guarantees post-merge CI
equals pre-merge CI on platforms where `wave_ci_trust_level()` returned `trust`,
so the wait is bounded. Do not merge on pending or failing checks.

## Abort Threshold (any one of these stops the loop)

- Any deferral recorded in this wave
- Any drift (stale OR broken) detected at wave boundary
- Any test failure in any flight
- Any CI non-success (failure, cancellation, timeout)
- On platforms without pre-merge CI trust: any main-branch CI failure after merge
- Any merge conflict
- Any explicit agent escalation (a sub-agent refusing to resolve a design concern)

NOT on the abort list:
- Code review findings of any severity — these are normal software development.
  The parent-agent review gate already fixes high+ findings in the worktree or
  defers them with user approval (deferrals DO abort). Stopping on every medium+
  code review finding would make wavemachine useless.
- Commutativity verification returning WEAK/ORACLE_REQUIRED — this triggers
  sequential merge via merge queue (safe fallback), not an abort. Only an actual
  merge conflict or CI failure during sequential merge would abort.

## On Abort

1. Call `wave_waiting("wavemachine aborted: <one-line summary>")` to mark the plan
   as awaiting human attention.
2. Run `python3 -m wave_status wavemachine-stop` to clear `wavemachine_active`,
   `wavemachine_started_at`, and `wavemachine_launcher` (clears the 🌊 indicator).
   Use the CLI — background sub-agents cannot write `.claude/status/state.json`
   directly. `wavemachine-stop` is idempotent, so running it on an already-cleared
   state is safe.
3. Post to `#wave-status` (`1487386934094462986`): `"🛑 **Wavemachine aborted** —
   <project>, wave <id>: <one-line blocker summary>. Agent: **<dev-name>** <dev-avatar>"`.
4. Report to the parent session with a structured summary:
   - Which wave was running when you aborted
   - The full blocker list from wave_health_check (types + details)
   - What was merged successfully before the abort
   - What the human needs to do to resume

## On Clean Completion

1. Run `python3 -m wave_status wavemachine-stop` to clear `wavemachine_active`
   (via CLI — background sub-agents cannot write state files directly).
2. Post to `#wave-status` (`1487386934094462986`): `"✅ **Wavemachine complete** —
   <project>, all <N> waves merged. Run /dod to verify. Agent: **<dev-name>** <dev-avatar>"`.
3. Report to the parent session:
   - All waves in the plan executed
   - Summary of what was merged across the run
   - Suggest running `/dod` for final project verification
```

## Monitoring From the Main Session

While wavemachine runs:
- Call `wave_show()` to see live progress
- Read `.status-panel.html` in a browser (opened during launch sequence)
- Watch Discord `#agent-ops` if the background worker is signed in there
- Check the statusline for the 🌊 indicator (disappears on completion/abort)

Do not attempt to spawn another wavemachine. Do not attempt to run `/nextwave` manually. The background worker owns the wave lifecycle for this plan until it exits.

## Blocker Types and What Each Means

When wavemachine aborts, the `wave_health_check()` response lists one or more blocker types. Each indicates what the human needs to do next:

- **`deferral`** — a sub-agent deferred an item; review the deferral, accept or implement, re-run `/wavemachine`
- **`drift_stale`** — a later wave's spec references file paths or symbols that have been renamed/moved; update the issue and re-run
- **`drift_broken`** — a later wave's spec is fundamentally incompatible with the post-merge codebase; rewrite, descope, or split the issue
- **`test_failure`** — a flight's test suite failed; fix the implementation or the test, re-run
- **`ci_failure`** — a PR's CI checks failed; diagnose via the run logs, fix, re-run
- **`main_ci_failure`** — (only on low-trust platforms) main went red after a merge; revert or forward-fix
- **`merge_conflict`** — a PR could not be merged automatically; rebase and re-run
- **`explicit_escalation`** — a sub-agent refused to resolve a design-level concern unilaterally; discuss with the user, update the spec, re-run

## Resuming After an Abort

Wave-status persistence means work picks up from where it stopped. Re-invoke `/wavemachine` after the blocker is resolved; the background worker will see the persisted state and continue from the next pending wave.

## Design Notes (v1 locked decisions)

- **Commit approval flow:** Option B — present checklist, auto-approve if clean. Audit trail preserved.
- **CI wait:** block on green. Safety over speed.
- **Pause vs abort:** abort on any blocker. Simpler state machine; resume by re-running `/wavemachine`.
- **Concurrency:** one plan at a time, no concurrent wave sessions.
- **Execution model:** background Agent with `run_in_background: true`. The worker is a CHILD of the main session — if the main session exits, the worker dies. Acceptable for v1; v2 will add truly detached execution via `setsid`.
- **Code review findings** are NOT in the abort list for v1. V2 will add `architectural_concern` classification.

## Non-Negotiables

- **One plan at a time.** Refuse to start if another wavemachine is active or another wave is in-flight.
- **Never `--admin` merge.** Wavemachine uses the merge queue exclusively; if the queue rejects, the worker aborts.
- **Never skip the pre-commit checklist.** Option B means auto-approving a CLEAN checklist, not skipping it.
- **Always clear the `wavemachine_active` flag** on exit (completion, abort, or crash). The statusline 🌊 indicator must always reflect reality.
- **Block on green CI.** Never merge on pending or failing checks.
- **Structured blocker report on abort.** Vague "something went wrong" is unacceptable — the report must let the human resume without spelunking.

## Pair

- `/prepwaves` plans the waves
- `/nextwave` executes one wave interactively
- **`/wavemachine` executes the whole plan autonomously**
- `/dod` verifies the project at the end
