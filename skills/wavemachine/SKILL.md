---
name: wavemachine
description: Campaign driver — loops one per-wave Workflow per pending wave; advances ONLY on gate PASS AND promoted (a PASS that did not land on the protected branch HOLDs); closed campaign exits; auto-vs-interactive is a one-line advance-vs-wait branch; cold-start rehydrate prunes already-promoted waves
---

# Wavemachine — Campaign Driver for the per-wave Workflow

> **The dynamic-workflows wave engine (cut over #691).** The campaign loop runs **in the
> main session** (not as a nested Workflow): it launches one per-wave Workflow per pending
> wave, reads its verdict, and advances. This replaced the legacy LLM-orchestrated
> `/wavemachine` (which looped `/nextwave auto`). Design of record:
> `docs/wavemachine-workflows-migration.md` §5.

## Axioms

Bound by WAVE_AXIOMS 2, 3, 4, 5, 6, 8, 9 (`WAVE_AXIOMS.md`). The campaign autonomy
contract (loop runs to terminal state or Legal Exit), the closed-list exits, the
Concerns Channel, the cost-asymmetry default-forward stance, the approval-frequency
rule (`auto` advances on a wave that PASSED **and promoted** with no per-wave human gate;
`interactive` surfaces the verdict per wave), and user-attention-as-cost all live in that
file. This skill is the operational binding.

## What this is

`/wavemachine` runs **one per-wave Workflow per pending wave** — the §3.1
closed-legal-exits pattern lifted one level. It is the campaign loop of §5, run in the
top-level session because:

1. **Interactive review-between-waves is a hard requirement, and a Workflow can't pause
   for it** — so a skill driver must exist regardless; a nested auto-only Workflow would
   merely duplicate it.
2. **The campaign loop is thin** — N pre-approved waves, one launch + verdict each. All
   determinism and all judgment live *inside* each per-wave Workflow (the §3.1 reconcile
   + the §3.4 trust gate); there is almost nothing at campaign altitude to get wrong.
3. **Resume is native + reboot-proof** — the skill rehydrates `promoted`/`pendingWaves`
   from wave-status (§3.3); a nested Workflow has only within-session resume.
4. **Observability** — each wave is its own `/workflows` run, individually inspectable.

**Mental model:** issue specs are source; the per-wave Workflows are the compiler;
sdlc-server tools are the runtime; **`/wavemachine` is `make all` for the wave
compiler.**

## The campaign loop (§5 — this is the whole skill)

Campaign state is script-held in the main session and mirrored to wave-status each
iteration. There is **no campaign-level planner** — waves are drawn from the
pre-approved phase/wave plan via `nextPendingWave()` — so success is `pendingWaves`
empty and nothing else (the §3.1 `plan.done`/success sentinel-collision is designed out,
not guarded against).

```
pendingWaves = approved phase/wave plan   # rehydrate prunes already-promoted
halt = null                               # null = converging; else a HOLD reason (NEVER a success)
waveRetry = {}; promoted = {}
MAX_WAVES = 64, MAX_WAVE_RETRY = 2, CAMPAIGN_FLOOR = 120_000

loop:
  # ── CLOSED LEGAL EXITS (campaign level) ──
  if pendingWaves empty:                         break                  # success — all waves promoted
  if promoted.size >= MAX_WAVES:                 halt='runaway'; break  # defensive bound → human
  if budget.total and budget.remaining() < CAMPAIGN_FLOOR: halt='cost'; break

  wave    = nextPendingWave()                    # from the approved plan
  verdict = run /nextwave for `wave`        # §3 spine → { gate, promoted, ... } (per-wave-workflow.js return)

  # ── INTERACTIVE: a clean gate returns { gate:'PASS', promoted:false } BY DESIGN (the Workflow
  #    never auto-promotes in interactive). Surface verdict + kahuna→protected diff, STOP for the
  #    human; the human routes the kahuna→protected merge. Resume ONLY after they confirm it landed. ──
  if MODE == 'interactive' and verdict.gate == 'PASS':
      surface verdict + kahuna→protected diff; STOP for human
      # On resume, VERIFY the merge actually landed — do NOT advance on the operator's word alone.
      # The human (or a /nextwave interactive-promote step) records the wave's terminal disposition
      # in wave-status when the kahuna→protected merge lands. Re-read it; advance ONLY if it is durably
      # 'promoted' — structurally symmetric with the auto branch's verdict.promoted check (a durable
      # FACT, not an assertion). A human "go" without a recorded promotion (conflict mid-merge, aborted,
      # not yet run) is NOT advanceable.
      if waveDisposition(wave) != 'promoted':       # read from wave-status (the same record auto checks)
          halt = 'wave-hold'; break                 # not on the protected branch → human review
      promoted.add(wave); pendingWaves.delete(wave); waveRetry[wave] = 0; continue

  # ── AUTO: advance ONLY on PASS-AND-promoted (the #687 correctness rule) ──
  if verdict.gate == 'PASS' and verdict.promoted == true:
      promoted.add(wave); pendingWaves.delete(wave); waveRetry[wave] = 0; continue

  # AUTO gate:'PASS' with promoted:false (kahuna→protected merge did NOT land — the Workflow's
  # promote node soft-failed and recorded the wave HELD) falls through here. It is NOT advanceable:
  # the wave's CODE is sound but it is not on the protected branch → HOLD for human attention.
  if (waveRetry[wave] = (waveRetry[wave]||0)+1) > MAX_WAVE_RETRY: halt=`wave-breaker:${wave}`; break
  halt = 'wave-hold'; break                       # HOLD | SKIPPED | (auto) PASS-not-promoted → human review
```

On every `continue` (the OK-path that advances to the next wave), the next iteration's
launch is a **single tool-use boundary** — it follows the **Per-wave handoff (no narrator
gap)** contract below: no narrative text between waves.

**CRITICAL — advance ONLY on PASS AND promoted.** `verdict.gate === 'PASS'` is NOT
sufficient. The per-wave Workflow (`per-wave-workflow.js`) returns `{ gate, promoted, ... }`,
and the two are distinct facts:

- `{ gate: 'PASS', promoted: true }` — trust gate passed **and** the kahuna→protected merge
  landed. In `auto` this is the only auto-advanceable verdict. Add to `promoted`, drop from
  `pendingWaves`.
- `{ gate: 'PASS', promoted: false }` — the trust gate passed but the wave is NOT on the
  protected branch. Two causes, distinguished by mode:
  - **`auto`:** the promote node soft-failed — the kahuna→protected merge **did not land** and
    the Workflow recorded the wave HELD. → **HOLD for human attention, do NOT advance.** Treating
    this as success would mark a wave done while its code never reached the protected branch.
  - **`interactive`:** the Workflow never auto-promotes by design — it returns the clean verdict
    for the human to route. → STOP, surface the diff, and on resume advance **only if wave-status
    durably records the wave `promoted`** — the same fact the auto branch reads off the verdict, now
    read off the durable record. The operator's "go" alone is not sufficient: a go without a recorded
    promotion (mid-merge conflict, aborted, not yet run) HOLDs (`wave-hold`). Interactive is thus
    structurally symmetric with auto — both require a durable `promoted` fact, never an assertion.
- `{ gate: 'HOLD' }` / `{ gate: 'SKIPPED' }` — a trust signal failed, or the flight loop hit a
  HOLD exit before the gate → wave-hold (both modes).

The auto-advance predicate is therefore `gate === 'PASS' && promoted === true`, evaluated
against the verdict's own fields — never inferred from `gate` alone. In `interactive`, the
PASS verdict (necessarily `promoted:false`) gates on the human routing the promotion **and** on
wave-status durably recording it `promoted` — the human owns the *decision*, the durable record
is the *fact* the loop advances on.

**Mode is a one-line advance-vs-wait branch, NOT two architectures.** `auto` advances on
PASS-and-promoted (a verdict fact); `interactive` runs the wave Workflow in interactive mode
(which returns `{ gate:'PASS', promoted:false }` on a clean gate), surfaces the verdict +
kahuna→protected diff, STOPS for the human, and — once the human routes the promotion — advances
**only if wave-status records the wave `promoted`** (a durable fact). Both run the identical loop
body and both gate on a durable `promoted` fact; only *where* that fact comes from (the verdict
vs. the post-STOP wave-status read) differs.

## Closed campaign-exit set (mirrors §3.1)

| Exit | Condition | Meaning |
|---|---|---|
| success | `pendingWaves` empty | every wave promoted to the protected branch |
| runaway | `promoted ≥ MAX_WAVES` | defensive bound → human |
| cost | budget floor | stop before the ceiling |
| wave-hold | a wave returns HOLD/SKIPPED, **or (auto) PASS-but-not-promoted** | the per-wave gate fired, or the gate passed but the kahuna→protected merge did not land → human review |
| wave-breaker | a wave hit a non-advanceable verdict > `MAX_WAVE_RETRY` times | one wave won't reach PASS-and-promoted → human |

- **`waveRetry` counts EVERY non-advanceable verdict, regardless of cause.** A trust-gate `HOLD`,
  a `SKIPPED`, and an auto PASS-but-not-promoted all increment the same counter — the campaign
  re-runs the wave (the inner Workflow rehydrates and resumes its loop) until it either reaches
  PASS-and-promoted or burns `MAX_WAVE_RETRY` attempts and trips `wave-breaker`. "Retry" here is
  "the wave was re-driven", not specifically "an issue was reworked" (the inner §3.1 per-issue
  rework breaker is a separate, finer-grained guard). The single counter is deliberate: the
  campaign does not distinguish *why* a wave failed to land — a wave that can't reach the protected
  branch after N attempts needs a human either way.
- **No campaign-level planner → no `plan done`/success collision.** Waves come from the
  pre-approved plan; there is no planner verdict to misread.
- **Progress is structural.** Each iteration either promotes a wave (`PASS` **and** `promoted`)
  or halts — a campaign iteration cannot make zero net progress and continue, so no idle-round
  detector is needed; the retry breaker covers a wave that repeatedly fails to reach
  PASS-and-promoted. A `gate:'PASS'` that did not promote is NOT progress: it does not advance,
  it HOLDs (auto) or waits on the human (interactive).

## Pre-flight (refuse to start on failure)

1. **Supporting CLIs on PATH** — probe all three in one shot:
   `command -v wave-status generate-status-panel mcp-log`.
   Any missing → refuse and name each; re-run `./install`.
2. **Plan exists** (`wave_show()`); **no other wave active**; **base branch clean**;
   **previous wave merged**; **at least one pending wave**; **no concurrent campaign**.

On any refusal: explain, suggest remediation, do NOT enter the loop. (Same gates as the
legacy `/wavemachine` pre-flight; see that skill for the detailed rationale.)

## Launch sequence (before the loop)

**First — pin the FlightDeck campaign card (#1026).** BEFORE any `wave-status` emit,
`export FLIGHTDECK_ACTIVITY_ID=<plan_id>` (the Plan tracking-issue number this campaign
runs) in the loop's shell. Every main-session emit — the state mutators (steps 1/§ below)
AND the per-wave tee, which keys on the same id — then lands on ONE card, keyed
deterministically on the plan, never the repo path (the driver owns the campaign card:
`wave-status init` runs in the sdlc-server MCP process whose env the driver cannot pin, so
the card can only be keyed here). Then emit its vitals ONCE (idempotent on resume — it just
refreshes the card):

```bash
dev_name="$(jq -r '.dev_name // empty' .claude/agent-identity.json 2>/dev/null)"
wave-status emit activity_start \
  --activity-id "$FLIGHTDECK_ACTIVITY_ID" --activity-type campaign \
  ${dev_name:+--agent "$dev_name"} \
  --detail "{\"planTotal\": <total waves in the approved plan>}" \
  --label "<project>" || true
```
(Omit `--agent` when the Dev-Name is absent — `${dev_name:+…}` — so the card falls back to
the project label rather than rendering an empty title; quote `<project>` in case it has spaces.)

`<total waves…>` (the wave denominator) and `<project>` (the fallback title) come from
`wave_show`/the plan. `--agent` is the Dev-Name (card title). The per-wave `promoted` step
then accrues the numerator (`per-wave-workflow.js`, #1026 incr 2).

1. Set the `wavemachine_active` flag (`wave-status wavemachine-start --launcher main`).
   Unset it on EVERY exit path (`wave-status wavemachine-stop`) — treat as a `finally`.
2. Regenerate + open the status panel (`generate-status-panel` then `xdg-open`).
3. **Pre-wave kahuna bootstrap** — once per Plan: `wave_init` with `kahuna:{plan_id, slug}`
   creates `kahuna/<plan_id>-<slug>` off the protected branch and writes `kahuna_branch`
   into wave state. Idempotent — a resume invocation sees the field populated and skips.
   Every per-wave Workflow is launched with that `kahunaBranch`.
4. Announce to `#wave-status`; emit `mcp-log wavemachine_start`.

## Launching a wave (the input blob — consistent with `/nextwave`)

Each iteration launches the per-wave Workflow via `/nextwave` with the same input blob
`per-wave-workflow.js` declares (its `params`, and `/nextwave`'s **Inputs** table). The
campaign driver supplies, per wave, from the approved phase/wave plan + project config:

| Field | Source |
|---|---|
| `waveId`, `issues` | `nextPendingWave()` + that wave's issue list (single repo, §4.1) |
| `targetRepo`, `targetRepoDir` | the wave's resolved repo + its durable clone dir |
| `kahunaBranch` | the per-Plan `kahuna_branch` from the launch-sequence bootstrap (step 3) |
| `protectedBranch` | from `.claude-project.md` |
| `mode` | the campaign's `MODE` (`auto` \| `interactive`) — passed through unchanged |
| `planId` | the wave Plan id (the promote node assembles the MR body from it) |
| `budget` | the campaign cost guard, if any |

The verdict consumed back is exactly `per-wave-workflow.js`'s return — `{ gate, promoted, … }`
— routed by the loop above. The driver passes `mode` straight through: in `interactive` the
Workflow returns `{ gate:'PASS', promoted:false }` on a clean gate (it never auto-promotes),
which the loop's interactive branch turns into the human STOP.

## Per-wave handoff (no narrator gap)

When a per-wave Workflow returns, the immediately following assistant message is a
tool-use block (status-panel regen + discord-status-post + next iteration's launch), NOT
narrative prose. "Wave N complete, starting N+1" between waves is forbidden — it costs
wall-clock (the cc-workflow#600 "Bug B" failure mode). In `interactive` mode the human
STOP is the one deliberate pause; everything else is a tight tool-use chain.

## Coarse driver status (#738) — and the stall-guard contract (#736)

The per-wave Workflow runs **async**: the driver launches it, **ends its turn**, and is
re-invoked on the completion verdict. So the campaign loop writes a **coarse
`current_action`** at its boundaries (the dynamic-model replacement for the legacy
per-phase lifecycle, which the engine no longer drives), via the `wave-status` CLI:

- **Immediately before launching a per-wave Workflow** — `wave-status awaiting-verdict <waveId>`.
  This is the LAST status write of the launch tool-use block, so when the turn ends to await
  the async verdict, `current_action.action == "awaiting-verdict"`.
- **On a HOLD / interactive verdict** (the one deliberate human pause) — `wave-status hold "<reason>"`
  before surfacing the diff and stopping.
- (Optional, for dashboard truthfulness) `wave-status promoting <waveId>` while a PASS wave promotes.

**This is the contract the stall-guard Stop hook depends on (#736).** The guard
(`config/settings.template.json`, the `Stop` hook keyed on `wavemachine_active`) no-ops when
`current_action.action` is `awaiting-verdict` (a legitimate async await — NOT a stall),
`hold` (a legitimate human pause), or `promoting` (an in-progress promotion); it blocks only
when `wavemachine_active` is set and the action implies the driver should be launching the
next wave but the turn ended without it. Writing `awaiting-verdict` in the same tool-use block
as the launch is therefore **load-bearing** — omit it and the guard false-fires on the await
(cc-workflow#736).

## Pending deferral resolution (#634)

`wave_health_check` (and the pre-flight gate) **blocks the loop when a wave has a pending
deferral** — this is by design: deferrals are human-judgment gates (infra waves HOLD on
`ORACLE_REQUIRED`; review findings need fix-forward), not stalls. The recovery path is an
explicit `wave-status` step, run **after** the deferred item has been adjudicated:

1. **Inspect** — the pending deferral and its reason surface in the campaign state / status
   panel (the same panel the launch sequence opens).
2. **Accept once adjudicated** — `wave-status defer-accept <index>`. This clears the pending
   deferral so the next `wave_health_check` / pre-flight passes and the loop advances.

`defer-accept` is the operator's "I have reviewed this and it is safe to proceed" signal —
**not** an auto-bypass. In `interactive` mode it is the human's call at the HOLD. In `auto`
mode a pending deferral is a legitimate pause for adjudication: the campaign does **not**
silently auto-accept a human-judgment gate, so an unattended run halts here until a deferral
is accepted (consistent with the async-await contract above — the driver is paused, not
stalled). Following this section alone is sufficient to recover; no source/memory dig needed.

> **Decision (cc-workflow#736 — async-aware INTERIM fix).** The legacy hook reason — "after
> /nextwave auto returns OK, invoke /nextwave auto again" — encoded the *synchronous* loop and
> false-fired on every async per-wave Workflow await and on manual promotion adjudication. The
> fix is option 1 of #736: make the existing guard **async-aware** by reading
> `current_action.action`, NOT retire it. The retire (ripping out the `wavemachine_active`
> plumbing) is the separate, gated cc-workflow#751.
>
> **The #600 inter-wave-stall invariant is PRESERVED, not superseded.** The no-narrator-gap
> handoff (Per-wave handoff, above) and the Stop hook together still forbid a genuinely-idle
> turn-end mid-campaign — the guard continues to block when `wavemachine_active` is set and the
> action is launch/idle-shaped. #736 only *narrows* the block away from the three legitimate
> non-stall states; it does not weaken the protection against a real stall. Regression:
> `tests/regression/test_wavemachine_stall_guard_async_aware.sh` (blocks the synchronous gap,
> no-ops the async await) alongside `test_wavemachine_handoff_no_narrator.sh` (#600).

## Resumability (mirrors §3.3, one level up)

On cold start the campaign rehydrates from wave-status's wave-completion records
(`wave_previous_merged` / `wave_topology`) and skips already-promoted waves;
`promoted` / `pendingWaves` seed from there. Same durable substrate as the inner loop.

A wave is "already-promoted" (and therefore pruned from `pendingWaves` on resume) only when
its per-wave Workflow recorded the terminal disposition `promoted` — i.e. `gate:'PASS'` **and**
the kahuna→protected merge landed (`persistTerminal('promoted', …)`, SEAM #688). A wave whose
Workflow recorded `held` (gate PASS-but-not-promoted, HOLD, or SKIPPED) is NOT pruned — it
re-enters `pendingWaves` and the campaign re-runs it. This is the resume-side mirror of the
advance rule: the same fact (did the wave reach the protected branch?) gates both the live
advance and the cold-start prune, so a resumed campaign never skips a wave that only *looked*
done. The per-wave Workflow itself rehydrates its own inner loop state (`per-wave-workflow.js`
rehydrate phase, SEAM #686) — the campaign driver only tracks wave-grain completion.

## Exhaustive Legal Exits

Per WAVE_AXIOMS Axiom 3 the campaign legal-exits list is the closed set above. Per
Axiom 4, unease that matches no exit rides the Concerns Channel (`[concern]` comment +
optional Discord ping) and the loop CONTINUES. Explicit non-exits (do NOT halt): phase
transitions, first multi-issue wave, session elapsed time, first-time execution of a
described pattern, recent successes increasing anxiety, general caution. If something
goes wrong it surfaces as a wave verdict (`HOLD`/`SKIPPED`) or a campaign exit above —
absence of those is presumption of healthy operation.

## Non-Negotiables

- **One Plan at a time.** Pre-flight refuses if another campaign is active.
- **`wavemachine_active` must always reflect reality** — set on entry, unset on every
  exit path. No `Edit` to `state.json`; go through the CLI.
- **NEVER run the loop in a background sub-agent.** The loop is top-level. (CC sub-agents
  lack the `Agent`/`Task` tool — `lesson_cc_subagent_tools.md` — so only the top-level
  session can launch a Workflow.)
- **The per-wave Workflow owns all wave-internal work.** `/wavemachine` only launches
  one per wave and routes on its verdict — it never spawns flights/Prime/reconcile itself.
- **The kahuna→protected merge is the per-wave Workflow's trust-gate job**, not the
  campaign driver's. The driver advances on `PASS` **AND** `promoted` (auto), or on the human's
  confirmation that the merge landed (interactive); it never merges to the protected branch
  itself. A `gate:'PASS'` without `promoted` is never treated as advanceable.
- **Per-wave handoff is a single tool-use boundary** — no inter-wave narration.
- **Structured blocker report on any abort** — name the wave (or failing signals), the
  exit type, and the remediation path.

## Pair

- `/prepwaves` — plans the waves.
- `/nextwave` — executes one wave via `per-wave-workflow.js`.
- **`/wavemachine` — loops one per-wave Workflow per pending wave. This skill.**
- `/dod` — verifies the project at Plan end.
