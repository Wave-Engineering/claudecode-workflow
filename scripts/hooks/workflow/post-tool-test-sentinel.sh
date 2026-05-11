#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# post-tool-test-sentinel.sh — PostToolUse hook (Bash matcher)
#
# Watches for test/lint/validate commands that succeed, and creates a
# session-scoped sentinel so pre-push-test-gate.sh allows the push.
#
# Recognized patterns:
#   pytest, python -m pytest, npm test, npx vitest, make test, make lint,
#   ./scripts/ci/validate.sh, ./scripts/ci/test.sh, ruff check, cargo test,
#   go test, bun test
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
EXIT_CODE=$(printf '%s' "$INPUT" | jq -r '.tool_result.exit_code // "0"' 2>/dev/null || true)

if [[ -z "$SESSION_ID" || -z "$COMMAND" ]]; then
	exit 0
fi

# Only mark sentinel on success
if [[ "$EXIT_CODE" != "0" ]]; then
	exit 0
fi

TEST_PATTERN='(pytest|python[0-9.]* -m pytest|npm test|npx vitest|make (test|lint|check)|\.\/scripts\/ci\/(validate|test)\.sh|ruff check|cargo test|go test|bun test)'

if printf '%s' "$COMMAND" | grep -qE "$TEST_PATTERN"; then
	touch "/tmp/claude-tests-ran-${SESSION_ID}"
	source "$(dirname "$0")/metrics.sh"
	log_metric "$SESSION_ID" "tests_ran" "command=$(printf '%s' "$COMMAND" | head -c 80)"
fi

exit 0
