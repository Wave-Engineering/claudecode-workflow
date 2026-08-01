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
3. **DEFAULT-DENY — merge only on an explicit pass.** Proceed **only** if `checks.summary == "all_passed"`. **Any other value STOPs**, including values that do not exist yet.

   This is deliberately an allowlist. The previous form blocked on `has_failures` and merged on everything else, which meant an unrecognised summary read as permission. That is how this gate was **inert on GitHub for its entire life**: `gh pr checks --json` does not exist on `gh 2.45.0` (the fleet version), the adapter left `summary` at its `'none'` initialiser and still returned `ok: true`, and `'none'` matched neither the `pending` branch nor the `has_failures` branch — so every GitHub merge fell straight through to step 4. The gate reported fine and did nothing. (cc-workflow#925; upstream reporting defect `mcp-server-sdlc#491`.)

   **`none` is not evidence of passing — it means the query told us nothing.**

   **On `none` (or any unrecognised value), do NOT stop outright — escalate to a source that works.** `pr_status` and `pr_wait_ci` do **not** share a code path, so a blind spot in one is not a blind spot in both. Measured on the same PR, same host, seconds apart (`gh 2.45.0`, **before** the `pr_status` fix in `mcp-server-sdlc#491`) —

   ```
   pr_status(32)   → checks: {total:0, passed:0, failed:0, pending:0, summary:"none"}
   pr_wait_ci(32)  → {total:2, passed:2, failed:0, pending:0}      ← correct
   gh pr checks 32 → lint pass, test pass                          ← agrees with pr_wait_ci
   ```

   So: call `pr_wait_ci(number)` and treat **its** result as authoritative — **as an allowlist, exactly like step 3 itself.** Proceed **only** on `status == "passed"`. **Every other status STOPs, including ones not listed here:**
   - `passed` → proceed. *(the only value that proceeds)*
   - `failed` → STOP.
   - `timed_out` → STOP.
   - `no_checks_configured` → **STOP.** The head-SHA cross-check ran and found no CI runs: this repo genuinely runs no checks for this ref. **A repo with no required checks is not a repo whose checks passed.** Route it to the no-checks-configured branch below.
   - `no_checks_yet` → **STOP.** Either runs exist for the head SHA that have not registered as checks, or the cross-check could not be run at all (`blocker: evidence_unavailable`). Never `mergeable`. This is not a question for a human — it means **wait, or find out why CI is not reporting**. If a forge routinely takes longer than the 45s default to register, widen `settle_window_sec` rather than learning to wave the status through.
   - `no_checks_required` → **gone as of `mcp-server-sdlc` v4.0.0 (#508).** Kept named here because the history is the reason the rule above exists. It was a *definite, successful* verdict returned at t=0 on an empty rollup (`mcp-server-sdlc#416`) — and an empty rollup is also exactly what a merely-QUEUED check looks like, so a PR whose CI had not started got a verdict whose plain-English name reads as "nothing is wrong." It was **removed rather than aliased** precisely so callers matching the old literal stop matching. If you are reading this in a transcript where it still appears, the server is older than v4.0.0: **STOP**.
   - `{ok: false}` or any error envelope → **STOP** and surface the error; do not silently continue past a gate that failed to run.
   - anything else → **STOP.** Two independent sources unable to confirm a pass is a stop, not a shrug.

   **Why this sub-list is an allowlist too (cc-workflow#925 code review):** the first draft of this fix converted the *outer* gate from a blocklist to an allowlist and then wrote the *inner* escalation as a blocklist — enumerating the statuses that stop, which silently permits every status nobody thought of. `no_checks_required` was already live and unlisted, so the escalation would have merged on it. (That token is now retired — see #508 — and its two successors are listed above explicitly rather than left to the catch-all, which is this rule being honoured rather than merely relied on.) **Fixing a defect at one layer while reproducing it at the next is the failure mode this whole section is about.** If `pr_wait_ci` ever gains a new status, it must land here as an explicit STOP before anything merges on it.

   Stopping outright would have been *correct but useless* at the time this was written: `pr_status` returned `none` for **every** GitHub PR on `gh 2.45.0`, so a bare default-deny converts a silent-permit into a total merge block. Default-deny means **never proceed without an explicit pass**; it does not mean refuse to go and get one.

   **Do not delete the escalation once `pr_status` is truthful.** `mcp-server-sdlc#491` fixes the GitHub instance, not the class — `mcp-server-sdlc#494` records the same silent-permissive shape on GitLab (`no_pipeline_data` returned with `ok: true`), still open. The escalation is written against **any** unrecognised summary precisely so it keeps working for variants nobody has named yet; narrowing it to the one value we happened to measure would rebuild the defect this section exists to close.

   Once `pr_wait_ci` has stopped you, distinguish the causes by hand, because they need different responses:
   - **no checks configured on this repo** (`no_checks_configured`) → a human decides whether merging without CI is acceptable here;
   - **checks exist but have not reported** (`no_checks_yet`) → not a decision, a wait. Re-run the gate, or widen `settle_window_sec`. If `blocker: evidence_unavailable`, the ref cross-check itself could not run — fix that before inferring anything;
   - **the query failed** (unsupported flag, auth, network) → fix the query; infer nothing about the checks.

   **If there is no human — HALT, do not improvise.** On a `kahuna/*` sandbox, under `/wavemachine` in `auto` mode, or with an armed `godspeed` mandate, "a human decides" has no addressee. Do **not** resolve it yourself: **do not merge**, emit a structured blocker (`wave-hold` shape on wave paths) naming the PR and the unresolved cause, and let the wave gate escalate it. An autonomous agent that reaches an underspecified branch will improvise, and improvising toward *proceed* is the exact failure this gate exists to prevent — the more so because `/precheck` lists this gate as non-bypassable *precisely because* it is the last control once the human is gone.

   Verify with `gh pr checks <number>` (no `--json`) or `gh run list --branch <head>`. **Do not read a bare "no output" as a pass** — that is the same failure one layer down.
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
- ONLY merge if `checks.summary == "all_passed"` — an allowlist, never a blocklist. `has_failures` blocks, and so does `none`, and so does any value not in this list. A blocklist of known-bad states silently permits every state you did not think of, which is exactly how this gate sat inert (cc-workflow#925). **But on `none`/unrecognised, escalate to `pr_wait_ci` first (step 3) — stop only if that also cannot confirm a pass.** Without that clause this rule reads as "block every GitHub merge", because `pr_status` returned `none` for every GitHub PR on `gh 2.45.0`.
- `pr_wait_ci` is an allowlist too — proceed only on `passed`. **`no_checks_configured` and `no_checks_yet` are both STOPs**, not passes: they mean the probe found nothing to wait for, or found that CI has not reported yet — never that anything succeeded. (`no_checks_required` was their single ambiguous predecessor, retired in `mcp-server-sdlc` v4.0.0.)
- NEVER merge into a protected, non-default, non-`kahuna/*` branch — `branch_guard` STOPs this (target must be the live default or a `kahuna/*` sandbox)
- Always squash + delete source branch
- Squash message replaces the entire commit history — make it comprehensive
- Merge conflicts → STOP and report, do NOT attempt to resolve
- Tool failure → report the `{ok: false, code, error}` envelope and suggest resolution
