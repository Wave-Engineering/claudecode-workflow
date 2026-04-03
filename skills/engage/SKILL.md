---
name: engage
description: Read CLAUDE.md, confirm development rules of engagement, and load current plan
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-engage does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-engage
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Engage: Rules of Engagement + Current State

This skill is the post-compaction (or session-start) ritual. It restores context and confirms operating rules.

## Steps

1. **Read CLAUDE.md** - Read the project's `CLAUDE.md` from the current working directory
   - If no `CLAUDE.md` exists, say so and skip to step 3

2. **Confirm Rules of Engagement** - Summarize the mandatory rules found in CLAUDE.md as a numbered list
   - Focus on the MANDATORY and ABSOLUTE rules
   - Be concise - one line per rule, not full paragraphs
   - This confirmation is required by the post-compaction protocol

3. **Load Current Plan** - Check for an active plan file
   - Look in the plan mode system context for a plan file path
   - If a plan file exists, read it and summarize the current state:
     - What was being worked on
     - What's done vs. pending
     - Any blockers or next steps
   - If no plan file exists, say "No active plan found."

4. **Present Ready State** - End with a brief "ready" message that includes:
   - Current git branch
   - Any pending/in-progress work from the plan
   - Ask the user what they'd like to work on

## Important

- Be concise. This is a status check, not a lecture.
- Do NOT start doing work. Just confirm state and wait for direction.
- If CLAUDE.md has a "Session Onboarding" section pointing to another file, read that too.
