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
P="$WORK/proj"
mkdir -p "$P/.claude" "$CLAUDE_CONTEXT_STATE_DIR"
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
