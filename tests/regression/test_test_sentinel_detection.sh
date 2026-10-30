#!/usr/bin/env bash
# test_test_sentinel_detection.sh — #1287: post-tool-test-sentinel.sh counts a repo's own
# test entrypoints, not only the kit's fixed list.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Drives the REAL hook with hook JSON on stdin. HOME is a temp dir, so the hook's metrics
# line never lands in the operator's real ~/.claude/logs.
#   - A script named like run_lint.sh / run-tests.sh counts (pattern).
#   - A command declared in the repo's .claude-project.md Toolchain counts (declared).
#   - An undeclared, unmatched command, a failed declared command, and a span under four
#     characters do not.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/hooks/workflow/post-tool-test-sentinel.sh"
WORK="$(mktemp -d)"
fail=0
n=0

echo "test_test_sentinel_detection"
echo "──────────────────────────────────────────"

# shellcheck disable=SC2329  # invoked by the EXIT trap below
cleanup() {
	rm -rf "$WORK"
	rm -f /tmp/claude-tests-ran-test-1287-$$-*
}
trap cleanup EXIT

# A throwaway repo that declares its own entrypoints.
git init -q "$WORK/repo"
cat >"$WORK/repo/.claude-project.md" <<'MD'
# Project Configuration

## Toolchain
- **Validation:** `./tools/check-all.sh`
- **Tests:** `make -C engine unit` and `ls`
- **Lint:** `ruffle-lint` — configured in `pyproject.toml`, sources in `bootstrap/`
- **Build:** `./tools/build-it.sh`
MD
mkdir -p "$WORK/home/.claude/logs"

# check <SENTINEL|NONE> <command> [stdout] [cwd] [interrupted]
# The payload is the documented PostToolUse Bash shape (#1361): tool_response carries
# stdout, stderr, interrupted and isImage, and no exit code.
check() {
	local want="$1" cmd="$2" out="${3:-}" cwd="${4:-$WORK/repo}" intr="${5:-false}" sid got
	n=$((n + 1))
	sid="test-1287-$$-$n"
	jq -n --arg s "$sid" --arg c "$cmd" --arg o "$out" --arg d "$cwd" --argjson i "$intr" \
		'{session_id: $s, cwd: $d, tool_input: {command: $c},
		  tool_response: {stdout: $o, stderr: "", interrupted: $i, isImage: false}}' |
		HOME="$WORK/home" bash "$HOOK"
	if [[ -f "/tmp/claude-tests-ran-$sid" ]]; then got=SENTINEL; else got=NONE; fi
	if [[ "$got" == "$want" ]]; then
		printf '  ok    %-8s %s (stdout %q)\n' "$got" "$cmd" "$out"
	else
		printf '  WRONG %-8s (want %s) %s (stdout %q)\n' "$got" "$want" "$cmd" "$out"
		fail=1
	fi
}

# Pattern: a repo's own lint/test script, wherever it lives.
check SENTINEL "bash tests/lint/run_lint.sh"
check SENTINEL "./scripts/run-tests.sh -v"
check SENTINEL "./lint.sh"
# Declared in .claude-project.md (no pattern would match these).
check SENTINEL "./tools/check-all.sh --fast"
check SENTINEL "make -C engine unit"
check SENTINEL "cd engine && ./tools/check-all.sh" # a later segment of the command
check SENTINEL "bash ./tools/check-all.sh"
check SENTINEL "ruffle-lint src/"
# A declared span counts only where a command starts, never as a mention: Toolchain lines
# also backtick file paths and prose (#1288 review).
check NONE "cat pyproject.toml"
check NONE "ls bootstrap/src"
check NONE "cd bootstrap/ && bun install"
check NONE "echo ./tools/check-all.sh"
check NONE "grep fast ./tools/check-all.sh"
# Not counted.
check NONE "./tools/other.sh"
check NONE "ls -la"              # `ls` is declared, but a span under 4 characters is ignored
check NONE "./tools/build-it.sh" # Build is not a test line
check NONE "echo hello"
check NONE "./tools/check-all.sh" "" "$WORK" # cwd outside any repo: nothing declared
# The kit's existing list still works.
check SENTINEL "./scripts/ci/validate.sh"
check SENTINEL "python3 -m pytest tests/"

# #1361: the sentinel counts only a test whose own exit status is known to be 0.
# The precheck lane form always exits 0 (the echo does), so its exit= line is the status.
check NONE './tools/check-all.sh > l 2>&1; echo "exit=$?"' "exit=1"
check SENTINEL './tools/check-all.sh > l 2>&1; echo "exit=$?"' "exit=0"
check NONE 'pytest > a 2>&1; echo "exit=$?"; pytest > b 2>&1; echo "exit=$?"' $'exit=0\nexit=2'
check SENTINEL 'pytest > a 2>&1; echo "exit=$?"; pytest > b 2>&1; echo "exit=$?"' $'exit=0\nexit=0'
check NONE 'ls; echo "exit=$?"' "exit=0" # a status line with no test segment is not a test
# The echo must report the test's own status, not a later step's (#1375 review).
check NONE 'pytest -q | tail -5; echo "exit=$?"' "exit=0"
check NONE 'pytest || true; echo "exit=$?"' "exit=0"
check NONE 'pytest; ls; echo "exit=$?"' "exit=0"
check SENTINEL 'cd engine && pytest > l 2>&1; echo "exit=$?"' "exit=0"
check SENTINEL $'pytest > l 2>&1\necho "exit=$?"' "exit=0"
# A backslash continuation is one command, not a newline connector.
check SENTINEL $'python3 -m pytest \\\n  tests/ -q'
check SENTINEL $'pytest -q \\\n  --tb=short && echo ok'
# No status line: a connector after the test masks its exit, so the status is unknown.
check NONE "pytest -q | tail -5"
check NONE "pytest; echo done"
check NONE "pytest || true"
check NONE "pytest & wait"
check NONE $'pytest\necho done'
# && chains keep the status: a later step runs only after the test succeeded.
check SENTINEL "cd engine && ./tools/check-all.sh && echo ok"
check SENTINEL "pytest && echo ok"
check SENTINEL "pytest 2>&1 && echo ok" # `>&` is a redirect, not a connector
check SENTINEL "pytest &> out.log"
check SENTINEL $'pytest\n' # a trailing newline is not a connector
# An interrupted run never counts.
check NONE "pytest" "" "$WORK/repo" true

# Each SENTINEL case logs one metrics line, into the temp HOME, never the real one.
if [[ ! -s "$WORK/home/.claude/logs/context-metrics.jsonl" ]]; then
	echo "  WRONG no metrics line in the temp HOME (did the hook write elsewhere?)"
	fail=1
fi

echo
if [[ $fail -eq 0 ]]; then
	echo "  all $n cases ok"
	exit 0
fi
echo "  test_test_sentinel_detection FAILED" >&2
exit 1
