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
#   1. Is this a PLAIN push we can read completely? A single-line `git push` (or
#      `git -C <plain path> push`, #1287) with
#      allowlisted flags, a plain remote and plain refspecs (plus an optional trailing
#      redirection or `| tail`/`| head`). If every destination is an agent's own working
#      branch or a wave integration branch, it is exempt: /precheck gates the MR, not the
#      push. Nothing else is ever exempt — no shell parsing, so nothing to bypass.
#   2. Otherwise, does the command contain a `git … push` anywhere? Then gate it on the
#      test sentinel, exactly as before #1232 — but detected anywhere in the command
#      (after `cd X &&`, in a subshell, behind `sudo`, inside `bash -c "…"`, past git's
#      global options), not only at its start.
#
# Before both: a PLAIN delete of ONE branch (`git push <remote> --delete <b>` or `:<b>`,
# git_push_delete_target in git-detect.sh) publishes no code, so it needs no test run and
# no working-branch prefix (#1364). If the target is protected, a release ref or a tag
# (GIT_PROTECTED_DELETE_RE, git_push_delete_protected), it is refused outright, test run
# or not: having run tests says nothing about deleting `main`. Other delete shapes fall
# back to the test-run rule; the forge's branch and tag protection is their backstop.
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
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
[[ -n "$CWD" ]] || CWD="$PWD"

if [[ -z "$SESSION_ID" ]]; then
	exit 0
fi

# --- Question 2 first (cheap): is there a `git … push` anywhere? ----------------------
# The detector is shared with secret-scan-gate.sh; see git-detect.sh for what it matches.
# Not a push → nothing to gate. A detector that fails to load must not read as "not a
# push" (exit 0, gate silently off): without it, any command mentioning git is blocked.
# A git-detect.sh older than this gate (mid-./install) lacks the #1364 pieces; under
# `set -u` an unset GIT_PROTECTED_REF_RE would abort with a non-blocking exit 1.
if ! source "$(dirname "$0")/git-detect.sh" 2>/dev/null || ! declare -F git_invokes >/dev/null ||
	! declare -F git_push_delete_target >/dev/null || ! declare -F git_push_delete_protected >/dev/null ||
	[[ -z "${GIT_PROTECTED_REF_RE:-}" || -z "${GIT_PROTECTED_DELETE_RE:-}" ]]; then
	case "$COMMAND" in *git*)
		jq -cn '{decision: "block", reason: "Push gate cannot run: its git-detect.sh helper did not load, so this command is blocked. Re-run the kit'"'"'s ./install, then retry."}'
		;;
	esac
	exit 0
fi
if ! git_invokes "$COMMAND" push; then
	exit 0
fi

# --- Question 1: a plain push whose every destination is exempt? ----------------------

# Working branches push freely (#1232, BJ 2026-10-17: "/precheck gates the MR, not the
# commit"): feature/, fix/, chore/, doc/ — singular `doc/`, never `docs/` (BJ: "'docs/'
# IS 100% WRONG"). A project with another convention (e.g. a Jira-keyed `DEVOPS-1234-x`)
# adds it as an extended regex in PUSH_GATE_EXTRA_BRANCH_RE, typically through the
# `env` block of its own .claude/settings.json. A protected or qualified ref is never
# exempt, whatever that regex says: GIT_PROTECTED_REF_RE (git-detect.sh) is checked first.
_working_re='^(feature|fix|chore|doc)/.+'
_extra_re="${PUSH_GATE_EXTRA_BRANCH_RE:-}"

# Integration-ref exemption (#724): pushes whose destination refs are all
# kahuna/* or wave-*/* are governed by the WAVE trust gate (commutativity +
# kahuna→release merge-result CI + code-reviewer + trivy), not this session
# sentinel — which is redundant for integration pushes and wrongly blocks
# legitimate no-test (docs/config) waves. #1299: campaign/* (the /wavemachine
# campaign branch) is exempt on the same footing; nothing leaves it for a
# protected branch except through the DoD-gated release PR.
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

	# One optional trailing `| tail -N` / `| head -N`, then any trailing redirections.
	if [[ "$cmd" =~ $GIT_PUSH_TAIL_RE ]]; then
		cmd="${cmd%"${BASH_REMATCH[0]}"}"
	fi
	while [[ "$cmd" =~ $GIT_PUSH_REDIR_RE ]]; do
		cmd="${cmd%"${BASH_REMATCH[0]}"}"
	done

	# What remains must be one line with no shell syntax at all.
	case "$cmd" in
	*$'\n'* | *[\;\&\|\`\$\(\)\<\>\{\}\'\"\\]*) return 1 ;;
	esac

	read -ra _toks <<<"$cmd"
	# `git push …`, or `git -C <path> push …` (#1287): an agent working in a second repo
	# cannot `cd` there and stay, because the session's cwd resets after each Bash call.
	# Exactly one -C and a plain path; -C changes which repo, never which refs are exempt.
	local first=2
	if [[ "${_toks[1]:-}" == "-C" ]]; then
		[[ "${_toks[2]:-}" =~ ^[A-Za-z0-9._/~-]+$ ]] || return 1
		first=4
	fi
	[[ ${#_toks[@]} -ge $((first + 2)) && "${_toks[0]}" == "git" && "${_toks[first - 1]}" == "push" ]] || return 1

	for tok in "${_toks[@]:first}"; do
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
		[[ "$dst" =~ $GIT_PROTECTED_REF_RE ]] && return 1
		if [[ "$dst" == kahuna/* || "$dst" == campaign/* || "$dst" == wave-*/* ]]; then
			: # integration refs (kahuna, /wavemachine campaign, old wave-*/ flight stem)
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

_delete_reason=$(
	cat <<'TXT'
This branch delete was refused. A delete needs no test run when it is ONE plain command deleting ONE branch that is not protected or a release ref: `git push <remote> --delete <branch>` or `git push <remote> :<branch>`, run as its own Bash call: no `cd … &&`, no `VAR=… git`, no `bash -c`, one branch per push. Put a remote's SSH key in `git config core.sshCommand '…'` once, not on the push line. A plain delete of a protected or release ref (main, master, develop, trunk, HEAD, release, release-*/release_*/release/*, stable, production, prod, gh-pages, version names like 1.2.3 or v1.2.3, any tag, qualified refs/…) is refused even after tests, and other shapes fall back to the test-run rule. Either way an agent never deletes one: ask the user. Do not delete it through the forge's API instead.
TXT
)
_block_delete() {
	source "$(dirname "$0")/metrics.sh"
	log_metric "$SESSION_ID" "hook_block" "hook=pre-push-test-gate" "command=git push --delete"
	jq -cn --arg r "$_delete_reason" '{decision: "block", reason: $r}'
	exit 0
}

# #1364: a plain single-branch delete. Protected (or a tag) → refused even after a test run.
if _del=$(git_push_delete_target "$COMMAND"); then
	if git_push_delete_protected "$CWD" "$COMMAND" "$_del"; then
		_block_delete
	fi
	exit 0
fi

if _exempt_plain_push; then
	exit 0
fi

SENTINEL="/tmp/claude-tests-ran-${SESSION_ID}"

if [[ -f "$SENTINEL" ]]; then
	exit 0
fi

# Anything that looks like a delete but was not a plain one gets told the approved path.
if [[ "$COMMAND" =~ (^|[[:space:]])(--delete|-d|:[^[:space:]]*)([[:space:]]|$) ]]; then
	_block_delete
fi

source "$(dirname "$0")/metrics.sh"
log_metric "$SESSION_ID" "hook_block" "hook=pre-push-test-gate" "command=git push"

cat <<'JSON'
{"decision":"block","reason":"Cannot push untested code. Run the project's test/lint/validate tooling first (e.g. pytest, make test, ./scripts/ci/validate.sh). The push will be allowed after tests pass. A test run piped to `tail`/`head`, or followed by `;` or `||`, does not count unless the command ends with `; echo \"exit=$?\"`. A plain `git push <remote> <branch>` to your own feature/, fix/, chore/ or doc/ branch needs no tests. (This gate matches the text `git push` anywhere in a command, quoted or not. If this command only mentions it, e.g. a grep or a commit message, run the tests first or reword it.)"}
JSON
exit 0
