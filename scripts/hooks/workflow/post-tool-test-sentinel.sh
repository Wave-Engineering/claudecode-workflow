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
#   any script named like `…/lint.sh`, `run_lint.sh`, `run-tests.sh`, `validate.sh` (#1287)
#   any command the repo declares in its `.claude-project.md` Toolchain Validation,
#   Tests or Lint line (#1287): a repo's own entrypoint counts without a kit change
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
EXIT_CODE=$(printf '%s' "$INPUT" | jq -r '.tool_result.exit_code // "0"' 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)

if [[ -z "$SESSION_ID" || -z "$COMMAND" ]]; then
	exit 0
fi

# Only mark sentinel on success
if [[ "$EXIT_CODE" != "0" ]]; then
	exit 0
fi

TEST_PATTERN='(pytest|python[0-9.]* -m pytest|npm test|npx vitest|make (test|lint|check)|\.\/scripts\/ci\/(validate|test)\.sh|ruff check|cargo test|go test|bun test|[/_-](lint|test|tests|validate)\.sh)'

# The commands this repo declares under Toolchain in its .claude-project.md: every backtick
# span on a Validation, Tests or Lint line. Spans shorter than 4 characters are ignored, so
# a stray `x` cannot make every command count.
declared_match() {
	local root cfg span
	[[ -n "$HOOK_CWD" ]] || return 1
	root=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null) || return 1
	cfg="$root/.claude-project.md"
	[[ -f "$cfg" ]] || return 1
	# shellcheck disable=SC2016  # the backticks are literal markdown, not expansions
	while IFS= read -r span; do
		[[ ${#span} -ge 4 ]] || continue
		[[ "$COMMAND" == *"$span"* ]] && return 0
	done < <(grep -E '^[[:space:]]*[-*][[:space:]]*\*\*(Validation|Tests|Lint):\*\*' "$cfg" |
		grep -oE '`[^`]+`' | tr -d '`')
	return 1
}

if printf '%s' "$COMMAND" | grep -qE "$TEST_PATTERN" || declared_match; then
	touch "/tmp/claude-tests-ran-${SESSION_ID}"
	source "$(dirname "$0")/metrics.sh"
	log_metric "$SESSION_ID" "tests_ran" "command=$(printf '%s' "$COMMAND" | head -c 80)"
fi

exit 0
