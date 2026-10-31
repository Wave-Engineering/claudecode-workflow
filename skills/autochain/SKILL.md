---
name: autochain
description: Plan a dependency-ordered chain of issues, then execute it autonomously on approval
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-autochain does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-autochain
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Autochain

Two stages. `plan` decides the order and stops. `run` executes an approved order.

**Policy lives in CLAUDE.md, not here.** The prod boundary, the commit gate and the issue
lifecycle are stated there once. This skill points at them; it does not restate them, because two
homes for one rule drift apart.

## Stage 1 — `/autochain plan <epic-or-issue-list>`

Read-only. Produces a reviewable order and **stops for approval.**

1. **Gather** the candidate issues.
2. **Establish dependencies by measurement, not assumption.** For each edge, name what is
   actually blocked and how you know. An assumed dependency is how an issue sits behind a blocker
   that was fixed weeks ago.
3. **Check each issue is executable before sequencing it.** Run `spec_validate_structure`. Read
   the acceptance criteria and ask whether they describe work that is still outstanding — an
   issue whose ACs were satisfied elsewhere will otherwise be discovered mid-branch. If a spec is
   thin, fix it now; that is part of planning.
4. **Separate what you can work from what you cannot.** Anything needing a human decision, an
   access you lack, or a production change goes in its own list with the reason and the owner.
   **A chain that silently omits these reads as complete.**

   **Check the merge is actually gated by CI.** `run` merges without a human, which makes CI the
   *only* opinion between a change and the protected branch. Call
   `mcp__sdlc-server__wave_ci_trust_level`; anything other than `pre_merge_authoritative` means
   required checks do not gate the merge, so the whole chain goes on the cannot-work list with that
   reason. Be clear about what a pass proves: CI **gates** the merge — not that the CI is
   thorough. If you know a repo's checks are thin, say so in the plan.
5. **Write the order into the epic**, with a one-line "why here" per issue. The epic is the state
   between stages — durable, survives compaction, visible without asking.
6. **Present** the order, what is blocked and on whom, and **stop.** Do not start work.

## Stage 2 — `/autochain run <epic>`

Precondition: an approved order exists in the epic. If it does not, run `plan` instead.

**Arm the gate before the first issue.** BJ's approval of the order is what lifts `/precheck`'s
human STOP — under CLAUDE.md's "Exception: Approved Autochain", not under anything this skill
says. Record it where `/precheck` can check it, with his words verbatim. **Write the quote to a
file with the `Write` tool** — never `echo` or a heredoc, and never as a shell argument: his words
can carry backticks and `$(…)`, and a shell would run them before the gate ever saw them.

```bash
# <scratchpad>/autochain-approval.txt written with Write: BJ's approval, quoted exactly
autochain-gate.sh arm <repo_root> <epic> --approval-file <scratchpad>/autochain-approval.txt <issue> <issue> ...
```

List exactly the issues in the approved order — no more. An issue added later is a set change
(below) and needs a fresh approval and a fresh `arm`. The approval expires `AUTOCHAIN_TTL_HOURS`
after arming (default 12): a chain that outlives it stops at `/precheck`'s human STOP, and that is
the moment to ask BJ to renew, not to re-arm on the old words.

For each issue, in order, while unblocked:

1. Mark it started (per CLAUDE.md's lifecycle rules — mark on start, never hand-set a terminal state).
2. Branch from the live default.
3. Implement, then commit and push (`/scp`; free on a working branch).
4. **Run `/scpmr` — it opens the draft PR/MR and runs `/precheck`, the skill, not your own assembly of its parts.** If you find yourself
   hand-rolling IBM, spec validation, trivy or the code review, stop and run the skill. Its Step 5
   runs `autochain-gate.sh check`; for an armed issue that has **passed**, it emits
   `[AUTO-APPROVED: autochain #<epic>]` and invokes `/mmr` itself. Nothing in this skill grants
   that — the gate does.

   **"Passed" is mechanical, not a judgment.** ALL of:
   - every checklist item verified — none unchecked, none "deferred" to get past the gate;
   - the latest Job D pass has **zero** unresolved critical or important findings;
   - every lane Job B ran (validate **and** tests — it runs all of them) reports `exit=0` on its own
     `LANE` line. Never a sub-agent's summary, and never a partial or still-running suite: "still
     running, will complete shortly" is not a result. The suite may die with the agent that said
     it, and even if it lives, nobody is holding its exit code;
   - Job C exit 0. A `[SKIPPED]` scan is not a pass when no human is reading the checklist —
     stop and report it.

   Anything short of that is a failed precheck: fix it, or stop.
5. `/mmr` — invoked by `/precheck` on the sentinel, after it posted the `precheck` status and marked the PR/MR ready; do not invoke it yourself around a failed gate.
6. **Verify the post-state.** Read the merge back — a merge that returned 200 is not a merge.
   Confirm the merge closed the issue via `Closes #N`; close it by hand **only** if the merge did
   not (per CLAUDE.md: merge does the closing, never hand-set a terminal state). Then
   `autochain-gate.sh consume <repo_root> <issue>` — a landed issue leaves the approval, so a later
   branch reusing its number cannot inherit it — and update the epic.
7. Next issue. The last `consume` disarms the gate; if the chain ends any other way, `disarm`.

### When the plan turns out to be wrong

- **Order changes inside the approved set** → update the epic, keep going, one line to BJ.
- **The set changes** — a new blocker, an issue that needs filing, a dependency that did not
  exist — → **stop and re-enter `plan`.** Continuing means executing something that was never
  approved.

### When one issue will not converge

An autonomous loop needs exits that do not depend on the agent deciding it is stuck. **Stop work
on the issue and get loud** (see Stopping) the moment ANY of these is true:

- three Job D passes on this issue and still not clean;
- a finding comes back after a pass marked it RESOLVED;
- CI goes red twice after fix-forward on the same PR;
- the same precheck job fails twice for the same cause.

These are not reasons to file and move on — the issue is still the work. They are the point at
which grinding alone costs more than asking BJ, and burning an evening spinning on issue 2 of 7
is the failure mode they exist to prevent.

### Findings mid-run — fix them HERE by default; filing is the exception

**Default: work the finding inside the issue you are on.** Not because the current issue
would be broken without it, but because a separate MR is expensive and the expense is
invisible at the moment you decide. Each one costs its own `/precheck` — including an
opus code review — plus a full CI run, a merge pipeline, and one of BJ's approval gates.
Two adjacent findings split into two MRs pay all of that twice and review each half
without the other in front of the reviewer.

The old test here was "is the current issue functional without it?" That test is too
permissive and it produced a real miss: #32 (strip template-only CLAUDE.md sections) and
#35 (the same defect in README and getting-started) were the same defect class, the same
mechanism, adjacent files. #32 was *functional* without #35, so #35 was filed separately
— two prechecks, four code-review rounds and four CI runs for what was one piece of work.

**File separately only when fixing it here would BLOCK.** Two cases, and they are about
blocking, not about subject matter:

- **It needs a decision you do not own** — a policy or taste call, or anything
  prod-shaped. Folding it in means stalling the chain on BJ's reply.
- **It lives in a repo you are not in.** Cross-repo means separate authorization.

"Different files", "different component", "not mentioned in the AC" and "found by
accident" are **not** reasons to file. Neither is "it would make the MR bigger" — a
coherent MR that fixes a thing and its neighbour reviews better than two that each
omit half the story.

**If you fold work in, amend the issue.** Add the scope you took on and the acceptance
criteria that cover it, so Story Completion Verification still means something —
otherwise you ship work no criterion describes, and the checklist quietly becomes a
formality. Say in the MR that the issue grew and why.

**If you do file, put it on the epic's not-in-chain list** with its reason and owner, and
say so in one line. Do not add it to the chain: that is a set change (above) — it needs a
fresh approval and a fresh `arm`, and the gate will not approve it until it has one. A filed
issue that is in neither the chain nor the not-in-chain list is one nobody is holding.

## Reporting

**Boundaries, not steps.** Into BJ's window:

- one line when an issue starts, one when it lands,
- when you are blocked,
- when a finding changes the chain's shape or order,
- anything you got wrong that he might otherwise act on.

Everything else goes in the issue, the MR, or a memory. If in doubt, put it in the artifact and
give him the link.

## Stopping

Only for something you cannot get past yourself, or a decision that is his. A stop is cheap when
it is real and expensive when it is reflex — if you can name the specific irreversible action or
the specific fork, stop; otherwise act and report after.

Deploys and anything that changes what production runs are his, per the ABSOLUTE prod rule.
**Do not assume a chain is deploy-free** — check, and if a step turns out to touch a tier, that
is a stop.

**If you need him, get loud:** `vox`, then `/owtx #call-4-bj "<what you need and what it
blocks>"` (OaW Mattermost by default). If `vox` fails, say so rather than assuming he heard.

**Any stop ends the approval.** Run `autochain-gate.sh disarm <repo_root>` before you stop for
any reason. Approval attached to a chain that was running; a stopped chain resumes only on a fresh
approval and a fresh `arm`. Leaving the gate armed would let a later, unrelated session merge one
of these issues without anyone having approved it in that context.
