---
name: review
description: Run a code review on staged changes, branch diff, or a specific file
---

# Code Review

Run a targeted code review using the `feature-dev:code-reviewer` subagent.

## Determine Scope

Parse the argument to determine what to review:

{{#if args}}
- `staged` → review only staged changes (`git diff --cached`)
- `branch` → review the full branch diff against the base branch
- `<filepath>` → review a specific file
- `mr <number>` or `pr <number>` → review a merge request / pull request by number
{{else}}
- No argument → default to `branch` (full branch diff)
{{/if}}

**Argument received:** `{{args}}`

## Gather Context

Before dispatching the reviewer, gather supporting context:

1. **Detect platform** — run `git remote -v | head -1`:
   - URL contains `github` → use `gh` CLI
   - URL contains `gitlab` → use `glab` CLI

2. **The diff** — based on scope above:
   - `staged`: run `git diff --cached`
   - `branch`: determine the base branch (look for `release/*` or `main`), run `git diff <base>...HEAD`
   - `<filepath>`: run `git diff HEAD -- <filepath>`, also read the full file
   - `mr <number>` or `pr <number>`:
     - **GitLab:** `glab mr diff <number>`
     - **GitHub:** `gh pr diff <number>`

3. **The issue** — if the current branch name contains an issue number (e.g., `fix/76-description`), fetch the issue description:
   - **GitLab:** `glab issue view <number>`
   - **GitHub:** `gh issue view <number>`

4. **Recent commit messages** — run `git log --oneline <base>...HEAD` to understand the intent

If the diff is empty, tell the user there's nothing to review and stop.

## Dispatch Reviewer

Launch a `feature-dev:code-reviewer` subagent with this prompt structure:

```
## Code Review Request

### Context
- Branch: {branch name}
- Issue: {issue title and description, if found}
- Intent: {summary from commit messages}

### Diff
{the diff content}

### Review Instructions
Review this code for:
1. Bugs and logic errors
2. Security vulnerabilities (OWASP top 10, injection, secrets exposure)
3. Edge cases and error handling gaps
4. Adherence to project conventions (check CLAUDE.md)
5. Anything that could fail in CI/CD or production

For each finding, rate confidence (high/medium/low). Only report HIGH confidence issues — skip nitpicks and style preferences. The project has linters for that.

If you find nothing significant, say so. A clean review is a valid outcome.
```

## Present Results

After the reviewer returns:

1. **If issues found** — present them organized by severity, with file paths and line numbers
2. **If clean** — say "Review passed — no high-confidence issues found"
3. **Do NOT auto-fix** — present findings and let the user decide what to address

## Important Rules

- This is READ-ONLY. Never edit files or commit as part of a review.
- Keep the reviewer focused. Long diffs should be split across multiple reviewer calls if needed (max ~500 lines per call for quality).
- Be honest about false positives. If the reviewer flags something questionable, say so.
- Do not block `/scp`. This is advisory, not a gate.
