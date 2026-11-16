# AC and DoD must be checkable before the item closes

**The rule (BJ, 2026-11-16).** An issue, epic, plan, PR or MR must never carry an acceptance
criterion or definition-of-done line that cannot be checked until after the item is closed.
It generalizes BJ's 2026-10-24 ruling (#1365: no line may need a *merge* to assess) to every
item and to every way an item closes: a merge, a hand close, a wave finishing, a campaign
ending.

Every skill that tells an agent how to write one of these items carries the one-sentence form
and points here. `scripts/precheck-ac-gate.sh lint` is the mechanical check, and it is a
backstop, not the rule: it knows phrasings, and a line it passes can still be post-close.

## What waits for the close

A line is post-close when the item can be closed and the line still cannot be ticked. The
shapes the lint knows (pattern ids in parentheses):

| Shape | Examples | Ids |
|---|---|---|
| Waits for a merge, release, tag, install or deploy | "after merge", "v1.2 is tagged", "the fix is released", "deployed" | P1-P6 |
| Waits for the close or a launch | "after close", "once it is closed", "when the epic closes", "after rollout", "after go-live" | P7 |
| Waits for time to pass | "no regressions for one week", "soak 24 h", "runs clean within 3 days", "tomorrow", "overnight" | P8 |
| Waits for a later event | "on the next ./install", "the next campaign runs clean" | P9 |
| Waits for a live environment | "verified in aws-test", "the live server shows X", "first real run", "The operator re-pins it", "is promoted" | P10 |
| Waits for someone's later word or a watch | "observed working", "no incidents are reported", "the customer signs off", "monitored for errors" | P11 |

A span of days, a `close` or a `re-pin` alone is not enough: "logs are retained for 7 days", "flushed when closed" and "the Dockerfile re-pins the digest" are checkable on the head and pass. The lint flags a span beside a word that says something must hold over it ("no regressions for one week"), a close only when the item is named ("when the epic closes") or the bare noun ends a clause ("filed on close"), and a re-pin or roll-out only when an operator does it.

The lint reads every checkbox, and every list item and table row (header rows excepted) under an Acceptance Criteria,
Definition of Done, DoD, Done when, Success criteria or Exit criteria heading, or under a bold
`**DoD:**` or `**Acceptance Criteria:**` label. It does not read prose. It cannot decide a
person's judgment ("BJ confirms the chime sounds subtle") or an artifact the release writes
("the digest appears in the release notes"): the author has to catch those.

## How to rewrite a line

Replace the wait with something checked on the PR/MR head, before the merge:

| Instead of | Write |
|---|---|
| "after install, the hook equals the kit" | a test that installs into a sandbox and compares; or `diff` of the installed copy against the source in CI |
| "the live server shows 0.16.0" | the pin or version string in the changed file, read in the diff |
| "no regressions for a week" | the regression test that pins the old failure, passing on the head |
| "verified in aws-test" | the render or plan output on the head, and the check CI runs against it |
| "the epic closes when the children are done" | "every child issue is closed" (checkable before the epic closes) |
| "the fleet picks it up on the next install" | the installer's own test, or a dry-run of it, exiting 0 |

Test: could you tick this box today, with the PR open and nothing merged, deployed or waited
for? If not, it is not a criterion.

## Where a real post-close check goes

A check that matters but truly needs the world to move is not deleted; it moves out of the
criteria:

- a **release or install runbook** step, or the release notes ("after the next install, run
  `<command>`");
- a **follow-up item** filed *after* the work lands, with its own checkable criteria;
- a **monitor or alert**, if it must hold over time;
- on `/sqtk`, a **triage squawk** while it is only a worry.

Do not hold the issue open to wait for it, and do not write "Refs #N" in place of `Closes #N` to
keep it open. The merge closes the item (`feedback_ac_must_be_premerge`).

## Escape hatches (unchanged)

- A line that names one of the words but is checkable before the merge ends with the literal
  `<!-- ac-gate: pre-merge -->`. `/precheck` lists every override at the merge call; use it for
  a real false positive only.
- Only BJ waives, with `WAIVED by BJ <YYYY-MM-DD>: <reason> (<url>)` at the end of the line.

## Where the rule is enforced and where it is not

| Where | What happens |
|---|---|
| `/issue` Step 2.5, `/prepwaves` 3.c, `/devspec` Step 3.5 | the agent runs `precheck-ac-gate.sh lint` on the drafted bodies and does not create anything on exit 2 |
| `/precheck` Job E, `/mmr` 6.5 | the gate grades the PR/MR body and every issue the PR closes; exit 2 blocks the merge |
| Not enforced | an item created by `gh issue create`, `glab issue create` or the sdlc `work_item` tool directly; an epic or plan closed by hand, which never passes a PR gate. Only the instruction and the author's judgment cover these. |

The last row is the gap a creation-time check would close; it is a separate decision.
