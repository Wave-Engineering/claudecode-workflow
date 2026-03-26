---
name: scpmmr
description: Stage, commit, push, create PR/MR, then merge it — full pipeline in one command
---

# Stage, Commit, Push, Create PR/MR, Merge

This is a combo skill that chains `/scp` and `/mmr` into a single invocation.

## Workflow

1. **Run `/scp`** — Execute the full scp workflow (stage, commit, push, create PR/MR)
   - If a commit approval is pending, treat this invocation as approval
   - If no commit is pending, run the full cold-start workflow
   - The scp skill will create a PR/MR if one doesn't exist

2. **Run `/mmr`** — Immediately after scp completes, merge the PR/MR
   - Target the PR/MR that was just created or already exists for this branch
   - Use `--admin` flag if branch protection requires it (same as prior merge patterns in this repo)
   - Follow the full mmr workflow: gather context, verify CI, generate squash message, merge

## Important

- This is a **convenience shortcut** — it does NOT skip any safety checks
- The pre-commit checklist from CLAUDE.md is still mandatory
- User approval is still required for the commit (invoking `/scpmmr` IS the approval)
- CI verification before merge still applies
- If any step fails, stop and report — do NOT continue to the next step
