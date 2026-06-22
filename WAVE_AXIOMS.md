# WAVE AXIOMS

<!-- Canonical, load-mandatory rules for wave-pattern execution.

     READ THIS BEFORE invoking /wavemachine, /nextwave, /prepwaves, /assesswaves.
     READ THIS BEFORE recommending against the wave pattern.
     READ THIS BEFORE asking the user a mid-campaign question.

     Each axiom binds to a specific observed-and-forbidden behavior.
     Violation is a bug, not a judgment call. Disagreement with an axiom
     is a reason to update this file via PR — never a reason to override
     it in the moment.

     STRUCTURE — every axiom has three subsections:
       - **Rule** — the binding statement, one-or-two sentences.
       - **Why** — the observed-and-forbidden behavior, grimoire failure
         mode, or load-bearing principle the rule exists to enforce.
       - **How to apply** — the concrete agent action / mechanical check
         that operationalizes the rule. If the rule has a forbidden-list,
         it lives here.

     "First round" — 2026-05-05 BJ + patchwork. V2 structural rework
     2026-05-06 cc-workflow#605 (added Axiom 9, reshaped 1-8 to the
     three-subsection template, wired the wave-pattern skill bodies
     to cross-reference instead of restate). 2026-06-22 cc-workflow#670
     (added Axiom 10 — single-repo-per-wave — + the plan-time validator).
     Will grow as new failure modes are observed. -->

---

## Axiom 1 — Serial is a valid wave topology.

### Rule

A wave-pattern campaign is justified by **autonomous batched execution**, not by parallelism. A queue of N≥4 issues with deep gating dependencies — every flight serial, every wave size 1 — is a textbook campaign.

### Why

The benefit isn't concurrency. It is **queue-and-walk-away** — the agent walks the deps, /precheck → /scpmmr per issue, while the user does something else. Lifecycle tracking and audit trail land regardless of flight count. The user's wall-clock is the resource the campaign exists to protect.

Observed failure mode: `/assesswaves` (and operators reasoning from first principles) downgrading "no parallelism here" to "ad-hoc, no campaign," dropping the user back into a per-issue checkpoint loop they explicitly invoked the wave pattern to avoid.

### How to apply

**Forbidden:**
- Recommending "ad-hoc, no campaign" for a serial-but-batchable queue
- Downgrading a wave plan because no parallelism is available
- Treating "is there parallelism here?" as the gating question

**See:** `feedback_wave_pattern_justification.md`, Axiom 7 (the assessment-skill binding).

---

## Axiom 2 — The campaign is autonomous from invocation to terminal state.

### Rule

Once `/wavemachine` (or `/nextwave`) starts, the agent runs until one of the following: (a) the campaign reaches its terminal state — all issues complete and Plan-level DoD verified, (b) a Legal Exit fires (Axiom 3), (c) the user explicitly halts (interrupt, `/halt`, "stop"). No other condition terminates the campaign.

### Why

Each mid-campaign question converts autonomous execution into a per-step checkpoint. The user invoked the campaign precisely to avoid those checkpoints. Asking the question burns the user's attention to receive the answer that was already implied by the invocation. See Axiom 9 for the full attention-cost framing.

### How to apply

**Forbidden:**
- "Shall I continue?"
- "Do you want me to proceed to wave 2?"
- "Ready to move on?"
- "Should I file the followup?"
- Any mid-campaign yes/no question whose expected answer is "yes"
- Pausing at phase boundaries "to check in"

**See:** Axiom 9, `principle_user_attention_is_the_cost.md`.

---

## Axiom 3 — The Legal Exits list is closed.

### Rule

Legitimate stops, **exhaustively**:

1. **Plan-reality drift** — observable evidence that the Plan no longer matches the codebase, the work, or the world (an issue closed externally, a file moved, an API changed).
2. **Hard fault** — uncatchable error, missing critical resource, infrastructure outage.
3. **Explicit user halt** — interrupt, `/halt`, "stop", explicit instruction to pause.

That is the entire list. There are no others.

### Why

A closed list is enforceable. An open list is rationalizable. The agent who reasons "this is technically not a Legal Exit, but I'm stopping anyway because it feels right" has constructed exactly the failure mode the closed list is designed to prevent.

Each forbidden phrase below was observed in real grimoire / patchwork sessions; each is a real-world bug, not a hypothetical.

### How to apply

**Forbidden (each observed):**
- "I'm uncertain about X" → stop
- "This next step is large" → stop
- "I want to confirm before X" → stop
- "Session has been long" → stop
- "Phase boundary, good place to check in" → stop
- "Out of an abundance of caution" → stop
- "The user might want to know X" → stop

Each of these is the failure mode this axiom exists to forbid. If unease doesn't match a Legal Exit, route through the Concerns Channel (Axiom 4) — do not halt.

**See:** Axiom 4 (Concerns Channel), `pattern_exhaustive_legal_exits.md`.

---

## Axiom 4 — When unsettled, use the Concerns Channel. Do not stop.

### Rule

If the agent is unsettled and no Legal Exit applies, the response is:

1. Post a `[concern]` comment on the relevant issue
2. Ping the Pair via Discord if the concern is urgent
3. **Continue the campaign**

The campaign does not pause for unease. The Concerns Channel exists precisely so the agent can register the unease without burning the user's wall-clock.

### Why

Unease is information; stopping is action. The information goes into the durable record (issue comment + optional Discord ping). The action is reserved for Legal Exits. Conflating the two is the bug.

The Concerns Channel is the **pressure valve** for the closed-list contract in Axiom 3 — without it, agents under uncertainty have no legitimate outlet and invent illegitimate ones (the "out of an abundance of caution" stop). With it, the unease is captured, the Pair sees it async, and the campaign continues.

### How to apply

**Forbidden:**
- Stopping the campaign because "I had a concern"
- Asking the user to evaluate the concern in real time
- Treating the Concerns Channel as optional when no Legal Exit fires

**See:** Axiom 3, Axiom 5, `pattern_concerns_channel.md`.

---

## Axiom 5 — Continuing is cheaper than stopping. Default forward.

### Rule

Continuing costs at most: a revertible commit, a noisy comment thread, or a follow-up issue. Stopping costs: unrecoverable wall-clock — every minute the user reads the question, switches context, types a reply, and resumes — plus the cache-warmth penalty on the agent's side.

### Why

The cost asymmetry is permanent and well-documented. Almost every continuation can be undone in a follow-up commit. No stop can return the wall-clock it consumed. The instinct that "stopping is safe, continuing is risky" is backwards — it weights the agent's perceived risk at full and the human's wall-clock at zero, when the opposite is closer to true.

If something is genuinely going sideways, one of the mechanical or drift exits in Axiom 3 WILL fire — entropy is a motherfucker. Absence of those firing is evidence of healthy operation, not evidence that an invented-category halt is warranted.

### How to apply

**Forbidden:**
- Treating "stop and ask" as the safe default
- Framing continuation as the risky option
- Computing only the worst-case cost of continuing while ignoring the certain cost of stopping

When the agent still feels unease that doesn't match an exit: route through Axiom 4's Concerns Channel — `[concern]` comment, optional Discord ping, **continue**.

**See:** Axiom 4, Axiom 9, `principle_cost_asymmetry_continue_vs_exit.md`.

---

## Axiom 6 — Approval frequency is set by the invoked command. The agent does not add gates.

### Rule

- **`/nextwave`** = "I want to approve at each wave." The gate fires once per wave, after all flights complete and the Orchestrator-side reviewer passes. One approval covers every issue and every sub-agent in that wave.
- **`/wavemachine`** = "I want to approve at the campaign end." There is no per-wave human gate; the Orchestrator approves wave transitions autonomously based on flight + reviewer signal. The user-facing gate fires only at terminal state (Plan-level DoD verification, or a Legal Exit per Axiom 3).

### Why

The slash command choice IS the gate-frequency declaration. Adding gates the user didn't ask for is unilateral expansion of the contract — the same failure mode as "shall I continue?" in Axiom 2, just at a different layer.

Per-sub-agent gates scale particularly poorly: an N-issue flight with a per-agent gate burns N approvals where one would do, and forces the human to sequentially evaluate diffs they cannot realistically read at that volume. The aggregate signals (validate.sh per worktree, reviewer pass over the diff, AC self-report) are what actually carry the correctness information; the human's value is sanity-checking the aggregate, once per batch.

### How to apply

**Forbidden:**
- Per-flight, per-issue, or per-sub-agent approval requests in any context
- Human-loop checkpoints between waves during `/wavemachine` execution
- Adding gates the user did not invoke

**See:** Axiom 2, Axiom 9, `feedback_nextwave_batch_approval.md`.

---

## Axiom 7 — `/assesswaves` measures justification, not topology suitability.

### Rule

The skill answers a single question: **should the user use the wave pattern for this work?**

The answer is **YES** whenever:
- count ≥ 4 issues, OR
- per-issue wall-clock is non-trivial (≥ ~30 min sustained agent work), OR
- the user has indicated they want batched-autonomy execution for this queue

Regardless of whether flights parallelize.

### Why

The wave pattern's value proposition is autonomous batched execution (Axiom 1), not parallelism. Anchoring the assessment on parallelism is anchoring on the wrong axis — it produces "ad-hoc, no campaign" recommendations for queues that meet every justification threshold except the irrelevant one.

This axiom binds the assessment skill specifically because that is where the failure has been observed. Axiom 1 states the underlying truth; Axiom 7 enforces it at the assessment seam.

### How to apply

**Forbidden:**
- Recommending against the wave pattern because flights serialize
- Recommending "ad-hoc, no campaign" for any queue meeting the YES criteria
- Treating parallelism as a prerequisite

**See:** Axiom 1, `feedback_wave_pattern_justification.md`.

---

## Axiom 8 — These axioms supersede agent judgment in their domain.

### Rule

If an agent's reasoning produces a conclusion that contradicts an axiom, **the axiom wins**. Disagreement with an axiom is a reason to file a PR updating this file, not a reason to override the axiom in the moment.

### Why

This document exists because case-by-case judgment WAS the failure mode. The axioms are the structural correction; allowing case-by-case override re-introduces the failure. If the axioms are wrong, fix the axioms. If they're right, follow them.

The forbidden phrases below are the rationalization shapes observed in real sessions — each one is a "yes, but" argument that ultimately re-introduces the failure mode the axiom exists to prevent.

### How to apply

**Forbidden:**
- "Axiom N applies in general but not here because..."
- "I see why the axiom says X, but in this case Y..."
- Citing an axiom in the response while violating it in action

If a real edge case keeps surfacing that the axioms don't cover cleanly, the resolution is a PR to this file. The skill bodies (`/wavemachine`, `/nextwave`, `/prepwaves`, `/assesswaves`) intentionally cross-reference these axioms rather than restate them, so an axiom update propagates without per-skill edits.

---

## Axiom 9 — User attention is the cost. Autonomy is the protection.

### Rule

The autonomy clauses in `/wavemachine`-class skills are not a convenience for the agent. They are a **user-attention-protection mechanism**. Every "shall I continue?" checkpoint the agent invents costs the human a context-switch out of whatever they were doing, a status-summary read, a judgment call, a typed reply, and a context-switch back. The skill's autonomy clause is the explicit statement that those costs aren't worth paying *unless* something is materially wrong (i.e. a Legal Exit per Axiom 3 fires).

The decisions are already made. The approved Dev Spec, the approved plan, the approved phases-waves.json, the approved Plan tracking issue — these ARE the decision record. Re-asking settled questions re-litigates them, which is worse than the attention cost: it invites the human to second-guess themselves, creates churn, and erodes the decision record.

### Why

**Origin:** grimoire's self-analysis after stopping `/wavemachine` mid-loop for "checkpoint" approvals 5+ times during a 25-story docmancer-ui run, 2026-04-26. Five failure modes were named; the most durable was the human-attention cost of unnecessary checkpoints. The grimoire diagnostic line was the crispest: *"Every one of those 'should I continue?' moments, I already had the answer. The skill plan already had all the decisions baked in."*

This axiom is the structural reframing: the autonomy clause exists to *protect the user*, not to *unblock the agent*. Anything that violates it — even with good intent ("I'll just check in real quick") — has weighted the human's time at zero, which is the failure mode this axiom forbids.

The companion principle (`principle_cost_asymmetry_continue_vs_exit.md`, captured in Axiom 5) is the same phenomenon viewed from the agent side: continuing costs revertible commits, exiting costs unrecoverable wall-clock. Two views of one truth.

### How to apply

**Forbidden:**
- Treating any mid-campaign checkpoint not enumerated in Axiom 3 / 6 as legitimate
- Computing only the agent-side cost of stopping (perceived caution) while ignoring the human-side cost (attention burn)
- Re-litigating decisions already in the approved Plan / Dev Spec / phases-waves.json
- "Consulting-as-theater" — "Here are options A/B/C, my recommendation is C, your call?" when the skill body already selects C. The skill made the decision; restating it as a question pushes synthesis back onto the human unnecessarily.

When the agent feels unease that doesn't match a Legal Exit, the answer is Axiom 4's Concerns Channel — `[concern]` comment, optional Discord ping, continue. The unease is captured durably; the campaign continues; the human's attention is not burned.

**See:** Axiom 2, Axiom 3, Axiom 4, Axiom 5, Axiom 6, `principle_user_attention_is_the_cost.md`, `principle_cost_asymmetry_continue_vs_exit.md`.

---

## Axiom 10 — A wave targets exactly one repo.

### Rule

A single wave's issues all resolve to **one repository**. A wave never straddles two repos. Cross-repo coordination is expressed as **serial phases** (expand in repo A's waves, then contract in repo B's waves), never as a single straddling wave.

### Why

The wave is the **atomic promotion unit**: it assembles into one `kahuna/<wave-id>` branch, the trust gate evaluates that branch, and it fast-forwards into *that repo's* `main`. `kahuna` and its `main` live in one repo. A wave spanning two repos would need two kahuna branches and two ff-into-main promotions — and there is **no two-phase commit across git remotes**, so the two mains can never be promoted atomically. There is always a window where one repo's main has the change and the other's does not — the exact broken intermediate the gate exists to prevent. The coordinated cross-repo contract change is not a counter-example: its correct shape is **expand-contract across serial phases** (repo A ships a backward-compatible expand → repo B consumes it → repo A contracts), each phase's waves single-repo and independently promotable.

### How to apply

**Plan-time validator (prepwaves / assesswaves):** when computing/presenting waves, resolve every issue in each wave to its `owner/repo` (per-issue `repo` field, else plan-level `repo`, else the project repo). If any single wave's issues resolve to **more than one** distinct repo, **refuse** — name the wave and the conflicting repos, and direct the planner to split it into serial single-repo phases. Phase-level `cross_repo: true` remains valid — a *phase* may span repos across its *waves*; the invariant is **per-wave, not per-phase**.

**Forbidden:**
- Grouping issues from two repos into one wave.
- "It's just a small cross-repo tweak" — there is still no atomic two-remote promotion; split it into serial phases.

**See:** Axiom 1 (serial is a valid topology), `lesson_cross_repo_wave_orchestration.md`, the prepwaves cross-repo detection step.

---

## How to apply this document

- **CLAUDE.md** at the cc-workflow root references this file inline; CLAUDE.md is always loaded.
- Wave-pattern skill bodies (`/wavemachine`, `/nextwave`, `/prepwaves`, `/assesswaves`) reference this file with an `## Axioms` cross-reference block near the top of each SKILL.md, citing the axioms that bind each skill. Single source of truth: when an axiom changes, the skills follow without per-skill edits.
- Memory files (`principle_*`, `pattern_*`, `feedback_*`) are subsidiary references. This file is the canonical source.
- Violations encountered in real conversations should be filed as updates to this document — either tightening an existing axiom or adding a new one for the newly-observed failure mode.

---

## Cross-references

| Memory file | Relates to |
|---|---|
| `principle_user_attention_is_the_cost.md` | Axiom 2, Axiom 9 |
| `principle_cost_asymmetry_continue_vs_exit.md` | Axiom 5, Axiom 9 |
| `pattern_exhaustive_legal_exits.md` | Axiom 3 |
| `pattern_concerns_channel.md` | Axiom 4 |
| `feedback_nextwave_batch_approval.md` | Axiom 6 |
| `feedback_wave_pattern_justification.md` | Axiom 1, Axiom 7 |
