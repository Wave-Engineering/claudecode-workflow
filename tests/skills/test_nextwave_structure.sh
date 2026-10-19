#!/usr/bin/env bash
# test_nextwave_structure.sh — structural regression tests for
# skills/nextwave/SKILL.md per Dev Spec §5.3 and phase-epic-taxonomy §8 Story 3.2.
#
# Covers:
#   - test_nextwave_no_unqualified_epic: `\bepic\b` (case-insensitive) in the
#     pipeline-operational contexts of the skill body returns zero. [R-10]
#   - test_nextwave_exhaustive_legal_exits: the `## Exhaustive Legal Exits`
#     section is present, its table lists every coded exit, and it states the non-exit.
#   - test_nextwave_axiom_crossref: the WAVE_AXIOMS.md cross-reference is
#     present in the body, AND a top-of-file `## Axioms` block exists per
#     the post-#605 structural rework. The previous incarnation of this
#     test asserted direct refs to two memory files; #605 routed those
#     through the axiom corpus, so the predicate is now the axiom file.
#
# Scope: asserts structural presence, not content. Content is human-reviewed.
# This mirrors Dev Spec §5.3.5's verification rubric.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/nextwave/SKILL.md"

FAILS=0

fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

pass() {
	echo "  [PASS] $*"
}

echo "test_nextwave_structure"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] SKILL.md missing: $SKILL"
	exit 1
fi

# --- test_nextwave_no_unqualified_epic ---------------------------------------
# Per Dev Spec §3.3 and R-10: `\bepic\b` (case-insensitive) must return zero
# in pipeline-operational contexts. The current skill body MUST NOT mention
# "epic" at all — any remaining reference would be a pipeline context (this
# is an execution skill, not a PM-layer doc).
if grep -n -i '\bepic\b' "$SKILL" >/dev/null; then
	grep -n -i '\bepic\b' "$SKILL" | sed 's/^/    /'
	fail "test_nextwave_no_unqualified_epic: 'epic' still present in SKILL.md"
else
	pass "test_nextwave_no_unqualified_epic: no unqualified 'epic' in SKILL.md"
fi

# --- test_nextwave_exhaustive_legal_exits ------------------------------------
# Per Dev Spec §5.3.2 structural template and §5.3.5 verification contract.

# 1. The exact heading `## Exhaustive Legal Exits` must exist.
if ! grep -qE '^## Exhaustive Legal Exits[[:space:]]*$' "$SKILL"; then
	fail "test_nextwave_exhaustive_legal_exits: '## Exhaustive Legal Exits' heading missing"
else
	pass "heading present: '## Exhaustive Legal Exits'"
fi

# Since the #712 cutover the list is the per-wave Workflow's coded exits, kept as one table,
# not the old Mechanical / Plan-reality / non-exits sub-sections.
LEGAL_EXITS="$(awk '/^## Exhaustive Legal Exits/{flag=1;next} /^## /{flag=0} flag' "$SKILL")"

# 2. The table must list every coded exit, one row each.
for exit_name in success runaway thrash cost impasse 'per-issue breaker' reconcile-blocked 'gate HOLD'; do
	if grep -qE "^\| ${exit_name} \|" <<<"$LEGAL_EXITS"; then
		pass "exit row present: '${exit_name}'"
	else
		fail "test_nextwave_exhaustive_legal_exits: no table row for exit '${exit_name}'"
	fi
done

# 3. The explicit non-exit must be stated: unease rides the concerns channel and the loop continues.
if grep -qF 'is NOT an exit' <<<"$LEGAL_EXITS" && grep -qF 'concerns[]' <<<"$LEGAL_EXITS"; then
	pass "non-exit stated: unease rides concerns[], the loop continues"
else
	fail "test_nextwave_exhaustive_legal_exits: the 'NOT an exit' / concerns[] statement is missing"
fi

# 5. Required memory-file cross-references (AC-3).
# Required cross-reference to the canonical axioms file (AC-3, post-#605
# structural rework). The previous incarnation of this test required direct
# cross-references to principle_user_attention_is_the_cost.md and
# principle_cost_asymmetry_continue_vs_exit.md. cc-workflow#605 restructured
# the wave-pattern skill bodies so they cite WAVE_AXIOMS.md as the single
# source of truth; the two memory files are reflected in Axiom 9 and the
# file's cross-reference table. This test now asserts the axiom-file
# cross-reference is present, which transitively covers both memory files
# via the axiom corpus.
if ! grep -q 'WAVE_AXIOMS\.md' "$SKILL"; then
	fail "cross-reference to WAVE_AXIOMS.md missing"
else
	pass "cross-reference to WAVE_AXIOMS.md"
fi

# Top-of-file Axioms cross-reference block (per #605 structural rework).
# Every wave-pattern skill body must begin with a `## Axioms` H2 that names
# the axioms binding the skill and points at WAVE_AXIOMS.md. This is the
# contract that prevents drift between the skill body and the axiom corpus.
if ! grep -qE '^## Axioms[[:space:]]*$' "$SKILL"; then
	fail "top-of-file '## Axioms' cross-reference block missing"
else
	pass "top-of-file '## Axioms' cross-reference block"
fi

# --- test_nextwave_resolves_plan_id (cc-workflow#1171) -----------------------
# Step 1 must read plan_id back from the persisted plan and thread it as
# args.planId, or a standalone run keeps degrading to a wave-scoped
# FlightDeck activity id — the gap #1171 exists to close.
if grep -q 'args\.planId' "$SKILL"; then
	pass "test_nextwave_resolves_plan_id: threads plan_id into args.planId"
else
	fail "test_nextwave_resolves_plan_id: no args.planId resolution in step 1"
fi

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
