---
name: vox
description: Speak to the user via text-to-speech — one-way voice announcements for status updates, approvals, and alerts
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
     Do this BEFORE executing any skill logic below. -->

# Voice Announcements

Use `vox` to speak to the user when they need to hear something. One-way audio — no mic input, just announcements.

## When to Use

- **Approval needed** — "Hey BJ, the build passed and I'm ready for your review on PR 91"
- **Work complete** — "All done — 34 tests passing, branch is pushed"
- **Errors requiring attention** — "Heads up, the deploy failed — looks like a connection timeout"
- **User explicitly asked to be notified** — "You asked me to let you know when the migration finished — it's done"

## When NOT to Use

- Routine progress updates the user didn't ask for
- Every commit or push
- Repeating what's already visible on screen
- Anything the user hasn't asked to hear about

## How to Use

```bash
vox "Hey BJ, tests are green and the PR is ready for review"
```

Options:
- `--voice NAME` — pick a voice (default: Taylor.wav)
- `--bg` — background playback so it doesn't block your work
- `--output FILE` / `-o FILE` — write audio to a file instead of playing it (useful for attachments)
- `--list-voices` — show available voices

## Tone

**Write for the ear, not the eye.** Brief, conversational, informative. Imagine you're calling across the room.

**Good:**
> "Hey BJ, PR 91 is merged. All 600 tests passing."

**Bad:**
> "build.sh exited with code 0. 54 validation checks passed. pytest returned 600 passed 0 failed in 17.53 seconds. gh pr merge completed successfully for pull request number 91."

Keep it to 1-2 sentences. Summarize, don't enumerate.

## Paralinguistic Tags

Chatterbox supports expressive tags — use sparingly for personality:

`[laugh]`, `[sigh]`, `[gasp]`, `[chuckle]`, `[groan]`, `[clear throat]`

Example: `vox "[clear throat] Attention please — the build is on fire."`

## Best-Effort

If `vox` fails (no backend, network down, no speakers), **continue normally**. Never block on audio. Never retry. Just move on.

```bash
vox "Done!" 2>/dev/null || true
```

## Voice Selection

28 voices available. Some suggestions:
- **Taylor** (default) — BJ's pick
- **Emily** — clear, neutral
- **Jade** — warm
- **Adrian** — deep
- **Olivia** — bright

Use `vox --list-voices` to see all options, or `--voice NAME` to pick one.
