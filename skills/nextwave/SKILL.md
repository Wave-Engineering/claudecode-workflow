---
name: nextwave
description: Execute the next pending wave of parallel spec-driven sub-agents on isolated worktrees
---

# NextWave: Execute One Wave of Parallel Agents

Execute the next pending wave from a plan created by `/prepwaves`. Launches parallel sub-agents on isolated worktrees, collects results, and presents pre-commit checklists for user approval. Merges via PR/MR — never directly to main.

## Prerequisites

- `/prepwaves` must have been run — wave plan must exist in the task list
- Previous waves (if any) must be merged to the main branch

## Platform Detection

Before starting, detect the platform from the git remote:
- **GitHub** (`github.com` in remote URL) — use `gh` CLI, create **pull requests** (PRs)
- **GitLab** (`gitlab` in remote URL) — use `glab` CLI, create **merge requests** (MRs)

Use the correct CLI and terminology throughout. The rest of this document uses "PR/MR" to mean whichever applies.

## Step 1: Pre-Flight Checks

Before launching any agents:

1. **Identify the next pending wave** — Read the task list, find the first wave task that is not completed
2. **Verify the main branch is clean** — `git status` shows no uncommitted changes, `git log` confirms previous wave's commits are present
3. **Verify previous wave is merged** — If this is not Wave 1, confirm that all issues from the prior wave have their code on the main branch
4. **Verify issue specs** — For each issue in this wave, read it via the platform CLI and confirm it has: Changes, Tests, Acceptance Criteria
5. **Verify branches exist** — Each issue's branch must exist (created during `/prepwaves`)

If any check fails, **stop and report** — do not launch agents on a bad foundation.

## Step 2: Launch Parallel Agents

For each issue in the current wave, launch a sub-agent with `isolation: "worktree"` and `subagent_type: "general-purpose"`.

**All agents in a wave MUST be launched in a single message** (parallel tool calls) to maximize concurrency.

### Agent Prompt Template

Each agent receives this prompt (filled in per-issue):

```
You are implementing a specific issue. You are a SPEC EXECUTOR — implement exactly what the issue describes. Do NOT make design decisions or change scope.

## Your Issue
Read issue #N from this repo using the platform CLI (gh issue view N, or glab issue view N).

## Rules
1. IMPLEMENT EXACTLY what the issue specifies — changes, tests, acceptance criteria
2. Do NOT make design changes. If something in the issue doesn't work as described or needs a design change, STOP and report back with what's wrong and why. Do NOT improvise.
3. Do NOT commit. Leave all changes uncommitted in the worktree.
4. Work on branch: feature/N-description

## Implementation Steps
1. Read the issue thoroughly — understand every acceptance criterion
2. Read the existing codebase files you'll be modifying
3. Implement the changes described in the issue
4. Write ALL tests listed in the issue
5. Run the test suite and fix any failures
6. Run the code-reviewer agent over your changes — fix any high+ risk findings

## When You're Done
Report back with:
- **What was implemented** — brief summary of changes made
- **Files modified/created** — list with brief descriptions
- **Test results** — which tests pass, any failures
- **Code review findings** — what was found, what was fixed, what remains (with risk levels)
- **Acceptance criteria status** — check each criterion, mark as done or explain what's missing
- **Concerns or blockers** — anything that didn't go as the issue described

Do NOT report success if tests fail or acceptance criteria are unmet. Be honest about the state.
```

## Step 3: Collect Results

As agents complete, collect their reports. For each agent:

1. **Read the agent's report** — what was built, test results, review findings, concerns
2. **Check for escalations** — did any agent flag a design issue or blocker?
3. **Note the worktree path** — where the agent's changes live

If any agent escalated a design concern:
- **Stop the wave** — present the concern to the user before proceeding
- The user may need to update the issue spec and re-run that agent

## Step 4: Present Pre-Commit Checklists

For EACH agent's work, present the full pre-commit checklist as defined in CLAUDE.md:

### Commit Context

| Field | Value |
|-------|-------|
| **Project** | (from Dev-Team identity) |
| **Issue** | #N — issue title |
| **Branch** | `feature/N-description` → `main` |

### Checklist
(The full CLAUDE.md checklist — Implementation Complete, TODOs, Docs, Pre-commit, Tests, Scripts, Code Review)

### Change Summary
(Categorized by codebase/docs/tests/config)

### Review Findings
**[fixed]** — high+ risk items resolved by the agent
**[deferred]** — medium and below for user assessment

**Wait for explicit user approval on EACH agent's work before committing.**

## Step 5: Commit, Push, and Create PR/MR

For each approved agent:

1. **Commit** on the feature branch in the worktree with proper commit message format:
   ```
   type(scope): description

   Closes #N   (GitHub)
   Closes #N   (GitLab — or use "Resolves #N" if project prefers)
   ```

2. **Push the feature branch** to the remote:
   ```bash
   git push -u origin feature/N-description
   ```

3. **Create a PR/MR** targeting the main branch:

   **GitHub:**
   ```bash
   gh pr create --title "feat(scope): description" --body "$(cat <<'EOF'
   ## Summary
   <brief description of changes>

   ## Changes
   <bullet list of what was modified>

   ## Test Results
   <paste test output summary>

   Closes #N

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )"
   ```

   **GitLab:**
   ```bash
   glab mr create --title "feat(scope): description" --description "$(cat <<'EOF'
   ## Summary
   <brief description of changes>

   ## Changes
   <bullet list of what was modified>

   ## Test Results
   <paste test output summary>

   Closes #N

   🤖 Generated with [Claude Code](https://claude.com/claude-code)
   EOF
   )" --source-branch feature/N-description --target-branch main
   ```

4. **Wait for CI** — If CI is configured, check that tests pass before merging:
   - GitHub: `gh pr checks <number>` (poll until tests pass; builds may be non-blocking)
   - GitLab: `glab mr view <number>` to check pipeline status

5. **Merge the PR/MR** — use the appropriate strategy based on what the platform supports:

   ### Merge strategy selection

   **Option A: Merge queue / merge train (preferred when available)**

   Merge queues (GitHub) and merge trains (GitLab) test each PR/MR on top of
   previously queued changes, preventing "passes alone, breaks together" skew.
   This is the safest option when a wave has multiple PRs/MRs merging in quick
   succession.

   - GitHub (merge queue enabled on repo):
     ```bash
     gh pr merge <number> --squash --delete-branch --merge-queue
     ```
   - GitLab (merge train enabled on project):
     ```bash
     glab mr merge <number> --squash --remove-source-branch --when-pipeline-succeeds
     ```

   To detect availability:
   - GitHub: check repo branch protection rules for "Require merge queue"
   - GitLab: check project settings → Merge requests → "Merge trains"

   **Option B: Sequential merge (fallback when queues/trains not available)**

   When merge queues/trains are not configured, merge PRs/MRs one at a time
   to avoid merge skew:

   1. Merge the first PR/MR:
      - GitHub: `gh pr merge <number> --squash --delete-branch`
      - GitLab: `glab mr merge <number> --squash --remove-source-branch`
   2. Pull to local main: `git checkout main && git pull`
   3. Verify remaining PR/MR branches are still clean against updated main
      (rebase if needed)
   4. Repeat for the next PR/MR

   This is slower but safe — each merge is tested against the actual state of main.

6. **Pull merged changes** to local main after all PR/MRs are merged:
   ```bash
   git checkout main && git pull
   ```

7. **Clean up worktrees** — remove all temporary worktrees for this wave

If the user rejects an agent's work:
- Note what needs to change
- The worktree can be re-used or discarded
- The issue stays open for the next `/nextwave` invocation

## Step 6: Wave Complete

After all PR/MRs are merged:

1. **Mark the wave task as completed** in the task list
2. **Verify the main branch is clean** — all merges successful, no conflicts
3. **Close issues** if not auto-closed by the PR/MR merge keywords — verify closure via the platform CLI
4. **Report wave status:**
   - How many issues completed vs. deferred
   - PR/MR URLs for the record
   - Any issues that need re-work
   - What the next wave contains
5. **Prompt:** "Wave N complete. Run `/nextwave` for Wave N+1, or `/cryo` to preserve state."

## Important

- This is an EXECUTION skill — it does NOT make design decisions
- Sub-agents are SPEC EXECUTORS — they implement what the issue says, nothing more
- If an agent needs to deviate from the spec, it escalates — it does NOT improvise
- Worktrees provide isolation — agents cannot interfere with each other or with `main`
- **NEVER merge directly to main** — always go through a PR/MR for audit trail and CI
- NEVER skip the pre-commit checklist — it exists because compaction has caused skipped reviews before
- NEVER commit without user approval — even if the agent reports all green
- One wave per invocation — the user controls the pace
- If compaction is imminent, run `/cryo` before it hits — the task list tracks wave progress
- Pair with `/prepwaves` for planning: `/prepwaves` plans, `/nextwave` executes
