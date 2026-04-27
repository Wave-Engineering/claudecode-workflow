#!/usr/bin/env bash
# test_prepwaves_structure.sh — structural regression tests for
# skills/prepwaves/SKILL.md per Dev Spec §8 Story 3.3 (phase-epic-taxonomy).
#
# Covers the one unit test called out in the issue body:
#   - test_prepwaves_no_unqualified_epic: `\bepic\b` (case-insensitive) in the
#     pipeline-operational contexts of the skill body returns zero. [R-11]
#
# Scope: asserts structural absence of unqualified "epic" prose. Tool/param
# identifiers like `epic_sub_issues` and `epic_ref` contain underscores, so
# `\bepic\b` word-boundary matching does not flag them — they are code
# references, not pipeline-layer vocabulary, and they stay.
#
# /prepwaves is a pre-wave planning tool, not an autonomy-loop skill, so no
# Exhaustive Legal Exits section is required here (contrast: nextwave,
# wavemachine).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/prepwaves/SKILL.md"

FAILS=0

fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

pass() {
	echo "  [PASS] $*"
}

echo "test_prepwaves_structure"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] SKILL.md missing: $SKILL"
	exit 1
fi

# --- test_prepwaves_no_unqualified_epic --------------------------------------
# Per Dev Spec §3.3 and R-11: `\bepic\b` (case-insensitive) must return zero
# in pipeline-operational contexts. /prepwaves is a pipeline skill (not PM
# layer), so the skill body MUST NOT mention unqualified "epic" at all.
# Tool/param identifiers with underscores (epic_sub_issues, epic_ref) are
# not flagged by `\bepic\b` — the underscore is a word character.
if grep -n -i '\bepic\b' "$SKILL" >/dev/null; then
	grep -n -i '\bepic\b' "$SKILL" | sed 's/^/    /'
	fail "test_prepwaves_no_unqualified_epic: 'epic' still present in SKILL.md"
else
	pass "test_prepwaves_no_unqualified_epic: no unqualified 'epic' in SKILL.md"
fi

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
