#!/usr/bin/env bash
# identity-collision-warn.sh — CC SessionStart hook (matcher: "startup|resume") (#1366)
#
# Two live sessions in one checkout share one identity file, so both read the same
# Dev-Name and both answer the same @name (2026-10-22: two sessions both resolved to one
# name, and one had to be held down by hand). This warns the NEWER session at start, so
# it can move to a worktree before it signs, checks in or answers anything. The older
# session keeps the identity and hears nothing.
#
# Contract (CC SessionStart hook):
#   stdin:  JSON with .cwd
#   stdout: injected as a system-reminder into the session's context
#   exit:   always 0; never blocks session start
#
# Dormant unless <cwd>/.claude/agent-identity.json exists. The detection is
# identity-claimants.sh, which reads the process table.

LOG_FILE="${IDENTITY_COLLISION_LOG:-$HOME/.claude/logs/identity-collision.log}"
CLAIMANTS="${IDENTITY_CLAIMANTS_BIN:-$(dirname "$0")/../../identity-claimants.sh}"

log() {
	mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null &&
		printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >>"$LOG_FILE" 2>/dev/null
	return 0
}

INPUT="$(cat 2>/dev/null || true)"
cwd="$(jq -r '.cwd // empty' <<<"$INPUT" 2>/dev/null)"
[[ -n "$cwd" ]] || exit 0
identity="$cwd/.claude/agent-identity.json"
[[ -f "$identity" ]] || exit 0

out="$(bash "$CLAIMANTS" "$cwd" 2>/dev/null)"
log "$cwd: ${out:-<no output>}"

case "$out" in
older\ *)
	pids="${out#older }"
	name="$(jq -r '.dev_name // empty' "$identity" 2>/dev/null)"
	name="${name:-unknown}"
	printf '[IDENTITY COLLISION] %s (Dev-Name %s) is already in use by another live session in this checkout (pid %s). Do not use that Dev-Name: do not sign with it, check in to #roll-call, or answer @%s. Tell the user, and move this session into its own git worktree.\n' \
		"$identity" "$name" "$pids" "$name"
	;;
esac
exit 0
