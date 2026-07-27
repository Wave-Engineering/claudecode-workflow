---
name: disc
description: Discord integration — /disc routes to disc-server MCP tools, plus discord-watcher CLI subcommands for forward/directmsg.
usage: |
  /disc send #ch "msg"  /disc read #ch  /disc list  /disc create #ch  /disc thread "name" in #ch
  /disc forward <agent> [--exclude a,b]  /disc forward off  /disc dm <agent> "msg"
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-disc does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-disc
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Disc — Discord Router (disc-server MCP + discord-watcher CLI)

Route each /disc intent to **its owning surface**. Most are `disc-server` MCP tool calls — but `forward` and `directmsg` are **not**. They are `discord-watcher` CLI subcommands, and there is **no `disc_forward` MCP tool**. Check the routing table below rather than assuming a `disc_*` tool exists for an intent.

**Resolve identity** — read `<project_root>/.claude/agent-identity.json` for `dev_name`, `dev_avatar`, `dev_team` (defaults: Claude, 🤖, unknown). Fall back to `/tmp/claude-agent-<md5(project_root)>.json` if the durable file is absent (transition window).

**Resolve channel/guild** — read `~/.claude/discord.json`. `.channels` is a flat name→id **string** map (`{"general":"…","roll-call":"…"}`), so read:
- guild → `.guild_id`
- default channel → `.default_channel_id` (top-level)
- roll-call channel → `.roll_call_channel_id` (top-level)
- any named channel → `.channels["<name>"]` (the value IS the id string — do NOT append `.id`), or `disc_resolve(name, guild_id)` if the name isn't in the map.

Last-resort fallbacks only if `discord.json` is missing the key: default `1487288523638837268`, roll-call `1487382005036617851`.

**Route intent — disc-server MCP tools:**
- send / check-in / no args → `disc_send(channel_id, "**<name>** <avatar> (<team>): <msg>")` — check-in sends to #roll-call
- read → `disc_read(channel_id, limit=20)` — summarize digest, highlight agent-addressed messages
- list → `disc_list(guild_id, type="text")` — format as clean list
- create channel → `disc_create_channel(guild_id, name)` — confirm with created id
- create thread → `disc_create_thread(channel_id, name)` — confirm with created id

**Route intent — `discord-watcher` CLI (Bash, NOT an MCP tool):**
- forward → `discord-watcher forward <agent> [--exclude a,b,c]` — routes this agent's doorbells to another **agent**. Confirms with `disc forward: forwarding doorbells to <label>`.
- forward off / stop → `discord-watcher forward --off` — confirms `rule cleared`, or `no rule to clear` if none was set.
- directmsg / dm → `discord-watcher directmsg <agent> <content...>` (`dm` is an accepted alias) — bypasses the forward rule and rides the deliver-router.
- doorbell → `discord-watcher doorbell` — the **channels-free** doorbell transport, for sessions started without `--channels`. Arm it with `doorbell-oneshot.sh`, never bare: see "Arming the channels-free doorbell" below.

Exact usage, read from the installed binary:
```
usage: discord-watcher forward <target> [--exclude a,b,c] | forward --off
usage: discord-watcher directmsg <target> <content...>
usage: discord-watcher doorbell
```

⚠️ **`<target>` is an AGENT, never a channel.** It becomes the aoe session name (`rule.target = {label, session}`), so it must be a **Dev-Name or Dev-Team token** (`babelfish`, `oaw`) — leading `@`/`#` are stripped. **This fails silently if you get it wrong:** any non-`--` token is accepted, so `forward #agent-ops` exits 0 and prints `forwarding doorbells to #agent-ops`. The rule is written and looks healthy; every doorbell then fails at delivery. Do not pattern-match off `#ch` used elsewhere in this skill.

⚠️ **`--exclude` is about what stays LOCAL, not who is excluded as a recipient.** Comma-separated **channel names, channel ids, or author usernames** — doorbells matching any of them are kept by this agent instead of being forwarded (`isExcludedFromForward`: matches `channel.name`, `channel.id`, or `msg.author.username`, normalized lowercase with `@`/`#` stripped).

**Message-side sigil (no invocation needed).** The watcher parses `//directmsg` / `//dm` at the **start** of a Discord message (`/^\/\/(?:directmsg|dm)\b\s*/i`). Correct form — **both parts are required**:

```
//dm @<dev-name|dev-team> <message>
```

`parseDirectMsg` matches `/^(\S+)\s+([\s\S]+)$/`, so a target token **and** a non-empty body are mandatory. `//dm help` returns null; `//dm need you now` silently parses `need` as the target, matches no agent, and the message is **forwarded away** — the exact failure the direct lane exists to prevent. The `@<target>` mention is also what routes the doorbell to that watcher at all.

The override is **scoped**, not global: it fires only when the target matches the *receiving* agent's own dev-name or dev-team (`isDirectMsgForLocal`), overriding **that agent's** forward rule. Relay this form to users verbatim when they ask how to reach an agent whose doorbells are forwarded; it is not something `/disc` invokes.

## Arming the channels-free doorbell (`doorbell`)

For sessions started **without** `--channels`: the MCP notification sink is never wired up, so no doorbell reaches the agent. `discord-watcher doorbell` (watcher **v1.6.0+**) is the alternate transport — same poll loop, same fail-closed delivery gate, but each deliverable message is emitted as one stdout line:

```
[doorbell] #<channel> channel_id=<id> msg_id=<id> from <author>: <preview>
```

⚠️ **Do NOT arm it the way the watcher's README and `--help` say to.** Both print:

```
Monitor({ command: "discord-watcher doorbell", persistent: true })
```

`Monitor` is **absent from some clients' tool surface** — check before relying on it. Where it is missing, the only background-process mechanism available notifies the agent when a task **exits**, and `doorbell` is a persistent loop that never exits. Armed that way the line is written to a file nobody reads and the agent is never woken: *silent* deafness, the exact failure the doorbell exists to prevent.

**Use the one-shot wrapper instead** — it makes the exit BE the doorbell, so the task-completion notification wakes the agent. Invoke it by **bare name** (`./install` symlinks every `scripts/*` file onto PATH); a relative `scripts/…` path only resolves inside the cc-workflow source tree, which is never where you want to be — the wrapper must run from the *target project's* root so identity resolves:

```bash
doorbell-oneshot.sh                 # blocks until a message arrives, prints it, exits
TIMEOUT=1800 doorbell-oneshot.sh    # bounded wait; exit 3 if nothing arrives
DRAIN_SECONDS=2 doorbell-oneshot.sh # widen the drain window (see the limit below)
DEBUG=1 doorbell-oneshot.sh         # also forward the watcher's stderr
```

Run it as a **background** task, then re-arm after handling the messages it printed (one batch → one turn). Cellar copy, for reference: `~/.claude/scripts/doorbell-oneshot.sh`.

**Read the exit code — it is the whole signal.** `0` = one or more `[doorbell]` lines on stdout; `2` = precondition failure (bash < 4, watcher missing, **watcher older than v1.6.0**, malformed `TIMEOUT`/`DRAIN_SECONDS`); `3` = `TIMEOUT` elapsed with nothing delivered; `4` = the `doorbell` subcommand exists but the watcher died without emitting a valid line — bad token, baseline-init failure, crash — with its stderr printed for you. Never treat a bare exit 0 with empty stdout as a message: re-arming on that is a hot loop, and the wrapper is built so it cannot happen.

A **pre-v1.6.0 watcher does not error** — it has no unknown-subcommand handler, so `doorbell` falls through to the MCP server and the process never exits. That would hang the wrapper forever at the default `TIMEOUT=0`, so the wrapper probes `doorbell --help` up front and fails with exit 2 instead. If you see that, the fix is a watcher upgrade, not a retry.

**It prints a batch, not one line** — and the batch is one channel's worth. After the first line the wrapper drains for `DRAIN_SECONDS` (default `0.2`) and prints everything already buffered. Handle **every** line before re-arming: the re-armed instance seeds its cursor past them and marks them delivered (see "Cold start does not replay" below), so a line you ignore is gone for good.

⚠️ **Known gap — the drain does not span channels.** Within one poll cycle the watcher waits 50–150ms of jitter plus an HTTP round trip between channels, and the wrapper kills it once the drain window closes, so channels it had not reached yet are never polled. Messages addressed to you in a *second* channel during the same cycle can therefore be missed, unrecoverably. If you are routinely addressed across several channels, raise `DRAIN_SECONDS` (2 covers the jitter and a round trip) — it narrows the gap without closing it. Closing it properly needs a cycle-boundary signal from the watcher.

**Three ways this goes silently deaf.** Every one of them polls normally and delivers nothing, so "no doorbells" never distinguishes healthy-and-quiet from broken:

1. **Wrong cwd → unresolved identity → fail closed.** Identity comes from `CLAUDE_PROJECT_DIR ?? process.cwd()` and is read from `<root>/.claude/agent-identity.json`; with either field unresolved, `shouldDeliverMessage` returns false for everything (deaf > over-broad). **Launch from the project root, or export `CLAUDE_PROJECT_DIR`.** Confirm via stderr: `state_change ... "what":"identity","from":"null/null","to":"<name>/<team>"` — the wrapper captures the watcher's stderr and replays it under `DEBUG=1` (and always on exit 4). It also warns when the identity file is missing.
2. **Never pipe to `head -1`** — it leaks an orphaned poller. Bun ignores `SIGPIPE` and swallows the write error, so closing the read end does **not** kill the child; it keeps polling Discord forever, and re-arming that way accumulates one poller per message. The wrapper reads through a fifo and kills the child by PID.
3. **Your own signature is filtered.** The self-echo gate drops any message containing `— **<dev-name>**`. A test message signed the normal way tests nothing — send it unsigned, from another account, or it will be correctly discarded.

**Cold start does not replay.** The cursor is seeded to the latest message per channel at startup, so pre-existing history is never re-delivered — same as the MCP watcher. A message landing in the exact instant of a `--channels`→`doorbell` cutover is not bridged. Forward-rule routing is intentionally **not** applied in doorbell mode: it always delivers this agent's own doorbells.

**Why the split matters:** these are different binaries. `disc-server` is the MCP server this skill mostly drives; `discord-watcher` is the notification daemon. A `disc_forward` tool does not exist and never has — attempting one fails. If a future intent has no `disc_*` tool, that is the expected shape for watcher-owned features, not a bug to route around.

**Turn-taking on shared channels** — before answering a team-addressed question when many agents are listening, follow the mic convention (claim the talking-stick or defer). Full convention: https://github.com/Wave-Engineering/claudecode-workflow/blob/main/docs/discord-mic-convention.md (in the cc-workflow repo at `docs/discord-mic-convention.md`; not deployed to the Cellar, so the bare relative path won't resolve from a non-repo session).
