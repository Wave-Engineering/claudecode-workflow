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
- `mcp__sdlc-server__pr_wait_ci` — server-side wait on pending checks (default 30s interval), bound to the head by `expected_sha`; each call is bounded and returns a resumable `pending` (step 2)
- `mcp__sdlc-server__pr_merge` — squash merge (direct; the fleet is queue-less)
- `mcp__sdlc-server__ci_wait_run` — optional post-merge main-branch pipeline wait (default 10s interval)
- `precheck-ac-gate.sh` — re-grades the AC just before the merge (step 6.5)

## Procedure

Determine target PR/MR: use `{{args}}` if provided (strip any `!` or `#` prefix); otherwise resolve via `pr_status` on the current branch's PR or fail if none exists.

1. `pr_status(number)` → require `state == "open"`; inspect `checks.summary`. **Then guard the merge target:** call `branch_guard({ role: "target", branch: <PR/MR target from pr_status> })`; on `verdict == "warn"` **STOP** and surface `reason` — you are about to merge into a **protected** branch that is neither the live default nor a `kahuna/*` sandbox integration branch. Silent for the live default and `kahuna/*` targets. *(Transition fallback until `branch_guard` is deployed (#465): resolve the live default inline via `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` / GitLab `glab api "projects/:id" --jq .default_branch` and STOP if the target is neither the live default nor matches `^kahuna/[0-9]+-`. The degraded path can't query host protection, so it errs toward stopping on any non-default, non-sandbox target — safe, and rare in this trunk-based flow.)*
1.5. **Precheck on the head (#1235).** Resolve the script as `/precheck` Step 0 does. Read the PR/MR's head as the platform sees it, `precheck-status.sh pr-head <repo_root> <N>` → `<head_sha> <head-branch> <base-branch>`, then run `precheck-status.sh get <repo_root> <head_sha>`.
   - `success` → continue.
   - Anything else: a push moved the head past the pass. Run **`/precheck rearm`** for this PR/MR. It refuses unless the local checkout is this PR/MR's head, reviews only the new commits, waits for CI, and on a clean delta posts the status on the new head. If rearm escalates to a full precheck, follow that one to its STOP.
   - **After a rearm, read the head again and `get` its status again.** Continue only if the head is the SHA rearm posted on and it reads `success`. Anything else → STOP. Rearm reporting success is not the check; the status on the PR/MR's head is.
   - Exit 3 (the head or the status could not be read) → STOP. Never merge on an unreadable gate.

   From the mcp-server-sdlc release that carries #592, `pr_merge` refuses a head without the status by itself. This step is what keeps that refusal from being the first you hear of it.
2. **The CI wait loop.** If `checks.summary == "pending"`, wait for CI this way. Step 3's escalation runs the same loop.
   - Record the start (`date +%s`), then call `pr_wait_ci(number, poll_interval_sec: 30, expected_sha: <head_sha from step 1.5's pr-head>)`. That head carries the precheck pass, so it is the head this merge binds to. `expected_sha` makes the server grade CI for exactly that commit, never a pipeline left over from an earlier head (mcp-server-sdlc#588).
   - **On `final_state == "pending"` with `resume == true`, call again with the same arguments,** plus the `max_wait_sec` cap below. The server bounds each call by `max_wait_sec` (default 1500 s), so a call returns before the MCP client's 1800 s idle timeout instead of dying silently (mcp-server-sdlc#587). `pending` is not a pass. It means "not finished yet, call again".
   - **Overall deadline: 60 minutes from the start.** When it expires with CI still pending, **STOP** with `CI still pending after <elapsed> min; checks <passed>/<total> passed, <pending> pending`. Ask whether to wait longer. An expired deadline is never a pass.
   - **Resumed calls never outrun the deadline.** On each resumed call, also pass `max_wait_sec: min(1500, <seconds left before the deadline>)`. When fewer than 1 s are left, the deadline has expired: STOP as above. Only a resumed call carries `max_wait_sec`. A server that returns `pending` knows the key, and the first call stays exactly as above, so the older-server fallback below sees only `expected_sha`.
   - Any other result ends the loop, and step 3's allowlist grades it. `failed` → STOP at once; it is never resumed.
   - **Older server.** A server from before the mcp-server-sdlc release carrying #588 rejects `expected_sha`. Its input schema is strict, so the call fails before the handler runs: usually as an MCP error (`-32602`, invalid params) with no JSON body, sometimes as `ok: false`. Either way its text contains `Unrecognized key(s) in object: 'expected_sha'`. **On exactly that error**, retry once without `expected_sha`, print `pr_wait_ci: server predates expected_sha (mcp-server-sdlc#588); head binding unavailable`, and continue the loop. That is the wait as it was before #588, no worse. Such a server never returns `pending`, so the loop ends on its first result. Any other MCP error or `ok: false` → STOP (step 3).
3. **DEFAULT-DENY — merge only on an explicit pass.** Proceed **only** if `checks.summary == "all_passed"`. **Any other value STOPs**, including values that do not exist yet.

   This is deliberately an allowlist. The previous form blocked on `has_failures` and merged on everything else, which meant an unrecognised summary read as permission. That is how this gate was **inert on GitHub for its entire life**: `gh pr checks --json` does not exist on `gh 2.45.0` (the fleet version), the adapter left `summary` at its `'none'` initialiser and still returned `ok: true`, and `'none'` matched neither the `pending` branch nor the `has_failures` branch — so every GitHub merge fell straight through to step 4. The gate reported fine and did nothing. (cc-workflow#925; upstream reporting defect `mcp-server-sdlc#491`.)

   **`none` is not evidence of passing — it means the query told us nothing.**

   **On `none` (or any unrecognised value), do NOT stop outright — escalate to a source that works.** `pr_status` and `pr_wait_ci` do **not** share a code path, so a blind spot in one is not a blind spot in both. Measured on the same PR, same host, seconds apart (`gh 2.45.0`, **before** the `pr_status` fix in `mcp-server-sdlc#491`) —

   ```
   pr_status(32)   → checks: {total:0, passed:0, failed:0, pending:0, summary:"none"}
   pr_wait_ci(32)  → {total:2, passed:2, failed:0, pending:0}      ← correct
   gh pr checks 32 → lint pass, test pass                          ← agrees with pr_wait_ci
   ```

   So: call `pr_wait_ci(number)` and treat **its** result as authoritative — **as an allowlist, exactly like step 3 itself.** Call it through step 2's CI wait loop, so the call carries `expected_sha` and resumes on `pending`. A verdict arrives in one of two fields: `final_state` (`passed`, `failed`, `timed_out`, `pending`) when CI was polled, or `status` (`no_checks_configured`, `no_checks_yet`) when the probe found no checks to poll. Grade whichever is present. Proceed **only** on `final_state == "passed"`. **Every other value STOPs, including ones not listed here:**
   - `passed` → proceed. *(the only value that proceeds)*
   - `failed` → STOP.
   - `timed_out` → STOP.
   - `pending` → **STOP.** Step 2's loop resumes a `pending` that carries `resume: true`, so one reaches this list only when it carries no `resume` or the 60-minute deadline expired. Either way CI has not finished, and an unfinished CI is not a pass (mcp-server-sdlc#587).
   - `no_checks_configured` → **STOP.** The head-SHA cross-check ran and found no CI runs: this repo genuinely runs no checks for this ref. **A repo with no required checks is not a repo whose checks passed.** Route it to the no-checks-configured branch below.
   - `no_checks_yet` → **STOP.** The STOP line names the facts: `no run for head <head sha from pr_status>; mergeable=<mergeable_state>`, plus `blocker=<blocker>` when there is one. Either runs exist for the head SHA that have not registered as checks, a hard blocker (a conflict, a criss-cross base) keeps CI from starting at all, or the cross-check could not be run (`blocker: evidence_unavailable`). Never `mergeable`. This is not a question for a human — it means **wait, or find out why CI is not reporting**. If a forge routinely takes longer than the 45s default to register, widen `settle_window_sec` rather than learning to wave the status through.
   - `no_checks_required` → **gone as of `mcp-server-sdlc` v4.0.0 (#508).** Kept named here because the history is the reason the rule above exists. It was a *definite, successful* verdict returned at t=0 on an empty rollup (`mcp-server-sdlc#416`) — and an empty rollup is also exactly what a merely-QUEUED check looks like, so a PR whose CI had not started got a verdict whose plain-English name reads as "nothing is wrong." It was **removed rather than aliased** precisely so callers matching the old literal stop matching. If you are reading this in a transcript where it still appears, the server is older than v4.0.0: **STOP**.
   - `{ok: false}` or any error envelope → **STOP** and surface the error; do not silently continue past a gate that failed to run.
   - anything else → **STOP.** Two independent sources unable to confirm a pass is a stop, not a shrug.

   **Why this sub-list is an allowlist too (cc-workflow#925 code review):** the first draft of this fix converted the *outer* gate from a blocklist to an allowlist and then wrote the *inner* escalation as a blocklist — enumerating the statuses that stop, which silently permits every status nobody thought of. `no_checks_required` was already live and unlisted, so the escalation would have merged on it. (That token is now retired — see #508 — and its two successors are listed above explicitly rather than left to the catch-all, which is this rule being honoured rather than merely relied on.) **Fixing a defect at one layer while reproducing it at the next is the failure mode this whole section is about.** If `pr_wait_ci` ever gains a new status, it must land here as an explicit STOP before anything merges on it.

   Stopping outright would have been *correct but useless* at the time this was written: `pr_status` returned `none` for **every** GitHub PR on `gh 2.45.0`, so a bare default-deny converts a silent-permit into a total merge block. Default-deny means **never proceed without an explicit pass**; it does not mean refuse to go and get one.

   **Do not delete the escalation once `pr_status` is truthful.** `mcp-server-sdlc#491` fixes the GitHub instance, not the class — `mcp-server-sdlc#494` records the same silent-permissive shape on GitLab (`no_pipeline_data` returned with `ok: true`), still open. The escalation is written against **any** unrecognised summary precisely so it keeps working for variants nobody has named yet; narrowing it to the one value we happened to measure would rebuild the defect this section exists to close.

   Once `pr_wait_ci` has stopped you, distinguish the causes by hand, because they need different responses:
   - **no checks configured on this repo** (`no_checks_configured`) → a human decides whether merging without CI is acceptable here;
   - **checks exist but have not reported** (`no_checks_yet`) → not a decision, a wait. Re-run the gate, or widen `settle_window_sec`. If `blocker: evidence_unavailable`, the ref cross-check itself could not run — fix that before inferring anything. Report it as `no run for head <sha>; mergeable=<mergeable_state>; blocker=<blocker>`, so the cause is on the line, not left to be rediscovered. Since Wave-Engineering/mcp-server-sdlc#609, `no_checks_configured` means only a mergeable PR whose run query certified no runs; a hard blocker or a persistent `UNKNOWN` mergeability reads `no_checks_yet`;
   - **the query failed** (unsupported flag, auth, network) → fix the query; infer nothing about the checks.

   **If there is no human — HALT, do not improvise.** On a `kahuna/*` sandbox, under `/wavemachine` in `auto` mode, with an armed `godspeed` mandate, or in an approved `/autochain` run, "a human decides" has no addressee. Do **not** resolve it yourself: **do not merge**, emit a structured blocker (`wave-hold` shape on wave paths) naming the PR and the unresolved cause, and let the wave gate escalate it. An autochain run has no wave gate, so it stops the chain and gets loud per `/autochain`'s Stopping section, which also disarms its approval. An autonomous agent that reaches an underspecified branch will improvise, and improvising toward *proceed* is the exact failure this gate exists to prevent — the more so because `/precheck` lists this gate as non-bypassable *precisely because* it is the last control once the human is gone. **Under a standing merge grant or a lead-agent grant there is a human, so ask:** the grant covers a clean precheck, and a repo with no CI is not one.

   Verify with `gh pr checks <number>` (no `--json`) or `gh run list --branch <head>`. **Do not read a bare "no output" as a pass** — that is the same failure one layer down.
4. **Decide where the squash commit comes from.** Ask three questions, in order, and take the first branch that matches:
   - **Is it an integration pair?** That means head `kahuna/*` or `campaign/*`, or base `kahuna/*`; step 1.5's `pr-head` prints the head and the base. If so, the gate exempts it and the server never reads a block. **Draft** the message (step 5), and pass it in step 7 as `pr_merge(number, squash_message)`, as before.
   - **Is the server gated?** It is when `pr_create`'s schema lists `squash_message` (the mcp-server-sdlc release that carries #592). If it isn't, **draft** and pass, as before. An older server never reads a block, so a block in the body changes nothing.
   - **Gated PR/MR on a gated server.** Read the body (`gh pr view <N> --json body -q .body` / `glab api "projects/:id/merge_requests/<N>" --jq .description`).
     - **It has a `## Squash commit` block:** that block IS the squash commit. `/scpmr` composed it and BJ's merge call approved it as written. **Don't draft one;** skip step 5. In step 7, call `pr_merge(number)` with **no** `squash_message`. The server squashes from the block and refuses a `squash_message` that differs from it (`squash_message_mismatch`). If what lands has changed, edit the block in the body, never the call.
     - **It has no block** (opened before the gate shipped): the server refuses the merge (`squash_block_missing`). Draft the message (step 5) and add it to the body, laid out exactly as below. Then call `pr_merge(number)` with no `squash_message`. Never bypass the refusal.
       - a line that is exactly `## Squash commit`
       - optionally, empty lines (not even spaces)
       - an opening fence ```` ```text ```` at column 0
       - the message
       - a closing ```` ``` ```` at column 0

       The body must hold no other `## Squash commit` line. If the message itself contains backticks, the fence must be longer than its longest backtick run, and the closing fence must be exactly the same length as the opening one.
5. **Draft the squash commit message** (only when step 4 says to). Use `pr_diff(number)` plus `git log target..source`. This is agent reasoning, the judgment layer:
   - Title: conventional commits `type(scope): description`
   - Body: what changed and why; key implementation decisions or trade-offs; notable side effects
   - Footer: `Closes #issue-number` for any linked issues (check the PR/MR description)
   - Comprehensive enough that `git log` alone tells the full story without opening the PR
   - **A draft that goes into a block** (step 4's last case) is checked by the server. It must meet every `squash_message` rule in `/scpmr` step 2: a subject of 72 characters or fewer with one of the listed types, `Closes #N`, and the `Co-Authored-By: Name <email>` trailer. Otherwise the merge is refused just as the missing block was.
6. **The approval is how you got here.** Since #1235 BJ's approval is the merge call itself. `/mmr` or `/scpmmr` typed after a precheck STOP, or an affirmative to it, IS the approval, and so is an exception path (`[AUTO-APPROVED: kahuna sandbox]`, `[AUTO-APPROVED: autochain #<epic>]`, a standing merge grant named on the checklist, or `[AUTO-APPROVED: lead-agent grant]` with the grant on the checklist). Show the PR/MR number, title, source→target branches and the squash message (the block, or the one drafted in step 5), and proceed. **Reached any other way** (an agent deciding on its own to merge, with no STOP answered and no exception), ask "May I merge this PR/MR?" and WAIT.
6.5. **Re-grade the AC (#1365).** The precheck status pins the head, not the bodies, so an edit to the issue or the PR/MR body after the pass, with no push, would otherwise merge ungraded. Resolve `precheck-ac-gate.sh` as `/precheck` Step 0 does (as `ACGATE`), and take the issue from `<head-branch>`, the head that step 1.5's `pr-head` printed, never from the local checkout, which may be the base or another branch. An integration head (`kahuna/*`, `campaign/*`) gives its plan id:

   ```bash
   if [[ "<head-branch>" =~ ^(feature|fix|chore|doc)/([0-9]+)- || "<head-branch>" =~ ^(kahuna|campaign)/([0-9]+)- ]]; then
     echo "issue=${BASH_REMATCH[2]}"
   else
     echo "STOP: no issue number in head branch <head-branch>"
     exit 1
   fi
   ```

   No match → **STOP**. Then, just before step 7:

   ```bash
   "$ACGATE" pr <repo_root> <N> <issue>; echo "exit=$?"
   ```

   - **Any non-zero exit → STOP**, and surface its `ac-gate:` lines. A script that cannot be found is a STOP too.
   - **`exit=0` with any `[waived]` or `[override]` line → STOP and route to BJ** (`#precheck` + `vox`), never to a lead, and print every `[waived]` and `[override]` line from the gate's output verbatim on the STOP. The gate checks a waiver's form, not who wrote it. The one way through: BJ himself typed this merge call in this session (`/mmr`, `/scpmmr`, or an affirmative to the STOP), and the checklist or STOP he answered showed those same waiver lines. Any exception path (kahuna, autochain, a standing merge grant, a lead-agent grant) with a waiver line is a STOP for BJ.
   - `exit=0` and no waiver line → step 7.
7. `pr_merge(number)` for a gated PR/MR on a gated server (step 4's last case); otherwise `pr_merge(number, squash_message)`. It's a squash merge, and it returns `merge_method`, `merge_commit_sha` and `url`.
8. **Post-merge**: switch to target branch, pull, delete local source branch if present. Optionally `ci_wait_run(ref: <PR/MR target from step 1>, expected_sha: <merge_commit_sha from step 7>, timeout_sec: 1800)` to confirm the target-branch pipeline lands clean — skip if the user wants to move on immediately.

   **Always pass `expected_sha`, sourced from step 7's `merge_commit_sha`.** Without it, `ci_wait_run` picks whatever run is newest *in the list at that moment* — if GitHub/GitLab hasn't dispatched the new run for the commit that just landed yet (there is always some propagation delay after a merge), it can silently grade a PREVIOUS merge's already-completed run instead, returning `ok:true, final_status:"success"` for a commit nobody asked about. Reproduced live (`mcp-server-sdlc#523`): `waited_sec:0` with the wrong `sha` in the response was the only tell — no error, no warning. `expected_sha` closes this by filtering to the exact commit before grading anything.

   **Use the SAME target reference as step 1's `branch_guard` call, never a literal `"main"`.** On the KAHUNA sandbox path the merge target is `kahuna/<N>-<slug>`, not `main` (see `/scpmmr`'s sandbox note) — pairing a hardcoded `ref: "main"` with `expected_sha` would query `--branch main --commit <sha>` for a commit that lives on neither, turning a merge that landed cleanly into a spurious `ok:false` on exactly the auto-approved path with no human present to notice the mismatch and move on.

   **If `merge_commit_sha` is absent from step 7's response** (the merge did not complete synchronously — see `pr_merge`'s aggregate-envelope semantics), do not call `ci_wait_run` without a sha: resolve the target branch's current HEAD after the pull and use that, or skip the wait entirely.
9. Report success with the merge commit URL.

## Important Rules

- NEVER merge without explicit user approval: BJ's merge call, or a mechanical exception (step 6)
- NEVER merge a head without a `precheck` pass (step 1.5). A push after precheck is rearmed, not waved through.
- ONLY merge if `checks.summary == "all_passed"` — an allowlist, never a blocklist. `has_failures` blocks, and so does `none`, and so does any value not in this list. A blocklist of known-bad states silently permits every state you did not think of, which is exactly how this gate sat inert (cc-workflow#925). **But on `none`/unrecognised, escalate to `pr_wait_ci` first (step 3) — stop only if that also cannot confirm a pass.** Without that clause this rule reads as "block every GitHub merge", because `pr_status` returned `none` for every GitHub PR on `gh 2.45.0`.
- `pr_wait_ci` is an allowlist too — proceed only on `final_state == "passed"` (the no-checks verdicts arrive in `status` instead, and both STOP). Resume on `pending` + `resume` under the 60-minute deadline (step 2), with each resumed call's `max_wait_sec` capped at the time left, and STOP on a `pending` the loop cannot resume. Pass `expected_sha` (the step 1.5 head) on every call; drop it only on the exact older-server error (step 2). **`no_checks_configured` and `no_checks_yet` are both STOPs**, not passes: they mean the probe found nothing to wait for, or found that CI has not reported yet — never that anything succeeded. (`no_checks_required` was their single ambiguous predecessor, retired in `mcp-server-sdlc` v4.0.0.)
- NEVER merge into a protected, non-default, non-`kahuna/*` branch — `branch_guard` STOPs this (target must be the live default or a `kahuna/*` sandbox)
- Post-merge `ci_wait_run` (step 8) MUST pass `expected_sha` (from `merge_commit_sha`) and MUST use the same target ref as step 1's `branch_guard` call, never a hardcoded `"main"` — without `expected_sha` a propagation race can silently grade a stale run (`mcp-server-sdlc#523`); a hardcoded `main` fails outright on the `kahuna/*` sandbox path, with no human present to notice
- Always squash + delete source branch
- On a gated server, a gated PR/MR's `## Squash commit` block IS the squash commit: merge with no `squash_message`, and never draft a competing one (step 4)
- Squash message replaces the entire commit history — make it comprehensive
- Merge conflicts → STOP and report, do NOT attempt to resolve
- Tool failure → report the `{ok: false, code, error}` envelope and suggest resolution
