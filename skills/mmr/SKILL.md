---
name: mmr
description: Merge a PR/MR with squash and source branch deletion
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
     Do this BEFORE executing any skill logic below. -->

# Merge PR/MR

Merge a pull request (GitHub) or merge request (GitLab) with squash commits, a detailed commit message, and source branch deletion.

## Detect Platform

Before any other step, detect the platform:

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

Use the detected platform's CLI and terminology (PR vs MR) throughout.

## Determine Target PR/MR

{{#if args}}
The user specified PR/MR number: {{args}} (strip any `!` or `#` prefix if present)
{{else}}
No PR/MR number provided. Detect the PR/MR for the current branch:
- **GitLab:** `glab mr list --source-branch=$(git branch --show-current)`
- **GitHub:** `gh pr list --head $(git branch --show-current)`
If none is found, report the error and stop.
{{/if}}

## Workflow

1. **Gather PR/MR Context** — Run these in parallel:
   - Get details: title, description, source/target branches
     - **GitLab:** `glab mr view <number>`
     - **GitHub:** `gh pr view <number>`
   - Get the full diff
     - **GitLab:** `glab mr diff <number>`
     - **GitHub:** `gh pr diff <number>`
   - Get all commits that will be squashed (`git log target..source`)

2. **Verify CI Status** — Check that the pipeline/checks have passed
   - **GitLab:** Check MR pipeline status via `glab mr view`
   - **GitHub:** `gh pr checks <number>`
   - If CI is still running, inform the user and ask whether to wait or proceed
   - If CI failed, stop and report — do NOT merge with failing checks

3. **Generate Squash Commit Message** — Compose a thorough, detailed message:
   - **Title line**: Use the PR/MR title (or improve it if vague), following conventional commits format: `type(scope): description`
   - **Body**: Write a detailed description covering:
     - What was changed and why
     - Key implementation decisions or trade-offs
     - Any notable side effects or behavioral changes
   - **Footer**: Include `Closes #issue-number` for any linked issues (check PR/MR description for references)
   - The message should be thorough enough that someone reading `git log` understands the full scope without looking at the PR/MR

4. **Present for Approval** — Show the user:
   - PR/MR number, title, source-branch to target-branch
   - The proposed squash commit message
   - Ask: "May I merge this PR/MR?" and WAIT for explicit approval
   - If user responds with `/mmr` again, treat as approval

5. **Merge** — Execute the merge:
   - **GitLab:** `glab mr merge <number> --squash --remove-source-branch --yes --squash-message "<message>"` — pass the squash message via a HEREDOC for correct formatting
   - **GitHub:** `gh pr merge <number> --squash --delete-branch --body "<message>"` — pass the body via a HEREDOC for correct formatting

6. **Post-Merge Cleanup** — After successful merge:
   - Switch to the target branch and pull
   - Delete the local source branch if it still exists
   - Report success with the merge commit URL

## Important Rules

- NEVER merge without explicit user approval
- NEVER merge if the pipeline/checks are failing
- Always use squash and delete/remove the source branch
- The squash commit message should be comprehensive — this replaces the entire commit history
- If the PR/MR has merge conflicts, stop and report — do NOT attempt to resolve them
- If the merge command fails, report the error and suggest resolution
