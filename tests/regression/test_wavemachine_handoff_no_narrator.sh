#!/usr/bin/env bash
# test_wavemachine_handoff_no_narrator.sh — regression test for issue #600.
#
# /wavemachine SKILL.md must structurally forbid inter-wave narrator gaps.
# After `/nextwave auto` returns OK, the next assistant message MUST be a
# tool-use block (status-panel regen + discord-status-post + the next
# iteration's wave_health_check), NOT narrative text. This is "Bug B" from
# Plan #581 campaign A — distinct from the sub-agent-level Prime stall in
# that the OUTER LOOP itself stalls when the agent emits prose between
# waves instead of looping cleanly.
#
# This is a doc-shape test (analogous to test_wavemachine_preflight_tools_check.sh)
# because the contract is behavioural instruction the agent follows, not Bash
# code we can execute. If a future edit silently weakens any of the three
# load-bearing pieces below, this test fails before merge.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/wavemachine/SKILL.md"
SETTINGS="$REPO_DIR/config/settings.template.json"

FAILS=0
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_wavemachine_handoff_no_narrator (#600)"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	fail "skill body not found: $SKILL"
	exit 1
fi

# 1. The "Wave-to-Wave Handoff" section must exist and use the canonical
#    "single tool-use boundary" wording. This is the load-bearing phrase the
#    skill body uses to bind the contract; if it's been softened, the rule
#    has been weakened.
if grep -qE "## Wave-to-Wave Handoff" "$SKILL"; then
	pass "Wave-to-Wave Handoff section exists"
else
	fail "Wave-to-Wave Handoff section missing — rule cannot be enforced"
fi

if grep -qE "single tool-use boundary" "$SKILL"; then
	pass "skill uses 'single tool-use boundary' canonical wording"
else
	fail "'single tool-use boundary' canonical wording missing"
fi

# 2. The Wave-to-Wave Handoff section must explicitly forbid narrative text
#    between waves. Tolerant phrasing: any of "no narrative text", "no narrator
#    gap", "MUST NOT contain narrative", "narration is forbidden", etc.
if grep -qiE "no narrator gap|no narrative text|MUST NOT contain narrative|narration.{0,40}forbidden|narrator.{0,40}forbidden" "$SKILL"; then
	pass "skill explicitly forbids inter-wave narration"
else
	fail "skill does not explicitly forbid inter-wave narration — agent may rationalize prose between waves"
fi

# 3. The loop body's step-4 OK-path must defer to "Wave-to-Wave Handoff"
#    rather than enumerating side effects in narration-friendly prose. The
#    tell is a reference to "Wave-to-Wave Handoff" (or the canonical "single
#    tool-use boundary" wording) inside the loop's OK branch description.
if awk '
	/^## The Loop/,/^## Wave-to-Wave Handoff/{
		print
	}
' "$SKILL" | grep -qiE "Wave-to-Wave Handoff|single tool-use boundary|no narrative text|no narrator"; then
	pass "loop OK-path defers to Wave-to-Wave Handoff contract (no narration-friendly enumeration)"
else
	fail "loop OK-path does not reference Wave-to-Wave Handoff — narrator gap may slip in"
fi

# 4. Non-Negotiables must include a rule about wave-to-wave handoff. This is
#    the canonical place enforceable rules live; without it, the contract is
#    documentation, not policy.
if awk '
	# Track entry/exit so the start line does not double-match the end pattern.
	BEGIN { in_section = 0 }
	/^## Non-Negotiables/ { in_section = 1; print; next }
	in_section && /^## / { exit }
	in_section { print }
' "$SKILL" | grep -qiE "Wave-to-wave handoff.*single tool-use boundary|no narrator gap"; then
	pass "Non-Negotiables enumerates the wave-to-wave handoff rule"
else
	fail "Non-Negotiables missing the wave-to-wave handoff rule"
fi

# 5. The Stop hook (config/settings.template.json) must be in place with the
#    decision:block contract conditional on wavemachine_active=true. This is
#    the structural safety net for premature termination; if it has been
#    removed, the in-turn-narration contract loses its complement.
if [[ -f "$SETTINGS" ]]; then
	# Settings template stores the hook command as a JSON string, so the
	# inner JSON-block payload appears with backslash-escaped quotes
	# (\"decision\":\"block\"). Match the literal substring rather than the
	# ERE form to be robust to that escaping.
	if grep -qF 'decision\":\"block' "$SETTINGS" && grep -qF 'wavemachine_active' "$SETTINGS"; then
		pass "Stop hook with decision:block + wavemachine_active conditional present in settings template"
	else
		fail "Stop hook decision:block + wavemachine_active conditional not found in $SETTINGS"
	fi
else
	fail "settings template not found: $SETTINGS"
fi

# 6. Defensive: the skill MUST NOT instruct the agent to "announce" wave
#    completion or "report progress" between waves — those are the failure
#    modes this rule prevents. The legitimate announcement points are
#    terminal-only (clean completion, abort, gate-blocked).
if awk '
	/^## The Loop/,/^## Trust-Score Gate/{
		print
	}
' "$SKILL" | grep -qiE "announce.{0,30}wave.{0,20}complete|report.{0,20}progress.{0,20}between|narrate.{0,20}wave"; then
	fail "loop body instructs inter-wave announcement/narration — defeats the no-narrator-gap contract"
else
	pass "loop body does not instruct inter-wave announcement/narration"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all checks passed"
exit 0
