#!/usr/bin/env bash
# subagent-stop-hook.sh - Monitors subagent context completion
# This hook runs when a subagent finishes its work
# It has access to agent_transcript_path for the subagent's own transcript

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LIB_DIR="${SCRIPT_DIR}/../lib"
STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude"
LOG_FILE="${STATE_DIR}/crystallizer.log"

# Source the analyzer
source "${LIB_DIR}/context-analyzer.sh" 2>/dev/null || exit 0

# Read hook input
INPUT=$(cat)

# SubagentStop receives agent_transcript_path for the subagent's transcript
AGENT_TRANSCRIPT=$(echo "$INPUT" | jq -r '.agent_transcript_path // empty')
AGENT_ID=$(echo "$INPUT" | jq -r '.agent_id // "unknown"')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.agent_type // "unknown"')
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // empty')

# Ensure log directory exists
mkdir -p "$STATE_DIR" 2>/dev/null || true

# If we have the subagent's transcript, analyze it
if [[ -n "$AGENT_TRANSCRIPT" && -f "$AGENT_TRANSCRIPT" ]]; then
    ANALYSIS=$(analyze_context "$AGENT_TRANSCRIPT" 200000 60 75 85)
    PERCENT=$(echo "$ANALYSIS" | jq -r '.percent // 0')
    TOTAL=$(echo "$ANALYSIS" | jq -r '.tokens.total // 0')
    
    SHORT_SESSION="${SESSION_ID:0:8}"
    echo "[$(date -Iseconds)] [${SHORT_SESSION}] [subagent:${AGENT_TYPE}] Final context: ${PERCENT}% (${TOTAL} tokens) Agent: ${AGENT_ID}" >> "$LOG_FILE" 2>/dev/null || true
    
    # If subagent was near its limit, log a note
    if (( $(echo "$PERCENT >= 75" | bc -l 2>/dev/null || echo 0) )); then
        echo "[$(date -Iseconds)] [${SHORT_SESSION}] [subagent:${AGENT_TYPE}] WARNING: Subagent finished at high context (${PERCENT}%)" >> "$LOG_FILE" 2>/dev/null || true
    fi
fi

# SubagentStop hooks don't inject messages into parent context by default
# Just log and exit
exit 0
