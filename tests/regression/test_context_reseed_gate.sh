#!/usr/bin/env bash
# test_context_reseed_gate.sh — #1225 regression test for
# scripts/hooks/workflow/context-reseed-gate.sh.
#
# Three properties:
#   - the threshold is <=, defaults to 15, and is overridable;
#   - the loop guards hold (stop_hook_active; a reseed already armed), or the
#     gate would block /reseed's own turn and the turn after every block;
#   - a missing or malformed reading never blocks AND is never silent once it
#     persists — reported once per session, after three consecutive misses; and
#     an old reading is still a reading (no age cutoff). A silent inert gate is
#     how nerf reported every session healthy for five months while measuring
#     nothing.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE="$REPO_DIR/scripts/hooks/workflow/context-reseed-gate.sh"

echo "test_context_reseed_gate"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
export CLAUDE_CONTEXT_STATE_DIR="$WORK/state"
# Never the real /tmp: a live nerf config for this session id would change every case.
export NERF_CONFIG_DIR="$WORK/nerf"
unset RESEED_CONTEXT_THRESHOLD_PCT
P="$WORK/proj"
mkdir -p "$P/.claude" "$CLAUDE_CONTEXT_STATE_DIR" "$NERF_CONFIG_DIR"
SID="sess-1"

reading() { # <pct> [age-seconds]
	printf '{"session_id": "%s", "remaining_percentage": %s, "ts": %s}' \
		"$SID" "$1" "$(($(date +%s) - ${2:-0}))" >"$CLAUDE_CONTEXT_STATE_DIR/$SID.json"
}
gate() { # [stop_hook_active] — prints the gate's stdout
	jq -cn --arg s "$SID" --arg c "$P" --argjson a "${1:-false}" \
		'{session_id: $s, cwd: $c, stop_hook_active: $a}' | bash "$GATE"
}
# expect <label> <want: block|silent|message> [env...]
expect() {
	local label="$1" want="$2" out rc got
	shift 2
	out="$(env "$@" bash -c "$(declare -f gate); SID='$SID' P='$P' GATE='$GATE' gate" 2>/dev/null)"
	rc=$?
	if [[ -z "$out" ]]; then
		got=silent
	elif [[ "$(jq -r '.decision // empty' <<<"$out")" == "block" ]]; then
		got=block
	elif [[ -n "$(jq -r '.systemMessage // empty' <<<"$out")" ]]; then
		got=message
	else
		got="other:$out"
	fi
	if [[ "$got" == "$want" && $rc -eq 0 ]]; then pass "$label"; else fail "$label (got $got rc=$rc, want $want)"; fi
}

# --- thresholds -------------------------------------------------------------------
reading 15
expect "15% remaining → block (default threshold 15, inclusive)" block
reading 16
expect "16% remaining → no block" silent
reading 14.6
expect "14.6% remaining → block" block
reading 20
expect "20% with RESEED_CONTEXT_THRESHOLD_PCT=25 → block" block RESEED_CONTEXT_THRESHOLD_PCT=25
reading 20
expect "20% with RESEED_CONTEXT_THRESHOLD_PCT=10 → no block" silent RESEED_CONTEXT_THRESHOLD_PCT=10
reading 10
expect "invalid threshold falls back to 15" block RESEED_CONTEXT_THRESHOLD_PCT=junk
reading 5
expect "kill-switch → no block" silent RESEED_CONTEXT_GATE_DISABLED=1

reading 5
out="$(gate)"
if [[ "$(jq -r .reason <<<"$out")" == *"/reseed"* && "$(jq -r .reason <<<"$out")" == *"5%"* ]]; then
	pass "block reason names the percentage and /reseed"
else
	fail "block reason: $out"
fi

# --- the autocompact ceiling (#1297) -------------------------------------------------
# remaining_percentage is against the MODEL window; /autocompact does not move it.
unset CLAUDE_CODE_AUTO_COMPACT_WINDOW
export CLAUDE_SETTINGS_FILE="$WORK/settings.json"
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading() { # <used> [model] [window] — remaining_percentage is the model-window figure
	local used="$1" model="${2:-claude-opus-5-5}" window="${3:-1000000}"
	jq -n --arg s "$SID" --arg m "$model" --argjson u "$used" --argjson w "$window" --argjson t "$(date +%s)" \
		'{session_id: $s, remaining_percentage: (100 - ($u * 100 / $w | floor)), ts: $t,
		  used_tokens: $u, window_tokens: $w, model_id: $m}' >"$CLAUDE_CONTEXT_STATE_DIR/$SID.json"
}

# Autocompact fires ~33k below its window, so 400k leaves 367k usable: the 15%
# gate fires from ~312k used.
full_reading 345000
expect "345k of 367k usable (5% left) → block, though 65% of 1M remains" block
out="$(gate)"
if [[ "$(jq -r .reason <<<"$out")" == *"367k usable before the 400k autocompact"* ]]; then
	pass "block reason names the usable ceiling and the autocompact window"
else
	fail "ceiling reason: $out"
fi
full_reading 315000
expect "315k of 367k usable (14% left) → block" block
full_reading 305000
expect "305k of 367k usable (16% left) → no block" silent
full_reading 300000
expect "300k of 367k usable (18% left) → no block" silent
full_reading 335000
expect "RESEED_AUTOCOMPACT_BUFFER_TOKENS=0 measures the raw window (335k of 400k, 16%)" silent RESEED_AUTOCOMPACT_BUFFER_TOKENS=0
full_reading 345000 'claude-opus-5-5[1m]'
expect "model_id with [1m] falls back to the base settings key" block

# Provider-qualified ids resolve to the canonical key (#1318: Bedrock's statusline
# says "us.anthropic.claude-opus-5-5"; the gate fell back to 1M and never fired).
for m in us.anthropic.claude-opus-5-5 global.anthropic.claude-opus-5-5 apac.anthropic.claude-opus-5-5 \
	anthropic.claude-opus-5-5-v1:0 'eu.anthropic.claude-opus-5-5-v2:0[1m]' us-gov.anthropic.claude-opus-5-5-v1:0 \
	claude-opus-5-5@20261001 claude-opus-5-5-20261001; do
	full_reading 345000 "$m"
	expect "$m resolves to claude-opus-5-5 (400k) → block" block
done
printf '{"modelSettings": {"us.anthropic.claude-opus-5-5": {"autoCompactWindow": 200000}, "claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 180000 us.anthropic.claude-opus-5-5
expect "an exact key outranks the canonical one (180k of 167k usable → block; 400k would not)" block
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"

# A window configured for other models but matching none of this one's keys is
# reported once per session, not blocked on: it reads exactly like no window.
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*.acw-unmatched-noted
full_reading 345000 claude-other-model
out="$(gate)"
msg="$(jq -r '.systemMessage // empty' <<<"$out")"
if [[ "$(jq -r '.decision // empty' <<<"$out")" != block && "$msg" == *'"claude-other-model"'* && "$msg" == *"settings have one for: claude-opus-5-5"* ]]; then
	pass "unmatched window → reported with the model and the keys, not blocked"
else
	fail "unmatched window: '$out'"
fi
expect "…and only once per session" silent
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*.acw-unmatched-noted
printf '{"modelSettings": {"claude-opus-5-5": {"effortLevel": "medium"}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000
expect "no window configured anywhere → silent (unset, not unmatched)" silent
printf '{"autoCompactWindow": 400000, "modelSettings": {"claude-x": {"autoCompactWindow": 200000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000 claude-other-model
expect "a top-level window applies → block, no unmatched report" block
out="$(gate)"
if [[ -z "$(jq -r '.systemMessage // empty' <<<"$out")" ]]; then pass "…with no systemMessage"; else fail "top-level window reported: '$out'"; fi
full_reading 900000 claude-other-model
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*.acw-unmatched-noted
out="$(gate)"
if [[ "$(jq -r '.decision // empty' <<<"$out")" == block && -n "$(jq -r '.systemMessage // empty' <<<"$out")" ]]; then
	pass "unmatched window on a blocking reading → block carries the report"
else
	fail "block + report: '$out'"
fi
full_reading 260000
expect "CLAUDE_CODE_AUTO_COMPACT_WINDOW overrides settings (260k of 267k usable)" block CLAUDE_CODE_AUTO_COMPACT_WINDOW=300000
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 200000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 160000
expect "200k window: 160k of 167k usable → block before autocompact (~167k)" block
printf '{"autoCompactWindow": 400000}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000
expect "top-level autoCompactWindow (pre-2.1.288 form) is honored" block
printf '{"autoCompactWindow": 200000, "modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 300000
expect "per-model autoCompactWindow outranks the top-level one" silent
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000 claude-other-model
expect "no autocompact setting for the model → 1M window less the buffer (64%), already reported" silent
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 2000000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000
expect "autocompact window above the model window is ignored (min)" silent
printf 'not json' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000
expect "malformed settings → model-window figure, exit 0" silent
full_reading 900000
expect "malformed settings still blocks on the model window (900k of 967k usable, 6%)" block
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": "lots"}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000
expect "non-numeric autocompact window → model-window figure" silent
printf '{"modelSettings": {"claude-opus-5-5": {"autoCompactWindow": 400000}}}' >"$CLAUDE_SETTINGS_FILE"
full_reading 345000
expect "junk CLAUDE_CODE_AUTO_COMPACT_WINDOW falls through to settings (400k → block)" block CLAUDE_CODE_AUTO_COMPACT_WINDOW=junk
full_reading 335000
expect "junk RESEED_AUTOCOMPACT_BUFFER_TOKENS falls back to 33000 (335k: 8%, not 16%)" block RESEED_AUTOCOMPACT_BUFFER_TOKENS=junk
full_reading 450000
expect "used beyond the ceiling floors at 0% → block" block
reading 50
expect "legacy reading (no token fields) ignores the settings ceiling" silent

# The buffer applies to the model's own window too, with no autocompact setting.
full_reading 160000 claude-other-model 200000
expect "native 200k window: 160k of 167k usable → block (raw: 20%, silent)" block
full_reading 830000 claude-other-model
expect "native 1M window: 830k of 967k usable (14%) → block (raw: 17%, silent)" block
# Claude Code's own forms for the env var, and its 100k floor.
full_reading 260000 claude-other-model
expect "CLAUDE_CODE_AUTO_COMPACT_WINDOW=300k is 300000" block CLAUDE_CODE_AUTO_COMPACT_WINDOW=300k
full_reading 345000 claude-other-model
expect "CLAUDE_CODE_AUTO_COMPACT_WINDOW=0.4M is 400000" block CLAUDE_CODE_AUTO_COMPACT_WINDOW=0.4M
full_reading 50000 claude-other-model
expect "CLAUDE_CODE_AUTO_COMPACT_WINDOW=50000 is raised to 100k (50k of 67k usable, 25%)" silent CLAUDE_CODE_AUTO_COMPACT_WINDOW=50000
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*

# --- nerf modes (#1352) -------------------------------------------------------------
# nerf's per-session config picks the behavior at the threshold; its ouch dart sets
# the threshold. Anything unreadable is ultraviolence — today's behavior.
NERF="$NERF_CONFIG_DIR/nerf-$SID.json"
nerf() { printf '%s' "$1" >"$NERF"; } # <json>
# reason_has <label> <substring>... — the gate's block reason contains each
reason_has() {
	local label="$1" out r s
	shift
	out="$(gate)"
	r="$(jq -r '.reason // empty' <<<"$out")"
	for s in "$@"; do
		[[ "$r" == *"$s"* ]] || {
			fail "$label (reason lacks '$s': $out)"
			return
		}
	done
	pass "$label"
}

rm -f "$NERF"
reading 10
reason_has "no nerf file at 10% → 'run /reseed now'" "run /reseed now, before anything else"
nerf '{"mode": "ultraviolence"}'
reason_has "ultraviolence at 10% → 'run /reseed now'" "run /reseed now, before anything else"
nerf '{"mode": "hurt-me-plenty"}'
expect "hurt-me-plenty at 10% → block" block
reason_has "…and the reason says to ask first" "ask" "do not reseed without" "nerf: hurt-me-plenty"
nerf '{"mode": "not-too-rough"}'
out="$(gate)"
if [[ -z "$(jq -r '.decision // empty' <<<"$out")" && "$(jq -r '.systemMessage // empty' <<<"$out")" == *"/reseed advised"* ]]; then
	pass "not-too-rough at 10% → a systemMessage, no block"
else
	fail "not-too-rough: '$out'"
fi
expect "…and nothing on a second Stop" silent
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*.reseed-advised
nerf '{"mode": "nightmare"}'
reason_has "unknown mode → ultraviolence" "run /reseed now, before anything else"
nerf '{"mode": '
reason_has "malformed nerf JSON → ultraviolence" "run /reseed now, before anything else"
nerf '{"darts_pct": {"ouch": 85}}'
reason_has "no mode field → ultraviolence" "run /reseed now, before anything else"

# The threshold: env, then 100 - ouch, then 15.
nerf '{"mode": "ultraviolence", "darts_pct": {"soft": 50, "hard": 60, "ouch": 70}}'
reading 30
expect "ouch 70 → blocks at 30% remaining" block
reason_has "…and names threshold 30%" "threshold 30%"
reading 31
expect "ouch 70 → no block at 31%" silent
reading 30
expect "ouch 70 with RESEED_CONTEXT_THRESHOLD_PCT=15 → no block at 30% (env wins)" silent RESEED_CONTEXT_THRESHOLD_PCT=15
expect "ouch 70 with a junk RESEED_CONTEXT_THRESHOLD_PCT → ouch applies (30%)" block RESEED_CONTEXT_THRESHOLD_PCT=junk
# 18446744073709551685 is 2^64 + 69: it would wrap to 69 in bash arithmetic (31%).
for o in 0 100 '"x"' '"70"' 70.5 18446744073709551685; do
	nerf "{\"darts_pct\": {\"ouch\": $o}}"
	reading 16
	expect "ouch $o → falls back to 15 (no block at 16%)" silent
	reading 15
	expect "ouch $o → falls back to 15 (block at 15%)" block
done

# Above the threshold, every mode is silent.
reading 50
for m in ultraviolence hurt-me-plenty not-too-rough; do
	nerf "{\"mode\": \"$m\"}"
	expect "$m at 50% → no output" silent
done
rm -f "$NERF" "$CLAUDE_CONTEXT_STATE_DIR"/*

# --- loop guards ------------------------------------------------------------------
reading 5
out="$(gate true)"
if [[ -z "$out" ]]; then pass "stop_hook_active → no block"; else fail "stop_hook_active blocked: $out"; fi
printf '{}' >"$P/.claude/reseed-armed.json"
out="$(gate)"
if [[ -z "$out" ]]; then pass "reseed already armed → no block"; else fail "armed reseed blocked: $out"; fi
rm -f "$P/.claude/reseed-armed.json"

# --- an old reading is still a reading -----------------------------------------------
# Remaining context only moves when messages arrive, and every message renders the
# statusline — so an idle session's hours-old reading is exact, not stale.
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*
reading 5 7200
out="$(gate)"
if [[ "$(jq -r '.decision // empty' <<<"$out")" == block ]]; then
	pass "a two-hour-old 5% reading still blocks (no age cutoff)"
else
	fail "old reading did not block: '$out'"
fi

# --- unavailable readings: never block; reported only once a miss PERSISTS -----------
# A session's first Stop can beat its first (debounced) statusline render, so one
# miss is not a fault. Reported on the 3rd consecutive miss, then never again.
rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*
o1="$(gate)"
o2="$(gate)"
o3="$(gate)"
o4="$(gate)"
if [[ -z "$o1" && -z "$o2" ]]; then
	pass "first two misses are silent (a first turn can beat the first render)"
else
	fail "reported too early: '$o1' / '$o2'"
fi
if [[ "$(jq -r '.systemMessage // empty' <<<"$o3")" == *"no remaining-context reading"* && "$(jq -r '.decision // empty' <<<"$o3")" != block ]]; then
	pass "third consecutive miss → reported, not blocked"
else
	fail "third miss: '$o3'"
fi
if [[ -z "$o4" ]]; then pass "…and only once per session"; else fail "repeated the message: $o4"; fi

rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*
gate >/dev/null
gate >/dev/null
reading 50
gate >/dev/null
rm -f "$CLAUDE_CONTEXT_STATE_DIR/$SID.json"
o="$(gate)$(gate)"
if [[ -z "$o" ]]; then
	pass "a good reading resets the run of misses"
else
	fail "misses were not reset by a good reading: '$o'"
fi

rm -f "$CLAUDE_CONTEXT_STATE_DIR"/*
printf '{"remaining_percentage": "lots"}' >"$CLAUDE_CONTEXT_STATE_DIR/$SID.json"
gate >/dev/null
gate >/dev/null
out="$(gate)"
if [[ "$(jq -r '.systemMessage // empty' <<<"$out")" == *malformed* ]]; then
	pass "a persistently malformed reading → reported, not blocked"
else
	fail "malformed reading: '$out'"
fi

out="$(printf '{"cwd": "%s"}' "$P" | bash "$GATE")"
if [[ "$(jq -r '.systemMessage // empty' <<<"$out")" == *"session id"* ]]; then
	pass "no session id → reported, not blocked"
else
	fail "no session id: '$out'"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS assertion(s) failed"
	exit 1
fi
echo "  all assertions passed"
