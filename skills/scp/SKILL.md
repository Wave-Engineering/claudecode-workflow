---
name: scp
description: Stage, commit, push to your working branch — free; gated only by the commit and push hooks
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-scp does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-scp
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Stage, Commit, Push

Commit and push your own working branch (`feature/`, `fix/`, `chore/`, `doc/`). **This is free** (#1233, #1235): it needs no `/precheck` and no approval. Back up work, test it in another sandbox, pair on one branch. Two gates apply, and both are hooks, not this skill:

- **commit:** `secret-scan-gate.sh` scans what is staged.
- **push:** `secret-scan-gate.sh` scans every commit being pushed. `pre-push-test-gate.sh` refuses protected and release refs and tags, and lets a plain working-branch push through. A plain delete of one non-protected branch (`git push <remote> --delete <b>` or `:<b>`) passes both gates with no test run and no scan.

The gate into a release branch is the **PR/MR**. That's `/precheck` (`/scpmr` runs it), and BJ's approval is at the **merge** (`/mmr`).

## Tools Used

- `mcp__sdlc-server__ibm` — branch/issue workflow gate (no protected branch; branch linked to an open issue). Handles platform detection internally.

## Execution

### Step 1: Branch + Issue Gate

Call `ibm()`. It verifies you are not on a protected branch, that a feature branch exists, and that the branch is linked to an open issue. Stop on failure and surface the remediation it returns. (Tools handle platform detection internally — no bash probing required.)

### Step 2: Draft the Commit Message

Generate a conventional commit message — this is agent reasoning, not a tool call.
{{#if message}}
- Use the provided message: "{{message}}"
{{else}}
- Auto-generate following conventional commits format: `type(scope): description`
- Summarize the "why" of the change, not just the "what"
- Include `Closes #XXX` if an issue is being resolved
- Append the Co-Authored-By line
{{/if}}

Write the message to a file with the `Write` tool and commit with `git commit -F <file>`. A message is full of backticks, and an inline `-m "…"` runs them.

### Step 3: Commit and Push

1. Stage specific files (never `git add -A` or `git add .`).
2. `git commit -F <file>`.
3. `git push <remote> <branch>` as a **plain, separate command** (`-u origin <branch>` the first time). That shape is what the push gate exempts; a compound or unusual push still needs a test run first.

**If the secret-scan gate blocks the commit or push** (`secret-scan-gate.sh`, #1234): it names each finding's file, line, rule and, for a push, the commit. It never shows the value. A real secret: remove it, and if it is already in a commit, rewrite that commit, because a later commit that deletes it still pushes it. A false positive: add the finding's allowlist key (`<file>:<rule>:<line>`, printed in the block message) to `.gitleaksignore` at the repository root, commit that, and retry. A rule-level allowlist goes in `.gitleaks.toml`. There is no bypass flag, and a missing gitleaks blocks too: install it with the kit's `./install`.

### Step 4: Report

Report the commit SHA and the push. If a PR/MR already exists for the branch and HEAD moved past its `precheck` status, say so: the next step is `/precheck rearm`, and `/mmr` runs it by itself. **No PR/MR is opened here**; `/scpmr` does that.

## Important Rules

- **NEVER commit to main or release/* branches** — always use feature branches. `ibm()` enforces this.
- **NEVER push without an issue** — all work must be tracked. `ibm()` enforces this.
- Never use `git add -A` or `git add .` — always stage specific files.
- Always include the Co-Authored-By line.
- Respect any project-specific commit rules in CLAUDE.md.
- If push fails due to protected branch, create a feature branch and retry.
- Pushing is not publishing a decision. A pushed working branch is reviewed at the PR/MR gate, before anything lands.
