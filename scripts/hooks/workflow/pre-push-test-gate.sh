#!/usr/bin/env bash
# pre-push-test-gate.sh — PreToolUse hook for Bash(git push*)
#
# Blocks git push if no test/lint/validate command has run this session.
# Tracks via a session-scoped sentinel file.
#
# The sentinel is created by a companion PostToolUse hook that watches for
# test-like commands (pytest, npm test, make test, validate.sh, etc).
#
# Disable: PUSH_GATE_DISABLED=1
set -uo pipefail

if [[ "${PUSH_GATE_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

if [[ -z "$SESSION_ID" ]]; then
	exit 0
fi

# Only gate actual push commands
if ! printf '%s' "$COMMAND" | grep -qE '^\s*git\s+push'; then
	exit 0
fi

SENTINEL="/tmp/claude-tests-ran-${SESSION_ID}"

if [[ -f "$SENTINEL" ]]; then
	exit 0
fi

source "$(dirname "$0")/metrics.sh"
log_metric "$SESSION_ID" "hook_block" "hook=pre-push-test-gate" "command=git push"

cat <<'JSON'
{"decision":"block","reason":"Cannot push untested code. Run the project's test/lint/validate tooling first (e.g. pytest, make test, ./scripts/ci/validate.sh). The push will be allowed after tests pass."}
JSON
exit 0
