---
name: disc
description: Discord integration via disc-server MCP — routes /disc intents to disc_* tool calls.
usage: |
  /disc send #ch "msg"  /disc read #ch  /disc list  /disc create #ch  /disc thread "name" in #ch
---

# Disc — disc-server MCP Router

Route all /disc intents to `disc-server` MCP tool calls.

**Resolve identity** — read `/tmp/claude-agent-<md5(project_root)>.json` for `dev_name`, `dev_avatar`, `dev_team` (defaults: Claude, 🤖, unknown).

**Resolve channel/guild** — read `~/.claude/discord.json`: `.guild_id`, `.channels.default.id` (default: 1487288523638837268), `.channels["roll-call"].id` (default: 1487382005036617851). Use `disc_resolve(name, guild_id)` when given a channel name.

**Route intent:**
- send / check-in / no args → `disc_send(channel_id, "**<name>** <avatar> (<team>): <msg>")` — check-in sends to #roll-call
- read → `disc_read(channel_id, limit=20)` — summarize digest, highlight agent-addressed messages
- list → `disc_list(guild_id, type="text")` — format as clean list
- create channel → `disc_create_channel(guild_id, name)` — confirm with created id
- create thread → `disc_create_thread(channel_id, name)` — confirm with created id
