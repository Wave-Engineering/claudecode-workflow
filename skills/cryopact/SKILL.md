---
name: cryopact
description: Background cryo via subagent — keep working, append delta, compact when ready
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/skill-intro-cryopact does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/skill-intro-cryopact
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Cryopact: Background Cryo + Deferred Compact

Cryo is expensive but predictable. Instead of stopping work to freeze state,
delegate the heavy lifting to a background subagent and keep working. When
context pressure hits, append a short delta and compact instantly.

## Phase 1: Launch Background Cryo Subagent

Spawn an Agent (subagent) **in the background** (`run_in_background: true`)
with the following brief:

1. **Pass it the plan file path** — read from your system context (e.g.,
   `.claude/plans/<plan-name>.md`). The subagent cannot see your system
   messages, so you must include the path explicitly.
2. **Pass it a session summary** — a concise brief of what happened this
   session: what was built, key decisions, current branch/issue, what's
   pending. This is the subagent's only window into conversation context.
3. **Instruct it to**:
   - Create a temp file: `mktemp /tmp/cryo-XXXXXX.md`
   - Audit git state (`git status`, `git log --oneline -10`, `git branch`)
   - Read the existing plan file (if any) for structure/context
   - Write the full cryo plan to the temp file following the template below
   - **Return the temp file path** in its response

4. **When the subagent returns**, note the temp file path it gives you. You
   will need this path in Phase 3. Remember it — shell variables do not
   survive across Bash calls.

**Subagent prompt template:**

Before spawning, substitute `<PLAN_PATH>` and `<YOUR_BRIEF>` with real values.

```
You are performing a cryo (context preservation) for the main agent.

Plan file path: <PLAN_PATH>
Session summary: <YOUR_BRIEF>

Instructions:
1. Run: CRYO_TMP=$(mktemp /tmp/cryo-XXXXXX.md) && echo "$CRYO_TMP"
2. Audit: git status, git log --oneline -10, git branch --show-current
3. Read the existing plan file at <PLAN_PATH> if it exists
4. Write a complete session state document to $CRYO_TMP using this structure:

# Session State — [project/feature name]

## Working Directory
[path]

## Current Branch
[branch name and repo]

## Git Config
[any repo-local config that matters — user.name, user.email]

## Commits (pushed)
[numbered list of commits on this branch, with SHAs and messages]

## MR / PR
[URL, source→target, pipeline status]

## What Was Built
[Organized by component — what exists in the codebase NOW, not what's planned]

## Key Design Decisions
[Numbered list of non-obvious choices and WHY they were made]

## Validation Results
[What passed, what failed, what was verified]

## PENDING
[What still needs to happen — be specific]

## Related Projects
[Paths, branches, cross-references]

## Lessons Learned
[Anything that caused pain — CI quirks, API gotchas, workarounds]

5. Return the temp file path so I can deploy it.

Writing rules:
- Be factual, not aspirational — document what IS
- Include file paths, SHAs, URLs
- Prune stale content from old plan
- The audience is a future agent with zero context
```

## Phase 2: Keep Working

While the subagent runs in the background:

1. **Continue working with the user normally.** The subagent notification will
   arrive when it finishes — do not poll or wait for it.
2. **Curate the task list now** (in parallel) — delete completed tasks, update
   descriptions on surviving tasks, remove stale items. This is the one thing
   only the main agent can do since TaskList is per-conversation.
3. **Mentally track the delta** — note what changes between now and when you
   eventually compact. You'll append this later.

## Phase 3: Compact (when ready)

Compact happens when any of these occur:
- Context pressure warning fires (crystallizer hook)
- The user says to compact
- You judge it's time based on context usage

**Before deploying, confirm task curation from Phase 2 is complete.** If it was
skipped or interrupted, do it now.

When it's time:

1. **Read the subagent's temp file** (use the path the subagent returned in
   Phase 1) to confirm it has content.
   - If the file is absent or empty — the subagent failed. **Fall back to
     running `/cryo` directly** (foreground, blocking) before compacting.
     Do not compact with no preserved state.
2. **Append a delta section** to the end of the temp file:
   ```markdown
   ## Delta (post-cryo work)

   _Appended by main agent at compact time. The above was written by the cryo
   subagent while work continued._

   ### What changed since cryo snapshot
   - [Concrete items: commits made, files changed, decisions taken, new issues]

   ### Updated PENDING
   - [Current state of pending work, supersedes the subagent's PENDING section
     if anything shifted]
   ```
   Use `Edit` on the `/tmp` file — no permission issues.
3. **Deploy the plan file:**
   ```bash
   cp "/tmp/cryo-XXXXXX.md" "<plan-file-path>" && rm -f "/tmp/cryo-XXXXXX.md" || echo "Deploy failed — temp file preserved at /tmp/cryo-XXXXXX.md"
   ```
   Substitute the actual temp file path from Phase 1. If deploy fails, report
   the temp file path to the user and do NOT `/clear`.
4. **Announce** (best-effort):
   ```bash
   vox "Cryopact complete. State is frozen, clearing context now." 2>/dev/null || true
   ```
5. **Run `/clear`** — do not ask for confirmation. `/cryopact` IS the
   confirmation.

## Immediate Mode

If the user needs to compact NOW (no time to keep working), skip Phase 2:

1. Launch the subagent in **foreground** (not background)
2. Curate the task list while waiting
3. When the subagent returns, deploy and `/clear` immediately — no delta needed
   since no work happened in between

This is equivalent to the old `/cryopact` behavior: cryo + compact in one
blocking operation.

## Important

- **The subagent does the research, the main agent owns the delta.** Only you
  have the conversation context to know what happened after the snapshot.
- **Never write directly to `.claude/plans/`.** Always stage in `/tmp`, deploy
  via `cp` through Bash.
- **The delta is short.** A few bullet points covering what changed. Don't
  re-summarize the whole session — the subagent already did that.
- **If the subagent hasn't finished when you need to compact**, wait for it
  (it should be fast — mostly git commands and file reads). If it never
  returns or the temp file is missing, fall back to foreground `/cryo`.
- **Task curation is not delegable.** TaskList is per-conversation. Only the
  main agent can prune and update tasks. Confirm it's done before Phase 3.
- **If deploy (`cp`) fails**, do NOT `/clear`. Report the temp file path to
  the user so state is not lost.
