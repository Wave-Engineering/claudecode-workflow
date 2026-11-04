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
# a 1M one alike — once it is measured against the usable window (THE CEILING).
#
# THE CEILING (#1297). Claude Code computes remaining_percentage against the
# MODEL's window, and /autocompact does not change it. With a 400k autocompact
# window on a 1M model, autocompact fires near 367k while the 15% gate waits for
# 850k: autocompact always wins. So when the reading also carries used_tokens,
# window_tokens and model_id, the percentage is recomputed against
# min(window_tokens, autocompact window), less the buffer autocompact fires below
# it. The autocompact window ("400000", "400k" or "1M"; raised to 100k) comes from
# CLAUDE_CODE_AUTO_COMPACT_WINDOW, else .modelSettings[<key>].autoCompactWindow
# in the settings file, for the first key that has one of: model_id as given, then
# with "[1m]" stripped, then canonical (provider prefix, "-vN:M", "@version" and
# "-YYYYMMDD" stripped: "us.anthropic.claude-opus-5-5" → "claude-opus-5-5", #1318),
# else its top-level autoCompactWindow (the pre-2.1.288 form). A missing or malformed
# autocompact window means the model window; one configured for other models but
# matching none of these keys is reported once per session, since it would read
# exactly like no window. A reading without the token fields uses
# remaining_percentage as-is. Known gaps: only the user settings file is read (not
# project, local or managed settings), and model aliases ("opus") are not mapped.
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
# NERF MODES (#1352). nerf (mcp-server-nerf) keeps its config in the project's
# <project>/.claude/nerf.json (CLAUDE_PROJECT_DIR, else the payload cwd) and, in an older nerf,
# in ${NERF_CONFIG_DIR:-/tmp}/nerf-<session_id>.json; nerf_config_file picks the newer of the
# two that exist (#1448). This hook reads .mode and .darts_pct.ouch from it. At or below the
# threshold:
#   ultraviolence (default)  block: run /reseed now, before anything else
#   hurt-me-plenty           block: ask the user whether to /reseed now or after
#                            the current step; do not reseed without the answer
#   not-too-rough            no block: one systemMessage per session advising
#                            /reseed (marker <state dir>/<session_id>.reseed-advised)
# A missing file, unreadable JSON, or a missing or unknown mode is ultraviolence:
# a gate that can't read nerf must never get weaker. Autocompact stays the
# backstop under every mode.
#
# THE THRESHOLD, first match wins: a numeric RESEED_CONTEXT_THRESHOLD_PCT; then
# 100 - .darts_pct.ouch, when ouch is an integer from 1 to 99; then 15.
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
#           report an unavailable reading or an unmatched autocompact window, or
#           to advise a reseed under not-too-rough (a block carries the report in
#           the same object), nothing otherwise
#   exit:   always 0
#
# Env: RESEED_CONTEXT_THRESHOLD_PCT — act at <= this many percent; overrides
#        nerf's ouch dart (see THE THRESHOLD)
#      NERF_CONFIG_DIR (default /tmp) — where the legacy per-session nerf config lives
#      RESEED_CONTEXT_GATE_DISABLED=1 — kill-switch
#      CLAUDE_CONTEXT_STATE_DIR — where the statusline persists readings
#      CLAUDE_CODE_AUTO_COMPACT_WINDOW — autocompact window override (tokens)
#      CLAUDE_SETTINGS_FILE (default ~/.claude/settings.json) — where
#        modelSettings.<model>.autoCompactWindow is read
#      RESEED_AUTOCOMPACT_BUFFER_TOKENS (default 33000) — how far below its
#        window autocompact fires

[[ "${RESEED_CONTEXT_GATE_DISABLED:-0}" == "1" ]] && exit 0

MISS_TURNS=3

INPUT=$(cat 2>/dev/null || true)
field() { printf '%s' "$INPUT" | jq -r "$1" 2>/dev/null || true; }

[[ "$(field '.stop_hook_active // false')" == "true" ]] && exit 0

HOOK_CWD="$(field '.cwd // empty')"
HOOK_CWD="${HOOK_CWD:-$(pwd)}"
[[ -f "$HOOK_CWD/.claude/reseed-armed.json" ]] && exit 0

STATE_DIR="${CLAUDE_CONTEXT_STATE_DIR:-$HOME/.claude/state/context}"
SESSION_ID="$(field '.session_id // empty')"

# THE ARITHMETIC lives in scripts/lib/context-math.sh (#1427), shared with the statusline so the
# two cannot disagree: nerf's mode and darts, the threshold, the autocompact window, and the
# percentage measured against what is usable. It is read here once, from the session's reading
# and nerf's per-session config. Anything unreadable is ultraviolence: this gate never weakens
# because it can't read nerf. The helper is part of the install; without it the gate cannot do
# its sums, and says so rather than go quiet.
CM_LIB="$(dirname "$(readlink -f "$0")")/../../lib/context-math.sh"
if [[ ! -r "$CM_LIB" ]]; then
	jq -cn --arg m "Context reseed gate: cannot load scripts/lib/context-math.sh ($CM_LIB) — the auto-reseed cannot fire until the kit is reinstalled." \
		'{systemMessage: $m}'
	exit 0
fi
# shellcheck source=scripts/lib/context-math.sh
source "$CM_LIB"
READING=""
if [[ "$SESSION_ID" =~ ^[A-Za-z0-9_-]+$ ]]; then
	READING="$STATE_DIR/${SESSION_ID}.json"
fi
# nerf's settings are the project's: <project>/.claude/nerf.json when it exists, else the legacy
# per-session file (#1448). A hook's CLAUDE_PROJECT_DIR is where the session was launched; the
# payload's cwd moves when the agent does.
NERF_FILE="$(nerf_config_file "${CLAUDE_PROJECT_DIR:-$HOOK_CWD}" "$SESSION_ID")"
declare -A CM=()
while IFS='=' read -r k v; do CM[$k]="$v"; done < <(context_math "$READING" "$NERF_FILE" "${CLAUDE_SETTINGS_FILE:-$HOME/.claude/settings.json}")
NERF_MODE="${CM[nerf_mode]:-ultraviolence}"
THRESHOLD="${CM[threshold_pct]:-15}"

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
[[ -f "$READING" ]] || unavailable "none written for this session after $MISS_TURNS turns"

PCT="$(jq -r '.remaining_percentage // empty' "$READING" 2>/dev/null || true)"
[[ "$PCT" =~ ^[0-9]+([.][0-9]+)?$ ]] || unavailable "the reading is malformed"
rm -f "$STATE_DIR/${SESSION_ID}.misses" # a good reading resets the run of misses

# Recompute against what is usable before autocompact fires (the helper did the sums).
NOTE=""
OF=""
if [[ -n "${CM[remaining_pct]}" ]]; then
	PCT="${CM[remaining_pct]}"
	OF=" of the $((CM[usable_tokens] / 1000))k usable before ${CM[ceiling_by]}"
fi
# A window is configured for some model but none of this model's keys: say so once, or a key
# mismatch reads exactly like no window at all.
if [[ -n "${CM[acw_filed]}" ]]; then
	MARK="$STATE_DIR/${SESSION_ID}.acw-unmatched-noted"
	if [[ ! -e "$MARK" ]]; then
		mkdir -p "$STATE_DIR" 2>/dev/null
		: >"$MARK" 2>/dev/null
		NOTE="Context reseed gate: no autoCompactWindow for model \"${CM[model_id]}\" (tried ${CM[acw_keys]}; settings have one for: ${CM[acw_filed]}) — measuring against the model's own window, which autocompact may beat."
	fi
fi

block() {
	jq -cn --arg r "$1" --arg n "$NOTE" '{decision: "block", reason: $r} + (if $n == "" then {} else {systemMessage: $n} end)'
}
note_only() {
	[[ -z "$NOTE" ]] || jq -cn --arg n "$NOTE" '{systemMessage: $n}'
}

if awk -v p="$PCT" -v t="$THRESHOLD" 'BEGIN { exit !(p <= t) }'; then
	AT="Context at ${PCT%.*}% remaining${OF} (threshold ${THRESHOLD}%"
	case "$NERF_MODE" in
	hurt-me-plenty)
		block "$AT, nerf: hurt-me-plenty) — the user chose to be asked first: tell them and ask whether to /reseed now or after the current step; do not reseed without their answer. If they already chose after the current step, finish it, then /reseed."
		;;
	not-too-rough)
		ADVISED="$STATE_DIR/${SESSION_ID}.reseed-advised"
		if [[ -e "$ADVISED" ]]; then
			note_only
		else
			mkdir -p "$STATE_DIR" 2>/dev/null
			: >"$ADVISED" 2>/dev/null
			jq -cn --arg m "$AT, nerf: not-too-rough) — /reseed advised." --arg n "$NOTE" \
				'{systemMessage: ([$m, $n] | map(select(. != "")) | join("\n"))}'
		fi
		;;
	*) block "$AT) — run /reseed now, before anything else." ;;
	esac
else
	note_only
fi
exit 0
