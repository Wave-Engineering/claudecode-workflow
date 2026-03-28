---
name: precheck
description: Pre-commit gate — verify branch/issue, run code-reviewer, present checklist, then stop and wait for approval
---

# Pre-Commit Gate

This skill is the **mandatory verification step** before any commit. It checks compliance, runs code review, presents the checklist, and **stops**. It does NOT commit, push, or create a PR/MR.

## When to Run

Run `/precheck` when you have finished your implementation work and are ready to commit. Do NOT wait for the user to invoke it — proactively run it when the work is done.

## Step 1: Branch & Issue Check

Verify the issue-branch workflow is in order:

1. **Not on a protected branch** — Run `git branch --show-current`. If on `main` or `release/*`, STOP and tell the user.
2. **Branch linked to an issue** — Extract the issue number from the branch name (e.g., `feature/83-precheck-skill` → `#83`). If no issue number is present, ask the user.
3. **Issue exists and is open** — Verify with `gh issue view <number>` / `glab issue view <number>`. If the issue is closed or missing, STOP and tell the user.

If any check fails, report the problem and stop. Do NOT proceed to code review.

## Step 2: Run Validation

Run the repo's validation/test tooling:
- Look for `./scripts/ci/validate.sh`, `Makefile` targets, `pytest`, `npm test`, etc.
- If validation fails, stop and fix the issues before proceeding.

## Step 3: Code Review

1. **Launch the `feature-dev:code-reviewer` subagent** (via the Agent tool with `subagent_type: "feature-dev:code-reviewer"`) over all changed files (staged + unstaged). Provide the subagent with the list of changed files and the issue context.
2. **WAIT for the agent to complete** — do NOT proceed until results are returned
3. **Fix any findings rated high risk or above** — make the fixes, re-run validation if needed
4. **Record all findings** for the checklist (both fixed and deferred)

## Step 4: Present the Checklist

Present the full pre-commit checklist. **A checkmark means you have VERIFIED this item by examining the codebase** — not assumed, not guessed.

### Commit Context

| Field | Value |
|-------|-------|
| **Project** | (project name from Dev-Team identity) |
| **Issue** | #NNN — issue title |
| **Branch** | `feature/NNN-description` → `main` |

### Checklist

- [ ] **Implementation Complete** - I have READ the associated issue(s) and VERIFIED against the codebase that EVERY acceptance criterion is implemented
- [ ] **TODOs Addressed** - I have SEARCHED the codebase for TODO/FIXME comments related to this work and either addressed them or confirmed none exist
- [ ] **Documentation Updated** - I have REVIEWED docs and updated any that are impacted by this commit
- [ ] **Pre-commit Passes** - I have RUN validation and it passes (not "it should pass" - I actually ran it)
- [ ] **New Tests Cover New Work** - I have WRITTEN tests that fully cover all new functionality introduced in this commit
- [ ] **All Tests Pass** - I have RUN the **entire** test suite and confirmed ALL tests pass
- [ ] **Scripts Actually Tested** - For any new scripts, I have EXECUTED them and verified they work. Linting is NOT testing.
- [ ] **Code Review Passed** - I have RUN the `code-reviewer` agent over all changed files. Issues rated **high risk or above** have been fixed.

### CRITICAL: Linting Is Not Testing

**Passing lint/typecheck does NOT mean code works.** Before claiming something is "tested", you MUST actually run it.

### Change Summary

Summarize changes by category:

**[codebase]** - Production code changes
**[documentation]** - Doc changes
**[test-modules]** - Test code changes
**[linters/config]** - Config changes

### Review Findings

Results from the `code-reviewer` agent:

**[fixed]** - Findings rated high risk or above that were resolved before this checklist
**[deferred]** - Findings rated medium or below, presented here for your assessment

If no findings in either category, state "(none)".

## Step 5: Voice Announcement

After presenting the checklist, announce completion via `vox` (best-effort — never block on audio):

```bash
vox "Hey BJ, precheck is done for issue <NUMBER>. <SUMMARY>. Ready for your call." 2>/dev/null || true
```

The announcement should be 1-2 sentences: mention the issue number, a brief summary of what was built, and the checklist status. Write for the ear — conversational, not robotic.

## Step 6: STOP and Wait

**After presenting the checklist and announcing, STOP.** Do not commit, push, or create a PR/MR.

The user will respond with one of:

| Response | Action |
|----------|--------|
| `/scp` | Approval granted — execute stage, commit, push |
| `/scpmr` | Approval granted — execute stage, commit, push, create PR/MR |
| `/scpmmr` | Approval granted — execute stage, commit, push, create PR/MR, merge |
| Affirmative ("yes", "approved", "go ahead") | Approval granted — execute stage, commit, push |
| Negative or rework instructions | Return to work — do NOT commit |

## Important Rules

- **Do NOT present a diff** — the user can get it if needed; it wastes tokens and scrolls off the display
- **Do NOT commit** — this skill is verification only
- **Do NOT skip the code-reviewer** — it must complete before the checklist is presented
- **Do NOT check items you haven't verified** — honesty over speed
- **Do NOT abbreviate the checklist** — present it in full every time
