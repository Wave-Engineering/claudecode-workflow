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
#
# The payload (#1361). The Claude Code hooks reference
# (https://code.claude.com/docs/en/hooks) gives PostToolUse `tool_input` and
# `tool_response`, and a Bash `tool_response` is `stdout`, `stderr`, `interrupted` and
# `isImage`. This hook reads only `tool_response.stdout` and `tool_response.interrupted`.
# There is no exit-code field. The hook used to read an `exit_code` under a payload key
# that does not exist, defaulted it to 0, and so counted every matching command, including a failed
# lane run as `<cmd> > <log> 2>&1; echo "exit=$?"`. PostToolUse fires when the whole
# command line exits 0, which says nothing about a test that ran before a `;`, `||`, `|`
# or `&`. So the sentinel is written only when the test's own status is known to be 0:
#   (a) stdout has one or more `exit=N` lines: every one is exit=0, and a matching segment
#       is followed (through `&&` only, then one `;` or newline) by `echo … exit=$?`, so
#       the line is the test's own status, not a later `tail`'s or `|| true`'s;
#   (b) no such line: some matching segment is followed only by `&&` (or is last), so the
#       command line's 0 is its own exit, or a later `&&` step's, which ran only after it;
#   (c) anything else is unknown, and writes nothing.
# An interrupted run never counts.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
STDOUT=$(printf '%s' "$INPUT" | jq -r '.tool_response.stdout // empty' 2>/dev/null || true)
INTERRUPTED=$(printf '%s' "$INPUT" | jq -r '.tool_response.interrupted // false' 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)

if [[ -z "$SESSION_ID" || -z "$COMMAND" ]]; then
	exit 0
fi

if [[ "$INTERRUPTED" == "true" ]]; then
	exit 0
fi

TEST_PATTERN='(pytest|python[0-9.]* -m pytest|npm test|npx vitest|make (test|lint|check)|\.\/scripts\/ci\/(validate|test)\.sh|ruff check|cargo test|go test|bun test|[/_-](lint|test|tests|validate)\.sh)'

# The commands this repo declares under Toolchain in its .claude-project.md: every backtick
# span on a Validation, Tests or Lint line. Spans shorter than 4 characters are ignored, so
# a stray `x` cannot make every command count.
DECLARED=""
load_declared() {
	local root cfg
	[[ -n "$HOOK_CWD" ]] || return 0
	root=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null) || return 0
	cfg="$root/.claude-project.md"
	[[ -f "$cfg" ]] || return 0
	# shellcheck disable=SC2016  # the backticks are literal markdown, not expansions
	DECLARED=$(grep -E '^[[:space:]]*[-*][[:space:]]*\*\*(Validation|Tests|Lint):\*\*' "$cfg" |
		grep -oE '`[^`]+`' | tr -d '`' | awk 'length($0) >= 4')
}
load_declared

# Cheap exit for the common case: nothing in the command could match.
mentions_declared() {
	local span
	while IFS= read -r span; do
		[[ -n "$span" && "$COMMAND" == *"$span"* ]] && return 0
	done <<<"$DECLARED"
	return 1
}
if ! printf '%s' "$COMMAND" | grep -qE "$TEST_PATTERN" && ! mentions_declared; then
	exit 0
fi

# split_segments fills SEGS and CONNS: each segment of $COMMAND and the connector after it,
# one of && || ; | & NL, or END for the last. A `&` inside `&&`, `>&` or `&>` is not a
# connector. Quotes are not parsed: over-splitting can only add connectors, which can only
# make a status unknown, never a pass. Bash 3.2 safe.
SEGS=()
CONNS=()
split_segments() {
	local s="$1" cur="" i=0 len c next prev=""
	len=${#s}
	_push() {
		SEGS+=("$cur")
		CONNS+=("$1")
		cur=""
	}
	while ((i < len)); do
		c="${s:i:1}"
		next="${s:i+1:1}"
		case "$c" in
		'&')
			if [[ "$next" == '&' ]]; then
				_push '&&'
				i=$((i + 2))
				prev='&'
				continue
			elif [[ "$prev" == '>' || "$next" == '>' ]]; then
				cur+="$c"
			else
				_push '&'
			fi
			;;
		'|')
			if [[ "$next" == '|' ]]; then
				_push '||'
				i=$((i + 2))
				prev='|'
				continue
			fi
			_push '|'
			;;
		';') _push ';' ;;
		$'\n') _push NL ;;
		*) cur+="$c" ;;
		esac
		prev="$c"
		i=$((i + 1))
	done
	_push END
}

# A declared span counts only where a command STARTS: the segment equal to the span, or
# the span plus arguments (optionally after `bash `/`sh `). Toolchain lines also backtick
# file paths and prose (`pyproject.toml`, `bootstrap/`), so a match anywhere in the text
# would let `cat pyproject.toml` count.
declared_match() {
	local seg="$1" span
	seg="${seg#"${seg%%[![:space:]]*}"}"
	seg="${seg#bash }"
	seg="${seg#sh }"
	while IFS= read -r span; do
		[[ -n "$span" ]] || continue
		[[ "$seg" == "$span" || "$seg" == "$span "* ]] && return 0
	done <<<"$DECLARED"
	return 1
}

seg_matches() {
	printf '%s' "$1" | grep -qE "$TEST_PATTERN" || declared_match "$1"
}

# Trailing newlines and spaces are not a connector, and neither is a backslash line
# continuation. $nl, not $'\n', inside the pattern: bash <= 4.2 keeps the quotes.
nl=$'\n'
TRIMMED="${COMMAND%"${COMMAND##*[![:space:]]}"}"
TRIMMED="${TRIMMED//\\$nl/ }"
split_segments "$TRIMMED"

# reported_match: a matching segment whose own status an `echo … exit=$?` prints. Only
# `&&` may come between the two, plus one `;` or newline just before the echo. So
# `pytest | tail; echo "exit=$?"` (tail's status) and `pytest || true; echo …` do not count.
is_status_echo() {
	printf '%s' "$1" | grep -qE '^[[:space:]]*echo[[:space:]].*exit=\$\?'
}
clean_match=false
reported_match=false
for ((k = 0; k < ${#SEGS[@]}; k++)); do
	seg_matches "${SEGS[k]}" || continue
	tail_ok=true
	for ((j = k; j < ${#CONNS[@]}; j++)); do
		[[ "${CONNS[j]}" == '&&' || "${CONNS[j]}" == END ]] || {
			tail_ok=false
			break
		}
	done
	[[ "$tail_ok" == true ]] && clean_match=true
	for ((j = k; j < ${#CONNS[@]} - 1; j++)); do
		if [[ "${CONNS[j]}" == ';' || "${CONNS[j]}" == NL ]]; then
			is_status_echo "${SEGS[j + 1]}" && reported_match=true
			break
		fi
		[[ "${CONNS[j]}" == '&&' ]] || break
	done
done

counts=false
STATUS_LINES=$(printf '%s\n' "$STDOUT" | grep -E '^exit=[0-9]+$' || true)
if [[ -n "$STATUS_LINES" ]]; then
	# (a) an explicit status: every exit= line is exit=0, and it reports a test's own exit.
	if ! printf '%s\n' "$STATUS_LINES" | grep -qv '^exit=0$' &&
		[[ "$reported_match" == true || "$clean_match" == true ]]; then
		counts=true
	fi
elif [[ "$clean_match" == true ]]; then
	counts=true # (b)
fi

if [[ "$counts" == true ]]; then
	touch "/tmp/claude-tests-ran-${SESSION_ID}"
	source "$(dirname "$0")/metrics.sh"
	log_metric "$SESSION_ID" "tests_ran" "command=$(printf '%s' "$COMMAND" | head -c 80)"
fi

exit 0
