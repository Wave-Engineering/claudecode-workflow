---
name: nerf
description: Context budget system with soft limits, doom modes, and scope monitor
usage: |
  /nerf                          Show status (mode, darts, context usage)
  /nerf status                   Same as /nerf
  /nerf mode                     Show current behavior mode
  /nerf mode <mode>              Set mode: not-too-rough | hurt-me-plenty | ultraviolence
  /nerf darts                    Show current dart thresholds
  /nerf darts <soft> <hard> <o>  Set all three dart thresholds (e.g. 150k 180k 200k)
  /nerf <limit>                  Set ouch dart, scale soft/hard proportionally
  /nerf scope                    Launch context monitor in new terminal
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-nerf does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-nerf
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Nerf: Context Budget Control

This skill routes to the `nerf-server` MCP. All operations are handled by
deterministic MCP tool calls — do NOT implement any logic in this skill file.

## Routing

Parse the user's input and call the corresponding MCP tool:

| User Input | MCP Tool | Arguments |
|------------|----------|-----------|
| `/nerf` | `nerf_status` | *(none)* |
| `/nerf status` | `nerf_status` | *(none)* |
| `/nerf mode` | `nerf_mode` | *(none — returns current)* |
| `/nerf mode <mode>` | `nerf_mode` | `{ "mode": "<mode>" }` |
| `/nerf darts` | `nerf_darts` | *(none — returns current)* |
| `/nerf darts <s> <h> <o>` | `nerf_darts` | `{ "soft": <s>, "hard": <h>, "ouch": <o> }` |
| `/nerf <limit>` | `nerf_budget` | `{ "ouch": <limit> }` |
| `/nerf scope` | `nerf_scope` | *(none)* |

## Parsing Rules

- Accept `k` suffix: `200k` → `200000`, `1.5m` → `1500000`
- A bare number (e.g., `/nerf 200k`) routes to `nerf_budget`, not `nerf_darts`
- Mode names are exact: `not-too-rough`, `hurt-me-plenty`, `ultraviolence`

## Important

- **Do NOT perform arithmetic** — the MCP server handles all calculations
- **Do NOT read or write config files** — the MCP server manages config state
- **Do NOT estimate context usage** — the MCP server shells out to the analyzer
- **Present the MCP tool's response as-is** — it returns pre-formatted output
