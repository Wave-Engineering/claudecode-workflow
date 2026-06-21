# Reseed Frequency and Context Fill
### Is it more efficient to reseed *often* than to wait until the window is full?

*A research white paper — cc-workflow reseed program*
*babelfish 🐠, with BJ · 2026-06-21*

---

## Abstract

We recently tuned the `/reseed` operation — the seed-and-clear compaction of a mid-flight agent
conversation — to ~0.95 recall / ~0.96 fidelity against a strict oracle, measured on a **near-full**
context window. That result raises a question we did not test: **how does reseed quality depend on
how full the window is when we reseed, and does that change the optimal reseed *frequency*?** The
working hypothesis is that, given high per-reseed fidelity, it may be *more efficient overall* to
reseed often at low fill than to wait until the window is nearly full. This paper argues the
hypothesis is non-obvious (two opposing forces produce a genuine interior optimum), shows why the
naive experiment is invalid, proposes a clean experimental design (a multi-needle-in-haystack that
isolates *fill* from *content*), and sketches the analytical cost model that converts a
fidelity-vs-fill curve into an efficiency recommendation.

---

## 1. Background

A reseed compresses a long, mid-flight conversation into a compact handoff "seed," which then
replaces the working context. It is **lossy compaction applied repeatedly**: even at 0.95 fidelity,
each reseed drops ~5% of the carried information, and the loss compounds over an agent's lifetime.

Our measured baseline (see `project_reseed_bench_result`): on a ~84K-token-content mid-development
session, a single tuned generation pass scores recall 0.94 / fidelity 0.96 (independent Sonnet
judge), at ~97.6% window reduction. Crucially, **that measurement was taken at one fill level —
near-full.** We have no data on whether the *same* operation does better or worse when the window is
half-empty.

## 2. The hypothesis

> Because per-reseed fidelity is high, it may be more efficient to **reseed often** (at low fill)
> than to **reseed rarely** (near-full). "I will happily pay for quality with time; ultimately it
> saves time." — the operating intuition.

The efficiency claim is about *total cost to do a unit of work*, where cost includes per-turn
inference (which scales with how full the context is) plus the cost of the reseed operations
themselves plus the quality lost to compression.

## 3. Why the hypothesis is non-obvious — two opposing forces

**Force A — frequent reseed makes every turn cheaper.** Every turn re-processes the working
context. A fuller window costs more per turn (more input, more cache-read). If you reseed at
half-full, you cap the working context smaller, so *every subsequent turn until the next reseed* is
cheaper. This force always favors reseeding **earlier**.

**Force B — frequent reseed compounds loss and pays the op cost more often.** Each reseed is a lossy
operation (~5% drop) and costs a fixed amount (~one model call, ~$3, ~2 minutes). Reseed twice as
often and you run the lossy operation twice as often — the information loss compounds faster, and you
pay the operation cost more frequently. This force always favors reseeding **later**.

Because A and B pull in opposite directions, there is a **genuine interior optimum** — some non-zero,
non-infinite reseed interval that minimizes total cost. The hypothesis is really a claim about *where
that optimum sits*, and whether it is earlier than our current "wait until near-full" habit.

**The tie-breaker is an unknown: does fidelity depend on fill?** If fidelity *degrades* as the
window fills (more to compress, more lost-in-the-middle, more candidate decisions competing for
attention), then reseeding early wins **twice** — cheaper turns *and* less loss per operation — and
the optimum shifts strongly earlier, vindicating the hypothesis. If fidelity is *flat* across fill,
Force B's compounding penalty dominates and "reseed when full" remains right. **Measuring the
fidelity-vs-fill curve is therefore the load-bearing experiment.**

## 4. Why the naive experiment is invalid

The obvious test — "take one conversation, truncate it to 25 / 50 / 75 / 100% of the window, reseed
each, compare fidelity" — is **confounded** and would produce a misleading curve:

1. **Truncation changes the content, which changes the oracle.** A 25%-fill conversation contains
   *fewer* must-capture decisions. "Recall 0.95 on the 25% cut" and "recall 0.95 on the full
   conversation" are not the same measurement against the same bar — you have changed the *task*,
   not merely the fill. You cannot hold a fixed quality standard against a moving target.
2. **Absolute size is its own regime, tangled with fill.** A 700K-token context is not just "a fuller
   200K context." It invokes a different attention profile, a more severe lost-in-the-middle effect,
   and possibly different effective-context limits. Naive truncation conflates *how full* with *how
   big*, and they are separate variables.

Any curve produced this way measures a mixture of fill, content, oracle difficulty, and size regime
— uninterpretable.

## 5. A valid design — multi-needle-in-haystack

The fix is to **stop varying the scored content and vary only the surrounding context.**

- **Needles (held fixed across all conditions).** A single, fixed set of *N* scoped operating
  decisions, with one fixed oracle. This is the *only* thing scored. Because it is identical in every
  condition, the quality bar is identical in every condition — apples-to-apples by construction.
- **Haystack (the independent variable).** Pad the window to target fills — e.g. ~100K / 300K /
  500K / 800K tokens — using **operationally-neutral filler**: real-looking conversation turns that
  contain *nothing the oracle cares about*. "Fidelity at 300K vs 800K" now compares the *same N
  decisions* buried in more or less surrounding context.
- **Position control.** Hold the needles at fixed *relative* positions across conditions (or
  randomize their positions and average over repeats). Otherwise the experiment silently measures
  lost-in-the-middle *position* effects rather than *fill*.
- **Pick one question, not both.** *Fill within a fixed window budget* (vary 100K→800K inside one
  model's 1M window — this is the efficiency hypothesis, "reseed at half-full") is a different
  experiment from *cross-regime absolute size* (200K model vs 700K vs 1M). Conflating them
  reintroduces the §4.2 confound. For the efficiency question, vary fill within the operating window.

**The fiddly part — filler authenticity.** Lost-in-the-middle only triggers on content the model
treats as genuine context, so the filler must be realistic; but it must also be *verifiably
oracle-empty*, or it changes the thing being scored. The likely source is real turns drawn from an
*unrelated* session, screened (by an independent pass) to contain no scoped operating decisions. The
quality of this screening is itself a validity threat (§7).

**Output:** a fidelity-vs-fill curve for the fixed needle set — the empirical object the whole
question turns on.

## 6. From curve to recommendation — the efficiency model

The fidelity-vs-fill curve is necessary but not sufficient; the efficiency claim needs an analytical
layer on top of it. Model the cost of doing a fixed amount of work as a function of the reseed
interval.

Let the working context grow by roughly *g* tokens per turn, and let reseeding occur whenever the
context reaches fill *S*. Then:

- **Turns between reseeds:** `T ≈ (S − S₀) / g`, where `S₀` is the post-reseed seed size (~2K
  tokens, near-constant).
- **Per-turn inference cost** scales with current context size; integrated over one reseed interval
  it is roughly `c · (S₀ + S)/2 · T` — the *average* context size times the number of turns times an
  effective per-token-per-turn rate `c` (cache-read economics folded into `c`).
- **Reseed operation cost** `R` (one model call) is paid once per interval.
- **Compression loss** `L(S)` — the fidelity cost per reseed — is paid once per interval, and
  **its dependence on `S` is exactly what §5 measures.**

Total cost per unit of work is `(per-turn integral + R + value(L(S))) / work-per-interval`. Minimize
over `S`:

- **Force A** lives in the per-turn integral: smaller `S` ⇒ smaller average context ⇒ lower
  integral. Always favors smaller `S`.
- **Force B** lives in `R` and `L`: smaller `S` ⇒ more intervals per unit work ⇒ `R` and `L` paid
  more often. Always favors larger `S`.
- **The decider:** if `L(S)` *rises* with `S` (fidelity degrades when full), the loss term reinforces
  Force A and pushes the optimal `S` down — toward frequent reseeding. If `L(S)` is flat, only Force
  B opposes A and the optimum sits higher.

The model also exposes the levers that move the answer in practice: prompt-cache economics (how much
`c` actually grows with fill), the real per-reseed dollar/time cost `R`, and how the organization
*values* a unit of fidelity loss `L` (a scoped grant dropped can be far more costly than its token
count suggests — which is the whole reason reseed exists).

## 7. Threats to validity

- **Filler leakage.** If the neutral haystack contains even a few operational decisions, it pollutes
  the oracle and inflates apparent loss. Mitigation: independent screening pass; spot-audit.
- **Judge monoculture.** Same lesson as the main bench — score with two different models; a model
  grading its own family inflates fidelity (~0.10 here). Keep the dual-judge.
- **Position artifacts.** If needle positions correlate with fill condition, lost-in-the-middle
  masquerades as a fill effect. Mitigation: fixed relative positions or randomize-and-average.
- **Single-fixture generalization.** One needle set is one topic; a degradation curve may be
  content-specific. Mitigation: ≥2 distinct needle sets before trusting the shape.
- **Cache-model fragility.** The per-turn cost term `c` depends on prompt-cache behavior that can
  change with platform/model; the analytical conclusion should be reported as a function of `c`, not
  a single number.

## 8. What each outcome would mean

- **Fidelity degrades with fill (curve slopes down):** reseed-early wins on both axes; the operating
  recommendation becomes "reseed at a target fill well below full," and the §6 model locates exactly
  where. Strongest version of BJ's hypothesis.
- **Fidelity flat across fill (curve is level):** the per-turn savings still favor *some* earlier
  reseeding, but compounding loss caps how often; the optimum is a moderate interval, not "as often
  as possible." A weaker but still actionable result.
- **Fidelity *improves* with fill (unlikely):** would argue for letting the window fill — the model
  uses the richer context to produce a better seed. Worth being open to.

## 9. Status and next step

Deferred by request (BJ is mobile; not running this now). The reseed bench
(`~/.claude/reseed-bench/`) and the tuned generator are ready to execute the §5 design; the main
build task is sourcing and screening the neutral filler corpus. Grounding results:
`project_reseed_bench_result`, `reference_reseed_improvement_techniques`. Promote to a backlog spike
issue when picked up.

---

*Appendix — measured baseline that motivates this (fixture-02, near-full, n=3, dual-judge):
reseed recall 0.94–0.96 / fidelity 0.95–0.98; `/compact` 0.71 / 0.45 on the same oracle; reduction
~97.6% (reseed) vs ~98.8% (`/compact`); post-hoc refinement loops lost on every axis.*
