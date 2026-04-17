---
name: wtf
description: Start a WTF flight recorder troubleshooting session
---

# /wtf — Start a Troubleshooting Session

Launch the WTF flight recorder for a new troubleshooting incident. Archives
any prior incident, prompts for an optional title, then puts Claude into
flight recorder mode where significant observations, theories, and corrective
actions are journaled automatically.

## Resolve Intent

Parse the invocation arguments:

- **No arguments** — start a new troubleshooting session (default behavior).
- **`record <text>`** — shorthand for `/wtf now <text>`. Route directly to
  the `/wtf now` skill with the provided text, then stop.

## Steps

### 1. Archive prior incident

Call the `wtf_freshell` MCP tool with no arguments. This archives any
currently active incident and creates a fresh one.

### 2. Prompt for incident title

Ask the user:

> What are you troubleshooting? (optional — press Enter to skip)

If the user provides a title, call `wtf_freshell` again with `{ "title": "<user's title>" }` to set the title on the newly created incident.

Wait for the user's response before proceeding.

### 3. Confirm and activate flight recorder mode

Tell the user the session is active, then follow these behavioral
instructions for the remainder of the conversation:

---

You are now in **WTF flight recorder mode**. A background journal is
capturing every tool call automatically. In addition to that automatic
capture, you should:

- Call `wtf_now` with `gen_type: "crafted"` and `action_type: "breadcrumb"`
  when you observe something diagnostically significant
- Call `wtf_now` with `gen_type: "crafted"` and `action_type: "theory"` when
  you form a hypothesis about the root cause
- Call `wtf_now` with `gen_type: "crafted"` and `action_type: "action"` when
  you take a corrective action (not exploratory commands)

**Bias toward recording.** When in doubt, record it. A noisy journal can be
distilled; a silent journal cannot be recovered.

At any time, the user may call `wtf_happened` to see the current timeline,
or `/wtf now` to add their own observations.

---

After injecting these instructions, confirm to the user:

> Flight recorder is active. I'll journal significant findings as we go.
> Use `/wtf now <text>` to add your own notes, or `wtf_happened` when you
> want to see the timeline.
