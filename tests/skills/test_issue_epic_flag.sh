#!/usr/bin/env bash
# test_issue_epic_flag.sh — structural regression tests for the `--epic N`
# flag on skills/issue/SKILL.md per Dev Spec §5.5.4.
#
# Covers `test_issue_epic_flag` called out in issue #516:
#   - `/issue feature --epic 42` applies both labels (type::feature, epic::42)
#   - Pre-check on Epic existence is documented
#   - --epic is invalid on plan/epic invocations

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/issue/SKILL.md"

FAILS=0

fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

pass() {
	echo "  [PASS] $*"
}

echo "test_issue_epic_flag"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] SKILL.md missing: $SKILL"
	exit 1
fi

# --- --epic flag recognition -------------------------------------------------
if grep -qE '\-\-epic N|\-\-epic <N>|\-\-epic [0-9]+' "$SKILL"; then
	pass "'--epic N' flag documented"
else
	fail "'--epic N' flag not documented"
fi

# Section heading for the flag's mechanics.
if grep -qE '^### .*--epic N' "$SKILL"; then
	pass "'--epic N' flag mechanics section present"
else
	fail "'--epic N' flag mechanics section missing"
fi

# --- Both labels applied (Dev Spec §5.5.4 step 2) ----------------------------
# Look for mention that both type::<subtype> AND epic::N are attached.
if grep -qE 'type::.*(AND|and|\+).*epic::|epic::.*(AND|and|\+).*type::|both labels' "$SKILL"; then
	pass "both-labels rule documented"
else
	fail "both-labels rule (type::<sub> + epic::N) not documented"
fi

# --- Pre-check on Epic existence (Dev Spec §5.5.4 step 1) --------------------
if grep -qiE 'pre-check|pre check|verify.*type::epic|exists.*type::epic|open.*type::epic' "$SKILL"; then
	pass "Epic-existence pre-check documented"
else
	fail "Epic-existence pre-check (§5.5.4 step 1) not documented"
fi

# --- Clear error path --------------------------------------------------------
if grep -qiE "fail.*clear error|error message|abort" "$SKILL"; then
	pass "failure-mode error path documented"
else
	fail "failure-mode error path not documented"
fi

# --- --epic invalid with type=plan/epic --------------------------------------
if grep -qE "invalid with type=.plan|invalid.*plan.*epic|--epic.*plan.*epic" "$SKILL"; then
	pass "'--epic invalid with plan/epic' rule documented"
else
	fail "'--epic invalid with plan/epic' rule missing"
fi

# --- No comment on Epic (Dev Spec §5.5.4 step 4) -----------------------------
if grep -qiE 'No comment.*Epic|no comment is posted on the Epic|label alone' "$SKILL"; then
	pass "'no comment on Epic' rule documented"
else
	fail "'no comment on Epic' rule (§5.5.4 step 4) not documented"
fi

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
