---
name: vox
description: Speak to the user via text-to-speech — one-way voice announcements for status updates, approvals, and alerts
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-vox does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-vox
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Voice Announcements

Use `vox` to speak to the user when they need to hear something. One-way audio — no mic input, just announcements.

## Setup (one-time per machine)

Run `vox --setup` to pick a TTS provider. Contract and examples live in `scripts/vox-providers/README.md`. The default (no setup) is silent — safe but inaudible.

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
- `--voice NAME` — voice name (exported to the provider as `VOX_VOICE`)
- `--bg` — background playback so it doesn't block your work
- `--output FILE` / `-o FILE` — write audio to a file instead of playing it
- `--setup` — pick a provider interactively

## Tone

**Write for the ear, not the eye.** Brief, conversational, informative. Imagine you're calling across the room.

**Good:**
> "Hey BJ, PR 91 is merged. All 600 tests passing."

**Bad:**
> "build.sh exited with code 0. 54 validation checks passed. pytest returned 600 passed 0 failed in 17.53 seconds. gh pr merge completed successfully for pull request number 91."

Keep it to 1-2 sentences. Summarize, don't enumerate.

## Best-Effort

If `vox` fails (no backend, network down, no speakers), **continue normally**. Never block on audio. Never retry.

```bash
vox "Done!" || true
```

Set `VOX_DISABLED=1` to no-op cleanly (CI, remote sessions, or temporary silence).
