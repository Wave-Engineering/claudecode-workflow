#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# pre-push-test-gate.sh — PreToolUse hook (Bash matcher) that gates `git push`
#
# Blocks git push if no test/lint/validate command has run this session.
# Tracks via a session-scoped sentinel file.
#
# The sentinel is created by a companion PostToolUse hook that watches for
# test-like commands (pytest, npm test, make test, validate.sh, etc).
#
# Two separate questions (#1232):
#   1. Is this a PLAIN push we can read completely? A single-line `git push` with
#      allowlisted flags, a plain remote and plain refspecs (plus an optional trailing
#      redirection or `| tail`/`| head`). If every destination is an agent's own working
#      branch or a wave integration branch, it is exempt: /precheck gates the MR, not the
#      push. Nothing else is ever exempt — no shell parsing, so nothing to bypass.
#   2. Otherwise, does the command contain a `git … push` anywhere? Then gate it on the
#      test sentinel, exactly as before #1232 — but detected anywhere in the command
#      (after `cd X &&`, in a subshell, behind `sudo`, inside `bash -c "…"`, past git's
#      global options), not only at its start.
#
# Must stay bash-3.2-safe (stock macOS): no `${x,,}`, no `mapfile`, no negative indices.
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

# --- Question 2 first (cheap): is there a `git … push` anywhere? ----------------------
# `git` as a word (bare, or a path like /usr/bin/git, or quoted as in `bash -c "git …"`),
# then any of git's GLOBAL options — `-C <dir>` / `-c <k=v>` and the value-taking long
# options with a plain, double- or single-quoted value; the `--opt=value` forms; the
# flag-only ones — then the `push` subcommand. Only real global options, so a subcommand's
# own flags (`git log --grep push`) are not mistaken for them. Not a push → nothing to gate.
# An option value is one shell word built from adjacent segments: plain characters, a
# backslash escape, a double- or single-quoted string, an unquoted `$( … )`, or a
# backtick substitution. So `core.sshCommand="ssh -i key"` (plain + quoted), `~/my\ repo`
# (plain + escape + plain), `$(git rev-parse --show-toplevel)` and `` `pwd -P` `` are each
# one value. `"$(dirname "$f")"` is one value as quoted `"$(dirname "` + plain `$f` +
# quoted `")"` — adjacency, not the `$( … )` segment, is what holds it together.
_dq='"'
_sq="'"
_bt='`'
# shellcheck disable=SC1003 # two literal backslashes: the ERE for one literal backslash
_bs='\\'
_optval="((${_bs}.|[^[:space:]${_dq}${_sq}${_bs}${_bt}]|${_dq}[^${_dq}]*${_dq}|${_sq}[^${_sq}]*${_sq}|${_bt}[^${_bt}]*${_bt}|\\\$\\([^)]*\\))+)"
_gopt_names="git-dir|work-tree|namespace|exec-path|config-env|super-prefix|shallow-file|attr-source"
_gopt_val="-[Cc]|--(${_gopt_names})"
_gopt_eq="--(${_gopt_names})=(${_optval})?"
_gopt_flag="-[pP]|--(no-pager|paginate|bare|no-replace-objects|no-lazy-fetch|no-optional-locks|no-advice|literal-pathspecs|glob-pathspecs|noglob-pathspecs|icase-pathspecs|exec-path)"
_gitopt="([[:space:]]+((${_gopt_val})[[:space:]]+${_optval}|${_gopt_eq}|${_gopt_flag}))*"
_detect_re="(^|[^[:alnum:]_.-])git${_gitopt}[[:space:]]+push([^[:alnum:]_-]|$)"
# Detect on the command as bash will run it: a backslash-newline continuation joins lines.
_detect_in="${COMMAND//$'\\\n'/ }"
if ! [[ "$_detect_in" =~ $_detect_re ]]; then
	exit 0
fi

# --- Question 1: a plain push whose every destination is exempt? ----------------------

# Working branches push freely (#1232, BJ 2026-10-17: "/precheck gates the MR, not the
# commit"): feature/, fix/, chore/, doc/ — singular `doc/`, never `docs/` (BJ: "'docs/'
# IS 100% WRONG"). A project with another convention (e.g. a Jira-keyed `DEVOPS-1234-x`)
# adds it as an extended regex in PUSH_GATE_EXTRA_BRANCH_RE, typically through the
# `env` block of its own .claude/settings.json. A protected or qualified ref is never
# exempt, whatever that regex says: _protected_re is checked first.
_working_re='^(feature|fix|chore|doc)/.+'
_extra_re="${PUSH_GATE_EXTRA_BRANCH_RE:-}"
_protected_re='^(main|master|develop|trunk|HEAD|release/.*|v[0-9].*|(heads|tags|remotes|refs)/.*)$'

# Integration-ref exemption (#724): pushes whose destination refs are all
# kahuna/* or wave-*/* are governed by the WAVE trust gate (commutativity +
# kahuna→release merge-result CI + code-reviewer + trivy), not this session
# sentinel — which is redundant for integration pushes and wrongly blocks
# legitimate no-test (docs/config) waves.
# #848/ENG-2 — flight branches use a STANDARD prefix (<type>/<issueNum>-<waveId>-<slug>);
# one for the ACTIVE wave (WAVE_FLIGHT_ID) counts as an integration ref. Since #1232 every
# flight branch also matches _working_re, so this check decides nothing today; it is kept,
# deliberately, so the integration exemption does not silently depend on the working-branch
# rule if either one is narrowed later.
_wave_id="${WAVE_FLIGHT_ID:-}"
_wave_id="${_wave_id//[^A-Za-z0-9._-]/_}" # mirror resume.js safeWaveId() so it matches the branch infix
_flight_re=""
if [[ -n "$_wave_id" ]]; then
	_wid_re="${_wave_id//./\\.}" # escape regex dots; remaining chars are [A-Za-z0-9_-] (literal)
	_flight_re="^(feature|fix|doc|chore)/[0-9]+-${_wid_re}-.+$"
fi

_exempt_plain_push() {
	local cmd="$COMMAND" tok dst remote="" n=0 skip=0
	local tail_re='[[:space:]]*\|[[:space:]]*(tail|head)([[:space:]]+-n)?([[:space:]]+-?[0-9]+)?[[:space:]]*$'
	local redir_re='[[:space:]]+(2>&1|[12]?>[[:space:]]*/dev/null|&>[[:space:]]*/dev/null)[[:space:]]*$'

	# One optional trailing `| tail -N` / `| head -N`, then any trailing redirections.
	if [[ "$cmd" =~ $tail_re ]]; then
		cmd="${cmd%"${BASH_REMATCH[0]}"}"
	fi
	while [[ "$cmd" =~ $redir_re ]]; do
		cmd="${cmd%"${BASH_REMATCH[0]}"}"
	done

	# What remains must be one line with no shell syntax at all.
	case "$cmd" in
	*$'\n'* | *[\;\&\|\`\$\(\)\<\>\{\}\'\"\\]*) return 1 ;;
	esac

	read -ra _toks <<<"$cmd"
	[[ ${#_toks[@]} -ge 4 && "${_toks[0]}" == "git" && "${_toks[1]}" == "push" ]] || return 1

	for tok in "${_toks[@]:2}"; do
		if [[ $skip -eq 1 ]]; then
			skip=0
			[[ "$tok" =~ ^[A-Za-z0-9._=-]+$ ]] || return 1 # a push option's plain value
			continue
		fi
		case "$tok" in
		-u | --set-upstream | -q | --quiet | -v | --verbose | -f | --force | --force-if-includes | --no-verify | --atomic | -n | --dry-run)
			continue
			;;
		--force-with-lease | --force-with-lease=*) continue ;;
		-o | --push-option)
			skip=1
			continue
			;;
		--push-option=*) continue ;;
		-*) return 1 ;; # anything else (--tags, --all, --mirror, --delete, -d, …): not plain
		esac
		if [[ -z "$remote" ]]; then
			[[ "$tok" =~ ^[A-Za-z0-9._-]+$ ]] || return 1 # a plain remote name, not a URL
			remote="$tok"
			continue
		fi
		# A refspec: plain characters only; `src:dst` or `dst`, optional leading `+`.
		[[ "$tok" =~ ^\+?[A-Za-z0-9._/@-]*(:[A-Za-z0-9._/@-]+)?$ ]] || return 1
		dst="${tok##*:}"
		dst="${dst#+}"
		dst="${dst#refs/heads/}"
		# Only a destination starting with a letter or digit can be exempt. Anything else may
		# be a revision shorthand (`@` is HEAD) that a permissive PUSH_GATE_EXTRA_BRANCH_RE
		# could otherwise exempt.
		[[ "$dst" =~ ^[A-Za-z0-9] ]] || return 1
		[[ "$dst" =~ $_protected_re ]] && return 1
		if [[ "$dst" == kahuna/* || "$dst" == wave-*/* ]]; then
			: # legacy integration refs (kahuna, old wave-*/ flight stem)
		elif [[ -n "$_flight_re" && "$dst" =~ $_flight_re ]]; then
			: # #848: a flight branch for the ACTIVE wave
		elif [[ "$dst" =~ $_working_re ]]; then
			: # an agent's own working branch
		elif [[ -n "$_extra_re" && "$dst" =~ $_extra_re ]]; then
			: # the project's own extra working-branch convention
		else
			return 1
		fi
		n=$((n + 1))
	done
	[[ $skip -eq 0 && $n -gt 0 ]]
}

if _exempt_plain_push; then
	exit 0
fi

SENTINEL="/tmp/claude-tests-ran-${SESSION_ID}"

if [[ -f "$SENTINEL" ]]; then
	exit 0
fi

source "$(dirname "$0")/metrics.sh"
log_metric "$SESSION_ID" "hook_block" "hook=pre-push-test-gate" "command=git push"

cat <<'JSON'
{"decision":"block","reason":"Cannot push untested code. Run the project's test/lint/validate tooling first (e.g. pytest, make test, ./scripts/ci/validate.sh). The push will be allowed after tests pass. A plain `git push <remote> <branch>` to your own feature/, fix/, chore/ or doc/ branch needs no tests. (This gate matches the text `git push` anywhere in a command, quoted or not. If this command only mentions it, e.g. a grep or a commit message, run the tests first or reword it.)"}
JSON
exit 0
