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

Exact usage, read from the installed binary:
```
usage: discord-watcher forward <target> [--exclude a,b,c] | forward --off
usage: discord-watcher directmsg <target> <content...>
```

⚠️ **`<target>` is an AGENT, never a channel.** It becomes the aoe session name (`rule.target = {label, session}`), so it must be a **Dev-Name or Dev-Team token** (`babelfish`, `oaw`) — leading `@`/`#` are stripped. **This fails silently if you get it wrong:** any non-`--` token is accepted, so `forward #agent-ops` exits 0 and prints `forwarding doorbells to #agent-ops`. The rule is written and looks healthy; every doorbell then fails at delivery. Do not pattern-match off `#ch` used elsewhere in this skill.

⚠️ **`--exclude` is about what stays LOCAL, not who is excluded as a recipient.** Comma-separated **channel names, channel ids, or author usernames** — doorbells matching any of them are kept by this agent instead of being forwarded (`isExcludedFromForward`: matches `channel.name`, `channel.id`, or `msg.author.username`, normalized lowercase with `@`/`#` stripped).

**Message-side sigil (no invocation needed).** The watcher parses `//directmsg` / `//dm` at the **start** of a Discord message (`/^\/\/(?:directmsg|dm)\b\s*/i`). Correct form — **both parts are required**:

```
//dm @<dev-name|dev-team> <message>
```

`parseDirectMsg` matches `/^(\S+)\s+([\s\S]+)$/`, so a target token **and** a non-empty body are mandatory. `//dm help` returns null; `//dm need you now` silently parses `need` as the target, matches no agent, and the message is **forwarded away** — the exact failure the direct lane exists to prevent. The `@<target>` mention is also what routes the doorbell to that watcher at all.

The override is **scoped**, not global: it fires only when the target matches the *receiving* agent's own dev-name or dev-team (`isDirectMsgForLocal`), overriding **that agent's** forward rule. Relay this form to users verbatim when they ask how to reach an agent whose doorbells are forwarded; it is not something `/disc` invokes.

**Why the split matters:** these are different binaries. `disc-server` is the MCP server this skill mostly drives; `discord-watcher` is the notification daemon. A `disc_forward` tool does not exist and never has — attempting one fails. If a future intent has no `disc_*` tool, that is the expected shape for watcher-owned features, not a bug to route around.

**Turn-taking on shared channels** — before answering a team-addressed question when many agents are listening, follow the mic convention (claim the talking-stick or defer). Full convention: https://github.com/Wave-Engineering/claudecode-workflow/blob/main/docs/discord-mic-convention.md (in the cc-workflow repo at `docs/discord-mic-convention.md`; not deployed to the Cellar, so the bare relative path won't resolve from a non-repo session).
