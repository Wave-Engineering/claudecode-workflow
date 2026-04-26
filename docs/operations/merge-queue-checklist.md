# Merge Queue Setup Checklist

Operational runbook for enabling GitHub Merge Queue on a repository (and verifying it actually works, not just that the configuration exists).

## Why This Document Exists

On 2026-04-07, all 6 Wave-Engineering GitHub repos had merge queue rulesets created without the corresponding workflow event trigger update. The configuration looked correct (`gh api ... rulesets` returned IDs, `max_entries_to_build: 1`, branch protection wired up) but **no PR could ever merge through the queue** because the workflow producing the required check was never invoked when GitHub added the PR to the queue. PRs sat forever waiting for checks that never fired.

The bug was caught only when the first PR (`mcp-server-sdlc#40`) actually exercised the queue end-to-end. The fix required temporarily deleting the rulesets to permit admin merges, landing the workflow change, then recreating the rulesets — see "Bootstrap Deadlock" below.

The lesson: **configuration existence is not configuration correctness.** Verification must include behavior testing — open a real PR and watch it merge.

## Pre-Rollout Checklist

Before enabling merge queue on a repo:

- [ ] Identify every workflow file that produces a status check listed as required in the target branch protection rule.
- [ ] Confirm the repo's `main` (or default) branch protection rule names the check(s) you intend to make required.
- [ ] Confirm no other workflow inadvertently produces a same-named check (would short-circuit the queue's wait).

## Workflow Trigger Requirement (LOAD-BEARING)

**Every workflow that produces a check required by the merge queue MUST subscribe to the `merge_group` event.**

From the official GitHub docs:

> You **must** use the `merge_group` event to trigger your GitHub Actions workflow when a pull request is added to a merge queue.

Required `on:` block shape:

```yaml
on:
  pull_request:
    branches: [main]
  merge_group:
```

Without `merge_group:`, GitHub adds the PR to the queue, no workflow fires, and the required check never reports — the PR sits in the queue indefinitely.

This is the single most common silent failure mode of GitHub Merge Queue. **It is not optional and there is no warning when it is missing.**

## Rollout Steps

1. **Update workflow event triggers** — for every workflow producing a required check, add `merge_group:` to the `on:` block. Land this change via a normal PR **before** enabling the queue ruleset.
2. **Create the merge queue ruleset** — `gh api repos/:owner/:repo/rulesets` with the merge-queue rule. Confirm `max_entries_to_build` matches the desired serialization mode.
3. **Wire branch protection required checks** — the queue's required-check list should match (or be a subset of) the branch protection rule's required check list.
4. **Verify ruleset is active** — `gh api repos/:owner/:repo/rulesets/<id>` returns `enforcement: active`.

## Post-Rollout Verification (THE STEP THAT WAS MISSED)

**Configuration verification is necessary but not sufficient. End-to-end merge verification is the contract.**

- [ ] **Verify workflow trigger:** for each workflow producing a required check, confirm `merge_group:` appears in the `on:` block. `grep -l "merge_group" .github/workflows/*.yml` should list every required-check producer.
- [ ] **Open a dummy PR** — a one-line README typo fix or a comment-only change. Branch off `main`, push, open PR.
- [ ] **Add the PR to the merge queue** via the UI or `gh pr merge --auto --squash <number>`.
- [ ] **Watch the queue** — `gh api repos/:owner/:repo/actions/runs?event=merge_group` should show a workflow run firing within ~30 seconds of queue entry. If no run appears within 2 minutes, the workflow trigger is wrong.
- [ ] **Confirm the PR merges end-to-end** — the queue should advance, the workflow should report green, and the PR should land on `main` without manual intervention.
- [ ] **Delete the dummy branch.**

If any of those steps stalls, **the merge queue is broken** regardless of what `gh api ... rulesets` reports. Roll back, fix, re-verify.

## Bootstrap Deadlock (Reference)

If you discover that an active merge queue ruleset is enforcing a never-firing check (the failure mode this doc exists to prevent), you cannot simply land the workflow fix — the broken ruleset blocks the very PR that would fix it. Even `--admin` merges are rejected once newer ruleset enforcement is in place.

The only path through the deadlock:

1. **Delete the merge queue ruleset** — `gh api -X DELETE repos/:owner/:repo/rulesets/<id>`. Branch protection alone permits the merge.
2. **Land the workflow fix PR** with `--admin` (or normal merge if branch protection allows it after ruleset deletion).
3. **Recreate the merge queue ruleset** with the same configuration as before.
4. **Run the post-rollout verification checklist** above against the rebuilt configuration.

This is a one-time bootstrap exception. Do **not** keep `--admin` enabled or rely on it for ongoing work — the going-forward rule is "no `--admin` merges anywhere."

## Affected Repos (2026-04-07 Bootstrap)

For institutional record. All 6 had `merge_group:` added via one-time admin merges:

- `Wave-Engineering/claudecode-workflow` (PR #298)
- `Wave-Engineering/mcp-server-discord` (PR #36)
- `Wave-Engineering/mcp-server-discord-watcher` (PR #2)
- `Wave-Engineering/mcp-server-nerf` (PR #12)
- `Wave-Engineering/mcp-server-sdlc` (PR #40 — also carried story #39 codegen pipeline)
- `Wave-Engineering/mcp-server-wtf` (PR #12)

## Related

- Postmortem: `claudecode-workflow#299`
- Lesson: `lesson_merge_queue_gh.md` (GitHub merge-queue gotcha — `gh pr merge` inconsistency)
- Policy: `policy_wave_engineering_merge_config.md` (all Wave-Engineering repos MUST have merge-queue + auto-merge enabled)
- The meta-lesson — verification must look at behavior, not declarations — also drove the runtime smoke test added to `mcp-server-sdlc` `validate.sh` in story #39.
