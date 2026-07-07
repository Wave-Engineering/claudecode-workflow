#!/usr/bin/env bash
# flightdeck-session-emit.sh — emit a FlightDeck session-lifecycle event (S1.7 / #857).
#
# Wired as SessionStart / Stop / SessionEnd hooks in config/settings.template.json.
# Emits session open / idle / close as a FlightDeck event via the emit CLI, so the
# operator sees live agent sessions on the deck (no agent in the reporting path).
#
# Fire-and-forget: it ALWAYS exits 0 (a hook must never fail a turn) and never
# blocks the session (emit ships in a background thread; unset FLIGHTDECK_INGEST_URL
# ⇒ buffer-only). Claude Code passes the hook JSON on stdin; session_id is read
# from it best-effort.
#
# Usage: flightdeck-session-emit.sh [open|idle|close]   (default: idle)

set -uo pipefail

phase="${1:-idle}"

# Session phase → event kind.
case "$phase" in
open) kind="activity_start" ;;
close) kind="activity_end" ;;
idle | *) kind="step" ;;
esac

# Best-effort session id: hook stdin JSON (.session_id) → env → cwd basename.
session=""
if [ ! -t 0 ]; then
	payload="$(cat 2>/dev/null || true)"
	if [ -n "$payload" ] && command -v jq >/dev/null 2>&1; then
		session="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null || true)"
	fi
fi
if [ -z "$session" ]; then
	session="${FLIGHTDECK_SESSION_ID:-${CLAUDE_SESSION_ID:-$(basename "$PWD")}}"
fi

activity="session:${session}"
host="$(hostname 2>/dev/null || echo unknown)"

# Locate the emit CLI. FLIGHTDECK_EMIT_CMD overrides (DI-seam for tests / a
# pinned interpreter); else the installed console command; else the module.
emit_event() {
	if [ -n "${FLIGHTDECK_EMIT_CMD:-}" ]; then
		# shellcheck disable=SC2086 # intentional word-split of the command prefix
		$FLIGHTDECK_EMIT_CMD "$@"
	elif command -v wave-status >/dev/null 2>&1; then
		wave-status emit "$@"
	else
		python3 -m wave_status.events.emit "$@"
	fi
}

emit_event "$kind" \
	--activity-id "$activity" \
	--agent "$host" \
	--phase "session" \
	--label "session-${phase}" >/dev/null 2>&1 || true

exit 0
