#!/usr/bin/env bash
# pre-tool-use.sh - Monitors context and injects warnings BEFORE tool execution
# Uses hookSpecificOutput.additionalContext format that actually works with PreToolUse

set -uo pipefail

# Configuration
CONTEXT_LIMIT="${CONTEXT_LIMIT:-200000}"
WARN_THRESHOLD="${WARN_THRESHOLD:-70}"
DANGER_THRESHOLD="${DANGER_THRESHOLD:-85}"
CRITICAL_THRESHOLD="${CRITICAL_THRESHOLD:-92}"
CRYSTALLIZE_MODE="${CRYSTALLIZE_MODE:-manual}"

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude"
LOG_FILE="${STATE_DIR}/crystallizer.log"

# Source analyzer
source "${LIB_DIR}/context-analyzer.sh" 2>/dev/null || exit 0

# Read hook input
INPUT=$(cat)

TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi

# Skip if this is a subagent
if [[ "$TRANSCRIPT_PATH" == *"/subagents/"* ]]; then
    exit 0
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

# Log
SHORT_SESSION="${SESSION_ID:0:8}"
echo "[$(date -Iseconds)] [${SHORT_SESSION}] [PreToolUse:${TOOL_NAME}] Context: ${PERCENT}% Action: ${ACTION}" >> "$LOG_FILE" 2>/dev/null || true

# Helper function to output with proper hookSpecificOutput format
output_context() {
    local context="$1"
    cat << EOF
{
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": "$context"
    }
}
EOF
}

case "$ACTION" in
    "none")
        exit 0
        ;;
    
    "warn")
        output_context "⚠️ CONTEXT WARNING: ${PERCENT}% used (${TOTAL}/${CONTEXT_LIMIT} tokens). Consider wrapping up current task soon."
        exit 0
        ;;
    
    "crystallize")
        # Crystallize state
        STATE_SUBDIR="${STATE_DIR}/context-states"
        CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
        
        if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
            ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        fi
        
        case "$CRYSTALLIZE_MODE" in
            "yolo")
                output_context "🔶 CONTEXT DANGER: ${PERCENT}% used. State saved to ${CRYSTAL_FILE}. AUTO-CLEAR ENGAGED - Run /clear NOW, then read the state file to continue."
                ;;
            "prompt")
                output_context "🔶 CONTEXT DANGER: ${PERCENT}% used. State saved to ${CRYSTAL_FILE}. Please summarize the state file for the user and ask if they want to /clear now."
                ;;
            *)
                output_context "🔶 CONTEXT DANGER: ${PERCENT}% used. State crystallized to ${CRYSTAL_FILE}. Recommend completing current task, then /clear and resume from state file."
                ;;
        esac
        exit 0
        ;;
    
    "critical")
        # Crystallize state urgently
        STATE_SUBDIR="${STATE_DIR}/context-states"
        CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
        
        if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
            ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        fi
        
        output_context "🚨 CRITICAL: ${PERCENT}% - AUTO-COMPACT IMMINENT! State saved to ${CRYSTAL_FILE:-FAILED}. STOP and run /clear NOW to avoid losing context!"
        exit 0
        ;;
esac

exit 0
