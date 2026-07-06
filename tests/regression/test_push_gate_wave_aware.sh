#!/usr/bin/env bash
# test_push_gate_wave_aware.sh — #724: pre-push-test-gate integration-ref exemption.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# The pre-push test gate blocks `git push` unless a per-session test sentinel exists.
# That sentinel heuristic is the WRONG gate for integration pushes inside a wave
# campaign (kahuna/* and wave-*/* are governed by the wave trust gate), and it wrongly
# blocks legitimate no-test (docs/config) waves. This test pins:
#   1. push to kahuna/* / wave-*/* exits 0 with NO sentinel (the exemption),
#   2. push to a protected ref (main / feature/*) still BLOCKS with no sentinel
#      (no safety regression — the load-bearing AC),
#   3. a mixed push (one integration + one protected ref) still BLOCKS (strict rule),
#   4. an existing sentinel still allows any push (pre-existing behavior intact).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE="$REPO_DIR/scripts/hooks/workflow/pre-push-test-gate.sh"
SID="test-724-pushgate-$$"
SENTINEL="/tmp/claude-tests-ran-${SID}"
fail=0

echo "test_push_gate_wave_aware"
echo "──────────────────────────────────────────"

cleanup() { rm -f "$SENTINEL"; }
trap cleanup EXIT

# Run the gate with a given command; capture stdout (block JSON) — exit is always 0
# (the hook signals a block via {"decision":"block"} on stdout, not the exit code).
run_gate() {
	# Explicitly clear WAVE_FLIGHT_ID so the base cases exercise the no-active-wave default,
	# independent of the ambient environment (#848).
	printf '%s' "{\"session_id\":\"$SID\",\"tool_input\":{\"command\":\"$1\"}}" | env -u WAVE_FLIGHT_ID bash "$GATE"
}

# #848: run the gate with an ACTIVE wave id (WAVE_FLIGHT_ID) set.
run_gate_wave() {
	printf '%s' "{\"session_id\":\"$SID\",\"tool_input\":{\"command\":\"$2\"}}" | WAVE_FLIGHT_ID="$1" bash "$GATE"
}
assert_allow_wave() {
	local out
	out="$(run_gate_wave "$1" "$2")"
	if printf '%s' "$out" | grep -q '"decision":"block"'; then
		echo "  [FAIL] expected ALLOW (WAVE_FLIGHT_ID=$1), got BLOCK: $2"
		fail=1
	else
		echo "  [PASS] allow (wave=$1): $2"
	fi
}
assert_block_wave() {
	local out
	out="$(run_gate_wave "$1" "$2")"
	if printf '%s' "$out" | grep -q '"decision":"block"'; then
		echo "  [PASS] block (wave=$1): $2"
	else
		echo "  [FAIL] expected BLOCK (WAVE_FLIGHT_ID=$1), got ALLOW: $2"
		fail=1
	fi
}

# assert_allow: gate output must NOT contain a block decision
assert_allow() {
	local out
	out="$(run_gate "$1")"
	if printf '%s' "$out" | grep -q '"decision":"block"'; then
		echo "  [FAIL] expected ALLOW, got BLOCK: $1"
		fail=1
	else
		echo "  [PASS] allow: $1"
	fi
}

# assert_block: gate output MUST contain a block decision
assert_block() {
	local out
	out="$(run_gate "$1")"
	if printf '%s' "$out" | grep -q '"decision":"block"'; then
		echo "  [PASS] block: $1"
	else
		echo "  [FAIL] expected BLOCK, got ALLOW: $1"
		fail=1
	fi
}

# 1 + 2: NO sentinel — integration refs exempt, protected refs still gate.
cleanup
assert_allow "git push origin kahuna/56"
assert_allow "git push -u origin kahuna/56-quartermaster-docs-labs"
assert_allow "git push origin wave-9101/issue-8"
assert_allow "git push origin HEAD:kahuna/56"
assert_block "git push origin main"
assert_block "git push origin feature/123-foo"

# 3: mixed push (integration + protected) must still BLOCK (strict — never let a
#    protected-ref push ride in on an integration ref in the same command).
assert_block "git push origin main kahuna/56"

# #848: new standard-prefix flight branches (<type>/<issueNum>-<waveId>-<slug>) are exempt ONLY for
# the ACTIVE wave (WAVE_FLIGHT_ID). Never a hand-authored feature/fix branch, never a sibling wave.
cleanup
assert_allow_wave "W-1" "git push origin chore/846-W-1-flight"
assert_allow_wave "W-1" "git push -u origin fix/847-W-1-review-signal"
assert_block_wave "W-1" "git push origin feature/123-foo"          # plain feature branch: no wave infix → BLOCK
assert_block_wave "W-1" "git push origin chore/846-W-12-flight"    # sibling wave W-12 ≠ W-1 → no over-exemption
assert_block "git push origin chore/846-W-1-flight"                # no active wave (WAVE_FLIGHT_ID unset) → safe default BLOCK

# 4: an existing sentinel allows any push (pre-existing behavior unchanged).
touch "$SENTINEL"
assert_allow "git push origin main"
cleanup

echo "──────────────────────────────────────────"
if [[ $fail -eq 0 ]]; then
	echo "  ALL PASS"
	exit 0
fi
echo "  FAILURES"
exit 1
