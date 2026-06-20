#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
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

# Integration-ref exemption (#724): pushes whose destination refs are all
# kahuna/* or wave-*/* are governed by the WAVE trust gate (commutativity +
# kahuna→release merge-result CI + code-reviewer + trivy), not this session
# sentinel — which is redundant for integration pushes and wrongly blocks
# legitimate no-test (docs/config) waves. Exempt only when EVERY refspec
# targets an integration branch; if any refspec targets a protected branch
# (e.g. `git push origin main kahuna/56`) we fall through and gate as before.
# Match the destination ref, never a substring of the whole command, so
# `git push origin main` is never exempted.
read -ra _push_tokens <<<"$COMMAND"
_after_push=0 _seen_remote=0 _n_refspecs=0 _n_integration=0
for _tok in "${_push_tokens[@]}"; do
	if [[ $_after_push -eq 0 ]]; then
		[[ "$_tok" == "push" ]] && _after_push=1
		continue
	fi
	[[ "$_tok" == -* ]] && continue # flags: -u, -o, --force-with-lease, …
	if [[ $_seen_remote -eq 0 ]]; then
		_seen_remote=1 # first non-flag token after `push` is the remote
		continue
	fi
	# remaining non-flag tokens are refspecs (src or src:dst); dest is after `:`
	_dst="${_tok##*:}"
	_n_refspecs=$((_n_refspecs + 1))
	[[ "$_dst" == kahuna/* || "$_dst" == wave-*/* ]] && _n_integration=$((_n_integration + 1))
done
if [[ $_n_refspecs -gt 0 && $_n_refspecs -eq $_n_integration ]]; then
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
