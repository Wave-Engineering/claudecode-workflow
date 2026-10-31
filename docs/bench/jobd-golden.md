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

## Sweep budget (projected from both pilots)

The basis is the first pilot's mean per pass at `medium` ($0.171 sonnet, $0.492 opus, over 2
PRs), scaled by the mini-pilot's per-level ratios. That gives these projections per pass:

- sonnet: $0.171 at `medium`, $0.169 at `high`, $0.444 at `xhigh`
- opus: $0.492 at `medium`, $0.579 at `high`, $1.015 at `xhigh`

The judge is $0.146 per pass, the higher of the two pilots ($0.117 here). Every design runs
both models on every (PR, level), so the model comparison stays paired throughout.

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

**Status:** waiting on BJ's choice of design. Nothing past the mini-pilot has run.
