---
name: nerf
description: Context budget system with soft limits, doom modes, and scope monitor
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
     Do this BEFORE executing any skill logic below. -->

# Nerf: Context Budget Control

Enforce a configurable soft context limit on the 1M window. Defaults to a 200k
budget with three escalating thresholds ("darts") and Doom-inspired behavior
modes.

## Subcommands

| Command | Behavior |
|---------|----------|
| `/nerf` | Alias for `/nerf status` |
| `/nerf status` | Display current mode, dart positions, and context usage |
| `/nerf mode` | Echo current mode |
| `/nerf mode <mode>` | Set behavior mode (see Doom modes below) |
| `/nerf darts` | Echo current dart thresholds |
| `/nerf darts <soft> <hard> <ouch>` | Set all three dart thresholds (absolute values, e.g., `150k 180k 200k`) |
| `/nerf <limit>` | Set ouch dart and scale soft/hard proportionally (e.g., `/nerf 200k`) |
| `/nerf scope` | Spawn `cc-context watch` in a new terminal window, session-aware |

## Doom Difficulty Modes

Three behavior modes, escalating in cold brutality:

| Mode | Doom Reference | Behavior |
|------|----------------|----------|
| `not-too-rough` | E1 | Warn only -- you see the warnings, you decide what to do |
| `hurt-me-plenty` | E3 (DEFAULT) | Auto-crystallize state at `hard` dart, ask before `/compact` |
| `ultraviolence` | E4 | Auto-crystallize, auto-compact -- no questions asked |

Mode mapping to existing `CRYSTALLIZE_MODE` values:
- `not-too-rough` -> `manual`
- `hurt-me-plenty` -> `prompt`
- `ultraviolence` -> `yolo`

## Nerf Darts (Thresholds)

Three named thresholds, expressed as absolute token counts:

| Dart | Meaning | Default |
|------|---------|---------|
| **soft** | Warning -- heads up, you're getting there | 150k |
| **hard** | Crystallize -- save state now | 180k |
| **ouch** | Critical -- compact or die | 200k |

These map to the existing crystallizer thresholds:
- `soft` -> `WARN_THRESHOLD`
- `hard` -> `DANGER_THRESHOLD`
- `ouch` -> `CRITICAL_THRESHOLD`

### Scaling shortcut

`/nerf <limit>` sets the ouch dart and scales the others proportionally:
- **soft** = 75% of ouch
- **hard** = 90% of ouch

Example: `/nerf 500k` sets soft=375k, hard=450k, ouch=500k.

## Session Config

Config is stored per-session at `/tmp/nerf-<session_id>.json`:

```json
{
  "mode": "hurt-me-plenty",
  "darts": {
    "soft": 150000,
    "hard": 180000,
    "ouch": 200000
  },
  "session_id": "<session_id>"
}
```

The `session_id` is extracted from the current session context (it appears in
output file paths and transcript paths).

## Execution

### `/nerf` or `/nerf status`

1. Read the session nerf config (or show defaults if none exists)
2. Get current context usage from the transcript (use `context-analyzer.sh` logic)
3. Display:

```
Nerf Status
  Mode:    hurt-me-plenty (auto-crystallize + ask)
  Budget:  200k tokens (real window: 1M)

  Darts:
    soft   150k  ---- warning
    hard   180k  ---- crystallize
    ouch   200k  ---- compact or die

  Current: 87k tokens (43%)
```

### `/nerf mode`

Without argument: echo the current mode name and its behavior.

### `/nerf mode <mode>`

1. Validate mode is one of: `not-too-rough`, `hurt-me-plenty`, `ultraviolence`
2. Write to session config
3. Confirm: `Mode set to <mode> (<behavior description>)`

### `/nerf darts`

Without arguments: echo current dart positions.

### `/nerf darts <soft> <hard> <ouch>`

1. Parse values (accept `150k` or `150000` format)
2. Validate: soft < hard < ouch
3. Write to session config
4. Confirm with new positions

### `/nerf <limit>`

1. Parse the limit value (e.g., `200k` -> 200000)
2. Compute: soft = limit * 0.75, hard = limit * 0.90, ouch = limit
3. Write to session config
4. Confirm with new dart positions

### `/nerf scope`

1. Determine the current `session_id` from context
2. Detect terminal emulator via `$TERM_PROGRAM`
3. Spawn `cc-context watch --session <session_id>` in a new terminal:

```bash
case "$TERM_PROGRAM" in
    ghostty)    ghostty -e cc-context watch --session "$SESSION_ID" ;;
    alacritty)  alacritty -e cc-context watch --session "$SESSION_ID" ;;
    kitty)      kitty cc-context watch --session "$SESSION_ID" ;;
    *)          x-terminal-emulator -e cc-context watch --session "$SESSION_ID" ;;
esac
```

4. Report: `Scope monitor launched in <terminal> for session <short_id>`

## Dependencies

- `~/.claude/context-crystallizer/hooks/post-tool-use.sh` -- reads nerf config
- `~/.claude/context-crystallizer/bin/cc-context` -- `--session` flag + nerf display
- `~/.claude/context-crystallizer/lib/context-analyzer.sh` -- token counting
