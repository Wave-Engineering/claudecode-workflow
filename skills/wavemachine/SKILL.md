---
name: wavemachine
description: Autopilot for wave-pattern execution. Runs a top-level loop that calls /nextwave auto per pending wave, guarded by wave_health_check as a circuit breaker. Stops at the first sniff of trouble. One plan at a time.
---

# Wavemachine — Autopilot for Wave-Pattern Execution

`/wavemachine` is the **Orchestrator-level autopilot** for a multi-wave plan. It runs in the top-level session (where `Agent` lives) as a simple loop: check health, pick the next pending wave, delegate that single wave to `/nextwave auto`, parse the result, repeat. The sophistication lives in the primitives — `/nextwave` does the real per-wave work, `wave_health_check()` decides whether to continue, the user controls when to interrupt.

**Mental model (compiling natural language):** issue specs are source; planning/execution sub-agents are the compiler; MCP tools are the runtime; **wavemachine is `make all` for the wave-pattern compiler.** It exists so the human can hand off a vetted multi-wave plan and get back a merged epic — or a single clean blocker report when something breaks.

**Why the loop runs in the top-level session (v2 shape):** CC sub-agents do NOT have the `Agent` tool. v1 spawned the wave loop in a background Agent sub-agent, so every `/nextwave` call inside it collapsed to serial execution — the parallel Flight spawn that makes a wave fast was silently lost. v2 keeps the loop *here*, at the top level, where Agent lives and `/nextwave auto` can spawn its parallel Flights properly. There is no background worker. See `decision_wavemachine_v2.md` and `lesson_cc_subagent_tools.md`.

## Tools Used

- `mcp__sdlc-server__wave_health_check` — circuit breaker; called before every iteration
- `mcp__sdlc-server__wave_next_pending` — identifies the next pending wave; loop exits when this returns null
- `mcp__sdlc-server__wave_show` — pre-flight state inspection; also reads `kahuna_branch` for bootstrap and gate
- `mcp__sdlc-server__wave_init` — pre-wave kahuna bootstrap (creates `kahuna/<epic_id>-<slug>` once per epic)
- `mcp__sdlc-server__wave_finalize` — opens kahuna→main MR at epic completion
- `mcp__sdlc-server__commutativity_verify` — trust-score signal; runs concurrently with the other three (R-23)
- `mcp__sdlc-server__ci_wait_run` — trust-score signal; waits for CI on the kahuna branch
- `mcp__sdlc-server__pr_merge` — auto-merge kahuna→main on all-green gate, with `skip_train: true`
- `mcp__sdlc-server__wave_previous_merged` — pre-flight verification that prior wave is on main
- `mcp__sdlc-server__wave_ci_trust_level` — cached by `/nextwave auto` for its internal gate decisions
- `mcp__sdlc-server__wave_waiting` — mark the plan paused with a human-readable reason on any abort
- `mcp__disc-server__disc_send` — announce to `#wave-status` (`1487386934094462986`) on start, completion, abort, gate pass/block
- The `Agent` tool — invoked AT THE GATE only, for the `feature-dev:code-reviewer` trust signal (one of four concurrent signals). The loop body itself never spawns Agents — `/nextwave auto` owns wave-internal Agent spawning.
- The `Bash` tool — invoked AT THE GATE for the `trivy fs` dependency scan trust signal.
- The Skill tool — invokes `/nextwave auto` per iteration (the one place wave work is delegated)
- `ScheduleWakeup` — OPTIONAL, fallback-only, used when a merge-queue idle is detected (not the primary execution model)

**Not used in the loop body:** wave-internal `Agent` spawning is owned by `/nextwave` — the loop body itself never spawns sub-agents per iteration. The single exception is the gate's `feature-dev:code-reviewer` Agent at epic completion (one of four concurrent trust signals — see "Trust-Score Gate and Auto-Merge"). Background Agent invocation is NEVER used anywhere in this skill; the loop and the gate both run synchronously in the top-level session.

## Pre-Flight Checks (refuse to start on failure)

Before entering the loop:

1. **Plan exists.** Call `wave_show()`. If it returns no state / empty state, refuse: "No wave plan exists. Run `/prepwaves <epic>` first."
2. **No other wave active.** Inspect `wave_show()`'s output — if `action` is `in-flight`, `planning`, or any active state, refuse: "Wave <id> is already active (action: <X>). Let it finish or clear state before starting wavemachine."
3. **Base branch clean.** `git status --porcelain` returns nothing on the configured base branch. Any untracked/modified files → refuse and list them.
4. **Previous wave merged.** Call `wave_previous_merged()`. If the prior wave's work is not on main, refuse.
5. **At least one pending wave remains.** Call `wave_next_pending()`. If null, refuse: "No pending waves. Plan is complete — run `/dod` to verify."
6. **No concurrent wavemachine.** Read `.claude/status/state.json` — if `wavemachine_active` is already `true`, refuse: "Wavemachine is already running in this project. Wait for it to complete or abort first."

On any refusal: explain the failure, suggest the remediation, **do not enter the loop**.

## Status Flag — Set on Entry, Unset on EVERY Exit Path

The `wavemachine_active` flag in `.claude/status/state.json` is the signal the statusline 🌊 indicator reads. v1's most common failure mode was leaving this flag set after an abort, so the indicator lied about whether autopilot was still running. v2 treats flag discipline as a non-negotiable.

**On entry (after pre-flight passes, before the first iteration):**

```
python3 -m wave_status wavemachine-start --launcher main
```

Writes `wavemachine_active: true`, `wavemachine_started_at`, and `wavemachine_launcher=main` into `state.json`. The CLI guarantees atomic writes via `save_json`. Do **not** `Edit` `state.json` directly — always go through this CLI.

**On EVERY exit path (happy completion, circuit breaker trip, per-wave BLOCKED/FAIL, user interrupt, tool denial, unexpected error):**

```
python3 -m wave_status wavemachine-stop
```

Clears `wavemachine_active` and the related metadata. Idempotent — safe to call even if already cleared. Treat this as a `finally` clause around the whole loop: no codepath out of `/wavemachine` may skip it.

## Launch Sequence (before the loop starts)

Once pre-flight passes:

1. **Set the active flag** (see above).
2. **Regenerate and open the status panel.** Run `./scripts/generate-status-panel`, then open `.status-panel.html` with `xdg-open` (Linux) or `open` (macOS). The panel is visible before work begins and updates as waves land.
3. **Detect CI trust** by calling `wave_ci_trust_level()` once. (The value is also cached by each `/nextwave auto` iteration; calling it here is informational — it shapes the start announcement.)
4. **Pre-wave kahuna bootstrap** (see "Pre-Wave Kahuna Bootstrap" below). Runs exactly once per epic on first `/wavemachine` invocation. On resume invocations the wave state already carries `kahuna_branch` and this step is a no-op.
5. **Post to Discord.** `disc_send` to `#wave-status` (`1487386934094462986`): `"🌊 **Wavemachine started** — <project>, <N> waves pending. Agent: **<dev-name>** <dev-avatar>"`. Resolve identity from `/tmp/claude-agent-<md5>.json`. If `disc_send` fails, log and continue — Discord is informational, not a gate.
6. **Emit observability event.** `scripts/mcp-log wavemachine_start epic=<epic_id> waves=<N> kahuna=<kahuna_branch>` — timestamps autopilot start in the fleet logfile so post-mortem can correlate with sdlc-server tool_call events.

## Pre-Wave Kahuna Bootstrap

**When this runs:** once per epic, during the launch sequence (step 4 above), BEFORE the loop's first iteration. This is the kahuna sandbox setup step group from Dev Spec §5.2.2 ("New step group — pre-wave kahuna bootstrap").

**Procedure:**

1. Read wave state via `wave_show()`. Inspect the `kahuna_branch` field.
2. **If `kahuna_branch` is present and non-empty:** SKIP — this is the resume path (Procedure D, §4.4.5). The kahuna branch already exists on the platform and in wave state; do nothing and continue to step 5 of the launch sequence.
3. **If `kahuna_branch` is absent or empty:** invoke `wave_init` with the `kahuna: { epic_id, slug }` argument, where:
   - `epic_id` is the master/epic issue number for the current plan (read from wave state's plan metadata).
   - `slug` is a human-readable kebab-case slug derived from the epic title (the same slug computation `wave_init` already documents).
   `wave_init` creates `kahuna/<epic_id>-<slug>` off the current main head, writes the branch name into wave state's `kahuna_branch` field, and returns success. (See Dev Spec §5.1.3 for the tool contract.)
4. **Emit the bootstrap notification.** `disc_send` to `#wave-status` (`1487386934094462986`):
   `"🏝 **Kahuna sandbox created** — <project>, epic #<epic_id>, branch `<kahuna_branch>`. Agent: **<dev-name>** <dev-avatar>"`. If `disc_send` fails, log and continue — Discord is informational.

**Idempotency.** This step is idempotent by design: the `kahuna_branch` field is the marker. A second `/wavemachine` invocation on the same epic will see the field populated in step 1 and skip creation. This is the foundation for Procedure D crash-recovery.

**Cross-reference.** Dev Spec §5.2.2 (gate behavior) and §5.1.3 (`wave_init` kahuna extension).

## The Loop (this is the whole skill; no background worker)

The loop runs in THIS session — the top-level Orchestrator session. Repeat until an exit condition fires:

```
loop:
  1. health = wave_health_check()
     if health.status != "HEALTHY":
         announce abort (see "On Circuit-Breaker Trip")
         python3 -m wave_status wavemachine-stop
         exit loop

  2. next = wave_next_pending()
     if next is None:
         # All waves merged — run the trust-score gate before announcing
         # completion. KAHUNA mode (kahuna_branch present in wave state):
         # invoke the gate step group below. Legacy mode (no kahuna_branch):
         # skip the gate, announce completion as before.
         run "Trust-Score Gate and Auto-Merge" step group
         (gate result determines completion vs gate_blocked exit; either
          branch unsets wavemachine_active and exits the loop)
         exit loop

  3. Invoke /nextwave auto
     (one Skill invocation, in this session. /nextwave auto owns the
      Orchestrator/Prime/Flight protocol for the single wave it executes.
      This is the ONE place /wavemachine delegates work.)

  4. Parse the last assistant message from /nextwave auto for the canonical
     status JSON:
         {"status": "OK" | "BLOCKED" | "FAIL", "wave_id": "<id>", ...}

     - "OK"      → wave landed, loop back to step 1
     - "BLOCKED" → stop; announce abort with the blocker detail
     - "FAIL"    → stop; announce abort with the failure detail
     - malformed / missing → treat as FAIL ("malformed /nextwave return"); stop

  5. (optional, fallback only) If a merge-queue-idle signal is detected in
     step 3's result and the wait is non-trivial, schedule a wakeup and
     resume the loop on the next firing. Only used as a fallback — the
     primary execution model is a tight synchronous loop.
```

The loop exits cleanly when any of the following happens:

- `wave_next_pending()` returns null (all waves merged — happy completion)
- `wave_health_check()` returns a non-HEALTHY status (circuit breaker trips)
- `/nextwave auto` returns BLOCKED or FAIL (per-wave abort)
- The user interrupts (Ctrl+C or tool-denial mid-wave — see "Interrupt Handling")

## Trust-Score Gate and Auto-Merge

**When this runs:** exactly once per epic, at the loop's clean-completion path — after `wave_next_pending()` returns null and §7 Definition-of-Done checks pass. This replaces the v1 "On clean completion" simple announcement with the autonomous gate evaluation specified in Dev Spec §5.2.2 ("New step group — trust-score gate and auto-merge").

**Legacy short-circuit.** If wave state has no `kahuna_branch` (legacy non-KAHUNA execution), skip this entire step group and fall through to the "On Clean Completion" announcement below — there is no kahuna→main MR to gate. This preserves backward compatibility with non-KAHUNA plans.

### Gate procedure (KAHUNA mode only)

1. **Run §7 Definition-of-Done checks.** Test suites, VRTM updates, etc. (See Dev Spec §7 for the full checklist.) If any DoD check fails, transition `action` → `gate_blocked` with the DoD failure recorded; emit notifications per Procedure C; preserve the kahuna branch; exit the loop. DoD failure short-circuits the gate before we open the kahuna→main MR.
2. **Invoke `wave_finalize`.** Opens the kahuna→main MR with an auto-assembled body derived from wavebus artifacts (one bullet per flight, linking the original flight MRs into kahuna). `wave_finalize` is idempotent: if an open kahuna→main MR already exists (resume path / Procedure D), it is reused (`created: false`). Capture the returned MR number.
3. **Transition wave state `action` → `gate_evaluating`.** This is the marker the wave-status CLI and dashboard read to render the trust-signal summary block (§5.2.5). It is also the marker Procedure D uses to detect a crashed-mid-gate session and re-enter idempotently (see "Procedure D — re-entry at the gate" below).
4. **Invoke the four trust signals CONCURRENTLY (R-23).** This is a HARD requirement. All four signals MUST be issued in a **single tool-use block** — no signal sequenced behind another in the happy path. The wave-pattern parallelism pattern (one assistant message containing four parallel tool calls) applies here. The four signals are:

   - **`commutativity_verify`** — `commutativity_verify(base_ref="main", changesets=[{id: "kahuna", head_ref: <kahuna_branch>}])`. Returns a verdict envelope (see "PROBE_UNAVAILABLE handling" below for the envelope shapes).
   - **`ci_wait_run`** — `ci_wait_run(ref=<kahuna_branch>, timeout_sec=1800)`. Waits for the latest CI run on the kahuna branch to settle (success/failure/cancelled).
   - **Code-reviewer Agent** — `Agent(subagent_type="feature-dev:code-reviewer", prompt=<composed diff over the full kahuna-vs-main range>)`. Returns a structured review with severity-tagged findings.
   - **Trivy dependency scan** — `Bash("trivy fs --scanners vuln --severity HIGH,CRITICAL --format json --quiet <repo_path>")`. Returns JSON with any HIGH/CRITICAL vulnerability findings (with available fixes).

   These four calls run concurrently in a single tool-use block. **Do NOT short-circuit** when one signal fails — collect all four results before evaluating the gate (per Procedure C, §4.4.4). The operator needs the complete signal set to triage a blocked gate.

5. **Evaluate the gate.** Each signal is classified pass/fail per Procedure C:
   - `commutativity_verify`: pass = verdict ∈ {`STRONG`, `MEDIUM`}; fail = verdict ∈ {`WEAK`, `ORACLE_REQUIRED`, `PROBE_UNAVAILABLE`}.
   - `ci_wait_run`: pass = `final_status == "success"`; fail otherwise.
   - Code-reviewer: pass = no critical or important findings; fail = one or more critical/important findings.
   - Trivy: pass = no HIGH/CRITICAL findings with available fixes; fail otherwise.

6. **All-green path** (every signal passes):
   - Invoke `pr_merge({number: <kahuna_mr_number>, skip_train: true, squash_message: <assembled body from step 2>})`. `skip_train: true` is required because the kahuna→main MR has already been gated by the four signals — bypassing the project's standard merge train is the whole point of the autonomous gate.
   - **Record disposition** in wave state's `kahuna_branches` history array: append `{branch: <kahuna_branch>, epic_id: <epic_id>, disposition: "merged", merged_at: <iso8601>, mr_number: <kahuna_mr_number>}`. (Schema per §5.1.)
   - **Delete the kahuna branch** from the platform (per R-03). On GitHub: `gh api -X DELETE repos/<owner>/<repo>/git/refs/heads/<kahuna_branch>` (or equivalent). On GitLab: `glab api -X DELETE projects/:id/repository/branches/<kahuna_branch_url_encoded>`.
   - **Emit `#wave-status` notification** (R-19): `"✅ **Kahuna gate passed** — <project>, epic #<epic_id> auto-merged to main. <N> flights, <M> commits. Agent: **<dev-name>** <dev-avatar>"`.
   - **Vox announcement** (conversational, brief): name, team, project, "kahuna gate passed, epic merged to main".
   - Then fall through to the standard "On Clean Completion" announcement and `wave_status wavemachine-stop`.

7. **Any-red path** (one or more signals fail):
   - Transition wave state `action` → `gate_blocked`, recording each failing signal's name + detail payload (so the dashboard's signal-failure detail block can render — §5.2.5).
   - **Preserve the kahuna branch** (per Procedure C). Do NOT delete it. Do NOT merge the kahuna→main MR. The MR stays open for human review.
   - **Emit `#wave-status` notification** per Procedure C, §4.4.4: epic name, each failing signal's name + short detail, kahuna branch name, the open kahuna→main MR URL.
   - **Vox announcement**: "Kahuna gate blocked for epic <epic_id>. <N> signals red. Ready for your review."
   - Call `wave_waiting("kahuna gate blocked: <one-line summary>")` so the plan is explicitly marked paused.
   - `wave_status wavemachine-stop` and exit the loop.

### PROBE_UNAVAILABLE handling

`commutativity_verify` may return one of two outer envelope shapes (cross-server contract documented in `mcp-server-sdlc#218`):

- **Probe present:** `{ok: true, verdict: "STRONG" | "MEDIUM" | "WEAK" | "ORACLE_REQUIRED", ...}`.
- **Probe missing:** `{ok: true, verdict: "PROBE_UNAVAILABLE", warnings: [...]}`. This is a **synthesized verdict** the sdlc-server emits when the `commutativity-probe` binary is not installed in the runtime environment. It is NOT a probe-side classification — it is a graceful-degradation marker.

**Treatment in the gate:** `PROBE_UNAVAILABLE` is **conservative-fail** — equivalent to `ORACLE_REQUIRED`. The gate MUST NOT auto-merge when the commutativity signal is unavailable. This is a deliberate cross-server contract: when we cannot verify commutativity, we refuse to grant the auto-merge privilege the gate normally extends. The any-red path applies; the operator triages by either installing the probe binary and re-running `/wavemachine` (which re-enters at the gate via Procedure D) or merging the kahuna→main MR manually after review.

Document the treatment explicitly so future readers see it: the four-signal gate is a *unanimous* gate, and an unavailable signal is treated identically to a red signal.

### Procedure D — re-entry at the gate

When `/wavemachine` is restarted (Orchestrator crash, user Ctrl-C mid-gate, etc.) and the pre-flight pass discovers wave state `action == gate_evaluating`, the loop driver MUST re-invoke this entire gate step group from step 4 onward. The four signals are **pure reads** (or are guarded by upstream idempotency: `wave_finalize` reuses an existing open MR; `pr_merge` is idempotent per the tool's own contract) — re-invoking them is safe.

The crash-recovery contract (per Dev Spec §4.4.5):
- `wave_finalize` from step 2 is already idempotent — calling it again returns the existing MR number with `created: false`.
- The four-signal block in step 4 is re-issued in a single tool-use block; results may differ from the prior attempt (e.g. CI now green where it was timing out before), and that is the desired behavior — the gate evaluates current truth.
- `pr_merge` from step 6 returns success on an already-merged PR.

The re-entry path is therefore: detect `gate_evaluating`, jump to step 4, run the gate to completion. Document this so the loop driver knows the gate is safe to retry.

**Cross-reference.** Dev Spec §5.2.2 (gate behavior), §4.4.4 (Procedure C — gate signal failure), §4.4.5 (Procedure D — orchestrator crash mid-epic), §7 (Definition of Done), R-23 (concurrency requirement), R-19 (notification requirement), R-03 (kahuna branch deletion on success).

## Circuit Breaker — `wave_health_check`

`wave_health_check()` is called **before every iteration**, including the first (so a broken starting state is caught before any work). It returns a structured health report. `/wavemachine` treats anything other than `HEALTHY` as a stop signal:

- The server classifies back-to-back failures, CI red-streaks, rate-limit signals, and other degraded-environment cues.
- `/wavemachine` does not second-guess the classification — it simply exits cleanly and surfaces the summary to the user.

This is the "first sniff of trouble" guard. It complements `/nextwave auto`'s own per-wave abort logic: `/nextwave` catches *this wave's* problems; `wave_health_check` catches *cross-wave* or *environmental* problems that would make the next wave unsafe to run.

## Interrupt Handling

Users can stop `/wavemachine` three ways:

1. **Ctrl+C** between iterations → the loop returns to user control naturally.
2. **Tool denial** on a tool call inside `/nextwave auto` → the invocation returns with an aborted tool-call marker; `/wavemachine` treats that as FAIL and stops.
3. **Ctrl+C mid-wave** → the in-flight `/nextwave auto` invocation is interrupted; control returns to `/wavemachine`.

In every interrupt case:

- Run `python3 -m wave_status wavemachine-stop` immediately to clear the flag (the statusline must match reality).
- **Leave the in-flight wave's bus tree in place** (`/tmp/wavemachine/<repo-slug>/wave-<N>/`). Do NOT call `wave-cleanup` on an interrupted wave — the partial state is forensic evidence for the human.
- Announce the interrupt to `#wave-status` (`1487386934094462986`): `"⏸ **Wavemachine interrupted** — <project>, wave <id> mid-flight, bus preserved at <path>. Agent: **<dev-name>** <dev-avatar>"`.
- Report to the user: which wave was interrupted, the bus root path, what was merged successfully before the interrupt, how to resume (re-run `/wavemachine` after reviewing the bus).

## Announcements (Discord + vox)

Preserve the v1 announcement surface — one Discord post per lifecycle event, optional vox on the terminal ones:

**On loop start** (see "Launch Sequence" above):

- Discord `#wave-status`: `"🌊 **Wavemachine started** — <project>, <N> waves pending. Agent: **<dev-name>** <dev-avatar>"`

**On clean completion** (`wave_next_pending()` returned null AND, in KAHUNA mode, the trust-score gate passed all-green):

- This announcement runs AFTER the trust-score gate's all-green path (see "Trust-Score Gate and Auto-Merge"). In KAHUNA mode, the gate has already auto-merged kahuna→main and posted its own `✅ **Kahuna gate passed**` notification — this announcement closes out the wavemachine session.
- In legacy non-KAHUNA mode (no `kahuna_branch` in wave state), the gate is skipped and this announcement runs directly when `wave_next_pending()` returns null.
- Discord `#wave-status`: `"✅ **Wavemachine complete** — <project>, all <N> waves merged. Run /dod to verify. Agent: **<dev-name>** <dev-avatar>"`
- `scripts/mcp-log wavemachine_complete epic=<epic_id> status=OK waves_merged=<N>`
- Vox (conversational, brief): name, team, project, "wavemachine complete, all waves merged".

**On gate-blocked completion** (KAHUNA mode, one or more trust signals failed):

- Per Procedure C / "Trust-Score Gate and Auto-Merge" any-red path: `"🛑 **Kahuna gate blocked** — <project>, epic #<epic_id>: <failing-signals summary>. MR <url> open for review. Agent: **<dev-name>** <dev-avatar>"`
- Vox alert: "Kahuna gate blocked for epic <epic_id>. <N> signals red. Ready for your review."
- `scripts/mcp-log --level warn wavemachine_complete epic=<epic_id> status=BLOCKED reason="kahuna gate blocked: <signals>"`
- `wave_waiting("kahuna gate blocked: <one-line summary>")` so the plan is explicitly marked paused.

**On circuit-breaker trip** (`wave_health_check` non-HEALTHY):

- Discord `#wave-status`: `"🛑 **Wavemachine aborted (circuit breaker)** — <project>: <one-line health summary>. Agent: **<dev-name>** <dev-avatar>"`
- `scripts/mcp-log --level error wavemachine_complete epic=<epic_id> status=ABORTED reason="circuit breaker: <summary>"`
- Call `wave_waiting("wavemachine aborted (circuit breaker): <one-line summary>")` so the plan is explicitly marked paused.

**On per-wave BLOCKED or FAIL** (from `/nextwave auto` return):

- Discord `#wave-status`: `"🛑 **Wavemachine aborted** — <project>, wave <id>: <one-line failure summary>. Agent: **<dev-name>** <dev-avatar>"`
- `scripts/mcp-log --level error wavemachine_complete epic=<epic_id> status=ABORTED wave=<id> reason="<summary>"`
- Call `wave_waiting("wavemachine aborted: <one-line summary>")`.

**On user interrupt** (see "Interrupt Handling" above).

All announcements are informational — if `disc_send` fails, log and continue; Discord is never a gate.

## Optional: ScheduleWakeup fallback

When a merge-queue-idle scenario is detected (a wave merged but the queue is churning and the next one cannot start cleanly), the loop MAY use `ScheduleWakeup` to back off rather than busy-loop. This is **not the primary execution model** — the default is a tight synchronous loop calling `/nextwave auto` back-to-back. Use wakeup only when:

- A `/nextwave auto` result indicates a bounded wait is needed (e.g. the merge queue reported pending state at the end).
- The wait is long enough (several minutes) that holding the session occupied is wasteful.

When waking up, re-enter the loop at step 1 (re-run `wave_health_check` from scratch).

## Non-Negotiables

- **One plan at a time.** Pre-flight refuses to start if another wavemachine is active or another wave is in-flight.
- **`wavemachine_active` flag must always reflect reality.** Set on entry via `wave_status wavemachine-start`; unset on EVERY exit path via `wave_status wavemachine-stop`. No `Edit` to `state.json`. The statusline 🌊 indicator is not allowed to lie.
- **NEVER run the loop in a background sub-agent.** No background Agent invocation, ever — not with the `run_in_background` parameter, not shelled out, not via any other escape hatch. The loop is top-level, period. (The gate's `feature-dev:code-reviewer` Agent runs *synchronously* at the top level — not in the background.)
- **NEVER spawn Flights or Prime directly.** `/nextwave auto` owns the Orchestrator/Prime/Flight protocol for each wave — `/wavemachine` only delegates wave work to it.
- **Circuit breaker before every iteration.** `wave_health_check` is called at the TOP of each loop iteration, not just the first.
- **Leave the bus alone on abort.** On any non-happy exit, the in-flight wave's bus tree stays on disk for forensics. `wave-cleanup` runs only on PASS, inside `/nextwave auto`.
- **Block on green CI.** `/nextwave auto` handles the per-wave CI gate; `/wavemachine` does not merge wave PRs directly and does not fast-path around it. The kahuna→main MR is the *only* PR `/wavemachine` merges, and only after the four-signal gate passes all-green.
- **R-23 — gate signals run concurrently in a single tool-use block.** The four trust signals (`commutativity_verify`, `ci_wait_run`, `feature-dev:code-reviewer` Agent, `trivy` Bash) MUST be issued in a single tool-use block — no signal sequenced behind another. Sequencing them silently would inflate the gate's wall-clock cost by ~4x and is a hard regression to catch in tests.
- **Do not short-circuit the gate.** Collect all four signal results before evaluating pass/fail (Procedure C, §4.4.4). The operator needs the complete signal set to triage a blocked gate.
- **`PROBE_UNAVAILABLE` is conservative-fail.** When `commutativity_verify` returns the synthesized `PROBE_UNAVAILABLE` verdict (probe binary not installed; cross-server contract per `mcp-server-sdlc#218`), the gate treats it identically to `ORACLE_REQUIRED` — no auto-merge. Document this so it cannot be silently relaxed.
- **Gate re-entry is idempotent.** Procedure D: a `/wavemachine` restart that finds wave state in `gate_evaluating` MUST re-invoke the four signals. They are pure reads (or upstream-idempotent) — safe to retry. Do not assume crash-mid-gate is unrecoverable.
- **Structured blocker report on any abort.** Vague "something went wrong" is unacceptable — the Discord announcement + the session report must name the wave (or the failing signals, at the gate), the blocker type, and the remediation path.

## Resuming After an Abort

Wave state is persistent on disk (`.claude/status/state.json` + the bus tree). When the blocker is resolved, simply re-invoke `/wavemachine`. The pre-flight checks validate the new starting state; the loop picks up from the next pending wave.

**Resuming at the gate (Procedure D, §4.4.5).** If the prior `/wavemachine` session crashed or was interrupted with wave state in `action == gate_evaluating`, the next invocation:
1. Skips the pre-wave kahuna bootstrap (the `kahuna_branch` field is already populated).
2. The loop's first iteration finds `wave_next_pending() == null` (all waves merged on the prior run) and falls into the "Trust-Score Gate and Auto-Merge" step group.
3. `wave_finalize` is idempotent: it returns the existing open kahuna→main MR with `created: false`.
4. The four trust signals are re-invoked in a single tool-use block (R-23). They are pure reads — re-evaluating yields current truth (e.g. CI may now be green where it was timing out before).
5. Gate evaluation proceeds normally — all-green merges and exits clean; any-red transitions to `gate_blocked` and exits paused.

This idempotent re-entry is what makes the gate crash-safe.

## Pair

- `/prepwaves` — plans the waves (authors the wave plan from a master epic).
- `/nextwave` — executes one wave end-to-end (Orchestrator/Prime/Flight on the filesystem bus). Interactive by default; `/nextwave auto` is the no-gate variant.
- **`/wavemachine` — loops over `/nextwave auto` with a health circuit breaker. This skill.**
- `/dod` — verifies the project at the end against the Deliverables Manifest.
