#!/usr/bin/env bash
# test_wave_engine_e2e_smoke.sh — #725 Wave Automation Restoration: the minimal
# end-to-end SMOKE harness (the linchpin — wave-engine live coverage was zero).
#
# It drives a 2-wave campaign through the REAL wave-status CLI on a throwaway git
# fixture, and runs the REAL inter-wave stall-guard Stop hook (extracted from the
# shipped settings template) at the campaign's turn-end boundaries. It proves the
# bootstrap fixes hold END-TO-END in a campaign lifecycle (not just in isolation):
#
#   #736 — at the async-await turn-end (current_action=awaiting-verdict) the
#          stall-guard NO-OPs (the campaign legitimately awaits the verdict);
#          a genuine synchronous stall still BLOCKS (#600 protection intact).
#   #636 — a waiting-ci heartbeat set mid-campaign does NOT survive wavemachine-stop:
#          the campaign-exit finally resets current_action to idle.
#   #628 — the campaign stays observable (`wave-status show` works at terminal).
#   lifecycle — the campaign reaches a clean terminal: both waves completed, both
#          issues closed, wavemachine ownership cleared.
#
# No live agents, no network, no new repo — a deterministic CLI+hook drive.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SETTINGS="$REPO_DIR/config/settings.template.json"

FAILS=0
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_wave_engine_e2e_smoke (#725)"
echo "──────────────────────────────────────────"

for tool in jq git python3; do
	if ! command -v "$tool" >/dev/null 2>&1; then
		echo "  [SKIP] $tool not on PATH — cannot run the e2e smoke"
		exit 0
	fi
done
if [[ ! -f "$SETTINGS" ]]; then
	fail "settings template not found: $SETTINGS"
	exit 1
fi

# The real stall-guard hook command, extracted from what ships (no re-typed copy).
HOOK_CMD=$(jq -r '.hooks.Stop[] | .hooks[] | select(.command | test("wavemachine_active")) | .command' "$SETTINGS")
if [[ -z "$HOOK_CMD" ]]; then
	fail "could not extract the wavemachine_active Stop hook from $SETTINGS"
	exit 1
fi

FIX="$(mktemp -d)"
trap 'rm -rf "$FIX"' EXIT
# wave-status resolves its root via `git rev-parse` — the fixture must be a repo.
git -C "$FIX" init -q
git -C "$FIX" config user.email smoke@example.com
git -C "$FIX" config user.name smoke

# Minimal 2-wave plan (one issue per wave keeps the coarse lifecycle the subject).
cat >"$FIX/plan.json" <<'JSON'
{
  "project": "e2e-smoke",
  "base_branch": "main",
  "master_issue": 1,
  "phases": [
    { "name": "P1", "waves": [
      { "id": "wave-1", "name": "W1", "issues": [ { "number": 101, "title": "I101", "deps": [] } ] },
      { "id": "wave-2", "name": "W2", "issues": [ { "number": 102, "title": "I102", "deps": [] } ] }
    ] }
  ]
}
JSON

# Drive the real CLI from inside the fixture repo.
ws() { (cd "$FIX" && PYTHONPATH="$REPO_DIR/src" python3 -m wave_status "$@" >/dev/null 2>&1); }
ws_out() { (cd "$FIX" && PYTHONPATH="$REPO_DIR/src" python3 -m wave_status "$@" 2>&1); }
# The hook reads ${CLAUDE_PROJECT_DIR}/.claude/status/state.json.
run_hook() { CLAUDE_PROJECT_DIR="$FIX" bash -c "$HOOK_CMD" 2>/dev/null; }
state_get() { jq -r "$1" "$FIX/.claude/status/state.json" 2>/dev/null; }

# ── Campaign init + start ─────────────────────────────────────────────────────
if ws init plan.json; then pass "init: state from plan"; else fail "init failed"; fi
ws wavemachine-start --launcher main
[[ "$(state_get '.wavemachine_active')" == "true" ]] &&
	pass "wavemachine-start: active flag set" || fail "wavemachine_active not set after start"

# ── Per-wave coarse lifecycle, with the hook exercised at the async-await ──────
drive_wave() { # $1 wave-id  $2 issue
	local wave="$1" issue="$2"
	ws set-current "$wave"
	ws preflight
	ws planning
	ws launching "$wave"
	ws awaiting-verdict "$wave"   # driver launches the async Workflow + ends its turn HERE

	# #736 E2E: the turn ends in awaiting-verdict → the stall-guard MUST NOT fire.
	local out
	out=$(run_hook)
	if [[ -z "$out" ]]; then
		pass "[$wave] async-await turn-end → stall-guard no-ops (#736 e2e)"
	else
		fail "[$wave] async-await turn-end → stall-guard FALSE-FIRED (#736 regression): $out"
	fi

	# A CI-polling heartbeat lands during promotion (this is the value that used to linger).
	ws waiting-ci "PR #$issue attempt 1: 1/1 passed"
	ws promoting "$wave"
	ws record-mr "$issue" "#$((issue + 900))"
	ws close-issue "$issue"
	ws complete
}

drive_wave wave-1 101
drive_wave wave-2 102

# ── Negative control: a genuine synchronous stall still BLOCKS (#600 intact) ───
ws set-current wave-2   # any active state...
(cd "$FIX" && PYTHONPATH="$REPO_DIR/src" python3 -m wave_status set-current wave-2 >/dev/null 2>&1)
# Force a synchronous-shaped action with the campaign still active.
tmp=$(jq '.wavemachine_active=true | .current_action={"action":"idle","label":"idle","detail":""}' "$FIX/.claude/status/state.json")
printf '%s' "$tmp" >"$FIX/.claude/status/state.json"
out=$(run_hook)
if echo "$out" | jq -e '.decision == "block"' >/dev/null 2>&1; then
	pass "synchronous gap while active → stall-guard BLOCKS (#600 protection intact)"
else
	fail "synchronous gap while active → did NOT block (stall-guard lost): '$out'"
fi

# Re-establish a lingering waiting-ci right before exit (the #636 scenario).
tmp=$(jq '.wavemachine_active=true | .current_action={"action":"waiting-ci","label":"waiting-ci","detail":"stale"}' "$FIX/.claude/status/state.json")
printf '%s' "$tmp" >"$FIX/.claude/status/state.json"

# ── Terminal: campaign-exit finally ───────────────────────────────────────────
ws wavemachine-stop

# #636 E2E: the stale waiting-ci does NOT survive campaign exit.
[[ "$(state_get '.current_action.action')" == "idle" ]] &&
	pass "wavemachine-stop: current_action reset to idle, stale waiting-ci cleared (#636 e2e)" ||
	fail "wavemachine-stop left current_action='$(state_get '.current_action.action')' (#636 regression)"
# Ownership cleared.
[[ "$(state_get '.wavemachine_active // "absent"')" == "absent" ]] &&
	pass "wavemachine-stop: ownership flag cleared" || fail "wavemachine_active still present after stop"
# Guard silent once inactive.
out=$(run_hook)
[[ -z "$out" ]] && pass "post-campaign (inactive) → stall-guard silent" ||
	fail "post-campaign stall-guard fired while inactive: $out"

# ── Lifecycle terminal state ──────────────────────────────────────────────────
[[ "$(state_get '.waves["wave-1"].status')" == "completed" ]] &&
	pass "wave-1 completed" || fail "wave-1 not completed: $(state_get '.waves["wave-1"].status')"
[[ "$(state_get '.waves["wave-2"].status')" == "completed" ]] &&
	pass "wave-2 completed" || fail "wave-2 not completed: $(state_get '.waves["wave-2"].status')"
[[ "$(state_get '.issues["101"].status')" == "closed" ]] &&
	pass "issue 101 closed" || fail "issue 101 not closed: $(state_get '.issues["101"].status')"
[[ "$(state_get '.issues["102"].status')" == "closed" ]] &&
	pass "issue 102 closed" || fail "issue 102 not closed: $(state_get '.issues["102"].status')"

# ── #628 E2E: the campaign stayed observable ─────────────────────────────────
show_out=$(ws_out show)
if [[ -n "$show_out" ]] && echo "$show_out" | grep -qiE "e2e-smoke|wave"; then
	pass "wave-status show produces observable output at terminal (#628 surface)"
else
	fail "wave-status show produced no observable output: '$show_out'"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all e2e smoke checks passed"
exit 0
