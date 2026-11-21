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

# check <SENTINEL|NONE> <command> [stdout] [cwd] [interrupted] [jq-filter]
# The payload is the documented PostToolUse Bash shape (#1361): tool_response carries
# stdout, stderr, interrupted and isImage, and no exit code. The optional jq filter
# reshapes it, e.g. to mark the run as backgrounded.
check() {
	local want="$1" cmd="$2" out="${3:-}" cwd="${4:-$WORK/repo}" intr="${5:-false}" shape="${6:-.}" sid got
	n=$((n + 1))
	sid="test-1287-$$-$n"
	jq -n --arg s "$sid" --arg c "$cmd" --arg o "$out" --arg d "$cwd" --argjson i "$intr" \
		'{session_id: $s, cwd: $d, tool_input: {command: $c},
		  tool_response: {stdout: $o, stderr: "", interrupted: $i, isImage: false}}' |
		jq "$shape" |
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
# A background run returns at launch, before the test has a status: launched that way, or
# backgrounded mid-flight.
check NONE "pytest" "" "$WORK/repo" false '.tool_input.run_in_background = true'
check NONE "pytest" "" "$WORK/repo" false '.tool_response.backgroundTaskId = "b1x2"'
check SENTINEL "pytest" "" "$WORK/repo" false '.tool_input.run_in_background = false'

# #1464: a repo we do not configure has no .claude-project.md, and its test command is
# declared in the per-user ~/.claude/declared-toolchains.md instead (HOME is the temp dir).
WORKP="$(cd "$WORK" && pwd -P)"
for r in partner partner-scp partner-path other; do git init -q "$WORK/$r"; done
git -C "$WORK/partner" remote add origin https://github.com/Partner/Lib.git
git -C "$WORK/partner-scp" remote add origin git@gitlab.example.com:team/svc.git
git -C "$WORK/other" remote add origin https://github.com/partner/other.git
cat >"$WORK/home/.claude/declared-toolchains.md" <<MD
# Declared toolchains (per user, never in the repo)

## github.com/partner/lib
- **Tests:** \`bash tests/run_unit.sh\`
- **Lint:** \`ab\`
- **Lint:** \`bash x\`

## https://gitlab.example.com/team/svc
- **Validation:** \`./ci/verify.sh\`

## $WORKP/partner-path
- **Tests:** \`make -C suite run\`

## github.com/unrelated/repo
- **Tests:** \`./only-for-unrelated.sh\`
MD
UT='bash tests/run_unit.sh > log 2>&1; echo "exit=$?"'
check SENTINEL "$UT" $'exit=0' "$WORK/partner" # https origin, any case, .git dropped
check SENTINEL "bash tests/run_unit.sh" "" "$WORK/partner"
check SENTINEL "./ci/verify.sh --all" "" "$WORK/partner-scp" # git@host:o/r.git matches an https key
check SENTINEL "make -C suite run" "" "$WORK/partner-path"   # keyed by the repo's absolute path
check NONE "$UT" $'exit=1' "$WORK/partner"                   # a failing run
check NONE "bash tests/run_unit.sh" "" "$WORK/partner" true  # interrupted
check NONE "bash tests/run_unit.sh" "" "$WORK/partner" false '.tool_input.run_in_background = true'
check NONE "bash tests/run_unit.sh | tail -3" "" "$WORK/partner" # a pipe hides the status
check NONE "bash tests/run_unit.sh" "" "$WORK/other"            # another repo's origin: no section
check NONE "./only-for-unrelated.sh" "" "$WORK/other"           # a section for a repo that is not this one
check NONE "cat tests/run_unit.sh" "" "$WORK/partner"           # a mention, not a command start
check NONE "ab" "" "$WORK/partner"                              # a span under 4 characters
check NONE "x --anything" "" "$WORK/partner"                    # `bash x` is 1 character once the interpreter goes
check NONE "make -C suite run" "" "$WORK/partner"               # path-keyed section is not this repo's
# The kit's own pattern never carries a partner's entrypoint.
if grep -q '^TEST_PATTERN=.*run_unit' "$HOOK"; then
	echo "  WRONG TEST_PATTERN carries tests/run_unit.sh"
	fail=1
else
	n=$((n + 1))
	echo "  ok    TEST_PATTERN carries no partner entrypoint"
fi
# No per-user file at all: nothing changes for a repo with no declaration.
mv "$WORK/home/.claude/declared-toolchains.md" "$WORK/home/.claude/declared-toolchains.off"
check NONE "bash tests/run_unit.sh" "" "$WORK/partner"
check SENTINEL "pytest" "" "$WORK/partner"
mv "$WORK/home/.claude/declared-toolchains.off" "$WORK/home/.claude/declared-toolchains.md"

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
