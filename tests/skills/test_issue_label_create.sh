#!/usr/bin/env bash
# test_issue_label_create.sh — structural regression tests for on-demand
# label_create logic on skills/issue/SKILL.md per Dev Spec R-14, §5.5.3 step 2,
# and §5.5.4 step 3.
#
# Covers `test_issue_label_create_ondemand` called out in issue #516:
#   - Missing `type::plan` triggers label_create call
#   - Missing `epic::N` triggers label_create call
#   - Canonical colour #5319E7 documented

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

echo "test_issue_label_create_ondemand"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] SKILL.md missing: $SKILL"
	exit 1
fi

# --- Tool reference ----------------------------------------------------------
if grep -q 'label_create' "$SKILL"; then
	pass "'label_create' tool referenced in SKILL.md"
else
	fail "'label_create' tool not referenced"
fi

if grep -q 'mcp__sdlc-server__label_create' "$SKILL"; then
	pass "fully-qualified 'mcp__sdlc-server__label_create' name present"
else
	fail "fully-qualified 'mcp__sdlc-server__label_create' name missing"
fi

# --- Canonical colour (Dev Spec §5.5.3 step 2, §5.5.4 step 3, R-14) ----------
if grep -q '#5319E7' "$SKILL"; then
	pass "canonical colour '#5319E7' documented"
else
	fail "canonical colour '#5319E7' missing"
fi

# --- type::plan label creation path (R-14, §5.5.3 step 2) --------------------
if grep -qE 'type::plan.*label_create|label_create.*type::plan|Plan tracking issue' "$SKILL"; then
	pass "type::plan on-demand creation path documented"
else
	fail "type::plan on-demand creation path missing"
fi

# Canonical description for type::plan.
if grep -q 'Plan tracking issue' "$SKILL"; then
	pass "type::plan canonical description present"
else
	fail "type::plan canonical description ('Plan tracking issue ...') missing"
fi

# --- epic::N label creation path (§5.5.4 step 3) -----------------------------
if grep -qE "epic::.*label_create|label_create.*epic::|epic::<N>|epic::N" "$SKILL"; then
	pass "epic::N on-demand creation path documented"
else
	fail "epic::N on-demand creation path missing"
fi

# Canonical description for epic::N.
if grep -q 'PM-layer thematic grouping' "$SKILL"; then
	pass "epic::N canonical description ('PM-layer thematic grouping') present"
else
	fail "epic::N canonical description missing"
fi

# --- Idempotent behaviour documented -----------------------------------------
if grep -qiE 'idempotent' "$SKILL"; then
	pass "idempotent-label_create behaviour documented"
else
	fail "idempotent-label_create behaviour not documented"
fi

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
