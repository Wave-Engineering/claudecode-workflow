# Job D on the golden-comment benchmark (#1195)

What does `/precheck` Job D's reviewer catch, and at what cost per pass, under each model?
This page is the instrument and its results. The harness is `scripts/bench/jobd-golden.py`;
its header has the step-by-step usage.

## The yardstick

[withmartian/code-review-benchmark](https://github.com/withmartian/code-review-benchmark)
(MIT), pinned at `949e4a1058c67b940f27b2c609958a7ea7a13b2c` by
`scripts/bench/fetch-code-review-benchmark.sh`, which refuses any other commit. Its `offline/`
set is 50 public PRs from five open-source codebases, each with human-verified golden comments
carrying a severity. Its pipeline extracts candidate issues from a review, de-duplicates them,
and has an LLM judge match each candidate to the goldens. Nothing from it is vendored here:
the cache is gitignored under `.bench/`.

## What is held constant

An arm is a `<model>.<effort>` pair. The arms differ by `--model` and `--effort` and nothing
else (`test_arms_differ_only_by_model_and_effort`):

- **Effort:** `review --effort` is required, one of `medium`, `high` and `xhigh`, which is
  the range a `/precheck` session runs Job D at. It's passed as `--effort` and recorded in
  every review and in the report. It matters because **Job D's subagent inherits the parent
  session's effort**, even when Job D overrides the model (#1394, measured with hook
  payloads). So the same `/precheck` reviews at whatever effort the session happens to run
  at. Both models apply all three levels as given. Before #1394 the bench had no effort
  setting: every pass, the pilot's included, ran at `medium`. (`CLAUDE_EFFORT` is output only.
  The variable that sets effort is `CLAUDE_CODE_EFFORT_LEVEL`, and the bench uses the flag.)
- **Prompt:** Job D-full as `skills/precheck/SKILL.md` states it, first pass. A drift test pins
  the bench's wording to the skill's, so an edit to the skill can't leave the bench measuring
  an old prompt.
- **Persona:** `feature-dev:code-reviewer`'s agent body, read from the installed plugin and
  recorded with its sha256 in every review and in the report. `claude -p` can't select a
  subagent type, so the body is passed as the system prompt.
- **Tools:** Read, Grep and Glob.
- **Tree:** the PR's head commit, shallow-fetched, with the PR's diff on disk in parts of at
  most 1500 lines, as `precheck-review-scope.sh gather` splits it.
- **Isolation:** every `claude -p` (reviewer and judge) runs with `--setting-sources ""`,
  `--strict-mcp-config` and no `--mcp-config`, `--disable-slash-commands`,
  `--no-session-persistence`, and `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`. So no user or project
  settings, no hooks (measured: `Registered 0 hooks`), no MCP servers, and no CLAUDE.md.
- **Judge:** one model, `claude-sonnet-5-5`, for every arm, named in every report. It's served
  to upstream's OpenAI client by `scripts/bench/claude-openai-shim.py`, which answers
  `chat.completions` with `claude -p` and refuses a request for any other model.
- **Telemetry:** each process carries the fleet's OTEL keys and
  `OTEL_RESOURCE_ATTRIBUTES=precheck_variant=<model>.<effort>|judge,bench_case=<repo>-<pr>`.

## Deviations from the real Job D, and why

- **No web tools.** The agent definition grants WebFetch and WebSearch. The bench leaves them
  out: the PRs are public, and a reviewer that could fetch a PR's real review thread would be
  reading the answers.
- **No CLAUDE.md.** In `/precheck` the reviewer sees the reviewed repo's CLAUDE.md. Here,
  CLAUDE.md discovery walks up from the cwd, and the PR trees sit inside this checkout, so
  without the switch every pass loaded *this* repo's rules (~9k tokens, measured), which
  are foreign to the reviewed code. The switch also drops a reviewed repo's own CLAUDE.md or
  AGENTS.md. `prepare` records any it finds in `pr.json` (`memory_files`); neither pilot PR
  has one.
- **First pass only.** Job D-full's later passes carry the previous pass's findings. The
  bench measures one pass per arm.

## Known limitations

- **Training leakage.** The PRs are public, and either model may have seen them, or their
  review threads, in training. That affects both arms alike, so **the arm-to-arm difference
  is the result; absolute recall is not.**
- **One judge.** The judge is itself a model. The planted check (below) shows that it
  separates a restating review from an unrelated one; it does not show that it agrees with a
  human on borderline matches.
- **Upstream's matching is per PR, not per line.** Findings carry no path or line; the judge
  matches on content.

## Planted judge check

Before any arm ran, two hand-written reviews of keycloak/keycloak#37429 (4 goldens) were
judged. One restated 2 of the goldens in other words; the other named 2 unrelated issues.

| arm | TP | FP | FN |
|---|---|---|---|
| restates 2 goldens | 2 | 0 | 2 |
| unrelated | 0 | 2 | 4 |

That's exactly the expected split, from 20 judge calls costing $0.09. The first attempt at this
check is what found the CLAUDE.md contamination: the same calls cost $0.72, because each one
carried ~9k tokens of this repo's rules.

## Pilot, 2026-10-31

2 PRs × {`claude-sonnet-5-5`, `claude-opus-5-5`}, all at effort `medium`, run serially on malory (admission a-2af983),
harness at `e6676ed`, judge `claude-sonnet-5-5`, persona sha256 `e79b6f21…c1551`
(code-reviewer 1.0.1). Every number below comes from the CLI's own result JSON (`total_cost_usd`,
`usage`) or from the judge's ledger, never from an estimate.

| PR (goldens) | arm | TP | FP | FN | USD | wall | turns | output tok | cache read tok |
|---|---|---|---|---|---|---|---|---|---|
| keycloak#37429 (4) | sonnet | 2 | 1 | 2 | 0.227 | 28 s | 6 | 2,804 | 122,808 |
| keycloak#37429 (4) | opus | 2 | 1 | 2 | 0.656 | 71 s | 15 | 5,696 | 492,258 |
| discourse-graphite#10 (4) | sonnet | 3 | 4 | 1 | 0.114 | 20 s | 4 | 2,318 | 30,401 |
| discourse-graphite#10 (4) | opus | 4 | 7 | 0 | 0.327 | 56 s | 8 | 5,087 | 111,504 |

| arm | precision | recall | USD / pass | wall / pass |
|---|---|---|---|---|
| sonnet | 5/10 = 0.50 | 5/8 = 0.63 | 0.171 | 24 s |
| opus | 6/14 = 0.43 | 6/8 = 0.75 | 0.492 | 63 s |

Recall by golden severity: both arms caught the Critical golden and all 4 Mediums, and both
missed both Lows. The arms differ on exactly **one golden**, discourse-graphite#10's High:
opus caught it and sonnet missed it. The judge made 130 calls for the four passes, at $0.585
and 2 min 42 s with 4 workers, with 0 errors.

**What the pilot shows, and what it doesn't.**

- Opus costs **2.9×** as much per pass and takes **2.6×** as long. It reads more (15 turns
  against 6 on keycloak) and writes about twice as much.
- With 8 goldens, a one-golden difference is noise. The pilot sizes the sweep; it doesn't
  answer the question.
- Precision here is a floor, not a measurement. The goldens aren't exhaustive, so a real
  defect that isn't one counts as a false positive. One example, *unverified*: opus's top
  keycloak finding, that two i18next bundles were changed to `{0}` `MessageFormat` placeholders
  i18next won't fill, is in no golden. The sweep should spot-check a sample of FPs by hand
  before reading precision across arms.

## Effort mini-pilot, 2026-10-31 (#1394)

keycloak#37429 (4 goldens) × {`claude-sonnet-5-5`, `claude-opus-5-5`} × {`medium`, `high`,
`xhigh`}, 6 passes run serially on malory (admission a-f4e91b), harness at `c6e4061`, judge
`claude-sonnet-5-5`. The host was loaded (about 26% idle, swap full), so wall-clock may read
high, while cost and turns do not depend on the host. Before the measured passes, one
throwaway request went out under each new `precheck_variant` label, because Prometheus
`increase()` drops a new series' first sample. With that step, the fleet's `cc_cost_usd`
matched the harness's `usage` to the cent on all six reviews. The judge read $0.61 against
the harness's $0.71, and the harness figure stands.

| arm | TP | FP | FN | USD | wall | turns | USD vs medium |
|---|---|---|---|---|---|---|---|
| sonnet.medium | 2 | 1 | 2 | 0.208 | 23 s | 4 | 1.00× |
| sonnet.high | 2 | 0 | 2 | 0.206 | 29 s | 5 | 0.99× |
| sonnet.xhigh | 3 | 4 | 1 | 0.541 | 139 s | 33 | 2.60× |
| opus.medium | 3 | 5 | 1 | 0.683 | 78 s | 16 | 1.00× |
| opus.high | 2 | 2 | 2 | 0.804 | 108 s | 22 | 1.18× |
| opus.xhigh | 2 | 2 | 2 | 1.409 | 225 s | 39 | 2.06× |

The judge made 155 calls for the six passes, at $0.705.

**What it shows.** Cost is the finding here, not quality:

- Sonnet costs the same at `medium` and `high`, then 2.6× at `xhigh`.
- Opus rises in steps: 1.18× at `high`, 2.06× at `xhigh`.
- Opus costs 3.3× sonnet at `medium` and 2.6× at `xhigh`.
- `xhigh` is where the turns go: 33 and 39, against 4 and 16 at `medium`.
- Recall is 2 or 3 of 4 in every arm, a one-golden spread on a single PR, so it says nothing
  about effort.

Every ratio comes from one PR at one pass per cell. Between the two pilots, the same arm on the
same PR moved by about 9% for sonnet (`medium`, $0.227 to $0.208) and about 4% for opus ($0.656
to $0.683). So sonnet's "flat to `high`" is within run-to-run noise. Opus's 1.18× is probably
real, but one sample can't size it. The 2–2.6× at `xhigh` is clearly outside the noise.

## Sweep budget (projected from both pilots)

The basis is the first pilot's mean per pass at `medium` ($0.171 sonnet, $0.492 opus, over 2
PRs), scaled by the mini-pilot's per-level ratios. That gives these projections per pass:

- sonnet: $0.171 at `medium`, $0.169 at `high`, $0.445 at `xhigh`
- opus: $0.492 at `medium`, $0.579 at `high`, $1.015 at `xhigh`

The judge is $0.146 per pass, the higher of the two pilots ($0.117 here). Every design runs
both models on every (PR, level), so the model comparison stays paired throughout. The review
column assumes each level appears equally often. The plan's real split (17/17/16 pairs at 50
PRs, 9/8/8 at 25) moves it by less than $0.6.

| design | passes | reviews | judge | **total** | serial wall |
|---|---|---|---|---|---|
| `rotate2`, 50 PRs | 200 | $95.6 | $29.2 | **~$125** (range $105–250) | ~7 h |
| `round-robin`, 50 PRs | 100 | $47.8 | $14.6 | **~$62** (range $55–125) | ~3.5 h |
| `rotate2`, 25 PRs | 100 | $47.8 | $14.6 | **~$62** (range $55–125) | ~3.5 h |

- **`rotate2`** runs each PR at 2 of the 3 levels, so every pair of levels is compared on
  the same PRs and PR difficulty cancels out.
- **`round-robin`** runs each PR at one level, so effort is compared between PRs: about 17
  per level, against a spread between PRs that the first pilot showed is large (2× in cost,
  and different goldens caught). It would detect only a large effort effect.
- **`rotate2` at 25 PRs** costs what `round-robin` does and keeps the within-PR effort
  comparison, but it halves the model pairs.

The ranges, the judge's lean high, and plan usage rather than a bill are as before: PR size
drives turns, the full set averages 2.7 goldens per PR against the pilots' 4, and the CLI's
`total_cost_usd` is an API-equivalent rate on the subscription login. Wall is serial reviews
plus judging at 4 workers (about 40 s per pass). Any design needs a cerberus admission, and
the throwaway-request step comes first.

**Status:** BJ chose `rotate2` at 50 PRs (`bj:needs` #130). It is running as Sweep A, below.

## Sweep A, 2026-10-31

`rotate2` over all 50 PRs × {`claude-sonnet-5-5`, `claude-opus-5-5`}: 200 passes, run serially
under `nice -n 10` on malory (admission a-7d33be). Every PR ran at two of the three levels, with
both models at each. Per level pair that is 17 PRs for `medium`/`high`, 17 for `medium`/`xhigh`
and 16 for `high`/`xhigh`. The harness was #1396's tree (`cc80d7a`), the judge
`claude-sonnet-5-5`, and the persona sha256 `e79b6f21…c1551`. A throwaway request under each
pass's `precheck_variant` label went first (`prime.py`), as in the mini-pilot. Every number below
comes from `report`, `compare` and `fp-sample` (#1398) over the run directory, never from an
estimate.

**Status:** complete.
- **Reviews:** 07:22:14Z to 11:48:16Z, 200 of 200 ok.
- **Judge:** `jobd-golden.py judge --workers 4` from #1408's tree, 12:31:41Z to 14:00Z, with 0 failed calls. It reused the 200 extract results of an earlier run.
- **That earlier run (r1, 11:49:35Z to 12:18:44Z) is invalid and excluded.** Its dedup and judge calls timed out behind the shim's queue (#1406), which scored every candidate as a false positive. Its outputs are kept in `r1-invalid/` in the run directory.

The tables come from `report --run .bench/runs/sweep-a --judge-model claude-sonnet-5-5` and `compare` with the same arguments.

**Cost.** The reviews cost $72.66 at the harness's `total_cost_usd`: opus $54.16, sonnet $18.50. The judge cost $18.81 (3,484 calls), of which $2.74 is the reused extract. The invalid r1 cost $4.74 (831 calls), about $2.00 of it wasted.

The fleet's `cc_cost_usd`, summed per series by its final value, read 105% of the review ledger. The extra ~$3.9 is the 200 throwaway priming requests, which the ledger leaves out. For the judge window it read 100%. Prometheus `increase()` reads 87% overall and as low as 66% on the cheap arms. That's because it drops each new series' first sample, and every (variant, PR) is a new series. Use the final-value method for cross-checks. The ledger stays the source for results.

### Per arm (`report`)

| arm | passes | TP | FP | FN | recall | USD / pass | wall / pass |
|---|---|---|---|---|---|---|---|
| sonnet.medium | 34 | 45 | 91 | 44 | 50.6% | 0.090 | 21 s |
| sonnet.high | 33 | 43 | 110 | 44 | 49.4% | 0.145 | 34 s |
| sonnet.xhigh | 33 | 55 | 122 | 43 | 56.1% | 0.323 | 92 s |
| opus.medium | 34 | 43 | 115 | 46 | 48.3% | 0.297 | 48 s |
| opus.high | 33 | 53 | 124 | 34 | 60.9% | 0.439 | 73 s |
| opus.xhigh | 33 | 51 | 130 | 47 | 52.0% | 0.896 | 158 s |

Per-arm sums mix PRs of different difficulty. The paired tables below answer the questions.

### Model: sonnet vs opus on the same (PR, level) (`compare` → `model`)

| level | PRs | opus TP | sonnet TP | sonnet wins / ties / losses | sign p | cost ratio (geomean, median) |
|---|---|---|---|---|---|---|
| medium | 34 | 43 | 45 | 8 / 19 / 7 | 1.0 | 0.303, 0.308 |
| high | 33 | 53 | 43 | 4 / 20 / 9 | 0.27 | 0.331, 0.332 |
| xhigh | 33 | 51 | 55 | 8 / 21 / 4 | 0.39 | 0.373, 0.379 |
| pooled | 50 | 147 | 143 | 12 / 22 / 16 | 0.57 | 0.334, 0.344 |

### Effort: the higher level against the lower, same PR and model (`compare` → `effort`)

| levels | model | PRs | lower TP | higher TP | higher wins / ties / losses | sign p | cost ratio (geomean, median) |
|---|---|---|---|---|---|---|---|
| high vs medium | opus | 17 | 22 | 24 | 2 / 15 / 0 | 0.50 | 1.367, 1.311 |
| high vs medium | sonnet | 17 | 20 | 22 | 4 / 11 / 2 | 0.69 | 1.556, 1.482 |
| xhigh vs medium | opus | 17 | 21 | 26 | 4 / 13 / 0 | 0.13 | 2.673, 2.501 |
| xhigh vs medium | sonnet | 17 | 25 | 30 | 6 / 10 / 1 | 0.13 | 3.287, 3.496 |
| xhigh vs high | opus | 16 | 29 | 25 | 1 / 11 / 4 | 0.38 | 1.906, 1.818 |
| xhigh vs high | sonnet | 16 | 21 | 25 | 3 / 11 / 2 | 1.0 | 2.097, 1.970 |
| high vs medium | pooled | 17 | 42 | 46 | 5 / 10 / 2 | 0.45 | 1.459, 1.422 |
| xhigh vs medium | pooled | 17 | 46 | 56 | 9 / 8 / 0 | **0.0039** | 2.964, 2.914 |
| xhigh vs high | pooled | 16 | 50 | 50 | 2 / 9 / 5 | 0.45 | 1.999, 1.869 |

**How to read the sign test.** Wins, ties and losses are counted per PR. The `PRs` column is
`compare`'s `prs` field, never `n`, which counts pairs and is twice `prs` in a pooled row. In
a pooled row a PR holds two pairs (two levels in the model table, two models in the effort
table), and its outcome is the sign of their summed TP difference, because two pairs on one
PR are not independent evidence. The test is exact and two-sided, with ties dropped. With
no ties, p under 0.05 takes these splits:

- an effort cell (16 or 17 PRs): 13 to 3, or 13 to 4;
- a model cell at one level (33 or 34 PRs): 23 to 10, or 24 to 10;
- a pooled model row (50 PRs): 33 to 17.

Ties lower the count and raise the bar. A null result means "no effect large enough to see",
not "no effect".

### False positives, spot-checked by hand (`fp-sample`)

Precision is a floor until a sample is checked, because the goldens aren't exhaustive. The
sample is split evenly between the models, drawn with a recorded seed, and blinded: the
worksheet's table hides the arm, and its key is opened only after every verdict is in. It is a
sample of findings, not of distinct defects. A model reviews each PR at two levels, so the same
issue can be drawn twice, once from each level.

| model | FPs | sampled | real | not real | unsure | corrected precision |
|---|---|---|---|---|---|---|
| opus | 369 | 15 | 11 | 3 | 1 | 0.285 → **0.81** (0.86 if the unsure one is real) |
| sonnet | 323 | 15 | 8 | 6 | 1 | 0.307 → **0.68** (0.72) |

Seed: 20261031 (`fp-sample --run .bench/runs/sweep-a --judge-model claude-sonnet-5-5 --n 30
--seed 20261031`). Worksheet: [`sweep-a-fp-sample.md`](sweep-a-fp-sample.md), verdicts filled in
and the key below its table.

Corrected precision is (TP + FP × real/sampled) / (TP + FP), with each model's real share applied
to its own FPs.

**Who checked.** Three agents did the checking, each with a third of the sample. Each was blind
to the arm, and each read the PR's diff and its head-commit files and cited `file:line` for every
verdict. The key was opened only after all 30 were in. One "real" verdict was re-checked against
the source by hand (row 18: `absolutize_urls` turns `//cdn…` into a site-relative path). It held.
"Real" includes three defects in code the PR didn't change (rows 2, 25, 26).

**Sampling error.** At 15 a model the real share is loose: 11/15 has a 95% interval of about
0.45–0.92, and 8/15 one of about 0.27–0.79. The model gap is not significant (Fisher exact,
p = 0.45).

### What it shows

**No detectable TP difference between sonnet and opus, at a third of the price.** Paired on the
same PR and level, the true-positive counts don't separate:
- pooled over all 50 PRs, sonnet wins on 12, ties on 22 and loses on 16 (p = 0.57);
- no single level comes near the bar. The largest gap, at `high`, favours opus, 53 TPs against
  43 (sonnet wins 4, loses 9; p = 0.27).

That is a null result, not a finding of equivalence: a shortfall of about a fifth, like the one
at `high`, is too small for this sweep to see. Sonnet costs 0.33× opus per pass (geometric mean;
0.30–0.37 by level).

**Effort: no pair survives correction; `xhigh` against `medium` is the only hint.**
- **xhigh against medium (pooled):** 9 wins, 0 losses, p = 2/512 = 0.0039, about 22% more TPs (46 → 56) at 3.0× the cost.
- **Other pairs:** `high` against `medium` and `xhigh` against `high` show nothing (p = 0.45 each).
- **Multiple tests:** 13 sign tests were run (4 model, 9 effort). The Bonferroni bar at 0.05 is 0.05/13 = 0.0038, and 0.0039 is just above it, so the result does not survive correction. With 17 PRs and 8 ties, 9 to 0 is the most extreme split possible, so this sweep could not have cleared the corrected bar on that pair at all.
- **Not monotonic:** the gain doesn't show up as a step through `high`. Read it as "maybe a modest recall gain at `xhigh`", worth a confirming run, not as a settled effect.

**Raw precision is a floor, and a low one.** On the point estimates, a hand-checked sample puts
corrected precision near 0.8 for opus and 0.7 for sonnet, against 0.29–0.31 raw, so the goldens
would miss more than half of what the reviewers flag that is real. The intervals are wide. At
the low end of sonnet's, 0.27 × 323 ≈ 87 real FPs is under its 143 TPs, so the goldens would
not miss most. The pooled real share, 19/30, has a 95% interval of about 0.44–0.80, which
includes 0.5. The sample
can't tell the models apart, but it moves where the reading should start: a finding Job D raises
that isn't in the goldens may well be a real defect, and should be read, not discounted.

**For `/precheck`'s Job D**, on this evidence:
- **Model:** sonnet at `medium` showed no detectable TP shortfall against opus at `medium`, at a third of the cost.
- **Effort:** `xhigh` might add recall for about 3× the cost and 3.3–4.4× the wall time (per-arm means, unpaired, which overstate the ratio as they did the cost by 10–13%). That's a trade to confirm before buying it, not one this sweep settles.

The sweep doesn't measure severity-weighted value. All rows count a Low golden the same as a
Critical.
