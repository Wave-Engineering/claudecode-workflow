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
#   any command declared for the repo in ~/.claude/declared-toolchains.md (#1464): for a
#   repo we do not configure, whose owners did not ask for our file. A `## <key>` section
#   (the origin as host/owner/repo, either `git@host:o/r.git` or `https://host/o/r` form, or
#   the repo's absolute path) holding `- **Tests:** `cmd`` lines, in the Toolchain shape
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
# An interrupted run never counts, nor does one in the background.
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

# A background run returns at launch, before the test has a status. It may be backgrounded
# up front (`run_in_background`) or mid-flight (a `backgroundTaskId` in the response).
BG=$(printf '%s' "$INPUT" | jq -r '(.tool_input.run_in_background // false) or ((.tool_response.backgroundTaskId // "") != "")' 2>/dev/null || true)
[[ "$BG" == true ]] && exit 0

TEST_PATTERN='(pytest|python[0-9.]* -m pytest|npm test|npx vitest|make (test|lint|check)|\.\/scripts\/ci\/(validate|test)\.sh|ruff check|cargo test|go test|bun test|[/_-](lint|test|tests|validate)\.sh)'

# The commands declared for this repo: every backtick span on a Validation, Tests or Lint
# line, from the repo's own .claude-project.md Toolchain and from the per-user file
# ~/.claude/declared-toolchains.md (#1464). Spans shorter than 4 characters are ignored, so
# a stray `x` cannot make every command count.
DECLARED=""
# shellcheck disable=SC2016  # the backticks are literal markdown, not expansions
TOOLCHAIN_LINE='^[[:space:]]*[-*][[:space:]]*\*\*(Validation|Tests|Lint):\*\*'

# toolchain_spans: the commands on every Toolchain line read from stdin.
toolchain_spans() {
	# shellcheck disable=SC2016
	grep -E "$TOOLCHAIN_LINE" | grep -oE '`[^`]+`' | tr -d '`' | awk 'length($0) >= 4'
}

# normalize_key <remote URL | path>: a remote as host/owner/repo (scheme and user@ stripped,
# the scp-style `:` made `/`, a trailing `.git` or `/` dropped, lower-cased), so
# git@github.com:o/r.git and https://github.com/o/r are one key. An absolute path stays as is.
normalize_key() {
	local k="$1" auth
	k="${k#"${k%%[![:space:]]*}"}"
	k="${k%"${k##*[![:space:]]}"}"
	k="${k//\`/}"
	if [[ "$k" == /* ]]; then
		printf '%s' "${k%/}"
		return 0
	fi
	if [[ "$k" == *://* ]]; then
		k="${k#*://}"
		auth="${k%%/*}"
		k="${auth##*@}${k#"$auth"}"
	else
		k="${k#*@}"
		k="${k/://}"
	fi
	k="${k%/}"
	k="${k%.git}"
	printf '%s' "$k" | tr '[:upper:]' '[:lower:]'
}

# The per-user file is markdown in the Toolchain shape, one section per repo we do not
# configure, keyed by the repo's remote URL or its absolute path:
#
#   ## github.com/partner/repo
#   - **Tests:** `bash tests/run_unit.sh`
#
# Only the section whose key matches this repo's origin or top-level path counts.
user_declared() {
	local root="$1" cfg="${HOME:-/nonexistent}/.claude/declared-toolchains.md"
	local origin okey="" key line in_match=0 spans=""
	[[ -f "$cfg" ]] || return 0
	origin=$(git -C "$root" remote get-url origin 2>/dev/null || true)
	[[ -n "$origin" ]] && okey=$(normalize_key "$origin")
	while IFS= read -r line || [[ -n "$line" ]]; do
		if [[ "$line" =~ ^##[[:space:]]+(.+)$ ]]; then
			key=$(normalize_key "${BASH_REMATCH[1]}")
			in_match=0
			if [[ "$key" == "${root%/}" || (-n "$okey" && "$key" == "$okey") ]]; then in_match=1; fi
			continue
		fi
		((in_match)) && spans+="$(printf '%s\n' "$line" | toolchain_spans)"$'\n'
	done <"$cfg"
	printf '%s' "$spans"
}

load_declared() {
	local root cfg repo_spans="" user_spans=""
	[[ -n "$HOOK_CWD" ]] || return 0
	root=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null) || return 0
	cfg="$root/.claude-project.md"
	[[ -f "$cfg" ]] && repo_spans=$(toolchain_spans <"$cfg")
	user_spans=$(user_declared "$root")
	DECLARED=$(printf '%s\n%s\n' "$repo_spans" "$user_spans" | awk 'NF')
}
load_declared

# Cheap exit for the common case: nothing in the command could match.
mentions_declared() {
	local span
	while IFS= read -r span; do
		[[ -n "$span" ]] || continue
		[[ "$COMMAND" == *"$span"* ]] && return 0
		# declared_match compares a span without its interpreter, so this prefilter must too
		# (a declared `bash tests/run.sh` run as `sh tests/run.sh`). No length floor here:
		# this only decides whether to look further, and declared_match holds the floor.
		span="${span#bash }"
		span="${span#sh }"
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
		# A span may itself be written `bash tests/run.sh`: compare without the interpreter.
		span="${span#bash }"
		span="${span#sh }"
		((${#span} >= 4)) || continue # the floor holds after the strip too
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
