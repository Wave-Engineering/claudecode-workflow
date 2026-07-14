# Branch Protection Setup Checklist

Operational runbook for configuring branch protection on a repository — and verifying it actually
works, not just that the configuration exists.

## Why This Document Exists

**Configuration existence is not configuration correctness.** Verification must include behavior
testing — open a real PR and watch what happens to it.

That lesson was bought with an outage. On 2026-04-07, all 6 Wave-Engineering GitHub repos had branch
rulesets that *looked* correct — `gh api ... rulesets` returned IDs, enforcement was active, branch
protection was wired up — but **no PR could merge**, for hours. A workflow producing a required check
was never invoked, so the check never reported, and every PR sat waiting on a status that would never
arrive. The bug surfaced only when the first PR (`mcp-server-sdlc#40`) actually exercised the path
end-to-end. Postmortem: `claudecode-workflow#299`.

Nothing about the API responses would have told you. Only a real PR did.

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

**Merge method is chosen per merge** (`gh pr merge --squash` vs `--merge`), never pinned per repo.
That is what lets one config serve both wave campaigns (merge-commit promote) and normal maintenance
(squash) for the whole life of the repo, with nothing to toggle.

Wave campaigns need no special repo configuration. Flights land on the `kahuna/*` integration branch,
never on the protected branch; the engine reconciles them with `flight_partition` / `flight_overlap`
and `commutativity_verify`, merging in dependency order. `kahuna→main` is then a single serialized,
trust-gated promotion. **Nothing ever merges to the protected branch concurrently**, so the protected
branch needs no serialization machinery beyond required checks.

## Two Traps

**1. `required_linear_history: true` forbids merge commits.** It blocks the merge-commit promote path,
and the failure does not announce itself as a linear-history problem. If the wave engine needs to land
`kahuna→main` as a merge commit — it does, whenever the kahuna branch is preserved across waves — this
must be `false`.

**2. Rulesets and classic branch protection are separate systems.** A repo can carry required checks in
one, the other, or both. Before deleting *any* ruleset, confirm what classic branch protection
(`gh api repos/:owner/:repo/branches/main/protection`) independently enforces — delete without checking
and you can leave the branch naked while the API still reports everything as fine.

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
- Policy: `policy_wave_engineering_merge_config.md` — the house rules this config implements
- The meta-lesson — verification looks at behavior, not declarations — also drove the runtime smoke
  test in `mcp-server-sdlc` `validate.sh` (story #39).
