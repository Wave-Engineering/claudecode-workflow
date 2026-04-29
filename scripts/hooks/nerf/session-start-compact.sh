#!/usr/bin/env bash
# session-start-compact.sh — CC SessionStart hook (matcher: "compact").
#
# Repaints the nerf statusline indicator after a compact resume so the
# widget reflects the post-compact context size. Paired with
# pre-compact.sh, which clears the stale entry before compaction.
#
# Contract (CC SessionStart hook, matcher: "compact"):
#   stdin:  JSON with .session_id, .transcript_path, .cwd, .source
#   exit:   always 0 (best-effort; never block resume)
#
# Override the binary path with NERF_BIN. Logs to stderr on subprocess
# failure per CLAUDE.md / lesson_best_effort_must_log.md — invisible
# best-effort failures are an anti-pattern.
#
# Issue: cc-workflow#555.

set -uo pipefail

LOG() { printf '[hooks/nerf/session-start-compact] %s\n' "$*" >&2; }

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)

NERF_BIN="${NERF_BIN:-$HOME/.local/bin/nerf-server}"
if [[ ! -x "$NERF_BIN" ]]; then
	LOG "nerf-server not executable at $NERF_BIN — skipping"
	exit 0
fi

if [[ -n "$SESSION_ID" ]]; then
	if ! "$NERF_BIN" refresh-indicator --session-id "$SESSION_ID" 2>/dev/null; then
		LOG "refresh-indicator failed (session_id=$SESSION_ID)"
	fi
else
	if ! "$NERF_BIN" refresh-indicator 2>/dev/null; then
		LOG "refresh-indicator failed (no session_id in stdin)"
	fi
fi

exit 0
