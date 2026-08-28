#!/usr/bin/env bash
# flightdeck-session-emit.sh — emit a FlightDeck session-lifecycle event (S1.7 / #857, #947).
#
# Wired as SessionStart / Stop / SessionEnd hooks in config/settings.template.json.
# Emits session open / idle / close as a FlightDeck event via the emit CLI, so the
# operator sees live agent sessions on the deck (no agent in the reporting path).
#
# Fire-and-forget: it ALWAYS exits 0 (a hook must never fail a turn) and never
# blocks the session (emit ships in a background thread; unset FLIGHTDECK_INGEST_URL
# ⇒ buffer-only). Claude Code passes the hook JSON on stdin; session_id and cwd are
# read from it best-effort.
#
# Session events are PRESENCE, not work (#947): they carry `activityType: session`
# so the deck renders them in the agent-presence strip, never as campaign cards,
# and `agent` is the Dev-Name from .claude/agent-identity.json — omitted entirely
# (never a fabricated hostname) when no identity resolves, so the deck renders it
# honestly unattributed (#1151, flightdeck#38). The hostname always rides
# separately in its own `host` field.
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

# Best-effort session id + project root: hook stdin JSON (.session_id/.cwd) →
# env → tmux pane → cwd basename.
session=""
root=""
if [ ! -t 0 ]; then
	payload="$(cat 2>/dev/null || true)"
	if [ -n "$payload" ] && command -v jq >/dev/null 2>&1; then
		session="$(printf '%s' "$payload" | jq -r '.session_id // empty' 2>/dev/null || true)"
		root="$(printf '%s' "$payload" | jq -r '.cwd // empty' 2>/dev/null || true)"
	fi
fi
# AX-4 (#1166): the fallback chain below MUST resolve to the SAME value across
# a session's separate open/idle/close hook firings (each a fresh subprocess),
# and to DIFFERENT values for two concurrent agents sharing a project
# directory — collision-resistant AND lifecycle-stable, not just one or the
# other. `$$`/PID would satisfy neither (a fresh PID every firing). Both tiers
# below hold for a whole session's lifetime:
#   - CLAUDE_CODE_SESSION_ID is Claude Code's own ambient session id, set on
#     every Bash tool subprocess for the session's full duration (confirmed
#     via the product changelog, cc-workflow#1165's resolve_session()). NOT
#     the same variable as the now-dead CLAUDE_SESSION_ID this fallback used
#     to check — that name is not a real env var (a skill-body template
#     substitution only), which is why this branch has never actually fired.
#   - TMUX_PANE is this repo's own established per-session identifier
#     elsewhere (skills/reseed/SKILL.md, scripts/hooks/workflow/
#     reseed-revive.sh) — stable for one tmux pane's lifetime, distinct per
#     pane, and this fleet runs one agent per pane by convention.
# `basename "$PWD"` remains the absolute last resort — the original collision
# risk, now narrowed to "not even running under tmux or a Claude Code Bash
# subprocess," a much rarer shape than before.
if [ -z "$session" ]; then
	if [ -n "${FLIGHTDECK_SESSION_ID:-}" ]; then
		session="$FLIGHTDECK_SESSION_ID"
	elif [ -n "${CLAUDE_CODE_SESSION_ID:-}" ]; then
		session="$CLAUDE_CODE_SESSION_ID"
	elif [ -n "${TMUX_PANE:-}" ]; then
		session="tmux-${TMUX_PANE#%}"
	else
		session="$(basename "$PWD")"
	fi
fi
[ -n "$root" ] || root="$PWD"

activity="session:${session}"
host="$(hostname 2>/dev/null || echo unknown)"

# Agent identity (#947 defect 2, honest-degradation fix #1151/flightdeck#38):
# attribute the session to a Dev-Name, never fake one. Canonical file:
# <root>/.claude/agent-identity.json; read-fallback to the legacy
# /tmp/claude-agent-<md5(root)>.json while the fleet cycles. Missing or
# unreadable ⇒ agent stays EMPTY, and the emit call below omits --agent
# entirely — flightdeck#38 gave the deck a real, honest degradation path
# (attributed:false, rendered distinctly, tallied) that doesn't require this
# emitter to manufacture an identity value. Before #38 landed, `agent="$host"`
# was the only available "visible degradation" the deck could render; keeping
# it now would fabricate a fake Dev-Name AND, per #38's own code review,
# nearly always suppress the real degradation signal (on live data v.agent is
# essentially never null, so a deck-side resolver that only degrades on a
# null agent barely ever fires — the honest-omission fix belongs at the
# producer, not the consumer). --host still always ships, unaffected — it is
# a separate, correctly-named field.
agent=""
identity="${root}/.claude/agent-identity.json"
if [ ! -r "$identity" ] && command -v md5sum >/dev/null 2>&1; then
	identity="/tmp/claude-agent-$(printf '%s' "$root" | md5sum | cut -d' ' -f1).json"
fi
if [ -r "$identity" ] && command -v jq >/dev/null 2>&1; then
	dev_name="$(jq -r '.dev_name // empty' "$identity" 2>/dev/null || true)"
	[ -n "$dev_name" ] && agent="$dev_name"
fi

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

# #1151: --agent is genuinely OMITTED (not passed as an empty string) when no
# Dev-Name resolved — an array, not a flat arg list, so the flag+value pair
# only exists when there's a real value to attach it to. Applies to BOTH the
# primary call and the legacy-argument retry below (#1151 AC2).
agent_args=()
[ -n "$agent" ] && agent_args=(--agent "$agent")

# --activity-type / --host are additive (#947). An older installed emit CLI
# rejects unknown flags (argparse exits 2), so retry with the legacy argument set
# rather than silently losing the event during the install window.
emit_event "$kind" \
	--activity-id "$activity" \
	--activity-type "session" \
	"${agent_args[@]}" \
	--host "$host" \
	--phase "session" \
	--label "session-${phase}" >/dev/null 2>&1 ||
	emit_event "$kind" \
		--activity-id "$activity" \
		"${agent_args[@]}" \
		--phase "session" \
		--label "session-${phase}" >/dev/null 2>&1 || true

exit 0
