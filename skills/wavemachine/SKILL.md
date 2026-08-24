---
name: wavemachine
description: Campaign driver — loops one per-wave Workflow per pending wave onto ONE campaign branch; advances ONLY on gate PASS AND integrated (a PASS that did not land on the campaign branch HOLDs); the protected branch is written exactly once, at the end, gated on the DoD; closed campaign exits; auto-vs-interactive is a one-line advance-vs-wait branch; cold-start rehydrate prunes already-integrated waves
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
rule (`auto` advances on a wave that PASSED **and integrated** with no per-wave human gate;
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

## One branch all the way through (#1052)

**A campaign has exactly ONE integration branch — `campaign/<planId>-<slug>` — and it writes the
protected branch exactly once, at the end, only if the DoD is met.** Every wave cuts a disposable
`kahuna/<planId>-<waveId>` off the campaign branch and integrates back into it. No wave, at any
point, merges to trunk.

This replaced per-wave merge-backs to the protected branch, which carried three costs:

1. **Rollback got harder.** An interim merge-back makes each wave a published trunk increment, so
   abandoning a campaign at wave 5 means reverting 4 merges from trunk instead of deleting a branch.
2. **It broke other people's environments.** Anyone branching off trunk mid-campaign inherited a
   *partial* increment — half a feature, by construction.
3. **It was never a real increment.** Nothing is deliverable until every wave lands *and* the DoD is
   met. A merge-back claimed delivery N waves early.

It also **dissolves #892** rather than mitigating it. The equality check that failed there compared a
long-lived integration branch against a base it had been **squash**-merged into — an impossible
comparison, because the squash rewrites the history being compared. With no interim merge-back, each
wave's kahuna is disposable and nothing continues from it, so a squash is harmless.

**The two prefixes are distinct on purpose.** git cannot hold a branch that is a directory prefix of
another branch — `campaign/56-plan` and `campaign/56-plan/W-1` cannot coexist
(`fatal: cannot lock ref … 'refs/heads/campaign/56-plan' exists`). Hence `campaign/…` for the
campaign and `kahuna/…` for the waves.

## The campaign loop (§5 — this is the whole skill)

Campaign state is script-held in the main session and mirrored to wave-status each
iteration. There is **no campaign-level planner** — waves are drawn from the
pre-approved phase/wave plan via `nextPendingWave()` — so success is `pendingWaves`
empty and nothing else (the §3.1 `plan.done`/success sentinel-collision is designed out,
not guarded against).

```
campaignBranch = campaign/<planId>-<slug>  # bootstrapped ONCE off the protected branch (#1052)
pendingWaves = approved phase/wave plan    # rehydrate prunes already-INTEGRATED waves
halt = null                                # null = converging; else a HOLD reason (NEVER a success)
waveRetry = {}; integrated = {}
MAX_WAVES = 64, MAX_WAVE_RETRY = 2, CAMPAIGN_FLOOR = 120_000

loop:
  # ── CLOSED LEGAL EXITS (campaign level) ──
  if pendingWaves empty:                         break                  # loop done — all waves INTEGRATED (not yet released)
  if integrated.size >= MAX_WAVES:               halt='runaway'; break  # defensive bound → human
  if budget.total and budget.remaining() < CAMPAIGN_FLOOR: halt='cost'; break

  wave    = nextPendingWave()                    # from the approved plan
  verdict = run /nextwave for `wave`             # §3 spine, integrationBase=campaignBranch
                                                 # → { gate, integrated, ... } (per-wave-workflow.js return)

  # ── INTERACTIVE: a clean gate returns { gate:'PASS', integrated:false } BY DESIGN (the Workflow
  #    never auto-promotes in interactive). Surface verdict + kahuna→campaign diff, STOP for the
  #    human; the human routes the kahuna→campaign merge. Resume ONLY after they confirm it landed. ──
  if MODE == 'interactive' and verdict.gate == 'PASS':
      surface verdict + kahuna→campaignBranch diff; STOP for human
      # On resume, VERIFY the merge actually landed — do NOT advance on the operator's word alone.
      # The human (or a /nextwave interactive-promote step) records the wave's terminal disposition
      # in wave-status when the kahuna→campaign merge lands. Re-read it; advance ONLY if it is durably
      # 'promoted' — structurally symmetric with the auto branch's verdict.integrated check (a durable
      # FACT, not an assertion). A human "go" without a recorded merge (conflict mid-merge, aborted,
      # not yet run) is NOT advanceable.
      if waveDisposition(wave) != 'promoted':       # read from wave-status (the same record auto checks)
          halt = 'wave-hold'; break                 # not on the campaign branch → human review
      integrated.add(wave); pendingWaves.delete(wave); waveRetry[wave] = 0; continue

  # ── AUTO: advance ONLY on PASS-AND-integrated (the #687 correctness rule, #1052 vocabulary) ──
  if verdict.gate == 'PASS' and (verdict.integrated == true or verdict.promoted == true):
      integrated.add(wave); pendingWaves.delete(wave); waveRetry[wave] = 0; continue

  # AUTO gate:'PASS' with integrated:false (kahuna→campaign merge did NOT land — the Workflow's
  # promote node soft-failed and recorded the wave HELD) falls through here. It is NOT advanceable:
  # the wave's CODE is sound but it is not on the campaign branch → HOLD for human attention.
  if (waveRetry[wave] = (waveRetry[wave]||0)+1) > MAX_WAVE_RETRY: halt=`wave-breaker:${wave}`; break
  halt = 'wave-hold'; break                       # HOLD | SKIPPED | (auto) PASS-not-integrated → human review

# ── RELEASE (#1052) — reached ONLY on the clean loop exit; the campaign's single trunk write ──
if halt == null:
    dod = verify the DoD against campaignBranch's actual tree   # not the checkboxes
    if every wave in the FULL plan integrated and dod.met == true:
        merge campaignBranch → protectedBranch    # ONE PR, its own CI run, then close the issues
    else:
        HOLD — protectedBranch untouched, campaignBranch preserved for inspection/resume
```

**`integrated` is not `released`.** The loop emptying `pendingWaves` means every wave is on the
campaign branch; it does **not** mean anything shipped. The release is a separate, single, DoD-gated
event — and a campaign that holds there is a campaign awaiting its DoD, not a failed one (the work
is durable on the campaign branch and fully resumable). The `verdict.promoted` fallback in the
advance predicate is the legacy-record path: a wave recorded by a pre-#1052 engine mid-campaign
still advances rather than stalling the upgrade.

On every `continue` (the OK-path that advances to the next wave), the next iteration's
launch is a **single tool-use boundary** — it follows the **Per-wave handoff (no narrator
gap)** contract below: no narrative text between waves.

**CRITICAL — advance ONLY on PASS AND integrated.** `verdict.gate === 'PASS'` is NOT
sufficient. The per-wave Workflow (`per-wave-workflow.js`) returns `{ gate, integrated, … }`,
and the two are distinct facts:

- `{ gate: 'PASS', integrated: true }` — trust gate passed **and** the kahuna→campaign-branch
  merge landed. In `auto` this is the only auto-advanceable verdict. Add to `integrated`, drop from
  `pendingWaves`.
- `{ gate: 'PASS', integrated: false }` — the trust gate passed but the wave is NOT on the
  campaign branch. Two causes, distinguished by mode:
  - **`auto`:** the promote node soft-failed — the kahuna→campaign merge **did not land** and
    the Workflow recorded the wave HELD. → **HOLD for human attention, do NOT advance.** Treating
    this as success would mark a wave done while its code never reached the campaign branch, and the
    release gate would later count it as integrated on the strength of a merge that never happened.
  - **`interactive`:** the Workflow never auto-promotes by design — it returns the clean verdict
    for the human to route. → STOP, surface the diff, and on resume advance **only if wave-status
    durably records the wave `promoted`** — the same fact the auto branch reads off the verdict, now
    read off the durable record. The operator's "go" alone is not sufficient: a go without a recorded
    merge (mid-merge conflict, aborted, not yet run) HOLDs (`wave-hold`). Interactive is thus
    structurally symmetric with auto — both require a durable fact, never an assertion.
- `{ gate: 'HOLD' }` / `{ gate: 'SKIPPED' }` — a trust signal failed, or the flight loop hit a
  HOLD exit before the gate → wave-hold (both modes).

The auto-advance predicate is therefore `gate === 'PASS' && integrated === true`, evaluated
against the verdict's own fields — never inferred from `gate` alone. (`promoted === true` is
accepted as the same fact under its legacy name, so a wave recorded by a pre-#1052 engine does not
stall a mid-campaign upgrade.) In `interactive`, the
PASS verdict (necessarily `integrated:false`) gates on the human routing the merge **and** on
wave-status durably recording it `promoted` — the human owns the *decision*, the durable record
is the *fact* the loop advances on.

**Mode is a one-line advance-vs-wait branch, NOT two architectures.** `auto` advances on
PASS-and-integrated (a verdict fact); `interactive` runs the wave Workflow in interactive mode
(which returns `{ gate:'PASS', integrated:false }` on a clean gate), surfaces the verdict +
kahuna→campaign diff, STOPS for the human, and — once the human routes the merge — advances
**only if wave-status records the wave `promoted`** (a durable fact). Both run the identical loop
body and both gate on a durable landed-fact; only *where* that fact comes from (the verdict
vs. the post-STOP wave-status read) differs.

## Closed campaign-exit set (mirrors §3.1)

| Exit | Condition | Meaning |
|---|---|---|
| success | `pendingWaves` empty | every wave integrated onto the campaign branch → the release gate runs |
| runaway | `integrated ≥ MAX_WAVES` | defensive bound → human |
| cost | budget floor | stop before the ceiling |
| wave-hold | a wave returns HOLD/SKIPPED, **or (auto) PASS-but-not-integrated** | the per-wave gate fired, or the gate passed but the kahuna→campaign merge did not land → human review |
| wave-breaker | a wave hit a non-advanceable verdict > `MAX_WAVE_RETRY` times | one wave won't reach PASS-and-integrated → human |
| release-hold | the loop completed but the DoD is not met (or is undeterminable) | **not a failure** — the protected branch is untouched and the campaign branch holds every wave; resumable once the DoD genuinely holds (#1052) |

- **`waveRetry` counts EVERY non-advanceable verdict, regardless of cause.** A trust-gate `HOLD`,
  a `SKIPPED`, and an auto PASS-but-not-integrated all increment the same counter — the campaign
  re-runs the wave (the inner Workflow rehydrates and resumes its loop) until it either reaches
  PASS-and-integrated or burns `MAX_WAVE_RETRY` attempts and trips `wave-breaker`. "Retry" here is
  "the wave was re-driven", not specifically "an issue was reworked" (the inner §3.1 per-issue
  rework breaker is a separate, finer-grained guard). The single counter is deliberate: the
  campaign does not distinguish *why* a wave failed to land — a wave that can't reach the campaign
  branch after N attempts needs a human either way.
- **No campaign-level planner → no `plan done`/success collision.** Waves come from the
  pre-approved plan; there is no planner verdict to misread.
- **Progress is structural.** Each iteration either integrates a wave (`PASS` **and** `integrated`)
  or halts — a campaign iteration cannot make zero net progress and continue, so no idle-round
  detector is needed; the retry breaker covers a wave that repeatedly fails to reach
  PASS-and-integrated. A `gate:'PASS'` that did not integrate is NOT progress: it does not advance,
  it HOLDs (auto) or waits on the human (interactive).
- **`release-hold` is conservative on absence.** An unreadable DoD manifest, a malformed verdict, or
  an errored DoD node all block the release: an undeterminable DoD is not a met DoD (SEAMS invariant
  6). Holding costs a conversation; releasing wrongly costs a revert of the whole campaign.

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
wave-status campaign-head \
  --activity-id "$FLIGHTDECK_ACTIVITY_ID" \
  ${dev_name:+--agent "$dev_name"} || true
```
(Omit `--agent` when the Dev-Name is absent — `${dev_name:+…}` — so the card falls back to
the project label rather than rendering an empty title.)

`campaign-head` derives `planTotal` (the wave denominator), `workItemsTotal` (the campaign-scope
work-item denominator, #1154), `waveWorkItems` (a per-wave work-item denominator map, #1157),
and the project label FROM THE PLAN itself (`phases-waves.json`) — never a hand-typed literal
(flightdeck#1145). It refuses loudly (non-zero exit, a message on stderr) rather than emitting
a card claiming an unknown total if the plan can't be read, or if the plan has zero waves, or
if it has zero work items; the `|| true` here only protects the launch sequence from aborting
on that refusal, it does not hide the message. `--agent` is the Dev-Name (card title). The
per-wave `promoted` step then accrues the wave numerator (`per-wave-workflow.js`, #1026 incr
2); `close-issue` (`state.py`'s `close_issue`, unrelated to wavemachine) accrues the
work-items numerator at BOTH campaign scope (always) and wave scope (#1157) — tagged with
the CLOSED ISSUE'S OWN wave (`_issue_wave_id`), not wherever `current_wave` happens to point,
since those two can legitimately drift (a straggler close after the campaign has advanced, a
human recovery via `set_current_wave`, `extend_state`'s auto-advance).

1. Set the `wavemachine_active` flag (`wave-status wavemachine-start --launcher main`).
   Unset it on EVERY exit path (`wave-status wavemachine-stop`) — treat as a `finally`.
2. Regenerate + open the status panel (`generate-status-panel` then `xdg-open`).
3. **Campaign-branch bootstrap (#1052)** — once per Plan: ensure `campaign/<plan_id>-<slug>` exists
   on origin, cut from the **current tip of the protected branch**, and push it. Then thread it into
   every per-wave launch as `integrationBase`.

   **Create-or-reuse, and reuse wins.** On a resume the branch already exists and carries every
   previously-integrated wave, so re-cutting it from the protected branch would silently discard the
   whole campaign to date. Verify by reading the ref back (`git rev-parse origin/campaign/…`), not by
   the push's exit code.

   **If the branch can be neither found nor created, the campaign ABORTS.** Do not substitute the
   protected branch as a fallback: that recovery is exactly the per-wave trunk write this shape
   exists to prevent. No campaign branch, no campaign.

   Each wave then gets its own disposable `kahuna/<plan_id>-<waveId>`, cut off the campaign branch by
   the per-wave Workflow's KAHUNA-BOOTSTRAP node (create-or-reuse, read-back verified, fail-loud —
   never re-cut an existing one, which would discard the flights already integrated into it).

   **A plan-supplied `kahuna_branch` is IGNORED inside a campaign** (the override is logged, not
   silent). `wave_init`'s `kahuna:{plan_id, slug}` bootstraps ONE plan-scoped `kahuna/<plan_id>-<slug>`
   off the plan's `base_branch` — shared across every wave and based on trunk. Both properties are
   wrong here: a campaign wave's kahuna is *disposable*, so wave 1's promote would delete wave 2's
   base; and a trunk-based branch gives wave 2 a baseline missing wave 1's integrated work. The
   campaign branch is a separate, client-side ref — and the two prefixes must stay distinct because
   git cannot hold a branch that is a directory prefix of another branch.
4. Announce to `#wave-status`; emit `mcp-log wavemachine_start`.

## Launching a wave (the input blob — consistent with `/nextwave`)

Each iteration launches the per-wave Workflow via `/nextwave` with the same input blob
`per-wave-workflow.js` declares (its `params`, and `/nextwave`'s **Inputs** table). The
campaign driver supplies, per wave, from the approved phase/wave plan + project config:

| Field | Source |
|---|---|
| `waveId`, `issues` | `nextPendingWave()` + that wave's issue list (single repo, §4.1) |
| `targetRepo`, `targetRepoDir` | the wave's resolved repo + its durable clone dir |
| `kahunaBranch` | this wave's **disposable** integration branch, `kahuna/<planId>-<waveId>` (namespaced by plan so two concurrent campaigns can't collide on `kahuna/W-1`) |
| `integrationBase` | **the campaign branch** from the launch-sequence bootstrap (step 3). This is where the wave lands (#1052). |
| `protectedBranch` | from `.claude-project.md`. Passed so the engine can *recognize* trunk — it derives "am I in a campaign?" from `integrationBase !== protectedBranch`, which is what retires `preserveKahuna` and moves the platform issue-close to the release node. Omit it and the engine defaults to `'main'` and mis-detects a campaign on any repo whose trunk is named otherwise. |
| `mode` | the campaign's `MODE` (`auto` \| `interactive`) — passed through unchanged |
| `planId` | the wave Plan id (the promote node assembles the MR body from it) |
| `budget` | the campaign cost guard, if any |

**`preserveKahuna` is deliberately NOT threaded (#1052).** The branch that must survive across waves
is the campaign branch, and it does; each wave's kahuna is disposable again. A campaign wave ignores
the flag even if a stale launcher passes it.

The verdict consumed back is exactly `per-wave-workflow.js`'s return — `{ gate, integrated, … }`
— routed by the loop above. The driver passes `mode` straight through: in `interactive` the
Workflow returns `{ gate:'PASS', integrated:false }` on a clean gate (it never auto-promotes),
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
(`wave_previous_merged` / `wave_topology`) and skips already-integrated waves;
`integrated` / `pendingWaves` seed from there. Same durable substrate as the inner loop.

A wave is "already-integrated" (and therefore pruned from `pendingWaves` on resume) only when
its per-wave Workflow recorded the terminal disposition `promoted` — i.e. `gate:'PASS'` **and**
the kahuna→campaign merge landed (`persistTerminal('promoted', …)`, SEAM #688). A wave whose
Workflow recorded `held` (gate PASS-but-not-integrated, HOLD, or SKIPPED) is NOT pruned — it
re-enters `pendingWaves` and the campaign re-runs it. This is the resume-side mirror of the
advance rule: the same fact (did the wave land on its integration base?) gates both the live
advance and the cold-start prune, so a resumed campaign never skips a wave that only *looked*
done. The per-wave Workflow itself rehydrates its own inner loop state (`per-wave-workflow.js`
rehydrate phase, SEAM #686) — the campaign driver only tracks wave-grain completion.

**The prune predicate is INTEGRATED, not released (#1052).** Nothing is released until the campaign
ends, so a released-keyed rehydrate would prune nothing and re-run the entire campaign on every
resume. Equally, a resumed run must carry its pre-run integrations forward into the release gate:
that gate judges completeness against the **full plan**, and a resumed run's own advance list covers
only its slice, so without the rehydrated set a resumed campaign could never satisfy completeness and
would hold forever with every wave actually integrated.

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
- **The kahuna→campaign-branch merge is the per-wave Workflow's trust-gate job**, not the
  campaign driver's. The driver advances on `PASS` **AND** `integrated` (auto), or on the human's
  confirmation that the merge landed (interactive); it never merges a wave itself. A `gate:'PASS'`
  without `integrated` is never treated as advanceable.
- **The campaign→protected merge happens EXACTLY ONCE, at the end, and only if the DoD is met
  (#1052).** No wave may write the protected branch. The DoD is verified against the campaign
  branch's actual tree, not its checkboxes, and an undeterminable DoD blocks the release.
- **Issues close at the release, not at each wave (#1046).** A wave's merge records durable engine
  state (`wave_close_issue`); the platform close (`gh issue close` / `glab issue close`) runs in the
  release node after the trunk merge. A closed issue is the board's claim that the work is delivered
  — closing at wave N makes that claim early, and an aborted campaign would leave closed issues for
  work that was deleted.
- **Per-wave handoff is a single tool-use boundary** — no inter-wave narration.
- **Structured blocker report on any abort** — name the wave (or failing signals), the
  exit type, and the remediation path.

## Pair

- `/prepwaves` — plans the waves.
- `/nextwave` — executes one wave via `per-wave-workflow.js`.
- **`/wavemachine` — loops one per-wave Workflow per pending wave. This skill.**
- `/dod` — verifies the project at Plan end.
