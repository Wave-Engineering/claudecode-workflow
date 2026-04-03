#!/usr/bin/env bash
# pre-tool-use-blocking.sh - BLOCKS tool execution at critical context levels
# Uses exit code 2 + stderr which DOES get shown to Claude
#
# This is aggressive - it will prevent Claude from using tools until context is cleared!

set -uo pipefail

CONTEXT_LIMIT="${CONTEXT_LIMIT:-200000}"
WARN_THRESHOLD="${WARN_THRESHOLD:-70}"
DANGER_THRESHOLD="${DANGER_THRESHOLD:-85}"
CRITICAL_THRESHOLD="${CRITICAL_THRESHOLD:-92}"

# Only block at critical? Set to "true" to allow tools at danger level
BLOCK_ONLY_CRITICAL="${BLOCK_ONLY_CRITICAL:-false}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude"
LOG_FILE="${STATE_DIR}/crystallizer.log"

source "${LIB_DIR}/context-analyzer.sh" 2>/dev/null || exit 0

INPUT=$(cat)
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.transcript_path // empty')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
    exit 0
fi

# Skip blocking for Read operations - let Claude read the state file!
if [[ "$TOOL_NAME" == "Read" ]]; then
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
TOTAL=$(echo "$ANALYSIS" | jq -r '.tokens.total // 0')

SHORT_SESSION="${SESSION_ID:0:8}"
echo "[$(date -Iseconds)] [${SHORT_SESSION}] [PreToolUse:${TOOL_NAME}:BLOCKING] Context: ${PERCENT}% Action: ${ACTION}" >> "$LOG_FILE" 2>/dev/null || true

case "$ACTION" in
    "none"|"warn")
        # Allow tool to proceed
        exit 0
        ;;
    
    "crystallize")
        if [[ "$BLOCK_ONLY_CRITICAL" == "true" ]]; then
            exit 0
        fi
        
        # Crystallize state
        STATE_SUBDIR="${STATE_DIR}/context-states"
        CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
        
        if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
            ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        fi
        
        # BLOCK with exit 2 - stderr goes to Claude!
        echo "🔶 CONTEXT DANGER: ${PERCENT}% (${TOTAL} tokens)

Tool execution BLOCKED to prevent context overflow.

State has been saved to: ${CRYSTAL_FILE:-${STATE_DIR}/context-state.md}

To continue:
1. Run /clear to reset context
2. Then read ${STATE_DIR}/context-state.md to restore where we left off

This block will lift after /clear." >&2
        exit 2
        ;;
    
    "critical")
        # Crystallize state urgently
        STATE_SUBDIR="${STATE_DIR}/context-states"
        CRYSTAL_FILE=$("${LIB_DIR}/crystallizer.sh" "$TRANSCRIPT_PATH" "$STATE_SUBDIR" "${CLAUDE_PROJECT_DIR:-.}" "$SESSION_ID" 2>/dev/null || echo "")
        
        if [[ -n "$CRYSTAL_FILE" && -f "$CRYSTAL_FILE" ]]; then
            ln -sf "$CRYSTAL_FILE" "${STATE_DIR}/context-state.md" 2>/dev/null || true
        fi
        
        # BLOCK with exit 2
        echo "🚨 CRITICAL: ${PERCENT}% - AUTO-COMPACT IMMINENT!

Tool execution BLOCKED - context overflow imminent!

State saved to: ${CRYSTAL_FILE:-${STATE_DIR}/context-state.md}

⚡ IMMEDIATE ACTION REQUIRED:
1. Run /clear RIGHT NOW
2. Read ${STATE_DIR}/context-state.md to continue

DO NOT attempt other operations - only /clear will work." >&2
        exit 2
        ;;
esac

exit 0
