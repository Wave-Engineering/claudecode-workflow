#!/usr/bin/env bash
# stop.sh - Fires when Claude finishes responding, injects context for next turn

set -uo pipefail

CONTEXT_LIMIT="${CONTEXT_LIMIT:-200000}"
WARN_THRESHOLD="${WARN_THRESHOLD:-70}"
DANGER_THRESHOLD="${DANGER_THRESHOLD:-85}"
CRITICAL_THRESHOLD="${CRITICAL_THRESHOLD:-92}"
CRYSTALLIZE_MODE="${CRYSTALLIZE_MODE:-manual}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude"
LOG_FILE="${STATE_DIR}/crystallizer.log"

source "${LIB_DIR}/context-analyzer.sh" 2>/dev/null || exit 0

INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi

mkdir -p "$STATE_DIR" 2>/dev/null || true
mkdir -p "${STATE_DIR}/context-states" 2>/dev/null || true

ANALYSIS=$(analyze_context "$TRANSCRIPT_PATH" "$CONTEXT_LIMIT" "$WARN_THRESHOLD" "$DANGER_THRESHOLD" "$CRITICAL_THRESHOLD")

if [[ -z "$ANALYSIS" ]]; then
    exit 0
fi

ACTION=$(echo "$ANALYSIS" | jq -r '.action // "none"')
PERCENT=$(echo "$ANALYSIS" | jq -r '.percent // 0')

SHORT_SESSION="${SESSION_ID:0:8}"
echo "[$(date -Iseconds)] [${SHORT_SESSION}] [Stop] Context: ${PERCENT}% Action: ${ACTION}" >> "$LOG_FILE" 2>/dev/null || true

output_context() {
    local context="$1"
    cat << EOF
{
    "hookSpecificOutput": {
        "hookEventName": "Stop",
        "additionalContext": "$context"
    }
}
EOF
}

case "$ACTION" in
    "none")
        exit 0
        ;;
    "warn"|"crystallize"|"critical")
        # Crystallize if needed
        if [[ "$ACTION" != "warn" ]]; then
            STATE_SUBDIR="${STATE_DIR}/context-states"
            CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
            if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
                ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
            fi
        fi
        
        output_context "🚨 CONTEXT AT ${PERCENT}% - State saved. Run /clear soon to avoid auto-compact!"
        exit 0
        ;;
esac

exit 0
