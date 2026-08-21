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

**Never pass the message as an inline double-quoted argument (#942).** Feed it in.

```bash
# Composing the text yourself, in the source, where you can see all of it:
vox <<'EOF'
Hey BJ, tests are green and the PR is ready for review
EOF

# Anything filled in at invocation time — a placeholder, a variable, a summary you
# are about to generate — goes through a file instead (#1136, see below):
vox < /tmp/announcement.md
```

Both are correct; the second is correct *always*, so prefer it when you are not
certain what the body will contain.

**Why, and it is not style.** Backticks and `$(...)` inside a double-quoted shell
string are **command substitution** — bash runs them before `vox` ever sees the
text. This:

```bash
# ANTI-EXAMPLE
vox "…the `mytool send alice hi` gate…"
```

*executes* `mytool send alice hi` before vox runs.
That is not hypothetical: it happened on 2026-07-20 (#942), where a comment about
CLI tools launched `discord-watcher directmsg` and an MCP server that then hung
forever, and the substituted span was **stripped from the message**, so the
announcement lost content while the side effect happened silently.

An agent announcing its own work is exactly the case that carries tool names —
"merged #942", "ran `validate.sh`" — so the hazard is worst where vox is most
useful.

**The quoting of the delimiter is load-bearing.** `<<'EOF'` (quoted) suppresses
all expansion; a bare `<<EOF` still substitutes backticks and `$(...)` and will
execute them. Verified both ways in `tests/test_body_never_inline.py`.

A message with no shell metacharacters is safe either way — but "I checked this
one" is not a rule that survives the next message, so pipe unconditionally.

**A quoted delimiter stops substitution. It does not stop TERMINATION (#1136).**
If the body contains a line equal to the delimiter, the heredoc ends there and
everything after it runs as shell — the text is silently truncated *and* the
remainder executes. This bit us ten minutes after the rule above shipped, filing
an issue whose body contained a heredoc example.

"Pick a distinctive delimiter" is the weak fix: it works only if you can predict
the content, and prose *about* shell tooling necessarily contains delimiter-shaped
lines. That turns a systematic property back into a per-invocation judgement call
— the thing this page just told you not to rely on.

**So when the body is filled in at invocation time, do not use a shell heredoc.**
Write it with a tool that has no delimiter semantics (the `Write` tool), then feed
the file to vox **on stdin**:

```bash
vox < /tmp/announcement.md          # correct
vox "$(cat /tmp/announcement.md)"   # also correct — expansion does not re-parse
```

**`vox` takes NO path argument.** `vox /tmp/announcement.md` sets the message to
the literal string `/tmp/announcement.md` and cheerfully synthesises *that*
(`scripts/vox`: any non-flag token becomes `TEXT`). It exits 0. You get no error
and no announcement — only a robot reading a filename to an empty room. `--output`
is not the counterpart either; it writes audio *out*, the opposite direction.
Verified by measurement, after an earlier draft of this very section prescribed
passing the path.

**The boundary is the CONTENT, not the author.** Use a heredoc only when you can
see the whole body in the source *and* no line of it could equal the delimiter.
If any part is filled in at invocation time — a `<one sentence>` placeholder, a
`...`, a variable the caller supplies — you cannot see the body, so use `Write` +
stdin. Asking "did I write this or did an agent?" is the wrong test; the shell
only cares what is in it.

One more mode, same family: an **indented** closing delimiter does not terminate
at all (use `<<-` if you need indentation, and even then only tabs). It has bitten
this repo before — see `skills/name/SKILL.md`.

**The invariant is narrower than "use a variable", and getting it wrong is easy.**
Substitution happens wherever prose appears as a **double-quoted literal in shell
source** — including at assignment:

```bash
# ANTI-EXAMPLE
msg="see `mytool send x`"   # ALREADY EXECUTED, here, at assignment.
vox "$msg"                  # this line is innocent; the damage is upstream
```

Expanding a variable does **not** re-substitute its contents, so the fix is not
"put it in a variable" — it is "never let the prose be shell source at all":

```bash
msg="$(cat body.md)"        # safe: the text came from a file
vox <<'EOF'                 # safer: it never becomes an argument
...
EOF
```

A fixed literal with no metacharacters is fine and needs no change — e.g.
`scripts/godspeed-lookback.sh:861`, which assigns a constant announcement and
then passes it as `vox "$vox_msg"` at :866. The rule targets **agent-composed
prose**, which is where tool names and code spans come from.

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
vox <<'EOF' || true
Done!
EOF
```

Set `VOX_DISABLED=1` to no-op cleanly (CI, remote sessions, or temporary silence).
