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

The arms differ by `--model` and nothing else (`test_arms_differ_only_by_model`):

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
  `OTEL_RESOURCE_ATTRIBUTES=precheck_variant=<model|judge>,bench_case=<repo>-<pr>`.

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

2 PRs × {`claude-sonnet-5-5`, `claude-opus-5-5`}, run serially on malory (admission a-2af983),
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

## Sweep budget (projected from the pilot)

50 PRs × 2 arms, paired, one pass each:

| item | basis | projected |
|---|---|---|
| sonnet reviews | 50 × $0.171 | $8.5 |
| opus reviews | 50 × $0.492 | $24.6 |
| judge | 100 passes × $0.146 | $14.6 |
| **total** | | **~$48** (range $40–100) |

The range allows for PR size: both pilot PRs are about 1,000 diff lines, and larger PRs
mean more turns. The judge line errs high: the full set averages 2.7 goldens per PR against
the pilot's 4, and judge calls scale with candidates × goldens. The USD figures are the CLI's
`total_cost_usd`. The runs use the fleet's subscription login, not an API key (`--bare` is
never used), so they draw plan usage at that API-equivalent rate rather than a bill.

Wall-clock at the pilot's settings: about 73 min of serial reviews plus about 68 min of
judging at 4 workers, so roughly 2.5 h on a shared host. It needs a cerberus admission.

**Status:** waiting on BJ's go (`bj:needs` #123). Nothing past the pilot has run.
