#!/usr/bin/env bash
# test_nextwave_structure.sh — structural regression tests for
# skills/nextwave/SKILL.md per Dev Spec §5.3 and phase-epic-taxonomy §8 Story 3.2.
#
# Covers:
#   - test_nextwave_no_unqualified_epic: `\bepic\b` (case-insensitive) in the
#     pipeline-operational contexts of the skill body returns zero. [R-10]
#   - test_nextwave_exhaustive_legal_exits: the `## Exhaustive Legal Exits`
#     section is present and contains the required sub-sections.
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

# 2. The three required sub-section headings must exist.
if ! grep -qE '^### Mechanical exits' "$SKILL"; then
	fail "test_nextwave_exhaustive_legal_exits: '### Mechanical exits' sub-section missing"
else
	pass "sub-section present: '### Mechanical exits'"
fi

if ! grep -qE '^### Plan-reality drift exits' "$SKILL"; then
	fail "test_nextwave_exhaustive_legal_exits: '### Plan-reality drift exits' sub-section missing"
else
	pass "sub-section present: '### Plan-reality drift exits'"
fi

if ! grep -qE '^### Explicit non-exits' "$SKILL"; then
	fail "test_nextwave_exhaustive_legal_exits: '### Explicit non-exits' sub-section missing"
else
	pass "sub-section present: '### Explicit non-exits'"
fi

# 3. The Mechanical exits sub-section must contain numbered items.
if ! awk '/^### Mechanical exits/{flag=1;next} /^### /{flag=0} flag && /^[0-9]+\. /{found=1} END{exit !found}' "$SKILL"; then
	fail "test_nextwave_exhaustive_legal_exits: Mechanical exits has no numbered items"
else
	pass "Mechanical exits contains numbered items"
fi

# 4. The Explicit non-exits sub-section must contain bulleted items.
if ! awk '/^### Explicit non-exits/{flag=1;next} /^### /{flag=0} /^## /{flag=0} flag && /^- /{found=1} END{exit !found}' "$SKILL"; then
	fail "test_nextwave_exhaustive_legal_exits: Explicit non-exits has no bulleted items"
else
	pass "Explicit non-exits contains bulleted items"
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

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
