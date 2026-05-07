---
name: wave
description: Show wave-pattern status for the current project via wave_show MCP tool
usage: |
  /wave           Show wave-pattern status for the current project
  /wave status    Same as /wave
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-wave does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-wave
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Wave: Wave-Pattern Status

This skill routes to the `sdlc-server` MCP. All operations are handled by
deterministic MCP tool calls — do NOT implement any logic in this skill file.

## Routing

Parse the user's input and call the corresponding MCP tool:

| User Input | MCP Tool | Arguments |
|------------|----------|-----------|
| `/wave` | `mcp__sdlc-server__wave_show` | `{}` |
| `/wave status` | `mcp__sdlc-server__wave_show` | `{}` |

## Future expansion (out of scope for this skill version)

The following routes are reserved and will be wired in follow-up issues. Do
NOT implement them ahead of spec — they are listed here so users and future
contributors can see the planned shape:

- `/wave health` → `mcp__sdlc-server__wave_health_check`
- `/wave topology` → `mcp__sdlc-server__wave_topology`
- `/wave next` → `mcp__sdlc-server__wave_next_pending`

## Important

- **Do NOT interpret the output** — present the MCP tool's response as-is.
- **Do NOT add commentary, summaries, or rephrasings** — the server returns
  structured status (Project / Phase / Wave / Flight / Action / Progress /
  Deferrals) that the user reads directly.
- **Do NOT call other `wave_*` tools** beyond `wave_show` for `/wave` and
  `/wave status` — additional routes are reserved (see above) but not yet
  wired.
