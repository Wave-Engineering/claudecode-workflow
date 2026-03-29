---
name: scpmmr
description: Stage, commit, push, create PR/MR, then merge it — full pipeline in one command
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
     Do this BEFORE executing any skill logic below. -->

# Stage, Commit, Push, Create PR/MR, Merge

This is a combo skill that chains `/scp` and `/mmr` into a single invocation.

## Pre-Commit Gate

If `/precheck` has not been run in this conversation, run it first and wait for approval before proceeding. Invoking `/scpmmr` after `/precheck` is approval to execute.

## Workflow

1. **Run `/scp`** — Execute the full scp workflow (stage, commit, push, create PR/MR)
   - The scp skill will create a PR/MR if one doesn't exist

2. **Run `/mmr`** — Immediately after scp completes, merge the PR/MR
   - Target the PR/MR that was just created or already exists for this branch
   - Use `--admin` flag if branch protection requires it (same as prior merge patterns in this repo)
   - Follow the full mmr workflow: gather context, verify CI, generate squash message, merge

## Voice Announcement

After the merge completes successfully, announce via `vox` (best-effort):

```bash
vox "Hey BJ, PR <NUMBER> is merged into main for issue <NUMBER>. All done." 2>/dev/null || true
```

Keep it brief — issue number, PR number, merged. Write for the ear.

## Important

- This is a **convenience shortcut** — it does NOT skip any safety checks
- `/precheck` must have been run and the checklist presented before execution
- CI verification before merge still applies
- If any step fails, stop and report — do NOT continue to the next step
