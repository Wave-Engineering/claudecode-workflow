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
            *)                CRYSTALLIZE_MODE="prompt" ;;
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

# Determine response based on action
case "$ACTION" in
    "none")
        # All good, exit silently
        exit 0
        ;;
    
    "warn")
        # Return a warning via additionalContext (message field doesn't work per CC bug)
        cat << EOF
{
    "additionalContext": "⚠️ CONTEXT WARNING: Usage at ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT} tokens). Consider wrapping up current task and crystallizing state soon."
}
EOF
        exit 0
        ;;
    
    "crystallize")
        # Auto-crystallize and respond based on mode
        STATE_SUBDIR="${STATE_DIR}/context-states"
        CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
        
        # Maintain a "latest" symlink for easy access
        if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
            ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        fi
        
        case "$CRYSTALLIZE_MODE" in
            "yolo")
                # YOLO mode: Instruct Claude to clear automatically
                cat << EOF
{
    "additionalContext": "🔶 CONTEXT DANGER: ${PERCENT}% used.\n\n**State crystallized to:** ${CRYSTAL_FILE}\n\n🤖 **AUTO-CLEAR ENGAGED (YOLO MODE)**\n\nI have saved the conversation state. Now executing automatic context clear to avoid lossy auto-compact.\n\n**IMPORTANT: Run /clear now, then read ${CRYSTAL_FILE} to restore context and continue.**"
}
EOF
                ;;
            "prompt")
                # Prompt mode: Ask Claude to present state and get user confirmation
                cat << EOF
{
    "additionalContext": "🔶 CONTEXT DANGER: ${PERCENT}% used.\n\n**State automatically crystallized to:** ${CRYSTAL_FILE}\n\n📋 **PLEASE REVIEW CRYSTALLIZED STATE:**\n\nRead and summarize the contents of \`${CRYSTAL_FILE}\` for the user, then ask:\n\n\"I've saved our conversation state to avoid losing context. Would you like me to run /clear now and resume from the saved state? (yes/no)\"\n\nIf user confirms, run /clear and then read the state file to continue."
}
EOF
                ;;
            *)
                # Manual mode (default): Just warn
                cat << EOF
{
    "additionalContext": "🔶 CONTEXT DANGER: Usage at ${PERCENT}% (${TOTAL}/${CONTEXT_LIMIT} tokens).\n\n**State automatically crystallized to:** ${CRYSTAL_FILE}\n\nRecommended actions:\n1. Complete your current atomic task\n2. Review the crystallized state file\n3. Run /clear to reset context\n4. Resume with fresh context (state file will be loaded)"
}
EOF
                ;;
        esac
        exit 0
        ;;
    
    "critical")
        # Critical - crystallize and respond based on mode
        STATE_SUBDIR="${STATE_DIR}/context-states"
        CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
        
        # Maintain latest symlink
        if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
            ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        fi
        
        case "$CRYSTALLIZE_MODE" in
            "yolo")
                # YOLO mode: Instruct Claude to clear immediately
                cat << EOF
{
    "additionalContext": "🚨 CRITICAL: ${PERCENT}% - AUTO-COMPACT IMMINENT!\n\n**State crystallized to:** ${CRYSTAL_FILE:-FAILED}\n\n🤖 **EMERGENCY AUTO-CLEAR (YOLO MODE)**\n\n**STOP EVERYTHING. Run /clear RIGHT NOW.**\n\nAfter clear, immediately read ${CRYSTAL_FILE} to restore context and continue where we left off."
}
EOF
                ;;
            "prompt")
                # Prompt mode: Urgent request for user confirmation
                cat << EOF
{
    "additionalContext": "🚨 CRITICAL: ${PERCENT}% - AUTO-COMPACT IMMINENT!\n\n**State crystallized to:** ${CRYSTAL_FILE:-FAILED}\n\n⚡ **URGENT: We need to /clear NOW to avoid lossy auto-compact!**\n\nQuickly confirm: Should I run /clear and resume from the saved state? We have seconds, not minutes.\n\n(Responding 'yes' or just pressing enter will proceed with /clear)"
}
EOF
                ;;
            *)
                # Manual mode: Strong warning
                cat << EOF
{
    "additionalContext": "🚨 CRITICAL CONTEXT ALERT: Usage at ${PERCENT}% - AUTO-COMPACT IMMINENT!\n\n**State crystallized to:** ${CRYSTAL_FILE:-FAILED}\n\n⚡ STOP CURRENT WORK and run /clear NOW to avoid lossy auto-compact!\n\nThe crystallized state file contains your conversation context. After /clear, read that file to resume."
}
EOF
                ;;
        esac
        exit 0
        ;;
esac

exit 0
