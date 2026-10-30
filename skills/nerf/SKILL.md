---
name: nerf
description: Context budget system with soft limits, doom modes, and scope monitor
usage: |
  /nerf                          Show status (mode, darts, context usage)
  /nerf status                   Same as /nerf
  /nerf mode                     Show current behavior mode
  /nerf mode <mode>              Set mode: not-too-rough | hurt-me-plenty | ultraviolence
  /nerf darts                    Show current dart thresholds
  /nerf darts <soft> <hard> <o>  Set all three darts, percent of window used (e.g. 51 63 85)
  /nerf <ouch>                   Set ouch dart (percent used), scale soft/hard proportionally
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

**Every routing entry MUST pass `session_id`.** See "Session ID" below.

| User Input | MCP Tool | Arguments |
|------------|----------|-----------|
| `/nerf` | `nerf_status` | `{ "session_id": "<current session ID>" }` |
| `/nerf status` | `nerf_status` | `{ "session_id": "<current session ID>" }` |
| `/nerf mode` | `nerf_mode` | `{ "session_id": "<current session ID>" }` |
| `/nerf mode <mode>` | `nerf_mode` | `{ "mode": "<mode>", "session_id": "<current session ID>" }` |
| `/nerf darts` | `nerf_darts` | `{ "session_id": "<current session ID>" }` |
| `/nerf darts <s> <h> <o>` | `nerf_darts` | `{ "soft": <s>, "hard": <h>, "ouch": <o>, "session_id": "<current session ID>" }` |
| `/nerf <ouch>` | `nerf_budget` | `{ "ouch": <ouch>, "session_id": "<current session ID>" }` |
| `/nerf scope` | `nerf_scope` | `{ "session_id": "<current session ID>" }` |

## Parsing Rules

- **Darts are percentages of the context window used**: integers from 1 to 99, with soft < hard < ouch. They're correct on any window size (200k or 1M). A trailing `%` is allowed and stripped: `85%` → `85`.
- Token counts (`200k`, `150000`) are **not** accepted. The server rejects them. If the user gives one, say that darts are now percentages and ask what percentage they mean. Do not convert it yourself: you don't know the window size.
- A bare number (e.g., `/nerf 85`) routes to `nerf_budget`, not `nerf_darts`.
- Mode names are exact: `not-too-rough`, `hurt-me-plenty`, `ultraviolence`.

## Modes

The mode tells the context reseed gate (`context-reseed-gate.sh`) what to do at the ouch
dart. The gate's threshold is `100 - ouch`, unless `RESEED_CONTEXT_THRESHOLD_PCT` is set.

| mode | at the ouch dart |
|---|---|
| `ultraviolence` (default) | the gate blocks the turn, and the agent runs `/reseed` at once |
| `hurt-me-plenty` | the gate blocks the turn, and the agent asks the user before it reseeds |
| `not-too-rough` | one reminder per session, no block |

The gate reads `mode` and `darts_pct.ouch` from `/tmp/nerf-<session_id>.json`, the file nerf
writes. A missing or unreadable file means `ultraviolence`.

## Session ID (required for all calls)

You MUST pass the real Claude Code session ID on every `nerf_*` call. The MCP
server has a multi-strategy resolver (env var → per-project transcript scan →
md5 fallback), but the explicit override is the only path that's free of
filesystem-state assumptions. Passing `session_id` keeps the skill working
even if the server's heuristic resolver regresses or runs in an environment
where transcript paths differ.

Find the session ID from the transcript path in conversation context. If
not available, omit `session_id` entirely — do NOT attempt to derive it from shell commands
or filesystem reads (`history.jsonl` and similar files are racy across
concurrent CC sessions and would silently feed the wrong UUID). Falling
through to the server's resolver chain is safe; injecting a wrong value
is not.

## Where the context reading comes from

Claude Code gives the window-aware context figure only to the statusline. The
kit's statusline (`config/statusline-command.sh`) persists it for each session
at `~/.claude/state/context/<session_id>.json`, and nerf reads that file. If
there's no reading, it's unreadable, or it's stale, nerf reports **unknown,
with the reason**. The indicator shows `ctx ?`. Pass that reason on to the
user; never present it as a healthy reading.

## Important

- **Do NOT perform arithmetic.** The MCP server handles all calculations.
- **Do NOT read or write config files.** The MCP server manages config state.
- **Do NOT estimate context usage.** The server reads the statusline's persisted reading.
- **Present the MCP tool's response as-is.** It returns pre-formatted output.
