#!/usr/bin/env bash
# test_wavemachine_stall_guard_async_aware.sh — regression test for cc-workflow#736.
#
# The inter-wave stall-guard is the Stop hook in config/settings.template.json
# keyed on wavemachine_active. In the legacy SYNCHRONOUS model the driver looped
# `/nextwave auto` in-session, so any turn-end while a campaign was active was a
# stall. In the dynamic-workflows model (migration doc §5) the per-wave Workflow
# runs ASYNC: the driver launches it, ENDS its turn, and is re-invoked on the
# completion verdict. During that legitimate await the old guard false-fired on
# EVERY async wave (and during manual promotion adjudication).
#
# The #736 interim fix makes the guard ASYNC-AWARE: it reads
# current_action.action and NO-OPs on a legitimate async-await (awaiting-verdict),
# human pause (hold), or in-progress promotion (promoting); it still BLOCKS a
# genuinely-synchronous gap (wavemachine_active=true with no in-flight marker).
#
# #1109 moved the guard into scripts/hooks/workflow/wavemachine-stall-guard.sh
# and made STALE state (last_updated older than 24 h, or unreadable) never block:
# it gets a systemMessage telling the human to verify instead.
#
# This test EXECUTES the script the settings template's Stop hook names, against
# synthetic state.json files — it is behavioural, not a doc-shape check. Full
# retire of the wavemachine_active plumbing is deferred to #751; this test pins
# the interim behaviour so that retire is a deliberate, visible change.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SETTINGS="$REPO_DIR/config/settings.template.json"

FAILS=0
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_wavemachine_stall_guard_async_aware (#736)"
echo "──────────────────────────────────────────"

for tool in jq; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		echo "  [SKIP] $tool not on PATH — cannot exercise the hook"
		exit 0
	fi
done

if [[ ! -f "$SETTINGS" ]]; then
	fail "settings template not found: $SETTINGS"
	exit 1
fi

# Find the stall-guard script through the template's Stop hook that names it, so
# the test exercises exactly what ships — not a re-typed copy that could drift.
HOOK_CMD=$(jq -r '.hooks.Stop[] | .hooks[] | select(.command | test("wavemachine-stall-guard\\.sh")) | .command' "$SETTINGS")
if [[ -z "$HOOK_CMD" ]]; then
	fail "no Stop hook naming wavemachine-stall-guard.sh in $SETTINGS"
	exit 1
fi
if jq -e '[.hooks.Stop[] | .hooks[] | select(.command | test("wavemachine_active"))] | length > 0' "$SETTINGS" >/dev/null; then
	fail "an inline wavemachine_active Stop command is still in $SETTINGS (#1109)"
fi
GUARD="$REPO_DIR/scripts/hooks/${HOOK_CMD#\~/.claude/scripts/hooks/}"
if [[ ! -x "$GUARD" ]]; then
	fail "the template's guard does not resolve to an executable in the repo: $GUARD"
	exit 1
fi

# The script's threshold must equal state.py's lease threshold (#1109, #1110).
sh_stale=$(sed -n 's/^STALE_SECONDS=\([0-9]*\)$/\1/p' "$GUARD")
py_stale=$(sed -n 's/^WAVEMACHINE_STALE_SECONDS = \([0-9]*\)$/\1/p' "$REPO_DIR/src/wave_status/state.py")
if [[ -n "$sh_stale" && "$sh_stale" == "$py_stale" ]]; then
	pass "STALE_SECONDS ($sh_stale) equals WAVEMACHINE_STALE_SECONDS in state.py"
else
	fail "STALE_SECONDS '$sh_stale' != WAVEMACHINE_STALE_SECONDS '$py_stale'"
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/.claude/status"
STATE="$WORK/.claude/status/state.json"

# Run the hook with CLAUDE_PROJECT_DIR pointed at the synthetic project. Returns
# the hook's stdout (a decision:block JSON object iff it blocks; a systemMessage
# on stale state; empty if no-op).
run_hook() {
	CLAUDE_PROJECT_DIR="$WORK" "$GUARD" </dev/null 2>/dev/null
}
# The same, as Claude Code re-fires the hook after a block it already obeyed.
run_hook_nudged() {
	printf '%s' '{"hook_event_name": "Stop", "stop_hook_active": true}' |
		CLAUDE_PROJECT_DIR="$WORK" "$GUARD" 2>/dev/null
}

FRESH=$(date -u +%Y-%m-%dT%H:%M:%SZ)
MINUTE_AGO=$(date -u -d '1 minute ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-1M +%Y-%m-%dT%H:%M:%SZ)
STALE=$(date -u -d '95 days ago' +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -v-95d +%Y-%m-%dT%H:%M:%SZ)

# Write a state fixture. A bare object gets a fresh last_updated, so the
# block-shaped cases test the same behaviour as before #1109.
write_state() {
	printf '%s' "$1" | jq -c --arg ts "$FRESH" 'if has("last_updated") then . else .last_updated = $ts end' >"$STATE"
}

# --- Case (a): wavemachine_active + legitimate async/human in-flight markers
#     MUST NOT block (no output) -------------------------------------------------
for action in awaiting-verdict hold promoting; do
	write_state "{\"wavemachine_active\": true, \"current_action\": {\"action\": \"$action\"}}"
	out=$(run_hook)
	if [[ -z "$out" ]]; then
		pass "active + current_action=$action → no block (legitimate await/pause/promote)"
	else
		fail "active + current_action=$action → BLOCKED (false-fire on legitimate async state): $out"
	fi
done

# --- Case (b): wavemachine_active + a synchronous/launch-shaped gap (no in-flight
#     marker) MUST still block ---------------------------------------------------
for action in launching idle "" merging; do
	write_state "{\"wavemachine_active\": true, \"current_action\": {\"action\": \"$action\"}}"
	out=$(run_hook)
	if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
		pass "active + current_action='$action' → blocks (synchronous gap, stall-guard intact)"
	else
		fail "active + current_action='$action' → did NOT block (stall-guard lost; #600 regression): '$out'"
	fi
done

# current_action entirely absent (legacy state shape) — active means block.
write_state '{"wavemachine_active": true}'
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "active + no current_action field → blocks (legacy state shape; stall-guard intact)"
else
	fail "active + no current_action field → did NOT block: '$out'"
fi

# --- Case (c): not active / no state.json → never block -----------------------
write_state '{"wavemachine_active": false, "current_action": {"action": "idle"}}'
out=$(run_hook)
if [[ -z "$out" ]]; then
	pass "wavemachine_active=false → no block"
else
	fail "wavemachine_active=false → BLOCKED (must only fire during an active campaign): $out"
fi

write_state '{"current_action": {"action": "idle"}}'
out=$(run_hook)
if [[ -z "$out" ]]; then
	pass "no wavemachine_active field → no block"
else
	fail "no wavemachine_active field → BLOCKED: $out"
fi

rm -f "$STATE"
out=$(run_hook)
if [[ -z "$out" ]]; then
	pass "no state.json → no block"
else
	fail "no state.json → BLOCKED: $out"
fi

# --- Supersession: the block reason must NOT carry the legacy synchronous
#     '/nextwave auto again' instruction (the false premise #736 removes) -------
write_state '{"wavemachine_active": true, "current_action": {"action": "idle"}}'
reason=$(run_hook | jq -r '.reason // ""')
if echo "$reason" | grep -qiE "invoke /nextwave auto again|/nextwave auto.*again"; then
	fail "block reason still carries the legacy '/nextwave auto again' synchronous instruction (#736 not fixed)"
else
	pass "block reason no longer carries the legacy '/nextwave auto again' instruction"
fi
if echo "$reason" | grep -qiE "awaiting-verdict|async"; then
	pass "block reason references the async-aware advance path"
else
	fail "block reason does not reference the async advance path — guidance is stale"
fi

# --- Case (d): staleness (#1109). Stale state never blocks; it warns. --------
write_state "{\"wavemachine_active\": true, \"current_action\": {\"action\": \"idle\"}, \"last_updated\": \"$STALE\", \"wavemachine_session_id\": \"old-sess\"}"
out=$(run_hook)
if echo "$out" | jq -e '(has("decision") | not) and (.systemMessage | test("stale") and test("verify") and test("old-sess"))' >/dev/null 2>&1; then
	pass "active + idle + 95-day-old last_updated → systemMessage (stale, verify, owner), no block"
else
	fail "active + idle + stale → expected a stale/verify systemMessage and no decision: '$out'"
fi

write_state '{"wavemachine_active": true, "current_action": {"action": "idle"}, "last_updated": null}'
out=$(run_hook)
if [[ -n "$out" ]] && echo "$out" | jq -e 'has("decision") | not' >/dev/null 2>&1; then
	pass "active + idle + no last_updated → no block"
else
	fail "active + idle + no last_updated → expected a non-blocking message: '$out'"
fi

write_state "{\"wavemachine_active\": true, \"current_action\": {\"action\": \"idle\"}, \"last_updated\": \"$MINUTE_AGO\"}"
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "active + idle + 1-minute-old last_updated → blocks (unchanged)"
else
	fail "active + idle + fresh → did NOT block: '$out'"
fi

write_state "{\"wavemachine_active\": true, \"current_action\": {\"action\": \"idle\"}, \"last_updated\": \"${MINUTE_AGO%Z}.123Z\"}"
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "fractional-second last_updated parses as fresh → blocks"
else
	fail "fractional-second last_updated → did NOT block (read as unparseable?): '$out'"
fi

write_state "{\"wavemachine_active\": true, \"current_action\": {\"action\": \"awaiting-verdict\"}, \"last_updated\": \"$STALE\"}"
out=$(run_hook)
if [[ -z "$out" ]]; then
	pass "active + awaiting-verdict + stale → silent"
else
	fail "active + awaiting-verdict + stale → expected silence: '$out'"
fi

# --- Case (e): the driver's own field (#1205). The incident replayed: the
#     driver awaits P1W1 while the Workflow's agents overwrite current_action. -
for action in waiting-ci in-flight merging planning; do
	write_state "{\"wavemachine_active\": true, \"driver_action\": {\"action\": \"awaiting-verdict\", \"wave_id\": \"P1W1\"}, \"current_action\": {\"action\": \"$action\"}, \"waves\": {\"P1W1\": {\"status\": \"in_progress\"}}}"
	out=$(run_hook)
	if [[ -z "$out" ]]; then
		pass "driver awaiting P1W1 (in_progress) + in-wave current_action=$action → silent (#1205)"
	else
		fail "driver awaiting P1W1 (in_progress) + current_action=$action → FALSE-FIRED (#1205): $out"
	fi
done

for st in completed held; do
	write_state "{\"wavemachine_active\": true, \"driver_action\": {\"action\": \"awaiting-verdict\", \"wave_id\": \"P1W1\"}, \"current_action\": {\"action\": \"idle\"}, \"waves\": {\"P1W1\": {\"status\": \"$st\"}}}"
	out=$(run_hook)
	if echo "$out" | jq -e --arg st "$st" '.decision == "block" and (.reason | test("P1W1") and test($st) and test("act on it now") and test("launch nothing"))' >/dev/null 2>&1; then
		pass "driver awaiting P1W1, wave $st → blocks once, naming the wave, worded for verdict-or-not"
	else
		fail "driver awaiting P1W1, wave $st → expected a block naming the finished wave: '$out'"
	fi
	# The Workflow marks the wave before it returns its verdict, so the nudge
	# must not repeat: on the re-fire (stop_hook_active) the stop goes through.
	out=$(run_hook_nudged)
	if [[ -z "$out" ]]; then
		pass "driver awaiting P1W1, wave $st, stop_hook_active → silent (no loop in the Workflow tail)"
	else
		fail "driver awaiting P1W1, wave $st, stop_hook_active → expected silence: '$out'"
	fi
done

write_state '{"wavemachine_active": true, "driver_action": {"action": "awaiting-verdict", "wave_id": "P9W9"}, "current_action": {"action": "idle"}, "waves": {}}'
out=$(run_hook)
if [[ -z "$out" ]]; then
	pass "driver awaiting a wave with no entry yet → silent"
else
	fail "driver awaiting a wave with no entry → expected silence: '$out'"
fi

write_state '{"wavemachine_active": true, "driver_action": {"action": "launching", "wave_id": "P1W2"}, "current_action": {"action": "awaiting-verdict"}}'
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "driver_action=launching → blocks, whatever current_action says"
else
	fail "driver_action=launching → did NOT block: '$out'"
fi

for action in hold promoting; do
	write_state "{\"wavemachine_active\": true, \"driver_action\": {\"action\": \"$action\", \"wave_id\": \"P1W1\"}, \"current_action\": {\"action\": \"merging\"}}"
	out=$(run_hook)
	if [[ -z "$out" ]]; then
		pass "driver_action=$action → silent"
	else
		fail "driver_action=$action → expected silence: '$out'"
	fi
done

# promoting is sticky: nothing overwrites driver_action once the wave is
# promoted, so a promoted wave with no next launch is the #600 stall.
write_state '{"wavemachine_active": true, "driver_action": {"action": "promoting", "wave_id": "P1W1"}, "current_action": {"action": "waiting-ci"}, "waves": {"P1W1": {"status": "in_progress"}}}'
out=$(run_hook)
if [[ -z "$out" ]]; then
	pass "driver promoting P1W1, wave still in_progress → silent"
else
	fail "driver promoting P1W1 (in_progress) → expected silence: '$out'"
fi

write_state '{"wavemachine_active": true, "driver_action": {"action": "promoting", "wave_id": "P1W1"}, "current_action": {"action": "idle"}, "waves": {"P1W1": {"status": "completed"}}}'
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block" and (.reason | test("P1W1") and test("promoted") and test("next wave"))' >/dev/null 2>&1; then
	pass "driver promoting P1W1, wave completed → blocks: launch the next wave"
else
	fail "driver promoting P1W1, wave completed → expected a block (the #600 stall): '$out'"
fi
# No once-rule here: the driver writes promoting only once it holds the verdict.
out=$(run_hook_nudged)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "driver promoting P1W1, wave completed, stop_hook_active → still blocks"
else
	fail "driver promoting P1W1, wave completed, stop_hook_active → did NOT block (#600 hole): '$out'"
fi

# held after a PASS is a promote soft-fail (not integrated) or an interactive
# promotion: never "launch the next wave".
write_state '{"wavemachine_active": true, "driver_action": {"action": "promoting", "wave_id": "P1W1"}, "current_action": {"action": "idle"}, "waves": {"P1W1": {"status": "held"}}}'
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block" and (.reason | test("P1W1") and test("Do NOT launch") and test("wave-status hold"))' >/dev/null 2>&1; then
	pass "driver promoting P1W1, wave held → blocks toward hold, never launch"
else
	fail "driver promoting P1W1, wave held → expected a hold-shaped block: '$out'"
fi
if echo "$out" | jq -e '.reason | test("Launch it now")' >/dev/null 2>&1; then
	fail "driver promoting P1W1, wave held → reason tells the driver to launch a non-integrated wave"
else
	pass "driver promoting P1W1, wave held → reason does not say launch"
fi
out=$(run_hook_nudged)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "driver promoting P1W1, wave held, stop_hook_active → still blocks"
else
	fail "driver promoting P1W1, wave held, stop_hook_active → did NOT block: '$out'"
fi

# The #600 launch stall is NOT a one-time nudge: it blocks on the re-fire too.
write_state '{"wavemachine_active": true, "driver_action": {"action": "launching", "wave_id": "P1W2"}}'
out=$(run_hook_nudged)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "driver_action=launching, stop_hook_active → still blocks"
else
	fail "driver_action=launching, stop_hook_active → did NOT block: '$out'"
fi

write_state "{\"wavemachine_active\": true, \"driver_action\": {\"action\": \"awaiting-verdict\", \"wave_id\": \"P1W1\"}, \"waves\": {\"P1W1\": {\"status\": \"completed\"}}, \"last_updated\": \"$STALE\"}"
out=$(run_hook)
if echo "$out" | jq -e '(has("decision") | not) and (.systemMessage | test("stale"))' >/dev/null 2>&1; then
	pass "a finished-wave stall on stale state → systemMessage, not a block"
else
	fail "a finished-wave stall on stale state → expected a stale systemMessage: '$out'"
fi

printf 'not json' >"$STATE"
out=$(run_hook)
rc=$?
if [[ -z "$out" && $rc -eq 0 ]]; then
	pass "unparseable state.json → exit 0, silent"
else
	fail "unparseable state.json → rc=$rc out='$out'"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all checks passed"
exit 0
