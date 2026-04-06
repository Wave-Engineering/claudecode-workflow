#!/usr/bin/env bash
# crystallizer.sh - Extracts critical state from transcript and saves to file
# This is the heart of the context preservation system

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

crystallize() {
    local TRANSCRIPT="$1"
    local OUTPUT_DIR="${2:-.claude}"
    local PROJECT_DIR="${3:-$(pwd)}"
    local SESSION_ID="${4:-}"
    
    # Generate unique filename with timestamp and session
    local TIMESTAMP=$(date +%Y%m%d-%H%M%S)
    local SHORT_SESSION="${SESSION_ID:0:8}"
    local FILENAME="context-state"
    
    if [[ -n "$SHORT_SESSION" ]]; then
        FILENAME="context-state-${TIMESTAMP}-${SHORT_SESSION}.md"
    else
        FILENAME="context-state-${TIMESTAMP}.md"
    fi
    
    local OUTPUT_FILE="${OUTPUT_DIR}/${FILENAME}"
    local TIMESTAMP_ISO=$(date -Iseconds)
    local FULL_SESSION_ID="${SESSION_ID:-$(basename "$TRANSCRIPT" .jsonl)}"
    
    # Create output directory if needed
    mkdir -p "$OUTPUT_DIR"
    
    # Extract recent conversation context
    # Get last 50 user messages and assistant responses
    local USER_MESSAGES ASSISTANT_MESSAGES TOOL_USES FILES_MODIFIED
    
    # Recent user prompts (last 10)
    #
    # In Claude Code's transcript format, "user"-type entries carry three
    # different content shapes:
    #   1. A plain string       — an actual user prompt (or slash-command
    #                              invocation, Discord watcher notification,
    #                              compaction continuation header)
    #   2. An array of text blocks — a skill invocation body (e.g., /precheck
    #                              loads the SKILL.md body into a "user" turn)
    #   3. An array of tool_result blocks — a tool response
    #
    # Only shape (1) is an actual user instruction. Filtering on
    # `.type == "text"` inside the array incorrectly captures skill bodies as
    # "user messages", polluting the Recent User Instructions section with
    # kilobytes of skill documentation. Restrict to plain strings.
    #
    # Windowing is done with jq slurp mode (`-s`) + array slicing rather than
    # `tail -N | head -N` on jq's text output. Line-based windowing produces
    # garbage when a single user message spans multiple lines (either empty
    # output, or a mid-message fragment), because it has no record-boundary
    # semantics. Slurp + slice operates on whole records.
    USER_MESSAGES=$(tail -500 "$TRANSCRIPT" | \
        jq -rs 'map(select(.type == "user" and .message.content) |
                    select((.message.content | type) == "string") |
                    .message.content) |
                .[-10:] |
                map("- " + (gsub("\n"; "\n  "))) |
                join("\n\n")' 2>/dev/null)
    
    # Recent assistant responses (summaries)
    ASSISTANT_MESSAGES=$(tail -500 "$TRANSCRIPT" | \
        jq -r 'select(.type == "assistant" and .message.content) |
               .message.content |
               if type == "array" then
                   map(select(.type == "text") | .text) | join("\n")
               elif type == "string" then .
               else empty end' 2>/dev/null | \
        tail -30 | head -15)
    
    # Files that were modified (from tool uses)
    FILES_MODIFIED=$(tail -1000 "$TRANSCRIPT" | \
        jq -r 'select(.type == "assistant") |
               .message.content[]? |
               select(.type == "tool_use") |
               select(.name == "Write" or .name == "Edit" or .name == "MultiEdit") |
               .input.file_path // .input.filePath // empty' 2>/dev/null | \
        sort -u | tail -20)
    
    # Recent tool operations
    TOOL_USES=$(tail -500 "$TRANSCRIPT" | \
        jq -r 'select(.type == "assistant") |
               .message.content[]? |
               select(.type == "tool_use") |
               "\(.name): \(.input | keys | join(", "))"' 2>/dev/null | \
        tail -15)
    
    # Get current git branch if in a repo
    local GIT_BRANCH=""
    if git rev-parse --git-dir > /dev/null 2>&1; then
        GIT_BRANCH=$(git branch --show-current 2>/dev/null || echo "unknown")
    fi
    
    # Build the crystallized state file
    cat > "$OUTPUT_FILE" << CRYSTAL
# Context State - Crystallized ${TIMESTAMP_ISO}

> **AUTO-GENERATED**: This file was created by the Context Crystallizer to preserve
> working state before context compaction. Read this to restore context.

## Session Info
- **Session ID**: ${FULL_SESSION_ID}
- **Crystallized**: ${TIMESTAMP_ISO}
- **Project**: ${PROJECT_DIR}
- **Git Branch**: ${GIT_BRANCH:-N/A}

## Files Modified This Session
\`\`\`
${FILES_MODIFIED:-No files modified}
\`\`\`

## Recent Tool Operations
\`\`\`
${TOOL_USES:-No tool operations recorded}
\`\`\`

## Recent User Instructions
The user's recent requests (most recent last):

${USER_MESSAGES:-No recent messages captured}

## Recent Assistant Context
Key points from recent responses:

${ASSISTANT_MESSAGES:-No recent responses captured}

## Recovery Instructions

When resuming after context clear:
1. Read this file to understand what was in progress
2. Check the files listed above for current state  
3. Continue from where we left off
4. Ask the user for clarification if context is unclear

---
*Crystallized by context-crystallizer v1.0*
CRYSTAL

    echo "$OUTPUT_FILE"
}

# Direct execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    if [[ $# -lt 1 ]]; then
        echo "Usage: $0 <transcript.jsonl> [output_dir] [project_dir]"
        exit 1
    fi
    crystallize "$@"
fi
