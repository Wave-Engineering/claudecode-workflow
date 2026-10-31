---
name: disc
description: DEPRECATED — use /owtx and /owrx (OaW Mattermost by default). /disc still works and still means Discord — disc-server MCP tools, or crewchat's chat_* tools with backend "discord" where they exist — and still arms the doorbell.
usage: |
  DEPRECATED: use /owtx (send) and /owrx (read); add "> discord" for Discord.
  /disc send #ch "msg"  /disc read #ch  /disc list  /disc create #ch  /disc thread "name" in #ch
  /disc doorbell  — arm the doorbell: crewchat-doorbell where chat_send exists
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-disc does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-disc
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Disc — Discord Router (deprecated)

> **Deprecated (#1348).** The kit's chat commands are now `/owtx` (send) and `/owrx` (read), and they go to the OaW Mattermost server by default. `/disc` keeps working, and keeps meaning **Discord**: nothing here changed where a `/disc` command goes. Removing it is a later major release.
>
> **Begin every `/disc` response with this line, verbatim:**
>
> `/disc is deprecated: use /owtx and /owrx (OaW Mattermost by default; add "> discord" for Discord).`

Route each /disc intent to **its owning surface**: a `disc-server` MCP tool, or crewchat's `chat_*` tool with `backend: "discord"` on a crewchat host. There is no `disc_forward` or direct-message intent any more: doorbell forwarding and the `//dm` lane were `discord-watcher` features, and the watcher was retired from the kit (#1344).

**Resolve identity** — read `<project_root>/.claude/agent-identity.json` for `dev_name`, `dev_avatar`, `dev_team` (defaults: Claude, 🤖, unknown). Fall back to `/tmp/claude-agent-<md5(project_root)>.json` if the durable file is absent (transition window).

**Resolve channel/guild** — read `~/.claude/discord.json`. `.channels` is a flat name→id **string** map (`{"general":"…","roll-call":"…"}`), so read:
- guild → `.guild_id`
- default channel → `.default_channel_id` (top-level)
- roll-call channel → `.roll_call_channel_id` (top-level)
- any named channel → `.channels["<name>"]` (the value IS the id string — do NOT append `.id`), or `disc_resolve(name, guild_id)` if the name isn't in the map.

Last-resort fallbacks only if `discord.json` is missing the key: default `1487288523638837268`, roll-call `1487382005036617851`.

## Transport

The kit's chat rules live in `docs/chat-tools.md` (the repo root's, else `~/.claude/docs/chat-tools.md`): "Transport: `chat_*` or `disc_*` (the dual-mode rule)", and "Doorbell: `crewchat-doorbell` or the one-shots". `/disc` applies them with Discord as its fixed target:

- **If `chat_send` is in your tool list**, send and read with the `chat_*` tools, always with `backend: "discord"`: `disc_send(channel_id, msg)` becomes `chat_send(to: channel_id, text: msg, backend: "discord")`, and `disc_read(channel_id, limit)` becomes `chat_read(channel: channel_id, limit, backend: "discord")`.
- **Otherwise** use `mcp__disc-server__disc_*` exactly as below.
- Discord-only ops (list, create channel/thread) stay on `mcp__disc-server__disc_*` on both kinds of host.

**Route intent — disc-server MCP tools** (send and read by the transport above):
- send / check-in / no args → `disc_send(channel_id, "**<name>** <avatar> (<team>): <msg>")` — check-in sends to #roll-call
- read → `disc_read(channel_id, limit=20)` — summarize digest, highlight agent-addressed messages
- list → `disc_list(guild_id, type="text")` — format as clean list
- create channel → `disc_create_channel(guild_id, name)` — confirm with created id
- create thread → `disc_create_thread(channel_id, name)` — confirm with created id
- doorbell → arm the doorbell exactly as "Doorbell: `crewchat-doorbell` or the one-shots" in `docs/chat-tools.md` says.

## Turn-taking on shared channels

Before answering a team-addressed question when many agents are listening, follow the mic convention (claim the talking-stick or defer). Full convention: https://github.com/Wave-Engineering/claudecode-workflow/blob/main/docs/discord-mic-convention.md (in the cc-workflow repo at `docs/discord-mic-convention.md`; not deployed to the Cellar, so the bare relative path won't resolve from a non-repo session).

## Reminding BJ: #call-4-bj

A reminder of a question BJ hasn't answered goes to `#call-4-bj` through `/owtx`, in the same turn; `/sqtk` rule 14 sets the format, including the `⏰⏰⏰⏰` first line when you are blocked.
