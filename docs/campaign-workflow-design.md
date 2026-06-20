# Campaign Workflow + Wave Oversight — Design Decision Record

**Status:** Decided 2026-06-20 (BJ + babelfish). Supersedes the #736 stall-guard.
**Scope:** the wave **campaign** layer (the loop that runs many waves), not the per-wave
spine (already a deterministic Workflow — `skills/nextwave/per-wave-workflow.js`).
**Tagline:** *deterministic loop, intelligent checkpoints.*

---

## 1. The problem (why this exists)

The #691 cutover made the **per-wave** engine deterministic JS (`per-wave-workflow.js`) but
left the **campaign loop** — launch wave → read verdict → advance or hold — as an **LLM
driving a loop** in the `/wavemachine` skill session. Because an LLM in a loop can stall,
we propped it up with a `Stop`-hook **cage** (the `wavemachine_active` stall-guard). That
guard then turned out to be legacy-synchronous and false-fired under the async engine
(#736), and every attempt to make it "async-aware" was another bar on the cage
([[lesson_cage_bars_signal_wrong_tool]]).

The deeper diagnosis (BJ): we were **using a non-deterministic tool to get determinism** —
hyper-specifying a deterministic loop to an AI agent instead of writing the loop as code.
The stall-guard is a symptom of the campaign loop being in the wrong execution model.

But the naive fix — "make it pure deterministic code, remove the LLM" — is also wrong, and
*why* is the heart of this design. When a wave finishes there is a real need for **judgment**:
*"here are all the signals; do I feel good about continuing this campaign, or is something
lurking?"* Pure determinism deletes that facility, and the problems it would have caught
**accumulate silently until they explode** and are far costlier to clean up later. So the
question is not "agent **vs** application." It is:

> **How do we keep the process deterministic AND still give an intelligent expert the
> opportunity to inspect and approve the output?** The answer to determinism-vs-intelligence
> must be **both.**

## 2. The decision

**Control flow is code; judgment is a seam.** Code owns the loop / sequencing / exits;
agents are *called* for the parts that need a brain — exactly the Workflow pattern (and
exactly what the per-wave trust gate already does one altitude down, calling a code-reviewer
`agent()` inside a deterministic gate).

1. **Auto-mode campaign loop = a deterministic Workflow.** It iterates the pending waves,
   runs each per-wave spine, routes on the `{gate, promoted}` verdict. No LLM in the loop ⇒
   it **cannot stall** ⇒ the stall-guard is **deleted, not patched** (#736 dissolves).

2. **Per-wave judgment = a dedicated sub-agent — the *wave-oversight* agent.** It *must* be a
   sub-agent: the session that launched the campaign Workflow cannot be re-invoked by the
   application it launched (turtles all the way down). After a wave's gate PASSes, the
   Workflow calls this agent — *"given the intent and the trajectory so far, is it sound to
   continue, or is something lurking?"* **Continue →** the loop advances deterministically.
   **Flag →** the Workflow **holds and ends**; a Workflow ending with a report *is* the human
   handoff (the model the migration already blessed per-wave).

3. **No cross-layer agent reuse.** Flight-layer oversight is the per-wave Workflow's
   **reconcile** agent (the only cross-flight view — already exists). Wave-layer oversight is
   this **new** agent. Different altitudes, different context. Reusing one across layers would
   only add churn and a coupling seam; Prime/reconcile context dissolves at wave end and is
   not a concern to economize.

4. **Mode split.** **Auto** = campaign Workflow + the judgment seam. **Interactive** =
   human-paced per-wave loop (the human *is* the judgment; nothing to stall-guard). #736 dies
   in both.

## 3. The seed — make-or-break

The whole design lives or dies on **how we seed the wave-oversight agent**. The decisions:

**No distillation.** The degradation risk lives entirely in a lossy summarization step — so
we delete that step. We hand the agent the **complete raw record + read/inspect tools** and
let *it* distill. The raw durable record is *more* complete than a running orchestrator's
compacted memory of the same events, so the agent is given *more*, not less. ("Fear is the
mind-killer" — the fear was of a step we are not taking.)

The seed comprises:

- **Intent — tiered, graceful degradation** (there is not always a devspec):
  1. **devspec** → hard checks: VRTM traceability + Deliverables-Manifest coverage via the
     `dod_*` / `devspec_*` tools.
  2. **plan issue / DDD domain model / sketchbook** → decision ledger + domain intent
     (`devspec_locate`, `ddd_locate_domain_model`, `ddd_locate_sketchbook` discover what exists).
  3. **just the issues** → each issue's own acceptance criteria + the wave plan. Always present.
  The agent is **told which tier it is on** and calibrates — rigorous spec-fidelity with a
  devspec; "ACs met + trajectory coherent" with only issues. Naming the tier prevents both
  faking a check it cannot do and hedging when it has solid ground.

- **Durable cross-wave trajectory** — for *every* completed wave, the raw structured record:
  `{gate, promoted}`, all four trust signals + their detail payloads, `concerns[]`,
  `deferrals[]`, rework / re-open events, the commutativity verdict, MRs/commits landed,
  issues closed. **Accumulated across waves** (see §5).

- **The just-landed wave in full** — its kahuna-vs-protected diff, gate signals, reconcile report.

- **The remaining plan** — so the judgment is "sound to proceed *into the rest*."

- **Live inspection** — read tools + the kahuna branch available, so it *goes and looks at the
  actual code* when something smells. A real inspection, not a record-reader.

- **Output schema** — `{ continue: bool, confidence, concern: { what, which_waves,
  which_subsystem, severity }, recommendation }`.

## 4. The prompt is the lens

Same record, wrong lens, and the checkpoint rubber-stamps. The prompt encodes the two failure
classes the per-wave gate **cannot** catch:

- **Accumulation** — every wave gated green, but waves 2, 4, 5 all raised concerns / deferrals
  / rework in the *same subsystem* ⇒ a lurking architectural problem each individual gate
  passed. ("Problems build over time until they explode," made into a checkpoint.)
- **Intent-drift** — a wave passes its *own* tests yet builds something other than what we
  specified. This is gameable at the per-wave layer (the flight writes both the code and the
  bar — the migration pilot proved *self-authored green tests ≠ correct-to-intent*). The
  devspec at the campaign layer is the **un-gameable** reference the flights did not write.

The prompt also tells the agent to **distinguish adaptation from drift**: a deviation that was
*consciously recorded* (a deferral, a logged concern) is adaptation; a *silent* deviation from
intent is drift. Devspec **+** trajectory together make that discrimination possible.

## 5. The concern-trajectory facility

The accumulated cross-wave record is **campaign state**, and the campaign layer's resume model
is **reboot-proof** (it was kept out of a nested Workflow precisely so it resumes from
durable `wave-status` across reboots / restarts / session poisoning). Therefore the trajectory
**must be durable** — holding it only in the campaign Workflow's memory means a reboot at wave
5 resumes with a judgment agent **blind to waves 1–4**: not context-creep, a silent
correctness hole, the exact "explodes later" failure now invisible across a restart.

Decision: a **dedicated structured concern/trajectory record in the `wave-status` family
(JSON** — not a new sqlite dependency, not free-form markdown the agent must parse loosely and
the dashboard cannot render). Written by **`persistIteration`** each wave (the existing
per-wave persistence seam, #688), **accumulating cross-wave**. **One artifact, three
consumers:** the judgment seed, the resume substrate, and the #738 dashboard. Forced by
durability; cleaner regardless.

## 6. Consequences for the open work

- **#736 (stall-guard) — dissolved.** Not made async-aware; deleted, because the auto loop is
  now a Workflow that cannot stall and interactive is human-paced. Re-scope #736 to point here.
- **#738 (coarse driver-states) — grows load-bearing.** Its persistence is now the *judgment
  seed*, not just a dashboard. The cross-wave trajectory accumulation is the new requirement.
- **Net-new work** (decompose into sub-issues / waves):
  1. The **auto-mode campaign Workflow** (loop over pending waves, run the per-wave spine,
     route on verdict, hold-and-end on a flag).
  2. The **wave-oversight agent** + the **seed contract** (intent-tier resolver, trajectory
     embed, live-inspection wiring, output schema) + the **judgment prompt** (the lens).
  3. The **concern-trajectory facility** in `persistIteration` (durable cross-wave record).
  4. The **mode split** (auto → Workflow; interactive → human-paced loop) and retiring the
     stall-guard + `wavemachine_active` plumbing it no longer needs.

## 7. Open question — the failure-shape smells

The judgment is only as good as the smells it hunts for. The remaining input (BJ's domain
knowledge of campaigns that actually exploded): **name the 3–4 concrete failure-shapes in the
record** — concern *volume*, the same *area* recurring, commutativity trend
(STRONG→MEDIUM→ORACLE_REQUIRED), rework rate, scope creep, something subtler — so they are
baked into both the seed's derived-lens and the judgment prompt. That list is the difference
between a checkpoint that works and one that rubber-stamps. (To be filled in before §6.2 ships.)

## 8. Why this is right (one paragraph)

The migration's thesis was "control flow becomes code, not an LLM driving a loop." We applied
it to the per-wave spine and stopped at the campaign layer, then spent weeks patching the cage
that the unfinished migration required. This finishes it — *and* recovers the judgment facility
pure determinism would have deleted, by relocating that judgment from the **loop driver** (where
it makes the loop non-deterministic) to a **called seam** (where it does not). Determinism and
intelligence stop being a trade and become a layering.
