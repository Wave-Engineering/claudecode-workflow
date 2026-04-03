#!/usr/bin/env bash
# session-start-hook.sh - Loads crystallized state when starting a new session
# Output from this hook gets injected into Claude's context

set -uo pipefail

STATE_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude"
STATES_SUBDIR="${STATE_DIR}/context-states"
LOG_FILE="${STATE_DIR}/crystallizer.log"

# Find the most recent state file
# Check both the legacy location and the new timestamped directory
STATE_FILE=""

if [[ -d "$STATES_SUBDIR" ]]; then
    # Find newest file in context-states directory
    STATE_FILE=$(find "$STATES_SUBDIR" -name "context-state-*.md" -type f 2>/dev/null | sort -r | head -1)
fi

# Fallback to legacy location
if [[ -z "$STATE_FILE" || ! -f "$STATE_FILE" ]] && [[ -f "${STATE_DIR}/context-state.md" ]]; then
    STATE_FILE="${STATE_DIR}/context-state.md"
fi

# Check if we have a crystallized state to restore
if [[ -n "$STATE_FILE" && -f "$STATE_FILE" ]]; then
    # Check how old the state file is
    if [[ "$(uname)" == "Darwin" ]]; then
        FILE_AGE=$(( $(date +%s) - $(stat -f %m "$STATE_FILE") ))
    else
        FILE_AGE=$(( $(date +%s) - $(stat -c %Y "$STATE_FILE") ))
    fi
    
    # Only load if less than 24 hours old
    if [[ $FILE_AGE -lt 86400 ]]; then
        echo "📋 **RESTORED CONTEXT STATE** (crystallized $(( FILE_AGE / 60 )) minutes ago)"
        echo ""
        echo "The following state was preserved from a previous session:"
        echo ""
        echo '```markdown'
        cat "$STATE_FILE"
        echo '```'
        echo ""
        echo "---"
        echo "Review the above context and continue where we left off. Ask the user for clarification if needed."
        echo ""
        
        # Log the restoration
        echo "[$(date -Iseconds)] Restored crystallized state (age: ${FILE_AGE}s)" >> "$LOG_FILE" 2>/dev/null || true
    else
        # State is old, just note it exists
        echo "ℹ️ Note: Old context state exists at ${STATE_FILE} ($(( FILE_AGE / 3600 )) hours old)"
        echo ""
    fi
fi

exit 0
