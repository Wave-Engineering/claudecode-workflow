---
name: lazyriver
description: Goal-seek loop — probe, judge sufficiency, steer, journal; emits a plan or answer
usage: |
  /lazyriver <goal statement>            Run the goal-seek loop toward a sufficiency judgment
  /lazyriver <goal> --resume <journal>   Continue a prior session from its findings journal
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-lazyriver does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-lazyriver
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# LazyRiver — Goal-Seek Loop

Run a **goal** — not a plan — to **sufficiency**. `/lazyriver` is the goal-seek half of
the executor model: give it an insight to reach, a hypothesis to test, or a design to
converge on, and it runs a `probe → journal → judge → steer` loop until the goal is met,
then emits either a **plan** (hand to `/devspec`) or a **direct answer** (hand to the user).

**See Also:** `docs/executor-model-devspec.md` (Plan #822 — the two-mode executor: this
skill is the goal-seek activity, distinct from the plan-execution activity that
`/wavemachine` / `/nextwave` run).

> **This is NOT a variant of `/wavemachine` or `/nextwave`.** Those execute a *known DAG to
> completeness* (plan-execution). `/lazyriver` seeks a *goal to sufficiency* (goal-seek).
> Different termination condition, different parallelizability, different agency profile.
> Conflating the two is the exact conceptual error Plan #822 fixes — see
> **Epistemic vs Artifact Dependency** below.

---

## Invocation

```
/lazyriver <goal statement>
```

Optional:

```
/lazyriver <goal statement> --resume <journal-path>
```

`<goal statement>` is a goal, not a task list. It terminates on a **judgment** ("are we
there?"), not a checklist:

| Goal type | Example |
|-----------|---------|
| Understand | `/lazyriver "understand why merges stall on the kahuna branch"` |
| Test a hypothesis | `/lazyriver "is the 1.18× pool advantage real or measurement noise?"` |
| Converge a design | `/lazyriver "get to an executor model we trust"` |
| Root-cause | `/lazyriver "find the root cause of the reseed fidelity loss"` |

`--resume <journal-path>` reopens a prior session's **findings journal** (see below) and
continues the loop from the accumulated state — the loop never starts cold if a journal
exists. This is what makes a cord-fire (escalation) recoverable rather than terminal.

---

## Core Loop

Each **leg** of the loop is one recorded, resumable unit. A leg runs four steps in order:

```
Loop (each leg):
  1. Probe   — run the current leg: research, experiment, implement-a-spike, or analyze.
               The probe is chosen by Step 4 of the *previous* leg (or the goal, on leg 1).
  2. Journal — append this leg's findings to the durable per-session journal.
  3. Judge   — sufficiency gate: "are we there yet?"
                 SUFFICIENT       → emit output (plan | answer) → TERMINATE
                 DIMINISHING/CAP  → escalation cord fires → ESCALATE to user
                 NOT YET          → continue to Step 4
  4. Steer   — formulate the next probe *from what this leg just taught*:
               "given what we now know, what is the single most informative next probe?"
               → set it as leg N+1's Probe → goto 1
```

The order is load-bearing: **journal before judge** (so the sufficiency call is made
against a durable record, and a cord-fire never loses the leg it just ran), and **judge
before steer** (so you never formulate a next probe for a goal that is already met).

This is a `ralph-wiggum` loop *unrolled*: a raw `while not done: try()` retry is agency ≈ 0.
Unrolling upgrades it three ways — **+ agency** (Step 4 judges the result and steers the
next probe), **+ memory** (Step 2's journal accumulates; the loop gets smarter each leg),
and **+ durability** (each leg is a recorded, resumable unit). LazyRiver = ralph-wiggum
**with a brain and a notebook.** Without the sufficiency gate and the escalation cord it
would just be an *expensive infinite loop* — the characteristic ralph failure mode.

---

## Execution Modes — in-session vs. background Workflow

The `probe → journal → judge → steer` loop above runs two ways; the *logic is
identical*, only *where it runs* differs:

- **In-session (synchronous).** The main agent runs the loop directly in its own
  context — the original mode. Best for a short goal-seek you want to watch, or
  when you are already the agent doing the probing.
- **Background Workflow (detached, #844).** The loop runs as a **background
  Workflow** — `skills/lazyriver/lazyriver-workflow.bundled.js` — so the
  operator's session stays interactive while the goal-seek floats. Same
  architecture the wave engine uses (`per-wave-workflow.js`); it completes the
  executor model's symmetry — both plan-execution *and* goal-seek run as
  background Workflows sharing the substrate, keeping their distinct logic.

**Launching the background Workflow** — invoke the Workflow tool with
`scriptPath: skills/lazyriver/lazyriver-workflow.bundled.js` and `args` (a JSON
object):

| arg | meaning |
|-----|---------|
| `goal` | the goal statement (required) |
| `journalPath` | durable markdown path the leg agents append to and `resume` reopens (**required** — the Workflow script has no filesystem, so the launcher supplies the path; all journal I/O + timestamps happen inside the leg agents, which have Bash/Write) |
| `maxLegs` | leg-count cap (default 10) |
| `resume` | `true` to rehydrate from an existing `journalPath` — the loop never starts cold if a journal exists. Resume is a "keep probing" signal: the diminishing cord counter **resets** (fresh legs, not an instant re-fire); raise `maxLegs` to resume past a leg-cap |

**The verdict** the Workflow returns — the driver *surfaces* it; it is **never a
silent background stall**:

- `{ outcome: 'sufficient', output: { kind: 'plan' | 'answer', content }, journalPath, legs }`
  — the goal is met; hand `output` to `/devspec` (plan) or the user (answer), per the Output Contract.
- `{ outcome: 'escalated', reason, journalPath, legs }` — the **escalation cord**
  fired (`cord:diminishing` = 2 consecutive zero-finding legs, or `cord:leg-cap`).
  The driver surfaces the journal + the sufficiency question to the operator,
  exactly like a wave HOLD. The journal is intact and `resume`-able (CT-04).

**Division of labor** (mirrors the wave engine): the sufficiency *call* is the
leg agent's judgment; the *cord* is a coded loop-guard in the Workflow script
(`river.js#cordCheck`) that cannot be forgotten. Source of truth:
`lazyriver-workflow.js` + `river.js`; regenerate the bundle with
`node skills/lazyriver/bundle.mjs` (drift-guarded by
`tests/regression/test_lazyriver_bundle_in_sync.sh`).

---

## Sufficiency Gate

**Re-evaluated at Step 3 of every leg** — it is the loop's termination condition, not a
one-time end check. Completeness (did all the DAG?) is *countable*; sufficiency (did we
reach the goal?) is a **call**. Every leg the gate asks:

> **"Are we there yet — and if not, what is the single most informative next probe?"**

Three outcomes:

- **Sufficient** → the goal is answered / the design is trusted / the hypothesis is
  decided. Emit the Output Contract and terminate.
- **Diminishing returns or budget exhausted** → the escalation cord fires (see below). Do
  **not** keep looping — hand the sufficiency judgment to the user.
- **Not yet, and still converging** → steer to the next probe (Step 4) and run another leg.

The gate is a *judgment*, and the agent owns it every leg. That is the whole reason
goal-seek needs a high-agency agent rather than a headless pool: someone has to decide
"are we there?" — and, when it is genuinely a close call, escalate rather than guess.

---

## Escalation Cord

> **The escalation cord is a `/lazyriver` primitive — NOT a `/wavemachine` primitive.**
> Its role is **safe loop termination in goal-seek**, not error recovery in plan-execution.
> Across all 28 legs of a plan-execution build (agent-smith) the cord fired **0 times** —
> because in plan-execution everything is known and there is nothing to escalate but a rare
> hard blocker; the cord is *vestigial* there. In goal-seek, *"am I converging? is this
> sufficient? am I stuck?"* **is the loop condition itself**, and escalate-to-human-for-a-
> sufficiency-judgment is how the loop terminates safely instead of spinning. The cord's
> home is here. (Full rationale: `docs/executor-model-devspec.md` §1.2, Appendix B.)

**Trigger — first of these to fire wins:**

| Trigger | Default | Signal |
|---------|---------|--------|
| Diminishing returns | 2 consecutive legs with **zero new findings** | The map has stopped moving — more probing is unlikely to change the sufficiency call. |
| Leg-count cap | **10 legs** | Budget guardrail against an infinite loop even if each leg still finds something. |

**On cord-fire:**

1. **Stop looping.** Do not formulate another probe.
2. **Escalate to the user** for a sufficiency judgment: present the journal so far, the
   current best answer/plan, and the specific question — *"is this good enough, or is there
   a probe you want me to run?"*
3. **The journal is intact.** A cord-fire is **not a data-loss event** (CT-04). Every
   finding accumulated across every leg is durable on disk; the user can accept the current
   state, redirect, or `--resume` the session later. The cord ends the *auto-loop*, not the
   *work*.

Escalate-don't-loop is the discipline: the moment the gate reads "diminishing" or the cap
is hit, the correct move is a human sufficiency call, never one more speculative leg.

---

## Findings Journal

`/lazyriver` maintains a **per-session findings journal** — a durable markdown notebook
that accumulates across legs. It is the loop's memory *and* its durability mechanism.

- **Format: markdown** (not JSONL). BJ can inspect it mid-session, and it matches the
  spike-notebook format that worked (`docs/executor-model-devspec.md` §5.N decision 3).
- **Append-only across legs.** Each leg's Step 2 appends a dated entry: the probe run, the
  findings (or explicitly "zero new findings" — that record is what the cord counts), and
  the steer decision that set the next probe.
- **Durable = resumable.** The journal is what `--resume <journal-path>` reopens. Because
  the journal is written *before* the judge step, a cord-fire, a crash, or a deliberate
  pause all leave a complete, resumable record. **Cord-fire ≠ data loss** (CT-04).

Suggested entry shape:

```markdown
## Leg N — <probe description>  (<date>)
**Probe:** what was run this leg
**Findings:** what we learned — or "zero new findings"
**Sufficiency:** <sufficient | not-yet | diminishing/cap → escalated>
**Steer:** the next probe (if continuing)
```

---

## Output Contract

When the sufficiency gate reads **sufficient**, the loop terminates on exactly one of two
outputs:

| Output | When | Handed to |
|--------|------|-----------|
| **Structured plan** | The goal-seek converged on *what should be built* | `/devspec` — structures it into a Dev Spec, then `/prepwaves` → `/wavemachine` execute it |
| **Direct answer** | The goal was an insight, a decision, or a root cause — no build follows | The **user** — the answer *is* the deliverable |

A goal-seek "done" means **answered**, however it turns out — not *artifact delivered*.
Emitting a plan does not mean the plan runs; it means the plan is now sufficient to hand to
plan-execution. The journal accompanies the output as the audit trail of how the
conclusion was reached.

---

## Relationship to /devspec

`/lazyriver` sits **upstream** of `/devspec` — it produces the input `/devspec` structures.
They **chain**; they do not compete:

```
 GOAL ──▶ [ /lazyriver ] ──▶ PLAN ──▶ [ /devspec ] ──▶ [ /wavemachine ] ──▶ ARTIFACT
          goal-seek loop            plan-structure       per-wave executor
          sufficiency-gated         + dispatch hints     fans / serializes per wave
          escalation-corded         (via /prepwaves)     completeness-gated
```

This is the DDD pipeline the kit already half-has: `/ddd`→`/devspec` *is* a goal-seek
(explore the domain until the design is sufficient), and `/prepwaves`→`/wavemachine` *is*
the plan-run. `/lazyriver` names and generalizes the upstream half. It is **not** a rival
to `/wavemachine` — it is the activity that *feeds* it.

**And they interleave.** When plan-execution hits something the plan didn't foresee (a wave
surfaces an unknown), the right move is to **drop back into `/lazyriver`** for that unknown,
resolve it to sufficiency, emit a plan patch, and **resume** the plan-run. A campaign is a
serial spine of plan-execution with goal-seek excursions wherever reality outruns the spec.

---

## Epistemic vs Artifact Dependency

The two activities differ most sharply in *why* they are (or are not) parallelizable. This
distinction is the reason `/lazyriver` cannot be a headless pool and is not merely
"serialize every wave":

| | **Plan-execution** (`/wavemachine`) | **Goal-seek** (`/lazyriver`) |
|---|---|---|
| Input | a complete, exact **DAG** (the spec / §8) | a **goal** |
| Terminates on | **completeness** — did all the DAG | **sufficiency** — a judgment |
| Dependency kind | **artifact** — B needs the file A produces | **epistemic** — you don't know what leg N+1 *is* until leg N tells you what you learned |
| Visible in a DAG? | yes — the edge is drawable at plan time | **no** — the map is drawn *by the walking* |
| Parallelizable? | **yes**, per-wave, wherever artifact deps are absent | **no** — epistemic dependency is intrinsically serial |
| Agency | A ≈ 0 (execute the spec) | A maximal (each leg is a steering judgment) |
| Escalation cord | vestigial (0/28 fires) | **core loop** |

**Artifact dependency** (plan-execution): story B depends on A because A produces an
artifact B consumes — an edge visible in the DAG, fannable *wherever it is absent*.
**Epistemic dependency** (goal-seek): leg N+1 depends on leg N because you cannot even
*formulate* leg N+1 until leg N's findings land. That dependency is invisible to any DAG,
unplannable, and impossible to parallelize away. It is the real reason the lazy-river is
its own activity rather than collapsing into "serialize every wave."

---

## Reasoning Rules

These govern how each leg is run. They are load-bearing — the systematic answers the
lazy-river spike (F-10, F-11) proved out across a full campaign.

1. **DI-seam-then-close for a forward dependency (F-10).** When a leg needs something not
   yet built, do **not** block and do **not** escalate reflexively. Inject a
   dependency-injected *seam* — a default that works today — and record it in the journal.
   A later leg supplies the real default and **closes the seam** with no call-site churn.
   This is the river's systematic answer to float-order friction: it was confirmed 5×
   across 4 phases of the agent-smith build, including a seam opened in one phase and closed
   a phase later by a config switch alone. **Fill-with-a-seam is the default for a forward
   dep; escalate only when you genuinely cannot seam it.**

2. **Zero-new-findings is the cord signal — trust it.** Two consecutive legs that add
   nothing to the journal is the diminishing-returns trigger. Do not talk yourself into "one
   more probe" — a flat journal is the map telling you more probing won't change the
   sufficiency call. Journal the zero-finding leg honestly (that record is what the cord
   counts) and let the cord fire.

3. **Escalate, don't loop.** When the sufficiency gate reads "diminishing" or the leg cap is
   hit, the correct move is a **human sufficiency judgment**, never another speculative leg.
   An unrolled-ralph loop without this discipline is just an expensive infinite loop. The
   cord terminates the auto-loop safely; the journal keeps the work.

4. **Journal every leg, before you judge.** The findings record is written at Step 2, before
   the Step 3 sufficiency call — so the judgment is made against a durable record and a
   cord-fire never loses the leg it just ran. Durability is not a nice-to-have; it is what
   makes the cord safe and `--resume` possible.

---

## When to Use / When Not to Use

### Use it when

- The **plan does not exist yet** — you have a goal, not a DAG. "Find the root cause." "Is
  hypothesis H true?" "Get to a design we trust."
- Termination is a **sufficiency judgment**, not a checklist — done means *answered*,
  however it turns out.
- Each next step is **discovered from the last** (epistemic dependency) — the map is drawn
  by the walking.

### Do not use it when

- **You already have a complete plan / DAG.** That is plan-execution — hand it to
  `/devspec`→`/prepwaves`→`/wavemachine`, not here. A thin or bad spec is *still*
  plan-execution (with a bad plan), not goal-seek.
- **The work is mechanical and known** — no judgment per step, nothing to steer. Run it as
  a wave.
- **A single, known question with a lookup answer** — just answer it; there is no loop.

**The discriminator** is the **termination condition**: if "done" is *countable*
(completeness), it is plan-execution; if "done" is a *call* (sufficiency), it is
`/lazyriver`.

---

## See Also

- `docs/executor-model-devspec.md` — Plan #822 Executor Model dev spec (this skill is
  Story 2.1 / DM-10; the two-mode reframe, requirements R-08…R-14, and Appendix B live
  there).
- `/devspec` — the downstream skill that structures a `/lazyriver` plan output.
- `/wavemachine`, `/nextwave` — the plan-execution executors `/lazyriver` feeds (distinct
  activity, not a variant).
- `/multithread` — the facilitation companion usable during a `/lazyriver` sub-question
  round.
