#!/usr/bin/env bash
# metrics.sh — shared function for context-metrics logging.
# Source this from other hooks: source "$(dirname "$0")/metrics.sh"
#
# Usage: log_metric <session_id> <event> [key=value ...]
# Output: appends one JSONL line to ~/.claude/logs/context-metrics.jsonl

METRICS_LOG="${HOME}/.claude/logs/context-metrics.jsonl"

log_metric() {
	local session="${1:-unknown}"
	local event="${2:-unknown}"
	shift 2
	local ts
	ts=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
	local extra=""
	for kv in "$@"; do
		local key="${kv%%=*}"
		local val="${kv#*=}"
		val=$(printf '%s' "$val" | sed 's/"/\\"/g' | head -c 200)
		extra="${extra},\"${key}\":\"${val}\""
	done
	printf '{"ts":"%s","session":"%s","event":"%s"%s}\n' "$ts" "$session" "$event" "$extra" >>"$METRICS_LOG"
}
