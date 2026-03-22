---
name: scp
description: Approve and execute pending commit, or run full stage/commit/push workflow
---

# Stage, Commit, Push

This skill handles the git commit workflow with context awareness.

## Check Context First

Determine if a commit approval is already pending in this conversation:
- Was a pre-commit checklist just presented?
- Was approval requested with a proposed commit message?

## If Commit Approval is Pending

The user invoking `/scp` is granting approval. Proceed immediately:

1. Stage the files that were discussed (use specific filenames, not `git add -A`)
2. Commit with the proposed message, appending:
   ```
   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
   ```
3. Push to the remote branch
4. Report success and include any pipeline/CI or PR/MR URL from the push output

## If No Commit is Pending (Cold Start)

Run the full workflow:

### Step 0: Branch Safety Check (CRITICAL)

**Before doing ANYTHING else:**

1. **Check current branch** - Run `git branch --show-current`
2. **If on `main` or `release/*`** - STOP. You are on a protected branch.
   - Ask the user: "You're on a protected branch. What issue number is this work for?"
   - Create a feature branch: `git checkout -b <type>/<issue>-description`
   - Only proceed after switching to a feature branch
3. **Detect platform** — run `git remote -v | head -1`:
   - URL contains `github` → use `gh` CLI, PR terminology
   - URL contains `gitlab` → use `glab` CLI, MR terminology
4. **If on a feature branch** - Verify a PR/MR exists for this branch
   - **GitLab:** `glab mr list --source-branch=$(git branch --show-current)`
   - **GitHub:** `gh pr list --head $(git branch --show-current)`
   - If none exists, one will be created after push

**Do NOT skip this step. Do NOT proceed on protected branches.**

### Step 1: Ensure Issue Exists

1. **Check for issue reference** - Look at the branch name for an issue number (e.g., `fix/76-description`)
2. **If no issue number in branch name** - Ask the user: "What issue is this work for?"
3. **If no issue exists** - Create one (`gh issue create` / `glab issue create`) or ask user to create one
4. **An issue MUST exist before proceeding**

### Step 2: Validate

Run the repo's validation script (`./scripts/ci/validate.sh`, `npm test`, `pytest`, etc.)
- If validation fails, stop and report errors

### Step 3: Show Changes

Run `git status` and `git diff` to display pending changes

### Step 4: Checklist

Present the pre-commit checklist if the project's CLAUDE.md defines one
- Mark items as verified based on work done this session
- Be honest - only check items you actually verified

### Step 5: Propose Message

Generate a conventional commit message based on the changes
{{#if message}}
- Use the provided message: "{{message}}"
{{else}}
- Auto-generate following conventional commits format: `type(scope): description`
- Include `Closes #XXX` if an issue is being resolved
{{/if}}

### Step 6: Request Approval

Ask "May I commit and push?" and WAIT for explicit approval
- Do NOT proceed without approval
- If user responds with `/scp` again, treat as approval

### Step 7: Commit, Push, MR

After approval:
1. Stage specific files (never `git add -A`)
2. Commit with the approved message + Co-Authored-By line
3. Push to the feature branch (with `-u` if new)
4. **If no PR/MR exists** — Resolve the target branch (see below), then create one
5. Report the PR/MR URL

### Resolving the Target Branch for PR/MR Creation

**NEVER use the system-injected `gitStatus` "Main branch" value as the PR/MR target.** It is auto-detected and frequently wrong.

1. **Check cache first** — Read `.claude/target-branch-cache.json` in the repo root
   - If it exists and has a `target_branch`, use it
2. **If no cache** — Query the platform:
   - **GitLab:**
     ```bash
     # Get the project's default branch
     glab api projects/:id | jq -r '.default_branch'
     # Check if it's locked down (merge blocked)
     glab api "projects/:id/protected_branches/<default-branch>"
     ```
   - **GitHub:**
     ```bash
     gh repo view --json defaultBranchRef -q '.defaultBranchRef.name'
     ```
3. **Decision tree:**
   - Default branch is an unlocked `release/*` → **use it**
   - Default branch is locked → find other unlocked `release/*` branches
   - Zero unlocked release branches → **STOP**: "No active release target found. Did you forget to set one up?"
   - Multiple unlocked release branches → check repo's CLAUDE.md, or ask the user
   - **GitHub with standard `main` default** → use `main` as target
4. **Write cache** — Save to `.claude/target-branch-cache.json`:
   ```json
   { "target_branch": "release/X.Y.Z", "platform": "gitlab", "project_id": "12345", "fetched_at": "2026-02-27T..." }
   ```
5. **Create PR/MR:**
   - **GitLab:** `glab mr create --target-branch <resolved-target> --remove-source-branch`
   - **GitHub:** `gh pr create --base <resolved-target>`

## Important Rules

- **NEVER commit to main or release/* branches** - Always use feature branches
- **NEVER push without an issue** - All work must be tracked
- Never use `git add -A` or `git add .` - always stage specific files
- Always include the Co-Authored-By line
- Respect any project-specific commit rules in CLAUDE.md
- If push fails due to protected branch, create feature branch and retry
- Always create a PR/MR if one doesn't exist for the feature branch
- **NEVER trust the gitStatus "Main branch" for PR/MR targets** — always resolve from the platform API or cache
