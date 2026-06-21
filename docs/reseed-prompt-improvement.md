# Reseed Prompt-Improvement Methodology

How we lifted `/reseed` faithfulness from **~0.88 recall / ~0.86 fidelity** to
**~0.95 / ~0.96** against a strict oracle — and, equally important, the approaches that
**failed** and why. This is the playbook for evidence-driven improvement of any
generation-shaped skill prompt, plus the quantified `/reseed`-vs-`/compact` tradeoff.

> The numbers here trace to the reseed-bench (a local harness under `~/.claude/reseed-bench/`)
> and the durable findings in memory `project_reseed_bench_result` and
> `reference_reseed_improvement_techniques`. This document is the institutional record so the
> next person improving a skill prompt does not re-walk the dead ends.

## The problem

A reseed compresses a long, mid-flight agent conversation into a compact handoff "seed."
The failure isn't "it's wrong 15% of the time" — it's that **~15% of the load-bearing
information is dropped on *every* reseed**. That's lossy compaction applied repeatedly, and
the loss compounds over an agent's life. The decisions that get dropped are the worst ones to
lose: **conversation-only operating decisions** (scoped grants, live priorities, hard-won
gotchas) that have no durable home on disk.

## How we measured (the bench)

You cannot improve what you cannot score. The bench:

1. **Fixture** — a real, *cold* conversation transcript (not a hand-written seed, which would
   flatter the result). Resumed as native context via a copied session so the live session is
   untouched.
2. **Independent oracle** — a rubric of the MUST-CAPTURE conversation-only decisions (each with
   its scope), MUST-NOT-BLOAT items (on-disk content to point at, not restate), and the
   fidelity discriminators (scoped grants must be carried *with* their condition, not
   flattened). Authored from the fixture's *own* content by a context that is **not** the
   scorer — independence matters or the oracle is biased.
3. **Dual judge (the monoculture check)** — score every seed with **two different models**
   (Opus *and* Sonnet). When we scored Opus-authored seeds with an Opus judge, fidelity read
   ~0.10 too high; the Sonnet judge exposed the inflation. A model grading its own output is the
   single biggest threat to a quality number — always break the monoculture.

**Methodology principle: measure before assuming a ceiling.** Early on we concluded "the
baseline is near-perfect, no room to improve" — based on the *inflated* self-judged 0.95. The
independent judge showed the real level was ~0.86 — leaving ~14% of genuine headroom (the
self-judge had read ~0.10 too high). Inflated metrics hide the very gap you're trying to close.

## What did NOT work — and why (the valuable part)

Every post-hoc "refine the seed after generating it" approach **failed to beat a single,
well-prompted generation pass.** Each failure isolated a real mechanism:

| approach | result (recall/fidelity) | root cause |
|---|---|---|
| **ralph-loop** (blind N-pass rewrite) | no lift, **2.7× cost** | a blind full-rewrite has no signal about *what* it missed and is as likely to drop a good item as add a missing one. Pure churn + drift. |
| **ECP** (extract → critic → patch) | *worse* (fidelity 0.80) | the oracle-blind critic **rubber-stamped** — returned "no gaps" while the judge found real misses. You cannot ask an LLM "is anything missing?": there is no internal signal for an *absence*, and a same-model/same-context critic shares the generator's blind spots exactly. |
| **CGR-v1** (source-anchored coverage probe, additive patch) | recall ↑0.96, **fidelity ↓0.67** | the presence-gate optimizes *recall*; the additive patch *adds* the missing decision but **flattens its scope** (a "while away" grant added without its lapse condition). Recall and fidelity are in tension under a presence-gate. |
| **CGR-v2** (scope-strict probe + repair patch) | traps fixed, but **overclaims + bloat** | fixed the scope-flattening, but every additional edit pass introduced a *new* error (hallucinated issue-closure, 44→72-line bloat). |

**The meta-lesson: post-hoc patch loops degrade the seed.** Additive or repair, every edit pass
is a fresh chance to flatten scope, overclaim status, or bloat. The single-shot baseline was
consistently the *tightest* output; the loops made it worse. This matches the literature
(Self-Refine / "LLMs Cannot Self-Correct Reasoning Yet", DeepMind): intrinsic iterative
self-correction has diminishing-then-*negative* returns.

> A genuinely useful by-product: ECP's failure taught us that the right way to verify omissions
> *with no answer key* is to invert the question — derive an atomic checklist **from the
> source**, then run closed per-item lookups ("present? quote-or-MISSING"). Recall-as-judgment
> (rubber-stamps) → recall-as-lookup (verifiable). The source *is* the oracle. This is the
> QuestEval recall mechanism; it's what made CGR's probe sharp even though CGR overall lost to
> the generator.

## What worked: tune the generator, don't post-process

The decisive move was a **textual-gradient pass on the generation prompt itself** — read what
the judges consistently penalized across ~10 seeds, then add targeted instructions to the
*generator* so the *first* pass is both high-recall and high-fidelity. No loop. The four rules:

1. **Live grant-status** — every grant carries its scope **and whether the condition still
   holds now** (flag likely-lapsed when it has ended). This was *the* fidelity discriminator.
2. **Status accuracy** — issue/MR/PR open-vs-closed and commit tips stated only as the
   conversation established them; never overclaim closure.
3. **Fuller recall categories** — role/lane/ownership assignments and error→fix pairs, in
   addition to priorities/threads/gotchas/identifiers.
4. **Final re-scan** — re-read the draft against the conversation for dropped decisions and
   verify each grant's live status before output.

**Result (n=3, dual-judge, fixture-02):** Opus mean recall 0.96 / fidelity 0.98; Sonnet 0.94 /
0.96 — every replicate ≥0.90 on both axes. Cheapest of everything tried (~$2.89/run vs $6–15
for the loops), and a compact 57-line seed with no patch-bloat. These four rules are now in
`skills/reseed/SKILL.md` (PR #762).

**Why generator-tuning beats post-processing:** the base generator already had *great* fidelity
— the loops *broke* it. Improving recall by editing the generation prompt is penalized for any
fidelity loss in the same pass (the model holds both goals at once), whereas a post-hoc loop
optimizes one axis blind to the other. Fix the source of the output, not the output.

## `/reseed` vs `/compact`

Same fixture, same oracle, same two judges:

| | recall (Opus/Sonnet) | fidelity (Opus/Sonnet) |
|---|---|---|
| **`/compact`** | 0.72 / 0.71 | **0.60 / 0.45** |
| **`/reseed`** (tuned) | 0.96 / 0.94 | 0.98 / 0.96 |

`/compact` drops **~a quarter of the must-capture content and roughly half the scope-fidelity.**
Both judges flag the *exact* failure `/reseed` exists to prevent: the scoped grant flattened to
a blanket "standing delegation" with its while-away condition and lapse status dropped — plus
missing gotchas, memory pointers, and the hand-patched caveat.

**When to use which:**
- **`/compact`** — a cheap continuation summary where little is at stake. It is genuinely
  inadequate for carrying scoped operating decisions; expect ~half the fidelity.
- **`/reseed`** — careful, mid-flight reduction where dropping a scoped grant or a live
  decision would mislead the revived agent. This is what the skill is for, now empirically
  priced.

**Caveats on the comparison:** n=1, and it is a *faithful proxy* — the literal `/compact`
returns no capturable text in headless `-p` mode (the summary lands in post-compact session
state, not the result envelope; it still costs the full ~$3 to run). The proxy resumes the
fixture and summarizes per the project's CLAUDE.md Compact Instructions, exactly what
`/compact`'s summarizer follows. If anything the proxy is *generous* to `/compact` — the real
command's task-continuation template would plausibly drop scoped grants even harder. The gap is
large enough that neither caveat changes the conclusion.

## Reduction — pairing quality with compression

Quality scores alone are only half the story: a high-fidelity seed that barely shrinks the
window is a poor *reduction*, and the whole point of reseed/compact is to shrink it. Recovered
from the seed artifacts (size vs. the fixture's ~83.6K-token conversation text content — same
denominator for every row):

| solution | ~tokens | reduction | fidelity (Sonnet) |
|---|---|---|---|
| input window | 83,624 | — | — |
| `/compact` | ~1,043 | **98.8%** | 0.45 |
| **`/reseed` (tuned, winner)** | ~1,900 | **97.6%** | **0.96** |
| baseline single-shot | ~1,800 | 97.7% | 0.86 |
| CGR-v2 (post-hoc loop) | ~3,239 | 96.1% | 0.77 |

Three findings that *reinforce* the quality conclusions:

1. **The winning generator-tuning adds fidelity, not size.** It compresses the same ~97.6% as
   the untuned baseline while scoring far higher — the four rules are not bought with bloat.
2. **Post-hoc loops bloat as well as degrade.** CGR-v2 is the *worst* compressor (96.1%, the
   largest seed) *and* lower quality — the patch penalty shows up on both axes.
3. **The `/compact` tradeoff is real but unfavorable for careful reductions.** `/compact`
   compresses *more* (98.8%, ~half the tokens) — but that extra ~850 tokens of compression costs
   ~half the fidelity (0.45 vs 0.96). Spending ~1,900 tokens instead of ~1,000 to keep the scoped
   operating decisions is cheap insurance when those decisions are load-bearing.

> **Lesson: track the reduction ratio as a first-class metric alongside quality.** We didn't, at
> first — it had to be recovered from the saved seed artifacts after the fact. A reduction that
> wins on fidelity but loses on compression (or vice versa) is not obviously better; you need
> both axes to compare solutions honestly.

## Takeaways for improving any skill prompt

1. **Build a bench with an independent oracle before touching the prompt.** A score you can't
   trust is worse than no score.
2. **Always dual-judge.** A model grading its own output inflates the number on exactly the axis
   you care about most.
3. **Measure the real baseline; don't assume a ceiling.** Inflated self-scores hid 14% of
   headroom here.
4. **Prefer generator-tuning over post-hoc loops.** Post-processing degrades; a single sharp
   pass that holds all goals at once wins on quality, cost, and speed.
5. **To verify omissions with no answer key, invert the question** — checklist-from-source +
   closed present/MISSING lookups, not "is anything missing?".
6. **Smoke-test every new inference path on a cheap fixture first.** Two methodology bugs in
   this effort (ralph reading a 9MB file the Read tool truncated; an over-extracted 251-item
   checklist) were caught cheaply this way.
7. **Track the reduction ratio as a first-class metric, not just quality.** A reseed/summary is
   a *compression*; a high-fidelity output that barely shrinks the window is a poor reduction.
   Log output-size-vs-input alongside recall/fidelity so solutions are compared on both axes. We
   had to recover it from saved artifacts after the fact — log it up front next time.

## Future work

The result above was measured at one fill level — a near-full window. The open question is whether
reseed fidelity depends on *how full* the window is, and whether that makes it more efficient to
reseed *often* at low fill than to wait until the window is near-full. That hypothesis, why the
naive truncation experiment is invalid, and a valid (needle/haystack) design are written up in
[`reseed-frequency-whitepaper.md`](reseed-frequency-whitepaper.md).
