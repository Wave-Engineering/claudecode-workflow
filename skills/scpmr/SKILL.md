---
name: scpmr
description: Stage, commit, push, and create PR/MR — but do not merge
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-scpmr does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-scpmr
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Stage, Commit, Push, Create PR/MR (No Merge)

Thin wrapper over `/scp` (rewritten to use `mcp__sdlc-server__ibm` + `pr_list` + `pr_create` via MCP tools). Runs the full scp workflow, then stops — does NOT merge. Explicit no-merge is the whole distinction from `/scpmmr`.

## Procedure

Requires `/precheck` first — invoking `/scpmr` after `/precheck` is approval to execute. If `/precheck` has not been run, run it first and wait for approval.

1. Run `/scp` — delegates to the rewritten skill; creates the PR/MR
2. Stop — report the PR/MR URL. User can run `/mmr` later when ready.
3. `vox` announcement (best-effort): identity from `/tmp/claude-agent-<md5>.json`, then name/team/project/issue/PR/"pushed and CI is running"

Do NOT merge — that's the distinction from `/scpmmr`. Convenience shortcut; does NOT skip any safety checks.
