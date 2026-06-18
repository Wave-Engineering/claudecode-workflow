---
name: wavemachine-next
description: Campaign driver — loops one per-wave Workflow per pending wave, routes on its verdict, closed campaign exits; auto-vs-interactive is a one-line advance-vs-wait branch
---

# Wavemachine-Next — Campaign Driver for the per-wave Workflow

> **Migration successor to `/wavemachine`.** The campaign loop runs **in the main
> session** (not as a nested Workflow): it launches one per-wave Workflow per pending
> wave, reads its verdict, and advances. The old `/wavemachine` (loops `/nextwave auto`)
> is unchanged and stays in place during migration. Design of record:
> `docs/wavemachine-workflows-migration.md` §5.

## Axioms

Bound by WAVE_AXIOMS 2, 3, 4, 5, 6, 8, 9 (`WAVE_AXIOMS.md`). The campaign autonomy
contract (loop runs to terminal state or Legal Exit), the closed-list exits, the
Concerns Channel, the cost-asymmetry default-forward stance, the approval-frequency
rule (`auto` advances on PASS with no per-wave human gate; `interactive` surfaces the
verdict per wave), and user-attention-as-cost all live in that file. This skill is the
operational binding.

## What this is

`/wavemachine-next` runs **one per-wave Workflow per pending wave** — the §3.1
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
sdlc-server tools are the runtime; **`/wavemachine-next` is `make all` for the wave
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
  verdict = run /nextwave-next for `wave`        # §3 spine → { gate: PASS | HOLD | SKIPPED }

  # ── ROUTE ON VERDICT — auto-vs-interactive is ONE advance-vs-wait line ──
  if verdict.gate == 'PASS':
      promoted.add(wave); pendingWaves.delete(wave); waveRetry[wave] = 0
      if MODE == 'interactive':  surface verdict + kahuna diff; STOP for human; advance on their go
      continue                                   # auto: advance immediately
  if (waveRetry[wave] = (waveRetry[wave]||0)+1) > MAX_WAVE_RETRY: halt=`wave-breaker:${wave}`; break
  halt = 'wave-hold'; break                       # HOLD/SKIPPED → human review (the per-wave gate fired)
```

**Mode is a one-line advance-vs-wait branch, NOT two architectures.** `auto` advances
on `PASS`; `interactive` surfaces the verdict and STOPS for the human, then advances on
their go. Both run the identical loop body.

## Closed campaign-exit set (mirrors §3.1)

| Exit | Condition | Meaning |
|---|---|---|
| success | `pendingWaves` empty | every wave promoted to the protected branch |
| runaway | `promoted ≥ MAX_WAVES` | defensive bound → human |
| cost | budget floor | stop before the ceiling |
| wave-hold | a wave returns HOLD/SKIPPED | the per-wave gate fired → human review |
| wave-breaker | a wave reworked > `MAX_WAVE_RETRY` | one wave won't converge → human |

- **No campaign-level planner → no `plan done`/success collision.** Waves come from the
  pre-approved plan; there is no planner verdict to misread.
- **Progress is structural.** Each iteration either promotes a wave (`PASS`) or halts —
  a campaign iteration cannot make zero net progress and continue, so no idle-round
  detector is needed; the retry breaker covers a wave that repeatedly fails to reach `PASS`.

## Pre-flight (refuse to start on failure)

1. **Supporting CLIs on PATH** — `wave-status`, `generate-status-panel`, `mcp-log`.
   Missing → refuse and name each; re-run `./install`.
2. **Plan exists** (`wave_show()`); **no other wave active**; **base branch clean**;
   **previous wave merged**; **at least one pending wave**; **no concurrent campaign**.

On any refusal: explain, suggest remediation, do NOT enter the loop. (Same gates as the
legacy `/wavemachine` pre-flight; see that skill for the detailed rationale.)

## Launch sequence (before the loop)

1. Set the `wavemachine_active` flag (`wave-status wavemachine-start --launcher main`).
   Unset it on EVERY exit path (`wave-status wavemachine-stop`) — treat as a `finally`.
2. Regenerate + open the status panel (`generate-status-panel` then `xdg-open`).
3. **Pre-wave kahuna bootstrap** — once per Plan: `wave_init` with `kahuna:{plan_id, slug}`
   creates `kahuna/<plan_id>-<slug>` off the protected branch and writes `kahuna_branch`
   into wave state. Idempotent — a resume invocation sees the field populated and skips.
   Every per-wave Workflow is launched with that `kahunaBranch`.
4. Announce to `#wave-status`; emit `mcp-log wavemachine_start`.

## Per-wave handoff (no narrator gap)

When a per-wave Workflow returns, the immediately following assistant message is a
tool-use block (status-panel regen + discord-status-post + next iteration's launch), NOT
narrative prose. "Wave N complete, starting N+1" between waves is forbidden — it costs
wall-clock (the cc-workflow#600 "Bug B" failure mode). In `interactive` mode the human
STOP is the one deliberate pause; everything else is a tight tool-use chain.

## Resumability (mirrors §3.3, one level up)

On cold start the campaign rehydrates from wave-status's wave-completion records
(`wave_previous_merged` / `wave_topology`) and skips already-promoted waves;
`promoted` / `pendingWaves` seed from there. Same durable substrate as the inner loop.
The per-wave Workflow itself rehydrates its own loop state (`per-wave-workflow.js`
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
- **The per-wave Workflow owns all wave-internal work.** `/wavemachine-next` only launches
  one per wave and routes on its verdict — it never spawns flights/Prime/reconcile itself.
- **The kahuna→protected merge is the per-wave Workflow's trust-gate job**, not the
  campaign driver's. The driver advances on `PASS`; it never merges to the protected branch.
- **Per-wave handoff is a single tool-use boundary** — no inter-wave narration.
- **Structured blocker report on any abort** — name the wave (or failing signals), the
  exit type, and the remediation path.

## Pair

- `/prepwaves` — plans the waves.
- `/nextwave-next` — executes one wave via `per-wave-workflow.js`.
- **`/wavemachine-next` — loops one per-wave Workflow per pending wave. This skill.**
- `/dod` — verifies the project at Plan end.
