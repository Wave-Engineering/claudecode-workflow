---
name: review
description: Run a code review on staged changes, branch diff, or a specific file
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-review does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-review
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Code Review

Targeted code review via the `feature-dev:code-reviewer` subagent.

## Tools Used
- `pr_diff` — unified diff for a PR/MR by number (platform-agnostic)
- `pr_files` — changed-file list for a PR/MR by number
- `spec_get` — fetch issue body as structured sections (platform-agnostic)

## Scope
Parse `{{args}}` (default `branch`): `staged` (`git diff --cached`), `branch` (full diff vs base), `<filepath>` (single file), `mr <number>` / `pr <number>` (PR/MR by number).

## Gather Context
1. **Diff + file list by scope:**
   - `staged`: `git diff --cached`
   - `branch`: determine base (`release/*` or `main`), run `git diff <base>...HEAD`
   - `<filepath>`: `git diff HEAD -- <filepath>` plus read the full file
   - `mr <number>` / `pr <number>`: `pr_files({number})` for the path-level overview, then `pr_diff({number})` for the unified diff. Tools handle platform translation — no `gh`/`glab` calls.
2. **Issue** — if branch name contains an issue number (e.g., `fix/76-description`), fetch via `spec_get({issue: N})`. The tool handles platform detection internally.
3. **Intent** — `git log --oneline <base>...HEAD`.

If the diff is empty, stop and tell the user there's nothing to review.

## Dispatch Reviewer

Launch a `feature-dev:code-reviewer` subagent with this prompt:

```
## Code Review Request

### Context
- Branch: {branch name}
- Issue: {issue title and description, if found}
- Intent: {summary from commit messages}
- Files changed: {from pr_files, if mr/pr scope}

### Diff
{the diff content — from pr_diff tool's response or git diff}

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

Issues found → organize by severity with file:line refs. Clean → "Review passed — no high-confidence issues found". **Do NOT auto-fix** — present findings; the user decides.

## Important Rules
- This is READ-ONLY. Never edit files or commit as part of a review.
- Split long diffs across multiple reviewer calls (max ~500 lines per call).
- Be honest about false positives. Do not block `/scp` — this is advisory, not a gate.
