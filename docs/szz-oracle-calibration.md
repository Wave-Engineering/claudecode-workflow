# SZZ oracle — calibration report

**Measured 2026-08-30 on `claudecode-workflow`, window 2025-08-30 → 2026-08-30.**
Reproduce with
`scripts/ci/szz-oracle.sh summary --since 2025-08-30 --until 2026-08-30`.
Pass `--until` — without it the command measures *today's* window, not the one
these numbers describe, and drifts a little further from them every day.

The oracle (`scripts/ci/szz-oracle.sh`) exists to give cc-workflow#1195 ground
truth about which changeset introduced which defect, so a review protocol can be
scored on escaped defects rather than on agreement with the review it is trying
to beat. An oracle nobody has calibrated is not ground truth — it is an opinion
with a script attached. This is its accuracy, measured before use.

## Headline

| number | value | what it means |
|---|---|---|
| yield | **87%** (124/143) | share of bug-fix commits SZZ can attribute at all |
| raw precision | **50%** (10/20) | hand-adjudicated, unfiltered |
| filtered precision | **67%** (10/15) | after dropping compound changesets, mechanically |
| ceiling | **77%** (10/13) | if non-defect `fix(` commits could also be excluded |
| usable fixtures | **102 pairs** | `szz-oracle.sh fixtures` output for this window |

67% is the number a consumer should plan against. It sits inside the 60–80%
band published for SZZ, which is mild evidence the implementation is not
unusual — not evidence it is correct. The 20-pair sample gives that 67% a 95%
interval of roughly ±24 points; it is a go/no-go signal, not a precise estimate.

### A note on the denominator

An earlier draft reported 124/144. The commit selector was `git log --grep='^fix'`,
and git matches that pattern line-by-line against the **whole** message, body
included — which is why `--grep='^Signed-off-by'` is a standard idiom. It enrolled
a `docs(harness):` commit whose body happened to carry a line beginning "fix".
Selection is now by subject (`^fix[(:]`), so the denominator is 143. That one
commit was itself unattributable, so the numerator did not move.

One wrong label in 144 barely shifts a rate. It is worth fixing anyway: the whole
claim of this oracle is that its labels are not arguable, and a label derived from
a prose coincidence is arguable.

## What the errors actually were

Ten of twenty pairs were wrong or unusable. The decomposition matters more than
the rate, because it says which errors are **mechanically removable**:

| error mode | n | removable? |
|---|---|---|
| compound culprit — a wave promotion or bulk cutover | 4 | **yes**, deterministically |
| blame stolen by a prose edit | 2 | no; detectable as a risk flag |
| the `fix(` commit repaired no defect (help text, redesign) | 3 | no; needs judgement |
| compound fix — one commit repairing several defects | 1 | partially |

**Compound changesets are the single largest error source.** A commit shaped
`plan(#N): PxWy — … to main` bundles an entire wave; no single `/precheck` ever
reviewed that bundle, so it cannot serve as a fixture no matter how correct the
blame is. `szz-oracle.sh fixtures` drops them and prints the count it dropped.
The rule keys on the wave pattern's *declared* emission convention rather than on
an inferred property like commit size — a contract this repo emits on purpose,
which is what keeps the rule derived rather than maintained.

**Blame theft by prose is real but must not be "fixed" by excluding Markdown.**
24% of attributable fixes delete lines from both docs and code, and 8% delete
more doc lines than code lines — in those, the heaviest blame can land on
whoever last edited the prose. The obvious remedy is wrong here: in this repo
`skills/*/SKILL.md` *is* the artifact under review, and the correctly-attributed
pair `62e202ee2 → e6a6fe5c4` is itself doc-dominated (15 doc lines vs 8 code).
Excluding Markdown would break a known-good attribution to chase a known-bad
one. It is reported as a stratification variable instead.

**Defect age does not predict correctness.** Fresh (≤7d) and stale (>7d) strata
both scored 50%. The expected gradient — older defects giving blame more chances
to be stolen — did not appear at this sample size, so age is not a useful filter.

## What this does to the study design in #1195

`#1195` proposes n≥30 sampled changesets. Measured here, only **17.8%** of
changesets are ever named as a culprit (33.7% counting every blamed commit, not
just the heaviest). Sampling changesets at random therefore yields ~5 positives
at n=30, and a paired McNemar test needs *discordant* pairs, which are rarer
still — the design as written is under-powered by roughly an order of magnitude.

The fix is not a bigger random sample; it is **case-control sampling**. Draw the
positive stratum from the 102 pairs `fixtures` emits, draw a matched negative
stratum from changesets never blamed, and report per-stratum rates with
reweighting. Base rate stops being a sampling risk and becomes a design
parameter. This does mean the study can no longer report "recall in the wild"
directly, which is a real cost and should be stated in the writeup.

## Sample — the 20 adjudicated pairs

Deterministic, stratified 10 fresh / 10 stale. Regenerate the evidence with
`scripts/ci/szz-oracle.sh worksheet --since 2025-08-30 --until 2026-08-30 --limit 20`.

| fix | culprit | stratum | verdict | reason |
|---|---|---|---|---|
| `0ab79cd49` | `1c464acd4` | fresh | YES | correct |
| `12a7f52dc` | `38d7dd7aa` | fresh | PARTIAL | redesign, not a defect |
| `1ac989d3e` | `d5a5c115b` | fresh | NO | compound culprit |
| `1c464acd4` | `53c85a535` | fresh | YES | correct |
| `1ef877b7d` | `bb1e04df7` | fresh | PARTIAL | compound fix (5 findings in one commit) |
| `2aa334ba1` | `b372429a5` | fresh | NO | blame stolen by prose — culprit touched only `README.md` |
| `2d734efe1` | `3b16c980b` | fresh | NO | environmental drift; correct when written |
| `2e6adda3b` | `28f1a9982` | fresh | YES | correct |
| `2fea67675` | `c9354eb02` | fresh | YES | correct |
| `37514115e` | `3b16c980b` | fresh | YES | correct |
| `02cba57a0` | `2e9f216d4` | stale | YES | correct |
| `0446632c5` | `5d1224dee` | stale | YES | correct |
| `06c4dd3f8` | `f5824de88` | stale | NO | not a defect — help-text improvement |
| `0e9b2612f` | `54001e25d` | stale | NO | compound culprit |
| `18ea88776` | `250bd1677` | stale | YES | correct |
| `27ed8f141` | `68ed26025` | stale | YES | correct |
| `2909a9cb7` | `ab59e5bac` | stale | NO | compound on both sides |
| `2dd6d2c8c` | `2500e8592` | stale | NO | compound culprit |
| `2ed2bcdc1` | `06c4dd3f8` | stale | NO | blame stolen by a comment edit |
| `2f2881bd9` | `7299cbdff` | stale | YES | correct |

Adjudicated by agent, not by a model call inside the oracle — the oracle stays
model-free on purpose, since its consumer is a benchmark that grades models.
A second adjudicator would give an inter-rater number this report does not have.
