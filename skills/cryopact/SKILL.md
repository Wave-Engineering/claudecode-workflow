---
name: cryopact
description: Background cryo via subagent — keep working, append delta, compact when ready
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-cryopact does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-cryopact
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
3. **Resolve the project root** for the subagent — run
   `git rev-parse --show-toplevel` and substitute `<PROJECT_ROOT>` in the
   prompt template.
4. **Instruct it to**:
   - Create a temp file: `mktemp /tmp/cryo-XXXXXX.md`
   - Read `skills/cryo/SKILL.md` for the plan template and writing rules
   - Follow cryo's Step 1 (Audit Current State) and Step 2 (Curate the Plan
     File) — but **skip Step 3** (task curation is not delegable)
   - Use the plan file path you provided (not discover it from system context)
   - Write the result to the temp file
   - **Return the temp file path** in its response

5. **When the subagent returns**, note the temp file path it gives you. You
   will need this path in Phase 3. Remember it — shell variables do not
   survive across Bash calls.

**Subagent prompt template:**

Before spawning, substitute `<PLAN_PATH>`, `<YOUR_BRIEF>`, and `<PROJECT_ROOT>`
with real values.

```
You are performing a cryo (context preservation) for the main agent.

Plan file path: <PLAN_PATH>
Session summary: <YOUR_BRIEF>

Instructions:
1. Run: CRYO_TMP=$(mktemp /tmp/cryo-XXXXXX.md) && echo "$CRYO_TMP"
2. Read the skill file at <PROJECT_ROOT>/skills/cryo/SKILL.md — it contains
   the plan template structure and writing rules.
3. Follow cryo's Step 1 (Audit Current State) and Step 2 (Curate the Plan
   File). SKIP Step 3 (task curation) — you don't have access to TaskList.
   Use the plan file path above when cryo references "the existing plan file."
4. Write the result to $CRYO_TMP — do NOT deploy to the plan path. The main
   agent handles deployment.
5. Return the temp file path so the main agent can deploy it.
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
   the temp file path to the user — do not proceed.
4. **Announce** (best-effort):
   ```bash
   vox "Cryopact complete. State frozen. Ready for compaction." 2>/dev/null || true
   ```
5. **Confirm to the user:**
   > Cryopact complete. State frozen at `<plan-file-path>`. Context will
   > compact naturally, or `/clear` manually when ready.

   **Do NOT run `/clear` automatically.** Compaction is coming anyway — that's
   why cryo was invoked. Let the user or the system decide when to compact.

## Immediate Mode

When autocompact is imminent (context pressure warning fired, or the user says
"now"):

1. Launch the cryo subagent in **background** (same as normal mode — NOT
   foreground). Foreground cryo burns main context with every tool call,
   accelerating the very compaction you're trying to outrun.
2. Main agent writes **minimal breadcrumbs** directly to the plan file — ~5
   lines, no template, no research:
   ```markdown
   # Breadcrumbs — [project name]
   - **Branch:** <branch>
   - **Last commit:** <SHA> <message>
   - **Issue:** #NNN
   - **Cryo temp file:** /tmp/cryo-XXXXXX.md (subagent writing in background)
   - **Status:** <one-line: "mid-implementation" / "tests passing" / etc.>
   ```
   Deploy via `cp` through Bash (same `/tmp` staging pattern).
3. Curate the task list (delete completed, update surviving descriptions).
4. Let compaction happen naturally. The subagent's temp file survives in `/tmp`
   regardless — next session's `/engage` can pick it up even if the main agent
   was compacted before the subagent finished.

This costs ~200 tokens of main context instead of the 2000+ a foreground cryo
would burn.

## Important

- **The subagent does the research, the main agent owns the delta.** Only you
  have the conversation context to know what happened after the snapshot.
- **Never write directly to `.claude/plans/`.** Always stage in `/tmp`, deploy
  via `cp` through Bash.
- **The delta is short.** A few bullet points covering what changed. Don't
  re-summarize the whole session — the subagent already did that.
- **Never auto-clear.** The agent preserves state; the user or system decides
  when to compact. Compaction is coming anyway — that's the whole reason cryo
  was invoked.
- **If the subagent hasn't finished when you need to compact**, write minimal
  breadcrumbs (see Immediate Mode) and let compaction happen. The subagent's
  temp file survives in `/tmp` for the next session.
- **Task curation is not delegable.** TaskList is per-conversation. Only the
  main agent can prune and update tasks. Confirm it's done before Phase 3.
- **If deploy (`cp`) fails**, report the temp file path to the user so state
  is not lost. Do not proceed with compaction.
