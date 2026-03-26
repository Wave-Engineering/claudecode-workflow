---
name: scpmr
description: Stage, commit, push, and create PR/MR — but do not merge
---

# Stage, Commit, Push, Create PR/MR (No Merge)

This is a combo skill that runs `/scp` with an explicit instruction to create the PR/MR but stop before merging.

## Workflow

1. **Run `/scp`** — Execute the full scp workflow (stage, commit, push, create PR/MR)
   - If a commit approval is pending, treat this invocation as approval
   - If no commit is pending, run the full cold-start workflow
   - The scp skill will create a PR/MR if one doesn't exist

2. **Stop** — Report the PR/MR URL and do NOT merge
   - The user wants to review the PR/MR before merging
   - They can later run `/mmr` to merge when ready

## Important

- This is a **convenience shortcut** — it does NOT skip any safety checks
- The pre-commit checklist from CLAUDE.md is still mandatory
- User approval is still required for the commit (invoking `/scpmr` IS the approval)
- Do NOT merge — that's the whole point of this skill vs `/scpmmr`
