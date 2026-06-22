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
# This test EXECUTES the actual hook command extracted from the settings template
# against synthetic state.json files — it is behavioural, not a doc-shape check.
# Full retire of the wavemachine_active plumbing is deferred to #751; this test
# pins the interim behaviour so that retire is a deliberate, visible change.

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

# Extract the stall-guard hook command (the only Stop hook keyed on
# wavemachine_active) straight from the template, so the test exercises exactly
# what ships — not a re-typed copy that could drift.
HOOK_CMD=$(jq -r '.hooks.Stop[] | .hooks[] | select(.command | test("wavemachine_active")) | .command' "$SETTINGS")
if [[ -z "$HOOK_CMD" ]]; then
	fail "could not extract the wavemachine_active Stop hook command from $SETTINGS"
	exit 1
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/.claude/status"
STATE="$WORK/.claude/status/state.json"

# Run the hook with CLAUDE_PROJECT_DIR pointed at the synthetic project. Returns
# the hook's stdout (a decision:block JSON object iff it blocks; empty if no-op).
run_hook() {
	CLAUDE_PROJECT_DIR="$WORK" bash -c "$HOOK_CMD" 2>/dev/null
}

write_state() { printf '%s' "$1" >"$STATE"; }

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

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all checks passed"
exit 0
