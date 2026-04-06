# Discord Watcher (Channels)

> Originally lived inline in CLAUDE.md under Session Onboarding. Moved here in
> #276 to reduce per-session context pressure. A follow-up issue will migrate
> this behavior into the `discord-watcher` MCP server's `instructions` block,
> at which point this file can shrink further.

If the session was started with `--channels` (or `--dangerously-load-development-channels`), a Discord watcher channel server pushes notifications when new messages arrive in any Oak and Wave text channel.

## When you receive a `<channel source="discord_watcher">` notification

1. Run `discord-bot read <channel_id> --limit 10` to get the full messages
2. If a message is addressed to you (`@<dev-team>`, `@<dev-name>`, or `@all`), process it and respond via `discord-bot send`
3. If not addressed to you, note it silently — do not act unless the content is clearly relevant to your current work
4. Ignore messages that contain your own signature (e.g., `— **beacon**`) to avoid echo loops — other agents' messages (also from `CC Developer`) should be processed normally

## Discord message format — sign every message

```
Your message content here.

— **<Dev-Name>** <Dev-Avatar> (<Dev-Team>)
```

Example: `— **beacon** 📡 (cc-workflow)`

The signature is used by the watcher to filter your own echoes. Messages without your signature will echo back to you.

## Message addressing convention

| Pattern | Meaning |
|---------|---------|
| `@<dev-team>` (e.g., `@cc-workflow`) | Addressed to a specific agent/project |
| `@<dev-name>` (e.g., `@beacon`) | Addressed to a specific agent by session name |
| `@all` | Addressed to all listening agents |
| No `@` prefix | Dropped by the watcher — agents do not receive unaddressed messages |
| Human Discord user message | Must include `@` addressing to reach agents |

The watcher pre-filters messages: only `@all`, `@<dev-team>`, and `@<dev-name>` notifications are delivered. Set `DISCORD_WATCHER_VERBOSE=1` to bypass filtering and receive all messages.

Voice message attachments are automatically transcribed via Whisper STT and delivered as `[voice memo from <author>: "<text>"]`.
