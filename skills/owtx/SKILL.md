---
name: owtx
description: Send chat on the OaW Mattermost server by default — /owtx #channel "msg", /owtx @user "msg" (a DM), or bare /owtx for a roll-call check-in; "> discord" or "> <server_id>" as the last pair routes one message elsewhere. Replaces /disc's send side.
usage: |
  /owtx #<channel> "<message>" [> <route>]   post to a channel
  /owtx @<user> "<message>" [> <route>]      a direct message
  /owtx                                      a roll-call check-in
---

# owtx — Transmit (OaW Mattermost by default)

`/owtx` sends one message. With no route it goes to your default backend, which for every OaW org is the OaW Mattermost server (`mattermost:oaw-dev`). There are no verbs: the target says what it is. `/owrx` is the read side. `/disc` is deprecated and still means Discord (#1348).

The transport, the route grammar and ask-once are the kit's chat rules in `docs/chat-tools.md` (the repo root's, else `~/.claude/docs/chat-tools.md`): "Transport: `chat_*` or `disc_*` (the dual-mode rule)" and "Routes: `> <route>`". This skill applies them.

## Grammar

`/owtx [#<channel> | @<user>] "<message>" [> <route>]`

| you type | call |
|---|---|
| `/owtx #general "msg"` | `chat_send(to: "general", text: "msg")` |
| `/owtx @bakerb "msg"` | `chat_dm(to: "bakerb", text: "msg")` |
| `/owtx #general "msg" > discord` | `chat_send(to: "general", text: "msg", backend: "discord")` |
| `/owtx #general "msg" > oaw-dev` | `chat_send(to: "general", text: "msg", backend: "mattermost:oaw-dev")` |
| `/owtx #general "a > b"` | `chat_send(to: "general", text: "a > b")`: the `>` is inside the quotes |
| `/owtx #general ship it > typo` | `chat_send(to: "general", text: "ship it > typo")`: `typo` is not a known route |
| `/owtx` | a roll-call check-in (below) |

- **`#<channel>`** → `chat_send(to: "<channel>", text, backend?)`. The name is passed as is, without the `#`.
- **`@<user>`** → `chat_dm(to: "<user>", text, backend?)`. On Mattermost that is a username. With `> discord`, `chat_dm` needs the Discord user ID, so say so if you were given a name.
- **No target** → a roll-call check-in.
- **The message** may be unquoted when it carries no route.

**The route** (`docs/chat-tools.md`, "Routes: `> <route>`"): only the **last** token pair, `> <route>`, and only when `<route>` is a known name. If the message is quoted, the pair must come after the closing quote. Everything else is message text.
- `discord` → `backend: "discord"`.
- `<server_id>` → `backend: "mattermost:<server_id>"`, for each Mattermost server `chat_health()` lists.
- **No route → omit `backend` entirely.** The shim's default applies: `home_backend`, then `chat-defaults.json`, then ask-once (`needs_human`: ask the question verbatim, `chat_set_default`, retry).

## Roll-call check-in

Bare `/owtx` posts to `roll-call` in the `/name` format, with no `backend`:

```
**<dev-name>** <dev-avatar> online — team `<dev-team>` @ <project-root>
```

Resolve identity from `<project_root>/.claude/agent-identity.json` (`dev_name`, `dev_avatar`, `dev_team`; defaults Claude, 🤖, unknown).

## Signing and addressing

- Sign as today: a last line of `— **<dev-name>** <dev-avatar> (<dev-team>)`. On Discord the daemon replaces your own trailing signature instead of doubling it.
- Emitted addressing is `@agents`, never `@all`.

## Without crewchat (no `chat_send` in your tool list)

The host has no crewchat daemon. Post through `mcp__disc-server__disc_send(channel_id: "<channel>", message)` (it accepts the channel name), and **say once that the message went to Discord because this host has no crewchat**. Never fail silently.

- A `> <server_id>` route can't be honoured here. Say so, and send nothing.
- `@<user>` has no Discord DM path in disc-server. Say so, and send nothing.

## Report

One line: where it went and the post ID, for example `sent to #general on mattermost:oaw-dev (post 8x…)`. A `chat_*` error is reported as is: it is not a cue to switch transports.
