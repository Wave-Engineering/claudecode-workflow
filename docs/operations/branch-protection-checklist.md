# Branch Protection Setup Checklist

Operational runbook for configuring branch protection on a repository — and verifying it actually
works, not just that the configuration exists.

## Why This Document Exists

**Configuration existence is not configuration correctness.** Verification must include behavior
testing — open a real PR and watch what happens to it.

That lesson was bought with an outage. On 2026-04-07, all 6 Wave-Engineering GitHub repos had merge
queue rulesets created without the corresponding workflow event trigger update. The configuration
looked correct (`gh api ... rulesets` returned IDs, `max_entries_to_build: 1`, branch protection
wired up) but **no PR could ever merge** because the workflow producing the required check was never
invoked when GitHub added the PR to the queue. PRs sat forever waiting for checks that never fired.
The bug was caught only when the first PR (`mcp-server-sdlc#40`) actually exercised the path
end-to-end. Postmortem: `claudecode-workflow#299`.

The merge queue is gone now (see "No Merge Queue" below) — but the meta-lesson outlives it, and is
the reason this checklist exists at all.

## The Standard Config

Every repo is born with this and keeps it for its whole life — no lifecycle toggling.

| Setting | Value | Why |
|---|---|---|
| Required status checks | on, `strict: true` | Green CI is the gate |
| Required reviews | none | Single-operator fleet; auto-merge on green *is* the gate |
| `allow_auto_merge` | `true` | PRs land themselves once green |
| Force-push / branch deletion | blocked | Protected means protected |
| `required_linear_history` | **`false`** | See the traps below — `true` forbids merge commits |
| `allow_squash_merge` | `true` (default method) | Normal PRs squash |
| `allow_merge_commit` | `true` | The wave engine's `kahuna→main` promote needs it |
| `allow_rebase_merge` | `false` | One less way to rewrite history |
| `delete_branch_on_merge` | `false` | Otherwise a persistent kahuna is deleted on promotion and the next wave strands |

Merge method is chosen **per merge** (`gh pr merge --squash` vs `--merge`), not per repo. That is the
whole reason one config serves both wave campaigns and normal maintenance — and it only works because
there is no merge queue forcing a single method for everything.

## No Merge Queue (and no GitLab merge trains)

**Do not enable a GitHub merge queue or GitLab merge trains.** If you find a repo without one, that is
correct — do not "restore" it.

Wave work never needed a queue. Flights target the `kahuna/*` integration branch, never the protected
branch. The engine reconciles them with `flight_partition` / `flight_overlap` and `commutativity_verify`,
merging in dependency order; `kahuna→main` is then a single serialized, trust-gated promotion. There is
no concurrent-merge-to-protected-branch point for a queue to guard.

What the queue actually cost:

- **3 pipelines per MR on GitLab** (push + merged-results + train). The claim that trains "batch
  flight-MRs into one pipeline run" is **false** — GitLab runs a pipeline *per MR in the train* and
  re-runs successors when a predecessor fails.
- **The `skip_train` divergence bug** — on a queue-enforced repo the flag was silently dropped and the
  queue's configured merge method governed instead, which is how a persistent kahuna diverged from main.
- **The 2026-04-07 outage** above, whose entire failure mode (`merge_group:` missing from an `on:` block)
  only exists because there is a queue.

Escalation: if a specific repo ever hits a genuine semantic merge race (two PRs green alone, broken
together, merged concurrently), raise it — a per-repo queue is a last resort, never a fleet default.

## Two Traps

**1. `required_linear_history: true` forbids merge commits.** It blocks the merge-commit promote path
*independently of any queue*, and the failure does not announce itself as a linear-history problem. If
the wave engine needs to land `kahuna→main` as a merge commit — it does, whenever the kahuna branch is
preserved across waves — this must be `false`.

**2. A merge-queue ruleset can be the only ruleset.** Before deleting one, confirm that classic branch
protection (`gh api repos/:owner/:repo/branches/main/protection`) independently carries the required
checks. Delete the ruleset without checking and you may leave the branch naked.

## Rollout Steps

1. **Set repo-level merge methods** — `gh api -X PATCH repos/:owner/:repo` with `allow_squash_merge=true`,
   `allow_merge_commit=true`, `allow_rebase_merge=false`, `allow_auto_merge=true`,
   `delete_branch_on_merge=false`.
2. **Set branch protection on the protected branch** — `gh api -X PUT
   repos/:owner/:repo/branches/main/protection` with the required checks (`strict: true`),
   `required_linear_history: false`, force-push and deletion blocked.
3. **Confirm it is active** — re-`GET` the protection and diff it against what you sent. The API
   accepting a payload does not mean it stored what you meant.
4. **Run the end-to-end verification below.** This is not optional.

## End-to-End Verification (THE STEP THAT GETS SKIPPED)

**Configuration verification is necessary but not sufficient. End-to-end behavior is the contract.**

A gate that blocks everything is as broken as one that blocks nothing. Only the *pair* of tests proves
it works — run both:

- [ ] **Red PR → BLOCKED.** Open a throwaway PR carrying a deliberately failing check (e.g. a broken
      test). Assert it **cannot** merge: `gh pr view <N> --json mergeStateStatus` reports `BLOCKED` and
      `gh pr merge <N>` is refused. *The gate holds.*
- [ ] **Green PR → MERGES.** Open a throwaway PR that is clean (e.g. a README typo fix). Assert it
      **merges through** the protection once checks pass. *The gate passes good work.*
- [ ] **Clean up** both throwaway branches.

If either stalls, **the protection is misconfigured** regardless of what the API reports. Fix, re-verify.

## Related

- Postmortem: `claudecode-workflow#299` (the 2026-04-07 outage that motivated behavior-testing)
- Policy: `policy_wave_engineering_merge_config.md` — the queue-less house rules
- The meta-lesson — verification looks at behavior, not declarations — also drove the runtime smoke
  test in `mcp-server-sdlc` `validate.sh` (story #39).

## Historical Record — the 2026-04-07 Merge-Queue Bootstrap

Kept for institutional memory. These 6 repos each carried a merge-queue ruleset from 2026-04-07 until
2026-07-13, when the fleet went queue-less and all six rulesets were deleted (classic branch protection,
which independently carried the required checks, was left intact):

- `Wave-Engineering/claudecode-workflow` (queue bootstrap PR #298)
- `Wave-Engineering/mcp-server-discord` (PR #36)
- `Wave-Engineering/mcp-server-discord-watcher` (PR #2)
- `Wave-Engineering/mcp-server-nerf` (PR #12)
- `Wave-Engineering/mcp-server-sdlc` (PR #40)
- `Wave-Engineering/mcp-server-wtf` (PR #12)
