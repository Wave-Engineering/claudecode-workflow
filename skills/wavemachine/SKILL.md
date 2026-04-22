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
- `mcp__sdlc-server__wave_show` — pre-flight state inspection
- `mcp__sdlc-server__wave_previous_merged` — pre-flight verification that prior wave is on main
- `mcp__sdlc-server__wave_ci_trust_level` — cached by `/nextwave auto` for its internal gate decisions
- `mcp__sdlc-server__wave_waiting` — mark the plan paused with a human-readable reason on any abort
- `mcp__disc-server__disc_send` — announce to `#wave-status` (`1487386934094462986`) on start, completion, abort
- The Skill tool — invokes `/nextwave auto` per iteration (the one place work is delegated)
- `ScheduleWakeup` — OPTIONAL, fallback-only, used when a merge-queue idle is detected (not the primary execution model)

**Not used:** the `Agent` tool is NEVER used directly from this skill — all sub-agent spawning is owned by `/nextwave`. Background Agent invocation is NEVER used anywhere in this skill; the loop is synchronous in the top-level session.

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
4. **Post to Discord.** `disc_send` to `#wave-status` (`1487386934094462986`): `"🌊 **Wavemachine started** — <project>, <N> waves pending. Agent: **<dev-name>** <dev-avatar>"`. Resolve identity from `/tmp/claude-agent-<md5>.json`. If `disc_send` fails, log and continue — Discord is informational, not a gate.

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
         announce completion (see "On Clean Completion")
         python3 -m wave_status wavemachine-stop
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

**On clean completion** (`wave_next_pending()` returned null):

- Discord `#wave-status`: `"✅ **Wavemachine complete** — <project>, all <N> waves merged. Run /dod to verify. Agent: **<dev-name>** <dev-avatar>"`
- Vox (conversational, brief): name, team, project, "wavemachine complete, all waves merged".

**On circuit-breaker trip** (`wave_health_check` non-HEALTHY):

- Discord `#wave-status`: `"🛑 **Wavemachine aborted (circuit breaker)** — <project>: <one-line health summary>. Agent: **<dev-name>** <dev-avatar>"`
- Call `wave_waiting("wavemachine aborted (circuit breaker): <one-line summary>")` so the plan is explicitly marked paused.

**On per-wave BLOCKED or FAIL** (from `/nextwave auto` return):

- Discord `#wave-status`: `"🛑 **Wavemachine aborted** — <project>, wave <id>: <one-line failure summary>. Agent: **<dev-name>** <dev-avatar>"`
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
- **NEVER run the loop in a background sub-agent.** No background Agent invocation, ever — not with the `run_in_background` parameter, not shelled out, not via any other escape hatch. No nested `Agent` calls from this skill body. The loop is top-level, period.
- **NEVER spawn Flights or Prime directly.** `/nextwave auto` owns the Orchestrator/Prime/Flight protocol for each wave — `/wavemachine` only delegates.
- **Circuit breaker before every iteration.** `wave_health_check` is called at the TOP of each loop iteration, not just the first.
- **Leave the bus alone on abort.** On any non-happy exit, the in-flight wave's bus tree stays on disk for forensics. `wave-cleanup` runs only on PASS, inside `/nextwave auto`.
- **Block on green CI.** `/nextwave auto` handles the per-wave CI gate; `/wavemachine` does not merge anything directly and does not fast-path around it.
- **Structured blocker report on any abort.** Vague "something went wrong" is unacceptable — the Discord announcement + the session report must name the wave, the blocker type, and the remediation path.

## Resuming After an Abort

Wave state is persistent on disk (`.claude/status/state.json` + the bus tree). When the blocker is resolved, simply re-invoke `/wavemachine`. The pre-flight checks validate the new starting state; the loop picks up from the next pending wave.

## Pair

- `/prepwaves` — plans the waves (authors the wave plan from a master epic).
- `/nextwave` — executes one wave end-to-end (Orchestrator/Prime/Flight on the filesystem bus). Interactive by default; `/nextwave auto` is the no-gate variant.
- **`/wavemachine` — loops over `/nextwave auto` with a health circuit breaker. This skill.**
- `/dod` — verifies the project at the end against the Deliverables Manifest.
