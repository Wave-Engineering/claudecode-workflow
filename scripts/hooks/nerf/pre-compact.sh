#!/usr/bin/env bash
# pre-compact.sh — CC PreCompact hook for nerf statusline.
#
# Wipes the stale `nerf:` entry from the shared statusline file before
# compaction replaces the conversation context. Without this, the widget
# keeps displaying the pre-compact token count (e.g. 126%) until the next
# nerf_* MCP tool call repaints it. Paired with session-start-compact.sh,
# which paints a fresh indicator after the compact resume.
#
# Contract (CC PreCompact hook):
#   stdin:  JSON with .session_id, .transcript_path, .cwd, .trigger
#   exit:   always 0 (best-effort; never block compaction)
#
# Override the binary path with NERF_BIN. Logs to stderr on subprocess
# failure per CLAUDE.md / lesson_best_effort_must_log.md — invisible
# best-effort failures are an anti-pattern.
#
# Issue: cc-workflow#555.

set -uo pipefail

LOG() { printf '[hooks/nerf/pre-compact] %s\n' "$*" >&2; }

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)

NERF_BIN="${NERF_BIN:-$HOME/.local/bin/nerf-server}"
if [[ ! -x "$NERF_BIN" ]]; then
	LOG "nerf-server not executable at $NERF_BIN — skipping"
	exit 0
fi

if [[ -n "$SESSION_ID" ]]; then
	if ! "$NERF_BIN" clear-indicator --session-id "$SESSION_ID" 2>/dev/null; then
		LOG "clear-indicator failed (session_id=$SESSION_ID)"
	fi
else
	if ! "$NERF_BIN" clear-indicator 2>/dev/null; then
		LOG "clear-indicator failed (no session_id in stdin)"
	fi
fi

exit 0
