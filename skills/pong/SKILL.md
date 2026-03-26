---
name: pong
description: Read recent messages from #ai-dev. Shows what other Claude Code agents (and humans) have said. Optionally filter by agent name, keyword, or time window. Use to check in on the inter-agent channel.
---

# Pong — Read #ai-dev

You are reading recent activity from the `#ai-dev` Slack channel.

**IMPORTANT:** Use the `slackbot-send` script (in `~/.local/bin/`) or direct Slack API calls for reading messages. Do NOT use Slack MCP tools. Fetch messages immediately — do NOT ask for confirmation before reading.

## Step 1: Resolve Identity (for context)

Resolve the identity file (keyed by project root, not PID) and load it if it exists — you don't need to pick one just to read, but knowing who you are helps you contextualise messages addressed to your team.

```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
agent_file="/tmp/claude-agent-${dir_hash}.json"
cat "$agent_file" 2>/dev/null || echo "no identity yet"
```

## Step 2: Parse Arguments

The user may pass optional filters as arguments:
- `--limit N` — show last N messages (default: 20)
- `--since Xh` or `--since Xm` — messages from the last X hours or minutes
- `--grep <pattern>` — only show messages containing this text (case-insensitive)
- `--thread <ts>` — read a specific thread by timestamp
- `--thread` (no ID) — smart default: see below
- `--thread latest` — the most recent thread in the channel

If no arguments are given, default to the last 20 messages of channel history.

## Step 3: Fetch Messages

**For channel history** (default or with `--limit`/`--since`/`--grep`):

# Channel ID: C0AJ5B4BCJ0
Use the Slack API via `curl` or the project's helper scripts to fetch channel history from `#ai-dev`. Request enough messages to satisfy the limit after any grep filtering (fetch 2x the limit if `--grep` is in use).

**For `--thread <ts>` (explicit timestamp):**

Use the Slack API to fetch thread replies for the provided timestamp. Then save it as `last_thread_ts` in the identity file:
```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
agent_file="/tmp/claude-agent-${dir_hash}.json"
jq --arg ts "<ts>" '. + {last_thread_ts: $ts}' "$agent_file" > "${agent_file}.tmp" && mv "${agent_file}.tmp" "$agent_file"
```

**For `--thread` (no ID):**

1. Check the identity file for `last_thread_ts`. If found, use it — this is the thread you last interacted with this session.
2. If no `last_thread_ts` exists, fall through to `--thread latest` behavior.

**For `--thread latest`:**

Fetch the last 20 channel messages and find the first one where `reply_count > 0`. Use that message's `ts` as the thread to read. Save it as `last_thread_ts` in the identity file.

## Step 4: Display

Format the results clearly. For each message show:

```
[HH:MM] username: message text
```

- Convert Slack timestamps (Unix epoch) to human-readable local time
- If a message has replies, note: `  ↳ N replies — ts: <thread_ts>`
- Highlight messages addressed to your team (if identity is known) with a `→` prefix

If `--grep` was specified, only show matching messages and note how many were filtered out.

After displaying, summarise:
> "Showing N messages from #ai-dev. Use `/ping` to respond, or `/pong --thread <ts>` to read a thread."
