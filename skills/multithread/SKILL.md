---
name: multithread
description: Parallelize a discussion over independent items — lay out all threads at once each with a take, batch-answer, drop sorted ones, iterate until dry.
usage: |
  /multithread <source>   Enumerate source into threads, present all with takes, batch-answer, iterate until dry
  /multithread            Infer source from the most recent open-questions block or list in conversation
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-multithread does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-multithread
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Multithread — Parallel Discussion Over Independent Items

Convert a serial walk through N independent questions, design holes, or review
comments into a concurrent discussion that converges in ≈ log(N) round-trips
instead of N.

**See Also:** `docs/executor-model-devspec.md` (Plan #822 §8 Story 3.1 — the
executor model: `/multithread` is the dialogue-facing companion to the
`/lazyriver` goal-seek loop and the `/wavemachine` plan-execution driver).

**Wave taxonomy position:** multithread is wave-pool for dialogue. The unit is
a discussion thread; the convergence checkpoint ("sorted / still open") is the
inter-wave barrier; the loop-until-dry is the same tail-catching discipline
wave-pool workflows use.

---

## Invocation

```
/multithread <source>
```

`<source>` is anything that enumerates to a list of independent items:

| Source type | Example |
|-------------|---------|
| Doc section | `/multithread docs/agent-smith-devspec.md §5.N` |
| Open-questions list | `/multithread the open questions` |
| PR review comments | `/multithread PR #813 review comments` |
| Ad-hoc list | `/multithread these: [a, b, c, …]` |
| No arg | Infer from the most recent open-questions block or list in conversation |

---

## Procedure

### Step 0 — Enumerate and label

Resolve `<source>` to a concrete list. Assign each item a **stable label**
(`T1 … TN`, or short slugs when N is small and slugs are more memorable).

Apply these normalizations before labeling:

- If an item is really two questions, split it into two threads — and say so.
- If two items are really one, merge them into one thread — and say so.
- If the source has zero items, report that and stop.

### Step 1 — Independence pass

Walk the list and annotate couplings: `T3 depends: T1`. This is a cheap
single-pass scan — no fan-out, no sub-agents. The goal is to make dependencies
**visible on turn one** rather than discovered by accident on turn six.

Flag tightly-coupled pairs (resolving A would rewrite what B even asks) — see
"When not to use" below for how to handle them.

### Step 2 — Present all threads at once

Lay out every thread in a single message. The canonical format is a compact
table:

```
| Label | Thread | Proposed take | Notes |
|-------|--------|---------------|-------|
| T1    | …      | …             | —     |
| T2    | …      | …             | depends: T1 |
```

**The take is mandatory.** Reacting is faster than authoring; a blank thread
is just a survey. Propose a disposition the user can accept, reject, or amend.
If genuinely uncertain, say so in the take — that is still a take.

For longer items (multi-sentence threads), use per-thread blocks instead of a
table:

```
**T1** — <thread title>
Take: <proposed disposition>

**T2** — <thread title>  (depends: T1)
Take: <proposed disposition, or "pending T1 — best guess: …">
```

Pick table vs. blocks based on item length; be consistent within a run.

### Step 3 — Human batch-answers

Accept the user's responses in any order and any subset. Silence on a thread
means **still open** — never assume-resolve.

A user response may be:

- A direct accept/reject/amend for one or more threads.
- A dependency note ("T3 depends on T1 — let's sort T1 first").
- A split or merge ("T5 and T6 are really the same").
- A question back (rare; answer it inline if quick, or open a new thread).

### Step 4 — Converge (the barrier)

After each batch-answer, explicitly report the convergence state before
re-presenting open threads:

```
Sorted: T1, T3, T7
Still open: T2, T5, T6
```

This is the inter-wave barrier — the "which ones do we still need to discuss?"
checkpoint. It prevents re-litigating sorted threads and makes progress visible.

### Step 5 — Iterate

Re-present **only** the open threads, with takes **updated** by what the sorted
threads taught. A just-resolved parent unlocks real answers for its dependents:
if T1 landed, T2's take is no longer "pending T1" — fill it in.

Loop Steps 3–5 until every thread is sorted. Each round is smaller than the
last; the conversation shrinks deliberately.

### Step 6 — Emit the Decision Record

When all threads are sorted, emit a Decision Record — one entry per thread:

```
| Label | Thread | Decision | Rationale |
|-------|--------|----------|-----------|
| T1    | …      | …        | …         |
```

Format for the destination context:

- **`/devspec` walk:** batch of `[ledger D-NNN]` entries + section edits ready
  to paste into the dev spec.
- **PR review:** a review-response table (one row per comment thread).
- **Ad-hoc:** a plain decisions list.

If the calling skill (e.g. `/devspec`) will consume the Decision Record
programmatically, hand back to it rather than formatting for human reading.

---

## Reasoning Rules

These govern every round. They are load-bearing — violating them degrades the
technique back toward serial.

1. **Always lead with a take.** Reacting is faster than authoring. A blank
   multithread is a survey. The value is that the user's next single turn can
   close as many threads as possible — optimize for that.

2. **Declare dependencies up front.** The whole edge over a serial walk is that
   couplings are visible on turn one, not discovered on turn six.

3. **Stable labels, shrinking conversation.** `T5` means the same thing in
   round 3 as in round 1. Never renumber between rounds. Sorted threads leave;
   they do not reappear.

4. **Round-trip minimization is the objective.** Every presentation decision
   should maximize how many threads the user can close in their next single
   message.

5. **Don't force it.** Tightly-coupled or genuinely-sequential decisions are
   not independent items. See "When not to use" below.

---

## Canonical Example — agent-smith §5.N (10 threads → 3 rounds)

A worked run against a real shape: the `§5.N Open Questions` block of the
`agent-smith` Dev Spec — 10 independent design decisions that a serial walk
would spend 10 round-trips on. Here they close in **3 batched rounds**.

### Round 1 — enumerate, independence pass, present all 10 with takes

Step 0–1 resolve the source to 10 threads and annotate the one coupling found
(`T2 depends: T1` — the replica naming scheme can't be fixed until we know where
identity is stored). Step 2 presents everything at once:

```
| Label | Thread                          | Proposed take                              | Notes        |
|-------|---------------------------------|--------------------------------------------|--------------|
| T1    | Identity store: file vs KV      | Project-local file (.claude/…), reboot-durable | keystone |
| T2    | Replica naming scheme           | pending T1 — best guess: <base>-<n> slug   | depends: T1  |
| T3    | Max concurrent replicas         | Hard cap (default 8), env-overridable      | —            |
| T4    | Heartbeat interval              | Adaptive: 5s idle → 1s under load          | —            |
| T5    | Replica teardown                | pending T4 — graceful drain, timeout TBD   | depends: T4  |
| T6    | Config source                   | Both: file baseline + env override         | —            |
| T7    | Log format                      | JSON lines (mcp.jsonl-compatible)          | —            |
| T8    | Spawn-failure retry             | Exponential backoff, 3 tries, then fail-loud | —          |
| T9    | Secrets injection               | Mounted file, never env                    | —            |
| T10   | Health surface                  | HTTP /healthz                              | —            |
```

Two dependency edges are visible on turn one (`T2→T1`, `T5→T4`), not discovered
on turn six. Every thread leads with a take, so the user's next single message
can close many at once.

### Round 1 batch-answer + convergence (Step 3–4)

User replies in one turn: *"T1 file, yes. T3 cap 8 ok. T6 both, yes. T7 JSON
yes. T9 mounted yes. T10 HTTP yes. Hold T4/T5, and T8 — say more on backoff."*

```
Sorted:     T1, T3, T6, T7, T9, T10
Still open: T2 (now unblocked by T1), T4, T5, T8
```

### Round 2 — re-present only the 4 open threads, takes updated (Step 5)

T1 landed, so T2 is no longer "pending" — its take is now concrete. Sorted
threads are gone; labels unchanged.

```
| Label | Thread              | Updated take                                            | Notes       |
|-------|---------------------|---------------------------------------------------------|-------------|
| T2    | Replica naming      | T1=file → identity file keys the name: `<host>-<pid>-<n>` | was: depends T1 |
| T4    | Heartbeat interval  | Adaptive confirmed; 5s/1s — or fixed 2s if simpler?     | —           |
| T5    | Replica teardown    | pending T4 — drain then SIGTERM; grace = 2× heartbeat   | depends: T4 |
| T8    | Spawn-failure retry | Backoff 250ms·2^n, cap 4s, 3 tries, then fail-loud      | —           |
```

User: *"T2 yes. T4 go adaptive. T8 yes. T5 still open — decide the grace number."*

```
Sorted:     T1, T2, T3, T4, T6, T7, T8, T9, T10
Still open: T5
```

### Round 3 — the last thread, unlocked by T4 (Step 5)

T4 resolved to adaptive (1s floor), so T5's "grace = 2× heartbeat" now has a
concrete number to propose.

```
| Label | Thread           | Updated take                                          |
|-------|------------------|-------------------------------------------------------|
| T5    | Replica teardown | T4=adaptive(1s floor) → drain, then SIGTERM after 2s grace; SIGKILL at 5s |
```

User: *"T5 yes."* All threads sorted — converge (3 rounds ≤ ⌈log₂10⌉+1 = 5).

### Step 6 — Decision Record (destination: Dev Spec §5.N ledger)

```
| Label | Thread              | Decision                                      | Ledger    |
|-------|---------------------|-----------------------------------------------|-----------|
| T1    | Identity store      | Project-local file, reboot-durable            | D-101     |
| T2    | Replica naming      | `<host>-<pid>-<n>`, keyed off identity file   | D-102     |
| T3    | Max concurrent      | Hard cap 8, env-overridable                   | D-103     |
| T4    | Heartbeat interval  | Adaptive 5s idle → 1s under load              | D-104     |
| T5    | Replica teardown    | Drain, SIGTERM @ 2s grace, SIGKILL @ 5s       | D-105     |
| T6    | Config source       | File baseline + env override                  | D-106     |
| T7    | Log format          | JSON lines                                    | D-107     |
| T8    | Spawn retry         | 250ms·2^n backoff, cap 4s, 3 tries, fail-loud | D-108     |
| T9    | Secrets injection   | Mounted file, never env                       | D-109     |
| T10   | Health surface      | HTTP /healthz                                 | D-110     |
```

**Result:** 10 independent decisions, 3 round-trips instead of 10. Labels were
stable across all rounds, dependents (T2, T5) filled in the moment their parents
landed, and the record is ready to paste into the Dev Spec as `[ledger D-1NN]`
entries.

---

## When to Use / When Not to Use

### Use it when

- A batch of open questions or design holes (e.g. a `§5.N Open Questions`
  block in a dev spec).
- PR or design review comments to work through.
- A set of independent design decisions or options to triage.
- Any situation where N independent things need deciding and you want fewer
  than N round-trips.

### Do not use it when

- **Genuinely sequential** — each answer reshapes the next question. That is a
  `/ddd`-style Socratic thread, not a fan-out. Walk them in order.
- **A single decision** — nothing to parallelize.
- **Tightly coupled** — one choice cascades and rewrites all the others.
  Resolve the keystone first, then multithread whatever remains independent.

**The independence test** (same test `/prepwaves` applies to stories): *Would
resolving A change what B even asks?* If no → same wave → multithread. If yes
→ serial edge → walk them in order.

---

## Wave Taxonomy Reference

| | Wave-pool | Lazy-river | Multithread |
|---|---|---|---|
| Unit | subagent | story | discussion thread |
| Concurrency | parallel | serial (width 1) | parallel |
| Minimizes | wall-clock | agency threshold | human round-trips |
| Barrier | between waves | none (float) | "sorted / still open" convergence |
| Best when | units independent | units dependent, high agency | decisions independent |

Multithread is wave-pool for dialogue. Pick the topology from the shape of the
work at every layer: decisions are usually independent → multithread them;
implementation usually has dependencies → float or pool it. Don't serialize a
discussion just because you'll serialize the build it feeds.
