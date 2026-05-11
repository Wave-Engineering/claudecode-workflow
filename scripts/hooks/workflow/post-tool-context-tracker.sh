#!/usr/bin/env bash
# post-tool-context-tracker.sh — PostToolUse hook (Skill|ToolSearch matcher)
#
# Logs when a skill is invoked or when ToolSearch loads deferred tool schemas.
# These are step-function context jumps worth tracking.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || true)
TOOL_NAME=$(printf '%s' "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null || true)

if [[ -z "$TOOL_NAME" ]]; then
	exit 0
fi

source "$(dirname "$0")/metrics.sh"

case "$TOOL_NAME" in
Skill)
	SKILL=$(printf '%s' "$INPUT" | jq -r '.tool_input.skill // "unknown"' 2>/dev/null || true)
	log_metric "$SESSION_ID" "skill_load" "skill=$SKILL"
	;;
ToolSearch)
	QUERY=$(printf '%s' "$INPUT" | jq -r '.tool_input.query // "unknown"' 2>/dev/null || true)
	log_metric "$SESSION_ID" "tool_search" "query=$QUERY"
	;;
esac

exit 0
