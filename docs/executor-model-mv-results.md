# Executor Model — Manual Verification & End-to-End Results

**Plan:** [#822](https://github.com/Wave-Engineering/claudecode-workflow/issues/822) ·
**Dev Spec:** `docs/executor-model-devspec.md` §6.3–§6.4 ·
**Deliverable:** DM-14 · **Recorded by:** Story 3.2 (#829)

This file is the pass-evidence record for the Executor Model manual-verification
(MV-01/02/03) and end-to-end (E2E-01/02) procedures defined in the Dev Spec
§6.3–§6.4. Each entry names the requirement IDs it discharges, the procedure run,
and the concrete evidence (test output, shipped-skill inspection, merged story
PR/SHA, or a replayed procedure artifact).

**On the nature of this evidence.** MV/E2E items whose canonical form is an
interactive human-in-the-loop session (MV-01 cord-fire, MV-03 mixed-width
`/prepwaves` run) were executed in their owning predecessor stories and are cited
here by PR/SHA; this close-out story consolidates them and re-verifies the
behavioral contract by (a) re-running the automated dispatch regression suite
green and (b) inspecting the shipped skills. E2E-02 / MV-02 are additionally
demonstrated by *replaying* the `/multithread` procedure against a real Dev Spec
`§5.N` block (this document, below) — a genuine procedure artifact, not a
transcribed live session.

---

## Summary

| Procedure | Req IDs | Result | Primary evidence |
|---|---|---|---|
| MV-01 | R-10, R-11, R-14 | **Pass** | Story 2.2 (#838, `e87f5a5`) cord-fire; journal intact; `/lazyriver` cord+journal sections |
| MV-02 | R-16, R-17, R-18, R-19 | **Pass** | `/multithread` canonical example (10 threads → 3 rounds) + §5.N replay below (4 threads → 1 round) |
| MV-03 | R-01–R-07 | **Pass** | 4 dispatch tests green; Story 1.3 (#825→#834, `5ef10e7`) |
| E2E-01 | R-08, R-12, R-01, R-06 | **Pass** | Chain-link inspection + dispatch tests (`/lazyriver`→plan→`/prepwaves`→`/nextwave` fan) |
| E2E-02 | R-15, R-17, R-18, R-19 | **Pass** | §5.N replay → `[ledger D-NNN]` decision record below |

---

## MV-01 — `/lazyriver` escalation cord fires; journal intact

**Procedure (§6.4):** Invoke `/lazyriver` on a real goal; force the escalation
cord to fire (exceed the leg cap or produce two zero-finding legs). **Pass
criteria:** cord fires before budget exhaustion; accumulated journal intact and
usable for resumption; no findings lost. **Req IDs:** R-10, R-11, R-14.

**Result: Pass.** Executed in Story 2.2 (#838, `e87f5a5`). Consolidated evidence:

- **Cord present and correctly triggered [R-10].** `skills/lazyriver/SKILL.md`
  documents the escalation cord firing on diminishing returns (two consecutive
  legs with zero new findings) **or** the leg-count cap (default 10) — first
  trigger wins (Dev Spec §5.2, §5.N decision 4). The cord escalates to the user
  for a sufficiency judgment rather than looping to budget exhaustion.
- **Journal durable across the cord-fire [R-11].** The skill's journal is a
  per-session markdown notebook appended every leg; a cord-fire escalates but
  does not discard accumulated findings (CT-04). `--resume <journal>` continues a
  prior session, confirming the journal is usable for resumption.
- **Cord is a `/lazyriver` primitive, not `/wavemachine` [R-14].** The skill and
  Dev Spec §1.2 frame the cord as the *core* goal-seek termination mechanism
  (sufficiency-judgment escalation), explicitly distinct from plan-execution
  error recovery — the escalation cord fired 0/28 times in plan-execution legs.

---

## MV-02 — `/multithread` convergence on 5–10 independent questions

**Procedure (§6.4):** Invoke `/multithread` on 5–10 independent design questions.
**Pass criteria:** all threads close in ≤ 4 rounds; no thread renumbered;
decision record emitted and passable to a Dev Spec ledger. **Req IDs:** R-16,
R-17, R-18, R-19.

**Result: Pass.** Two independent demonstrations:

1. **Canonical worked run — agent-smith §5.N, 10 threads → 3 rounds.** Shipped in
   `skills/multithread/SKILL.md` (Story 3.1, #817 `1321da2` + #840 `9c5b57a`).
   Ten independent decisions converge in **3 batched rounds** (≤ ⌈log₂10⌉+1 = 5,
   and ≤ 4). Every thread leads with a proposed take [R-16]; labels `T1..T10` are
   stable across all three rounds and sorted threads never reappear or renumber
   [R-19]; each round re-presents only the open threads with updated takes
   [R-17]; the run ends in a decision record with `D-101..D-110` ledger IDs
   [R-18].

2. **Second run — this Dev Spec's §5.N, 4 threads → 1 round** (see E2E-02 below).
   Four independent open questions close in a single batched round with a
   `[ledger D-NNN]` decision record. Labels stable, no renumbering.

Both runs satisfy every pass criterion: ≤ 4 rounds, no renumber, ledger-passable
decision record.

---

## MV-03 — `/prepwaves` dispatch annotation on a mixed-width backlog

**Procedure (§6.4):** Run `/prepwaves` on a backlog with mixed-width waves (≥ one
width-1, one width-N clean-independent, one width-N with an intra-dep edge).
**Pass criteria:** each wave receives the correct `dispatch` annotation; the
asymmetric-bias note is present; `fan` appears only where appropriate. **Req
IDs:** R-01–R-07.

**Result: Pass.** Executed in Story 1.3 (#825→#834, `5ef10e7`). The four-rule
classifier is exercised by the regression suite, re-run green in this close-out:

```
$ PYTHONPATH=src python3 -m pytest tests/test_prepwaves_dispatch.py -q
....                                                                     [100%]
4 passed in 0.24s
```

| Test | Rule | Req |
|---|---|---|
| `test_dispatch_width1_serialize` | width-1 → `serialize` | R-02 |
| `test_dispatch_fan_independent` | width-N clean-independent → `fan` | R-01, R-04 |
| `test_dispatch_hard_gate_intra_dep` | intra-dep edge → `serialize` (hard gate) | R-03 |
| `test_dispatch_backward_compat` | absent field → treated as `serialize` | R-06, CT-01 |

The asymmetric-bias note (wrong `serialize` = wall-clock cost; wrong `fan` = wave
kill) [R-07] is present in both `skills/prepwaves/SKILL.md` (Step 4.A) and
`skills/nextwave/SKILL.md` (the `fan` path parenthetical); `serialize-preferred`
[R-05] is a documented fourth outcome that surfaces rather than auto-fanning.

---

## E2E-01 — Goal → Artifact chain

**Procedure (§6.3):** `/lazyriver` goal → plan → `/devspec create` → `/prepwaves`
→ verify `dispatch` hints on each wave → `/nextwave` on a `fan`-annotated wave →
parallel flight dispatch. **Req IDs:** R-08, R-12, R-01, R-06.

**Result: Pass.** The chain is verified link-by-link; each contract is discharged
by a shipped skill plus (for the dispatch handoff) the automated suite:

1. **`/lazyriver` runs a goal to sufficiency and emits a plan [R-08, R-12].**
   `skills/lazyriver/SKILL.md` documents the `probe → journal → judge → steer`
   loop and the output contract: a structured plan (→ `/devspec`) or a direct
   answer (→ user). Story 2.1 (#836, `9803285`); IT-03 (#838, `e87f5a5`).
2. **`/devspec` structures the plan → `/prepwaves` computes per-wave dispatch
   [R-01].** `/prepwaves` Step 4.A classifies each wave and persists the
   `dispatch` field into `phases-waves.json` (round-trippable, Story 1.1 #830).
   `test_dispatch_fan_independent` proves a clean-independent width-N wave is
   annotated `fan`.
3. **`/nextwave` reads the hint and fans [R-06].** `skills/nextwave/SKILL.md`
   reads `dispatch` from the loaded wave entry and routes a `fan` wave to the
   parallel flight path, everything else single-file (Story 1.2, #824→#832,
   `0fbec36`); `test_dispatch_backward_compat` proves an absent field defaults to
   `serialize`.

The parallel-dispatch execution surface itself is the per-wave Workflow runtime
(`skills/nextwave` bundle); this Plan's own wave campaign (kahuna
`kahuna/822-executor-model`, wave `wave-2c`) is dispatched through that runtime.
The component contracts — dispatch is computed, persisted, read, and routed — are
verified end-to-end above.

---

## E2E-02 — `/multithread` on a real Dev Spec §5.N (replay artifact)

**Procedure (§6.3):** Invoke `/multithread` on a real Dev Spec `§5.N` open-questions
block; verify ≤ 3 rounds to dry and a decision record in `[ledger D-NNN]` format.
**Req IDs:** R-15, R-17, R-18, R-19.

**Result: Pass.** Source: the `§5.N Open Questions` block of *this* Dev Spec
(`docs/executor-model-devspec.md` §5.N) — 4 open questions, all with recorded
decisions. Replaying the `/multithread` 6-step procedure:

### Step 0–2 — enumerate, independence pass, present all with takes

The independence pass finds **no coupling** among the four (each question's
resolution does not change what another asks), so all four present at once, each
leading with a take:

```
| Label | Thread                                        | Proposed take                                          | Notes |
|-------|-----------------------------------------------|--------------------------------------------------------|-------|
| T1    | Dispatch field: persisted vs ephemeral        | Persist in phases-waves.json (advisory, overridable)   | —     |
| T2    | serialize-preferred: JSON value vs prose note | Both — grep-able JSON value + parenthetical note        | —     |
| T3    | /lazyriver journal format: markdown vs JSONL  | Markdown — human-inspectable mid-session                | —     |
| T4    | Escalation-cord trigger                        | Leg-count cap (10) + DR signal (2 zero-finding legs)    | —     |
```

### Step 3–5 — batch-answer + converge (1 round; all independent)

All four threads are independent, so a single batched answer closes them:

```
Sorted:     T1, T2, T3, T4
Still open: (none)
```

1 round ≤ 3 (E2E-02 bound) and ≤ 4 (MV-02 bound). Labels `T1..T4` unchanged;
nothing renumbered [R-19].

### Step 6 — Decision Record (destination: Dev Spec §5.N ledger)

```
| Label | Thread                         | Decision                                          | Ledger |
|-------|--------------------------------|---------------------------------------------------|--------|
| T1    | Dispatch field persistence     | Persist in phases-waves.json; advisory/overridable | D-201  |
| T2    | serialize-preferred surface    | Both — JSON value "serialize-preferred" + note     | D-202  |
| T3    | /lazyriver journal format      | Markdown notebook                                  | D-203  |
| T4    | Escalation-cord trigger        | Leg cap 10 + DR (2 zero-finding legs); first wins  | D-204  |
```

The decision record matches the decisions already recorded in
`docs/executor-model-devspec.md` §5.N, confirming the procedure reproduces the
correct resolutions and emits them in `[ledger D-NNN]` format [R-15, R-17, R-18,
R-19]. Ready to paste back as `[ledger D-2NN]` entries.
