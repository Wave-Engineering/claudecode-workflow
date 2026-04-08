---
name: scpmmr
description: Stage, commit, push, create PR/MR, then merge it — full pipeline in one command
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-scpmmr does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-scpmmr
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Stage, Commit, Push, Create PR/MR, Merge

Combo skill chaining `/scp` → `/mmr`. Both underlying skills are rewritten to use Origin Operations MCP tools: `/scp` uses `pr_list` + `pr_create`; `/mmr` uses `pr_status` + `pr_diff` + `pr_wait_ci` + `pr_merge` + `ci_wait_run` (optional post-merge main-branch pipeline wait, server-side, zero token burn).

## Procedure

Requires `/precheck` first — invoking `/scpmmr` after `/precheck` is approval to execute. If `/precheck` has not been run, run it first and wait for approval.

1. Run `/scp` — creates the PR/MR via `pr_create`
2. Run `/mmr` — targets the just-created PR/MR. Handles merge-queue auto-fallback internally via `pr_merge` (no `--admin` flag needed). Post-merge `ci_wait_run(ref: "main", timeout_sec: 1800)` confirms the main-branch pipeline lands clean.
3. `vox` announcement (best-effort): identity from `/tmp/claude-agent-<md5>.json`, then name/team/project/issue/PR/"merged into main"

## Important

- Convenience shortcut — does NOT skip any safety checks
- `/precheck` must run and be approved first
- CI verification before merge is handled by `pr_wait_ci` inside `/mmr`
- Any step failure → STOP and report, do NOT continue to the next step
