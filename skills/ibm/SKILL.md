---
name: ibm
description: Reminder to follow Issue → Branch → PR/MR workflow for the current work
---

# IBM: Issue → Branch → PR/MR Workflow Reminder

**STOP.** Before writing any code, verify you have followed the proper workflow.

## Step 0a: Detect Platform (CRITICAL)

**Before anything else, determine whether this is a GitHub or GitLab project.**

```bash
git remote -v | head -1
```

- If the URL contains `github` → **GitHub** — use `gh` CLI, PRs, GitHub terminology
- If the URL contains `gitlab` → **GitLab** — use `glab` CLI, MRs, GitLab terminology

Store the result for use in all subsequent steps:
```bash
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if echo "$REMOTE_URL" | grep -qi github; then
  PLATFORM="github"; CLI="gh"
elif echo "$REMOTE_URL" | grep -qi gitlab; then
  PLATFORM="gitlab"; CLI="glab"
else
  echo "Unknown platform — ask the user"; exit 1
fi
```

## Step 0b: Resolve Target Branch (CRITICAL)

**Determine the correct branch to branch from and target PRs/MRs to.**

1. **Delete any existing cache** — `rm -f .claude/target-branch-cache.json` (new issue = fresh lookup)
2. **Query the platform for the project's default branch:**
   - **GitLab:** `glab api projects/:id | jq -r '.default_branch'`
   - **GitHub:** `gh repo view --json defaultBranchRef -q '.defaultBranchRef.name'`
3. **Verify the default branch is not locked down (GitLab only):**
   ```bash
   # Check protected branch rules — if merges are fully blocked, it's locked
   glab api "projects/:id/protected_branches/<default-branch>"
   ```
   On GitHub, branch protection rules rarely block PRs from targeting the default branch — skip this check unless issues arise.
4. **Decision tree:**
   - Default branch is an unlocked `release/*` → **use it** as target
   - Default branch is locked → look for other unlocked `release/*` branches
   - Zero unlocked release branches → **STOP and warn the user**: "No active release target. The project needs an unlocked release branch before work can begin."
   - Multiple unlocked release branches → check repo's CLAUDE.md, or ask the user
   - **GitHub with standard `main` default** → use `main` as target (this is the normal GitHub Flow)
5. **Cache the result** — Write `.claude/target-branch-cache.json`:
   ```json
   { "target_branch": "release/X.Y.Z", "platform": "gitlab", "project_id": "12345", "fetched_at": "2026-02-27T..." }
   ```

**NEVER use the system-injected `gitStatus` "Main branch" value.** It is auto-detected and frequently wrong for projects using release branches.

## Step 1: Issue

Does an issue exist for this work?
- If NO: Create one with `$CLI issue create` (`gh issue create` / `glab issue create`)
- If YES: Note the issue number

## Step 2: Branch

Are you on a feature branch linked to the issue?
- Branch from the **resolved target branch** (from Step 0b), not `main` (unless `main` IS the resolved target)
- Name format: `feature/<issue-number>-description` or `fix/<issue-number>-description`
- Example: `git checkout -b feature/42-add-coppermind-homepage`

## Step 3: PR/MR

After committing, create a PR or MR targeting the **resolved target branch**:
- **GitLab:** `glab mr create --target-branch <resolved-target> --remove-source-branch`
- **GitHub:** `gh pr create --base <resolved-target>`
- Include `Closes #<issue-number>` in the description

## Quick Reference

```bash
# Detect platform (do this FIRST)
REMOTE_URL=$(git remote get-url origin 2>/dev/null)
if echo "$REMOTE_URL" | grep -qi github; then CLI="gh"; else CLI="glab"; fi

# Resolve target branch
TARGET=$(jq -r '.target_branch' .claude/target-branch-cache.json)

# Create issue
$CLI issue create --title "Description" --description "Details"

# Create branch from resolved target
git checkout "$TARGET" && git pull
git checkout -b feature/<issue>-description

# After commit, create PR/MR
# GitLab:
glab mr create --target-branch "$TARGET" --remove-source-branch
# GitHub:
gh pr create --base "$TARGET"
```

## Remember

- **No commits without an issue**
- **No pushes without a branch**
- **No merges without a PR/MR**
- **Always target the resolved release branch (or `main` on GitHub if that is the resolved target)**
- **Always resolve the target branch fresh at the start of new work**
- **Always detect the platform before running CLI commands**
