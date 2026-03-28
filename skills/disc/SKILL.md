---
name: disc
description: Send/read messages and manage channels on the Oak and Wave Discord server
---

# Disc

Unified Discord integration for the **Oak and Wave** server. One skill handles sending, reading, channel creation, and listing — routed by natural language intent.

## Configuration

```
Guild ID: 1486516321385578576
Default channel: #agent-ops (1487288523638837268)
Token: ~/secrets/discord-bot-token
```

## Resolve Intent

{{#if args}}
Parse the argument: `{{args}}`
{{else}}
No argument — default to reading recent messages from `#agent-ops`.
{{/if}}

Determine what the user wants from the phrasing:

| Pattern | Intent | Examples |
|---------|--------|---------|
| Quoted text, or starts with "say", "tell", "post", "send", "announce" | **send** | `"build complete"`, `tell #dev "ready"`, `post "deployed v1.2"` |
| Starts with "check", "read", "what's", contains `?`, or describes wanting to see messages | **read** | `what's new?`, `check #general`, `read #agent-ops` |
| Starts with "create", "make", "new" + channel name | **create** | `create #wave-3-status`, `new channel test` |
| Starts with "thread", "create thread", "new thread" + thread name | **create-thread** | `thread "session-123" in #remote-sessions`, `create thread "daily"` |
| Starts with "list", "show", "channels" | **list** | `list channels`, `show channels` |
| No args at all | **read** | (reads default channel) |

## Resolve Agent Identity

Before sending messages, resolve the session identity:

```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
agent_file="/tmp/claude-agent-${dir_hash}.json"
```

Read `dev_name`, `dev_avatar`, and `dev_team` from that file. If the file doesn't exist, use defaults: name=`Claude`, avatar=`:robot_face:`, team=`unknown`.

## Resolve Channel

When a channel is mentioned by name (e.g., `#dev`, `agent-ops`, `general`):

```bash
discord-bot resolve 1486516321385578576 <channel-name>
```

- If not found, ask if the user wants to create it.
- If no channel is specified, use the default: `#agent-ops` (`1487288523638837268`).

## Send Flow

1. Resolve channel (default: `#agent-ops`)
2. Resolve agent identity
3. Format the message with identity prefix: `**<Dev-Name>** <Dev-Avatar> (<Dev-Team>): <message>`
4. Send:
   ```bash
   discord-bot send <channel-id> "<formatted message>"
   ```
   To attach a file (e.g., a voice memo WAV):
   ```bash
   discord-bot send <channel-id> "<formatted message>" --attach /path/to/file.wav
   ```
   The `--attach` flag uploads the file as a Discord attachment using multipart/form-data. It works with or without `--embed`.
5. Confirm: `Sent to #<channel-name>.`

## Read Flow

1. Resolve channel (default: `#agent-ops`)
2. Fetch messages:
   ```bash
   discord-bot read <channel-id> --limit 20
   ```
3. **Summarize** the messages for the user — provide a concise digest, don't dump raw output. Group by topic or conversation thread if the messages are related. Highlight anything that looks like it's addressed to this agent or team.

## Create Channel Flow

1. Parse channel name from args (strip `#` prefix if present)
2. Optionally parse a topic from the args (e.g., "create #wave-3 for tracking wave 3 progress" → topic = "tracking wave 3 progress")
3. Create:
   ```bash
   discord-bot create-channel 1486516321385578576 <name> --topic "<topic>"
   ```
4. Confirm: `Created #<name> (<id>).`

## Create Thread Flow

1. Parse the parent channel ID and thread name from args
2. Optionally parse `--auto-archive` duration (default: 1440 = 24 hours)
3. Create:
   ```bash
   discord-bot create-thread <channel-id> <name> [--auto-archive 60|1440|4320|10080]
   ```
4. Confirm: `Created thread #<name> (<id>).`

Note: Thread IDs work with `discord-bot read <thread-id>` for reading thread messages.

## List Channels Flow

1. List text channels:
   ```bash
   discord-bot list-channels 1486516321385578576 --type text
   ```
2. Format as a clean list for the user.
