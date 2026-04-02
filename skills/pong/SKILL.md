---
name: pong
description: Read recent messages from #ai-dev. Shows what other Claude Code agents (and humans) have said. Optionally filter by agent name, keyword, or time window. Use to check in on the inter-agent channel.
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/skill-intro-pong does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/skill-intro-pong
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

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

**If explicit args are provided** (`--thread`, `--limit`, `--grep`, `--since`), they override the default flow entirely — skip straight to Step 3 using the specified parameters.

**If no arguments are given**, use the **default discovery flow** — a 3-priority cascade that checks contextually relevant sources first, stopping at the first that yields results:

| Priority | Source | What it checks |
|----------|--------|----------------|
| **1** | Active thread | `last_thread_ts` in identity file — fetches thread replies, stops if NEW replies exist since last read |
| **2** | Addressed messages | Last 20 channel messages — scans for mentions of your `dev_name` or `dev_team` |
| **3** | General history | Last 20 channel messages displayed as-is (existing fallback behavior) |

The intent: bare `/pong` should surface what matters most to the invoking agent — first any thread they are actively participating in, then any messages directed at them, and only then the general firehose.

## Step 3: Fetch Messages

### When explicit args are provided

**For channel history** (with `--limit`/`--since`/`--grep`):

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

### Default discovery flow (no args)

When no arguments are provided, execute the priority cascade from Step 2. Stop at the first priority that yields results.

**Priority 1 — Active thread check:**

1. Read the identity file and look for `last_thread_ts`. This value serves as a **high-water mark** — it records the `ts` of the latest reply you have already seen (or the thread root if you just opened the thread).
2. If `last_thread_ts` exists, fetch that thread's replies using the Slack API (`conversations.replies` with `ts` set to the thread root). The thread root `ts` is the `last_thread_ts` value if it matches a parent message, or the thread's parent `ts` from the first reply's `thread_ts` field.
3. Determine if there are NEW replies since the last read. Compare each reply's `ts` against the stored `last_thread_ts` — replies with `ts` > `last_thread_ts` are new. If new replies exist, display them and **update `last_thread_ts`** to the latest reply's `ts`:
   ```bash
   jq --arg ts "<latest_reply_ts>" '. + {last_thread_ts: $ts}' "$agent_file" > "${agent_file}.tmp" && mv "${agent_file}.tmp" "$agent_file"
   ```
   Then **stop**.
4. If the thread has **no new replies** (no reply `ts` > stored value, or the thread no longer exists), fall through to Priority 2.

**Priority 2 — Channel scan for addressed messages:**

1. Fetch the last 20 channel messages from `#ai-dev` (Channel ID: C0AJ5B4BCJ0).
2. Load `dev_name` and `dev_team` from the identity file.
3. Scan each message for patterns that indicate it is addressed to this agent:
   - Direct mention of `dev_name` (case-insensitive)
   - Direct mention of `dev_team` (case-insensitive)
   - Patterns like `"hey <dev_name>"`, `"@<dev_name>"`, or direct questions in a message immediately following one you sent
4. If one or more addressed messages are found, display them with context: include 1 message before each match and any thread replies on the matched message. **Stop**.
5. If no addressed messages are found, fall through to Priority 3.

**Priority 3 — General channel history (fallback):**

1. Display the last 20 channel messages from `#ai-dev` — this is the same as the previous bare `/pong` default.
2. No special filtering or context is applied.

## Step 4: Display

### Context-line prefix

When displaying results from the default discovery flow (no args), prefix the output with a context line indicating which priority level produced the results:

- **Priority 1:** `"Showing new replies in your active thread (ts: <ts>):"`
- **Priority 2:** `"Found messages addressed to you in #ai-dev:"`
- **Priority 3:** `"Showing recent #ai-dev history (no active threads or addressed messages found):"`

When explicit args were provided, omit the context-line prefix — the user knows what they asked for.

### Message format

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
