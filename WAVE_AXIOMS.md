# WAVE AXIOMS

<!-- Canonical, load-mandatory rules for wave-pattern execution.

     READ THIS BEFORE invoking /wavemachine, /nextwave, /assesswaves.
     READ THIS BEFORE recommending against the wave pattern.
     READ THIS BEFORE asking the user a mid-campaign question.

     Each axiom binds to a specific observed-and-forbidden behavior.
     Violation is a bug, not a judgment call. Disagreement with an axiom
     is a reason to update this file via PR — never a reason to override
     it in the moment.

     "First round" — 2026-05-05 BJ + patchwork. Will grow as new
     failure modes are observed. -->

---

## Axiom 1 — Serial is a valid wave topology.

A wave-pattern campaign is justified by **autonomous batched execution**, not by parallelism. A queue of N≥4 issues with deep gating dependencies — every flight serial, every wave size 1 — is a textbook campaign.

**Forbidden:**
- Recommending "ad-hoc, no campaign" for a serial-but-batchable queue
- Downgrading a wave plan because no parallelism is available
- Treating "is there parallelism here?" as the gating question

**Why:** The benefit isn't concurrency. It is queue-and-walk-away — the agent walks the deps, /precheck → /scpmmr per issue, while the user does something else. Lifecycle tracking and audit trail land regardless of flight count. The user's wall-clock is the resource the campaign exists to protect.

**See:** `feedback_wave_pattern_justification.md`, `/assesswaves` skill body.

---

## Axiom 2 — The campaign is autonomous from invocation to terminal state.

Once `/wavemachine` (or `/nextwave`) starts, the agent runs until one of the following: (a) the campaign reaches its terminal state — all issues complete and Plan-level DoD verified, (b) a Legal Exit fires (Axiom 3), (c) the user explicitly halts (interrupt, `/halt`, "stop"). No other condition terminates the campaign.

**Forbidden:**
- "Shall I continue?"
- "Do you want me to proceed to wave 2?"
- "Ready to move on?"
- "Should I file the followup?"
- Any mid-campaign yes/no question whose expected answer is "yes"
- Pausing at phase boundaries "to check in"

**Why:** Each mid-campaign question converts autonomous execution into a per-step checkpoint. The user invoked the campaign precisely to avoid those checkpoints. Asking the question burns the user's attention to receive the answer that was already implied by the invocation.

**See:** `principle_user_attention_is_the_cost.md`.

---

## Axiom 3 — The Legal Exits list is closed.

Legitimate stops, **exhaustively**:

1. **Plan-reality drift** — observable evidence that the Plan no longer matches the codebase, the work, or the world (an issue closed externally, a file moved, an API changed).
2. **Hard fault** — uncatchable error, missing critical resource, infrastructure outage.
3. **Explicit user halt** — interrupt, `/halt`, "stop", explicit instruction to pause.

That is the entire list. There are no others.

**Forbidden (each observed):**
- "I'm uncertain about X" → stop
- "This next step is large" → stop
- "I want to confirm before X" → stop
- "Session has been long" → stop
- "Phase boundary, good place to check in" → stop
- "Out of an abundance of caution" → stop
- "The user might want to know X" → stop

Each of these is the failure mode this axiom exists to forbid.

**Why:** A closed list is enforceable. An open list is rationalizable. The agent who reasons "this is technically not a Legal Exit, but I'm stopping anyway because it feels right" has constructed exactly the failure mode the closed list is designed to prevent.

**See:** `pattern_exhaustive_legal_exits.md`.

---

## Axiom 4 — When unsettled, use the Concerns Channel. Do not stop.

If the agent is unsettled and no Legal Exit applies, the response is:

1. Post a `[concern]` comment on the relevant issue
2. Ping the Pair via Discord if the concern is urgent
3. **Continue the campaign**

The campaign does not pause for unease. The Concerns Channel exists precisely so the agent can register the unease without burning the user's wall-clock.

**Forbidden:**
- Stopping the campaign because "I had a concern"
- Asking the user to evaluate the concern in real time
- Treating the Concerns Channel as optional when no Legal Exit fires

**Why:** Unease is information; stopping is action. The information goes into the durable record (issue comment + optional Discord ping). The action is reserved for Legal Exits. Conflating the two is the bug.

**See:** `pattern_concerns_channel.md`.

---

## Axiom 5 — Continuing is cheaper than stopping. Default forward.

Continuing costs at most: a revertible commit, a noisy comment thread, or a follow-up issue. Stopping costs: unrecoverable wall-clock — every minute the user reads the question, switches context, types a reply, and resumes — plus the cache-warmth penalty on the agent's side.

**Forbidden:**
- Treating "stop and ask" as the safe default
- Framing continuation as the risky option
- Computing only the worst-case cost of continuing while ignoring the certain cost of stopping

**Why:** The cost asymmetry is permanent and well-documented. Almost every continuation can be undone in a follow-up commit. No stop can return the wall-clock it consumed.

**See:** `principle_cost_asymmetry_continue_vs_exit.md`.

---

## Axiom 6 — Approval frequency is set by the invoked command. The agent does not add gates.

- **`/nextwave`** = "I want to approve at each wave." The gate fires once per wave, after all flights complete and the Orchestrator-side reviewer passes. One approval covers every issue and every sub-agent in that wave.
- **`/wavemachine`** = "I want to approve at the campaign end." There is no per-wave human gate; the Orchestrator approves wave transitions autonomously based on flight + reviewer signal. The user-facing gate fires only at terminal state (Plan-level DoD verification, or a Legal Exit per Axiom 3).

**Forbidden:**
- Per-flight, per-issue, or per-sub-agent approval requests in any context
- Human-loop checkpoints between waves during `/wavemachine` execution
- Adding gates the user did not invoke

**Why:** The slash command choice IS the gate-frequency declaration. Adding gates the user didn't ask for is unilateral expansion of the contract — the same failure mode as "shall I continue?" in Axiom 2, just at a different layer.

**See:** `feedback_nextwave_batch_approval.md`, `principle_user_attention_is_the_cost.md`.

---

## Axiom 7 — `/assesswaves` measures justification, not topology suitability.

The skill answers a single question: **should the user use the wave pattern for this work?**

The answer is **YES** whenever:
- count ≥ 4 issues, OR
- per-issue wall-clock is non-trivial (≥ ~30 min sustained agent work), OR
- the user has indicated they want batched-autonomy execution for this queue

Regardless of whether flights parallelize.

**Forbidden:**
- Recommending against the wave pattern because flights serialize
- Recommending "ad-hoc, no campaign" for any queue meeting the YES criteria
- Treating parallelism as a prerequisite

**Why:** The skill body literally says "serial is a valid wave topology." Anchoring on parallelism in the assessment is anchoring on the wrong axis. See Axiom 1 for the full rationale; this axiom binds the assessment skill specifically because that is where the failure has been observed.

---

## Axiom 8 — These axioms supersede agent judgment in their domain.

If an agent's reasoning produces a conclusion that contradicts an axiom, **the axiom wins**. Disagreement with an axiom is a reason to file a PR updating this file, not a reason to override the axiom in the moment.

**Forbidden:**
- "Axiom N applies in general but not here because..."
- "I see why the axiom says X, but in this case Y..."
- Citing an axiom in the response while violating it in action

**Why:** This document exists because case-by-case judgment WAS the failure mode. The axioms are the structural correction; allowing case-by-case override re-introduces the failure. If the axioms are wrong, fix the axioms. If they're right, follow them.

---

## How to apply this document

- **CLAUDE.md** at the cc-workflow root references this file inline; CLAUDE.md is always loaded.
- Wave-pattern skill bodies (`/wavemachine`, `/nextwave`, `/assesswaves`) reference this file with explicit "READ FIRST" framing in their procedure sections.
- Memory files (`principle_*`, `pattern_*`, `feedback_*`) are subsidiary references. This file is the canonical source.
- Violations encountered in real conversations should be filed as updates to this document — either tightening an existing axiom or adding a new one for the newly-observed failure mode.

---

## Cross-references

| Memory file | Relates to |
|---|---|
| `principle_user_attention_is_the_cost.md` | Axiom 2 |
| `principle_cost_asymmetry_continue_vs_exit.md` | Axiom 5 |
| `pattern_exhaustive_legal_exits.md` | Axiom 3 |
| `pattern_concerns_channel.md` | Axiom 4 |
| `feedback_nextwave_batch_approval.md` | Axiom 6 |
| `feedback_wave_pattern_justification.md` | Axiom 1, Axiom 7 |
