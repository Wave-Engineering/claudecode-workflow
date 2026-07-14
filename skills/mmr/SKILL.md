---
name: mmr
description: Merge a PR/MR with squash and source branch deletion
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-mmr does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-mmr
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Merge PR/MR

Squash-merge a pull request (GitHub) or merge request (GitLab) with a detailed commit message and source branch deletion. All platform differences are handled inside the MCP tools — no inline `gh`/`glab` bash.

## Tools Used
- `mcp__sdlc-server__pr_status` — state, merge_state, mergeable, checks summary, target branch
- `mcp__sdlc-server__branch_guard` — validate the merge target against the live default (protected-gated, `kahuna/*`-exempt)
- `mcp__sdlc-server__pr_diff` — unified diff for squash message drafting
- `mcp__sdlc-server__pr_wait_ci` — server-side block on pending checks (default 30s interval, 30min timeout)
- `mcp__sdlc-server__pr_merge` — squash merge (direct; the fleet is queue-less)
- `mcp__sdlc-server__ci_wait_run` — optional post-merge main-branch pipeline wait (default 10s interval)

## Procedure

Determine target PR/MR: use `{{args}}` if provided (strip any `!` or `#` prefix); otherwise resolve via `pr_status` on the current branch's PR or fail if none exists.

1. `pr_status(number)` → require `state == "open"`; inspect `checks.summary`. **Then guard the merge target:** call `branch_guard({ role: "target", branch: <PR/MR target from pr_status> })`; on `verdict == "warn"` **STOP** and surface `reason` — you are about to merge into a **protected** branch that is neither the live default nor a `kahuna/*` sandbox integration branch. Silent for the live default and `kahuna/*` targets. *(Transition fallback until `branch_guard` is deployed (#465): resolve the live default inline via `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` / GitLab `glab api "projects/:id" --jq .default_branch` and STOP if the target is neither the live default nor matches `^kahuna/[0-9]+-`. The degraded path can't query host protection, so it errs toward stopping on any non-default, non-sandbox target — safe, and rare in this trunk-based flow.)*
2. If `checks.summary == "pending"` → `pr_wait_ci(number, poll_interval_sec: 30, timeout_sec: 1800)`. On `timed_out` ask whether to wait longer. On `failed` STOP.
3. If `checks.summary == "has_failures"` → STOP and report. Do NOT merge with failing checks.
4. `pr_diff(number)` → use the diff content (plus `git log target..source`) to draft the squash commit message.
5. **Draft the squash commit message** (agent reasoning — this is the judgment layer):
   - Title: conventional commits `type(scope): description`
   - Body: what changed and why; key implementation decisions or trade-offs; notable side effects
   - Footer: `Closes #issue-number` for any linked issues (check the PR/MR description)
   - Comprehensive enough that `git log` alone tells the full story without opening the PR
6. **Present for approval**: PR/MR number, title, source→target branches, the drafted squash message. Ask "May I merge this PR/MR?" and WAIT. A second `/mmr` invocation counts as approval.
7. `pr_merge(number, squash_message)` — squash merge. Returns `merge_method`, `merge_commit_sha`, `url`.
8. **Post-merge**: switch to target branch, pull, delete local source branch if present. Optionally `ci_wait_run(ref: "main", timeout_sec: 1800)` to confirm the main-branch pipeline lands clean — skip if the user wants to move on immediately.
9. Report success with the merge commit URL.

## Important Rules

- NEVER merge without explicit user approval
- NEVER merge if `checks.summary == "has_failures"`
- NEVER merge into a protected, non-default, non-`kahuna/*` branch — `branch_guard` STOPs this (target must be the live default or a `kahuna/*` sandbox)
- Always squash + delete source branch
- Squash message replaces the entire commit history — make it comprehensive
- Merge conflicts → STOP and report, do NOT attempt to resolve
- Tool failure → report the `{ok: false, code, error}` envelope and suggest resolution
