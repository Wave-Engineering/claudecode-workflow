---
name: scp
description: Approve and execute pending commit, or run full stage/commit/push workflow
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-scp does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-scp
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Stage, Commit, Push

Git commit workflow with context awareness. Reasoning layer (commit message drafting, validation orchestration) stays as agent prose; mechanical layer (branch/issue checks, PR existence, PR creation) routes through MCP tools.

## Tools Used

- `mcp__sdlc-server__ibm` — branch/issue workflow gate (no protected branch; branch linked to an open issue). Handles platform detection internally.
- `mcp__sdlc-server__pr_list` — check whether a PR already exists for the current branch.
- `mcp__sdlc-server__pr_create` — create the PR with the drafted title/body.

## Pre-Commit Gate

**Before executing, verify that `/precheck` has been run in this conversation.**

- If `/precheck` was run and the user approved (via `/scp`, `/scpmr`, `/scpmmr`, or an affirmative like "yes", "approved", "go ahead") → proceed to execution.
- If `/precheck` has NOT been run → run it first and wait for approval before proceeding.

**Sandbox auto-approval path.** When `/precheck` detects a KAHUNA sandbox context (base ref matches `^kahuna/[0-9]+-`), it emits the sentinel `[AUTO-APPROVED: kahuna sandbox]` and invokes `/scpmmr` directly — `/scp` is reached transitively through that auto-invocation, not by a human typing `/scp`. The approval here is structural (the wave Orchestrator dispatched a Flight Agent into a sandbox) rather than per-commit. See `skills/precheck/SKILL.md` and Dev Spec §5.2.1 for the rule. Non-sandbox behaviour is unchanged.

## Execution

### Step 1: Branch + Issue Gate

Call `ibm()`. It verifies you are not on a protected branch, that a feature branch exists, and that the branch is linked to an open issue. Stop on failure and surface the remediation it returns. (Tools handle platform detection internally — no bash probing required.)

### Step 2: Validate

Run the repo's validation script (`./scripts/ci/validate.sh`, `npm test`, `pytest`, etc.).
- If arriving from an approved `/precheck` run and no files have changed since, skip this step.
- If validation fails, stop and report errors.

### Step 3: Draft the Commit Message

Generate a conventional commit message — this is agent reasoning, not a tool call.
{{#if message}}
- Use the provided message: "{{message}}"
{{else}}
- Auto-generate following conventional commits format: `type(scope): description`
- Summarize the "why" of the change, not just the "what"
- Include `Closes #XXX` if an issue is being resolved
- Append the Co-Authored-By line
{{/if}}

Draft a matching PR title (≤72 chars, same `type(scope): description` convention) and body (`## Summary`, `## Changes`, `## Linked Issues` with `Closes #N`, `## Test Plan`).

### Step 4: Commit, Push, PR

Git plumbing stays as git:
1. Stage specific files (never `git add -A` or `git add .`).
2. `git commit` with the drafted message.
3. `git push` to the feature branch (with `-u origin <branch>` if it has no upstream).

Then route PR handling through MCP tools:
4. `pr_list({head: "<current-branch>"})` — check whether a PR already exists for this branch.
5. If the list is empty, call `pr_create({title, body, base, head, draft?})` with the drafted title/body. For `base`, use the repo's default branch (resolve once per session via `gh repo view --json defaultBranchRef -q '.defaultBranchRef.name'` and cache locally); `head` is the current branch.
6. Report the PR URL (either the pre-existing one from `pr_list` or the newly-created one from `pr_create`).

## Important Rules

- **NEVER commit to main or release/* branches** — always use feature branches. `ibm()` enforces this.
- **NEVER push without an issue** — all work must be tracked. `ibm()` enforces this.
- Never use `git add -A` or `git add .` — always stage specific files.
- Always include the Co-Authored-By line.
- Respect any project-specific commit rules in CLAUDE.md.
- If push fails due to protected branch, create a feature branch and retry.
- Always create a PR if one doesn't exist for the feature branch.
