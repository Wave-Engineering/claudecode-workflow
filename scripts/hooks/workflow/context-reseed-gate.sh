#!/usr/bin/env bash
# context-reseed-gate.sh — CC Stop hook. Blocks the end of a turn when the
# session's remaining context has fallen to the threshold, telling the agent to
# run /reseed before anything else. (#1225)
#
# THE NUMBER. Claude Code hands only the statusline the authoritative,
# window-aware .context_window.remaining_percentage; config/statusline-command.sh
# persists it per session to ${CLAUDE_CONTEXT_STATE_DIR:-~/.claude/state/context}/
# <session_id>.json as {session_id, remaining_percentage, ts}. This hook reads it.
# A percentage, not a token count, so one threshold is right on a 200k window and
# a 1M one alike.
#
# NEVER SILENTLY INERT. A gate that cannot read its input and says nothing is
# indistinguishable from a gate that is happy — that is exactly how nerf measured
# nothing for five months while reporting every session healthy. A missing or
# malformed reading does not block, but it is reported once per session.
# Headless (`claude -p`) sessions have no statusline, so they never have a
# reading; most end before MISS_TURNS Stops, so the gate is SILENT there — and
# deliberately so: a headless run has no human to read a systemMessage.
#
# NO AGE LIMIT, and a miss is reported only after it PERSISTS. The statusline
# renders on conversation events, debounced, so (a) a session's first Stop can
# arrive before the first reading is written, and (b) an idle session's reading
# is old but still exact — remaining context only moves when messages arrive,
# and every message renders. An age cutoff (issue #1225 first proposed 10 min)
# turned both into false "unavailable" reports and spent the once-per-session
# report on them, silencing a later, real failure. So a miss must recur on
# MISS_TURNS consecutive Stops before it is reported.
#
# LOOP GUARDS:
#   - stop_hook_active == true → exit 0. Claude Code's own guard: this Stop is
#     the continuation of a turn a Stop hook already blocked.
#   - <cwd>/.claude/reseed-armed.json present → exit 0. A reseed is already in
#     flight; without this, /reseed's own turn (seed written, /clear sent) would
#     be blocked by the very condition it is resolving.
#
# Contract (CC Stop hook):
#   stdin:  JSON with .session_id, .cwd, .stop_hook_active
#   stdout: {"decision":"block","reason":…} to block, {"systemMessage":…} to
#           report an unavailable reading, nothing otherwise
#   exit:   always 0
#
# Env: RESEED_CONTEXT_THRESHOLD_PCT (default 15) — block at <= this many percent
#      RESEED_CONTEXT_GATE_DISABLED=1 — kill-switch
#      CLAUDE_CONTEXT_STATE_DIR — where the statusline persists readings

[[ "${RESEED_CONTEXT_GATE_DISABLED:-0}" == "1" ]] && exit 0

MISS_TURNS=3
DEFAULT_THRESHOLD=15

INPUT=$(cat 2>/dev/null || true)
field() { printf '%s' "$INPUT" | jq -r "$1" 2>/dev/null || true; }

[[ "$(field '.stop_hook_active // false')" == "true" ]] && exit 0

HOOK_CWD="$(field '.cwd // empty')"
HOOK_CWD="${HOOK_CWD:-$(pwd)}"
[[ -f "$HOOK_CWD/.claude/reseed-armed.json" ]] && exit 0

THRESHOLD="${RESEED_CONTEXT_THRESHOLD_PCT:-$DEFAULT_THRESHOLD}"
[[ "$THRESHOLD" =~ ^[0-9]+([.][0-9]+)?$ ]] || THRESHOLD="$DEFAULT_THRESHOLD"

STATE_DIR="${CLAUDE_CONTEXT_STATE_DIR:-$HOME/.claude/state/context}"
SESSION_ID="$(field '.session_id // empty')"

# A miss: count it, and report once per session after MISS_TURNS consecutive
# misses. Without a usable session id there is nowhere to count, so report at once.
unavailable() {
	local why="$1" misses_file misses marker
	if [[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
		marker="$STATE_DIR/${SESSION_ID}.unavailable-noted"
		[[ -e "$marker" ]] && exit 0
		mkdir -p "$STATE_DIR" 2>/dev/null
		misses_file="$STATE_DIR/${SESSION_ID}.misses"
		misses=$(($(cat "$misses_file" 2>/dev/null || echo 0) + 1))
		if ((misses < MISS_TURNS)); then
			printf '%s\n' "$misses" >"$misses_file" 2>/dev/null
			exit 0
		fi
		rm -f "$misses_file"
		: >"$marker" 2>/dev/null
	fi
	jq -cn --arg m "Context reseed gate: no remaining-context reading ($why) — the ${THRESHOLD}% auto-reseed cannot fire until the statusline persists one." \
		'{systemMessage: $m}'
	exit 0
}

[[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]+$ ]] || unavailable "no usable session id"
READING="$STATE_DIR/${SESSION_ID}.json"
[[ -f "$READING" ]] || unavailable "none written for this session after $MISS_TURNS turns"

PCT="$(jq -r '.remaining_percentage // empty' "$READING" 2>/dev/null || true)"
[[ "$PCT" =~ ^[0-9]+([.][0-9]+)?$ ]] || unavailable "the reading is malformed"
rm -f "$STATE_DIR/${SESSION_ID}.misses" # a good reading resets the run of misses

if awk -v p="$PCT" -v t="$THRESHOLD" 'BEGIN { exit !(p <= t) }'; then
	jq -cn --arg r "Context at ${PCT%.*}% remaining (threshold ${THRESHOLD}%) — run /reseed now, before anything else." \
		'{decision: "block", reason: $r}'
fi
exit 0
