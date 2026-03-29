# Discord Configuration

All Discord integration in the Claude Code workflow kit reads server-specific
values from a user-scoped configuration file. This allows each team to point
their agents at their own Discord server without modifying source.

## Configuration File

**Location:** `~/.claude/discord.json`

### Schema

```json
{
  "guild_id": "1234567890",
  "token_path": "~/secrets/discord-bot-token",
  "channels": {
    "default":         { "name": "agent-ops",        "id": "1234567890" },
    "roll-call":       { "name": "roll-call",        "id": "1234567890" },
    "wave-status":     { "name": "wave-status",      "id": "1234567890" },
    "remote-sessions": { "name": "remote-sessions",  "id": "1234567890" }
  }
}
```

### Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `guild_id` | string | Yes | Discord server (guild) ID |
| `token_path` | string | No | Path to bot token file (default: `~/secrets/discord-bot-token`) |
| `channels` | object | Yes | Map of channel roles to channel info |
| `channels.<role>.name` | string | Yes | Human-readable channel name (without `#`) |
| `channels.<role>.id` | string | Yes | Discord channel snowflake ID |

### Channel Roles

| Role | Purpose | Used By |
|------|---------|---------|
| `default` | General agent communications | `discord-bot`, `disc` skill |
| `roll-call` | Agent check-in on session start | `disc` skill, `CLAUDE.md` identity |
| `wave-status` | Auto-updating wave execution status | `discord-status-post` |
| `remote-sessions` | AFK session relay threads | `afk-notify` |

## Fallback Chain

Every component reads configuration using a three-level fallback:

1. **Config file** (`~/.claude/discord.json`) -- preferred
2. **Environment variables** -- useful for CI or ephemeral environments
3. **Hardcoded defaults** -- backward compatibility with the Oak and Wave server

### Environment Variables

| Variable | Overrides | Default |
|----------|-----------|---------|
| `DISCORD_GUILD_ID` | `guild_id` | `1486516321385578576` |
| `DISCORD_DEFAULT_CHANNEL` | `channels.default.id` | `1487288523638837268` |
| `DISCORD_ROLL_CALL_CHANNEL` | `channels.roll-call.id` | `1487382005036617851` |
| `DISCORD_WAVE_STATUS_CHANNEL` | `channels.wave-status.id` | `1487386934094462986` |
| `DISCORD_REMOTE_SESSIONS_CHANNEL` | `channels.remote-sessions.id` | `1487462945972682763` |
| `DISCORD_TOKEN_PATH` | `token_path` | `~/secrets/discord-bot-token` |

## Per-User Scoping Strategy

When multiple developers share a single Discord server, consider these
approaches for isolating agent traffic:

### Option A: Per-Team Channel Prefixes

Create team-namespaced channels: `#teamname-agent-ops`,
`#teamname-roll-call`, etc. Each team member's `discord.json` points to
their team's channels. Clean separation but more channels to manage.

### Option B: Shared Channels with Identity-Based Routing

Use the existing `@<dev-team>` and `@<dev-name>` addressing convention.
All agents share the same channels, and the watcher's pre-filtering
ensures each agent only sees messages addressed to it. Already implemented
in `discord-watcher`.

### Option C: Both (Recommended for Larger Teams)

Combine per-team channels for noisy traffic (roll-call, status) with
shared channels for cross-team coordination (agent-ops). This gives clean
separation where it matters while preserving a single place for
team-wide announcements.

Implementation of per-team channel auto-creation is a planned follow-up.
