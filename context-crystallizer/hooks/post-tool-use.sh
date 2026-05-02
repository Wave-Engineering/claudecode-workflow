#!/usr/bin/env bash
# post-tool-use-hook.sh - Monitors context and triggers crystallization
# This hook runs after every tool use and checks context utilization
#
# Edge cases handled:
# - Multiple CC instances: Each gets correct transcript_path, state files include session ID
# - Subagents: Detected via path pattern, monitored but don't trigger parent crystallization
#
# Modes (set via CRYSTALLIZE_MODE env var):
# - manual:  Warn only, human decides everything (default)
# - prompt:  Crystallize + ask Claude to present state and request user confirmation for /clear
# - yolo:    Crystallize + instruct Claude to run /clear automatically

set -uo pipefail

# ---------------------------------------------------------------------------
# Nerf config: session-scoped overrides for thresholds and mode
# ---------------------------------------------------------------------------
# If a nerf config exists for this session, read darts + mode from it.
# Otherwise fall back to env vars / hardcoded defaults.
#
# The nerf config is written by the /nerf skill at:
#   /tmp/nerf-<session_id>.json
#
# Format:
#   { "mode": "hurt-me-plenty",
#     "darts": { "soft": 150000, "hard": 180000, "ouch": 200000 },
#     "session_id": "<id>" }
# ---------------------------------------------------------------------------

# Real context window — always 1M for Opus on the current plan
REAL_CONTEXT_WINDOW="${REAL_CONTEXT_WINDOW:-1000000}"

# Start with hardcoded defaults (overridden below if nerf config exists)
_NERF_SOFT=150000
_NERF_HARD=180000
_NERF_OUCH=200000
_NERF_MODE="hurt-me-plenty"

# Configuration - adjust these thresholds as needed
# CONTEXT_LIMIT is set to the nerf'd budget (ouch dart), NOT the real window
CONTEXT_LIMIT="${CONTEXT_LIMIT:-200000}"
WARN_THRESHOLD="${WARN_THRESHOLD:-60}"
DANGER_THRESHOLD="${DANGER_THRESHOLD:-75}"
CRITICAL_THRESHOLD="${CRITICAL_THRESHOLD:-85}"

# Crystallization mode: manual, prompt, or yolo
CRYSTALLIZE_MODE="${CRYSTALLIZE_MODE:-manual}"

# Subagent thresholds (they have smaller context typically)
SUBAGENT_WARN="${SUBAGENT_WARN:-60}"
SUBAGENT_DANGER="${SUBAGENT_DANGER:-75}"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude"
LOG_FILE="${STATE_DIR}/crystallizer.log"

# Source libraries
source "${LIB_DIR}/context-analyzer.sh" 2>/dev/null || {
    # Fallback if not installed in expected location
    source "$(dirname "$0")/../lib/context-analyzer.sh" 2>/dev/null || {
        echo '{"error": "could not load context-analyzer.sh"}' >&2
        exit 0  # Don't block on library errors
    }
}

# Read hook input from stdin
INPUT=$(cat)

# Extract transcript path and session ID from hook input
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
    # No transcript available, exit silently
    exit 0
fi

# ---------------------------------------------------------------------------
# Read session nerf config (if it exists)
# ---------------------------------------------------------------------------
if [[ -n "$SESSION_ID" ]]; then
    NERF_CONFIG="/tmp/nerf-${SESSION_ID}.json"
    if [[ -f "$NERF_CONFIG" ]]; then
        # Read darts
        _NERF_SOFT=$(jq -r '.darts.soft // 150000' "$NERF_CONFIG" 2>/dev/null || echo 150000)
        _NERF_HARD=$(jq -r '.darts.hard // 180000' "$NERF_CONFIG" 2>/dev/null || echo 180000)
        _NERF_OUCH=$(jq -r '.darts.ouch // 200000' "$NERF_CONFIG" 2>/dev/null || echo 200000)

        # Read mode and map to CRYSTALLIZE_MODE
        _NERF_MODE=$(jq -r '.mode // "hurt-me-plenty"' "$NERF_CONFIG" 2>/dev/null || echo "hurt-me-plenty")
        case "$_NERF_MODE" in
            "not-too-rough") CRYSTALLIZE_MODE="manual" ;;
            "hurt-me-plenty") CRYSTALLIZE_MODE="prompt" ;;
            "ultraviolence")  CRYSTALLIZE_MODE="yolo" ;;
            *)
                echo "[$(date -Iseconds)] [crystallizer-hook] WARN: unrecognized nerf mode '$_NERF_MODE' — defaulting to hurt-me-plenty behavior" >&2
                CRYSTALLIZE_MODE="prompt"
                ;;
        esac

        # Convert absolute darts to percentage thresholds of the real window
        # The crystallizer uses percentages: (dart / context_limit) * 100
        # We set CONTEXT_LIMIT to the ouch dart so percentages align
        CONTEXT_LIMIT="$_NERF_OUCH"
        if [[ "$_NERF_OUCH" -gt 0 ]]; then
            WARN_THRESHOLD=$(echo "scale=0; ($_NERF_SOFT * 100) / $_NERF_OUCH" | bc 2>/dev/null || echo 70)
            DANGER_THRESHOLD=$(echo "scale=0; ($_NERF_HARD * 100) / $_NERF_OUCH" | bc 2>/dev/null || echo 85)
            CRITICAL_THRESHOLD=85  # Trigger critical with margin for 200k windows
        fi
    fi
fi

# Detect if this is a subagent by checking the path
IS_SUBAGENT=false
if [[ "$TRANSCRIPT_PATH" == *"/subagents/"* ]]; then
    IS_SUBAGENT=true
    # Use lower thresholds for subagents
    WARN_THRESHOLD="$SUBAGENT_WARN"
    DANGER_THRESHOLD="$SUBAGENT_DANGER"
fi

# Ensure state directory exists
mkdir -p "$STATE_DIR" 2>/dev/null || true
mkdir -p "${STATE_DIR}/context-states" 2>/dev/null || true

# Analyze context
ANALYSIS=$(analyze_context "$TRANSCRIPT_PATH" "$CONTEXT_LIMIT" "$WARN_THRESHOLD" "$DANGER_THRESHOLD" "$CRITICAL_THRESHOLD")

if [[ -z "$ANALYSIS" ]]; then
    exit 0
fi

ACTION=$(echo "$ANALYSIS" | jq -r '.action // "none"')
PERCENT=$(echo "$ANALYSIS" | jq -r '.percent // 0')
TOTAL=$(echo "$ANALYSIS" | jq -r '.tokens.total // 0')

# Log the check (include session ID for multi-instance debugging)
SHORT_SESSION="${SESSION_ID:0:8}"
AGENT_TYPE="main"
[[ "$IS_SUBAGENT" == "true" ]] && AGENT_TYPE="subagent"
echo "[$(date -Iseconds)] [${SHORT_SESSION}] [${AGENT_TYPE}] Context: ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}) Action: ${ACTION}" >> "$LOG_FILE" 2>/dev/null || true

# For subagents, only warn - don't crystallize parent state
if [[ "$IS_SUBAGENT" == "true" ]]; then
    case "$ACTION" in
        "warn"|"crystallize"|"critical")
            cat << EOF
{
    "additionalContext": "⚠️ SUBAGENT CONTEXT: ${PERCENT}% used. Subagent approaching context limit - consider completing this task soon."
}
EOF
            ;;
    esac
    exit 0
fi

# ---------------------------------------------------------------------------
# Zone classification + per-crossing debounce
# ---------------------------------------------------------------------------
# Map ACTION to a dart zone. The in-chat message fires only on zone transitions,
# so the agent sees one message per crossing rather than one per tool call.
# Downward crossings (after /compact) update the tracked zone so a subsequent
# climb re-announces.
#
# ultraviolence wants re-fires on every crossing; that's achieved naturally —
# a /compact drops the zone back to "none", then climbing re-triggers the
# transition detection.
# ---------------------------------------------------------------------------
case "$ACTION" in
    "warn")        CURRENT_ZONE="soft" ;;
    "crystallize") CURRENT_ZONE="hard" ;;
    "critical")    CURRENT_ZONE="critical" ;;
    *)             CURRENT_ZONE="none" ;;
esac

# Key by session_id; fall back to a hash of the transcript path so concurrent
# sessions without a session_id don't share state.
_CROSSING_KEY="${SESSION_ID:-$(echo "$TRANSCRIPT_PATH" | md5sum | cut -c1-8)}"
CROSSING_FILE="/tmp/nerf-crossing-${_CROSSING_KEY}.json"

LAST_ZONE="none"
if [[ -f "$CROSSING_FILE" ]]; then
    LAST_ZONE=$(jq -r '.last_zone // "none"' "$CROSSING_FILE" 2>/dev/null || echo "none")
fi

SHOULD_ANNOUNCE=false
if [[ "$CURRENT_ZONE" != "$LAST_ZONE" ]]; then
    SHOULD_ANNOUNCE=true
    # Update the crossing-state file atomically (temp file + rename) so
    # concurrent hook invocations don't tear each other's writes.
    _CROSSING_TMP="${CROSSING_FILE}.tmp.$$"
    if echo "{\"last_zone\":\"${CURRENT_ZONE}\"}" > "$_CROSSING_TMP" 2>/dev/null; then
        mv -f "$_CROSSING_TMP" "$CROSSING_FILE" 2>/dev/null || rm -f "$_CROSSING_TMP" 2>/dev/null
    fi
fi

# not-too-rough mode silences all in-chat messages; crystallization still runs.
if [[ "$_NERF_MODE" == "not-too-rough" ]]; then
    SHOULD_ANNOUNCE=false
fi

# ---------------------------------------------------------------------------
# Per-session cooldown: prevent calling crystallizer.sh on every tool use
# once the threshold is crossed. The warning still fires every call; only
# the expensive crystallizer.sh subprocess is rate-limited.
#
# Cooldown is keyed by session ID so concurrent sessions don't interfere.
# Tunable via CRYSTALLIZER_COOLDOWN_MINUTES (default: 10).
# ---------------------------------------------------------------------------
CRYSTALLIZER_COOLDOWN_MINUTES="${CRYSTALLIZER_COOLDOWN_MINUTES:-10}"
# Key by session_id; fall back to a hash of the transcript path so concurrent
# sessions without a session_id don't share one cooldown file.
_COOLDOWN_KEY="${SESSION_ID:-$(echo "$TRANSCRIPT_PATH" | md5sum | cut -c1-8)}"
COOLDOWN_FILE="/tmp/crystallizer-cooldown-${_COOLDOWN_KEY}"

_is_cooling_down() {
    if [[ -f "$COOLDOWN_FILE" ]]; then
        local last_run now elapsed
        last_run=$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)
        now=$(date +%s)
        elapsed=$(( now - last_run ))
        if [[ $elapsed -lt $(( CRYSTALLIZER_COOLDOWN_MINUTES * 60 )) ]]; then
            return 0  # still cooling down
        fi
    fi
    return 1  # cooldown expired or no stamp
}

_stamp_cooldown() {
    date +%s > "$COOLDOWN_FILE" 2>/dev/null || true
}

# Run crystallizer.sh, maintain latest symlink, stamp cooldown.
# Sets CRYSTAL_FILE in caller scope.
_run_crystallizer() {
    local state_subdir="${STATE_DIR}/context-states"
    CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$state_subdir" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
    if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
        ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        _stamp_cooldown
    fi
}

# Determine response based on action
case "$ACTION" in
    "none")
        # All good, exit silently
        exit 0
        ;;

    "warn")
        # Soft dart crossed. Message only on transition; silent in not-too-rough.
        if [[ "$SHOULD_ANNOUNCE" == "true" ]]; then
            case "$_NERF_MODE" in
                "ultraviolence")
                    cat << EOF
{
    "additionalContext": "⚠ ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}). Rip and tear — but also /compact. Do it at your next tool break."
}
EOF
                    ;;
                *)  # hurt-me-plenty (default)
                    cat << EOF
{
    "additionalContext": "⚠ Context at ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}). The Imps are stirring. Consider /compact at your next natural break."
}
EOF
                    ;;
            esac
        fi
        exit 0
        ;;

    "crystallize")
        # Hard dart crossed. Run crystallization if cooldown allows (independent
        # of mode — even not-too-rough gets automatic crystallization). Emit an
        # in-chat message only on zone transition and only if mode warrants it.
        if ! _is_cooling_down; then
            CRYSTAL_FILE=""
            _run_crystallizer
        fi

        if [[ "$SHOULD_ANNOUNCE" == "true" ]]; then
            case "$_NERF_MODE" in
                "ultraviolence")
                    cat << EOF
{
    "additionalContext": "⚠⚠ ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}). /compact NOW. Hold the line no longer."
}
EOF
                    ;;
                *)  # hurt-me-plenty (default)
                    cat << EOF
{
    "additionalContext": "⚠⚠ Context at ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}). Cacodemon sighted. Strongly recommend /compact — don't let the session rot."
}
EOF
                    ;;
            esac
        fi
        exit 0
        ;;

    "critical")
        # Ouch dart crossed — auto-compact imminent. Run crystallization
        # regardless of mode (safety net); in-chat message only on transition
        # and only if mode warrants it.
        if ! _is_cooling_down; then
            CRYSTAL_FILE=""
            _run_crystallizer
        fi

        if [[ "$SHOULD_ANNOUNCE" == "true" ]]; then
            case "$_NERF_MODE" in
                "ultraviolence")
                    cat << EOF
{
    "additionalContext": "⚠⚠⚠ ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}). /compact THIS TURN. No excuses, no deferrals, no \"just one more thing.\" The session ends now or it ends worse later."
}
EOF
                    ;;
                *)  # hurt-me-plenty (default)
                    cat << EOF
{
    "additionalContext": "⚠⚠⚠ Context at ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT}). Cyberdemon in the corridor. /compact immediately. The auto-compact is merciless."
}
EOF
                    ;;
            esac
        fi
        exit 0
        ;;
esac

exit 0
