---
name: scpmr
description: Stage, commit, push, and create PR/MR — but do not merge
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
     Do this BEFORE executing any skill logic below. -->

# Stage, Commit, Push, Create PR/MR (No Merge)

This is a combo skill that runs `/scp` with an explicit instruction to create the PR/MR but stop before merging.

## Pre-Commit Gate

If `/precheck` has not been run in this conversation, run it first and wait for approval before proceeding. Invoking `/scpmr` after `/precheck` is approval to execute.

## Workflow

1. **Run `/scp`** — Execute the full scp workflow (stage, commit, push, create PR/MR)
   - The scp skill will create a PR/MR if one doesn't exist

2. **Stop** — Report the PR/MR URL and do NOT merge
   - The user wants to review the PR/MR before merging
   - They can later run `/mmr` to merge when ready

## Voice Announcement

After the PR/MR is created and pushed, resolve agent identity and announce via `vox` (best-effort):

```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
DEV_NAME=$(jq -r '.dev_name // "agent"' "/tmp/claude-agent-${dir_hash}.json" 2>/dev/null)
DEV_TEAM=$(jq -r '.dev_team // "unknown"' "/tmp/claude-agent-${dir_hash}.json" 2>/dev/null)
PROJECT=$(basename "$project_root")

vox "Hey BJ, this is $DEV_NAME from $DEV_TEAM on $PROJECT. PR <NUMBER> is up for issue <NUMBER>. Pushed and CI is running." 2>/dev/null || true
```

Keep it brief — identify yourself, issue number, PR number, status. Write for the ear.

## Important

- This is a **convenience shortcut** — it does NOT skip any safety checks
- `/precheck` must have been run and the checklist presented before execution
- Do NOT merge — that's the whole point of this skill vs `/scpmmr`
