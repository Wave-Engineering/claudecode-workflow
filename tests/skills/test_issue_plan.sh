#!/usr/bin/env bash
# test_issue_plan.sh — structural regression tests for skills/issue/SKILL.md's
# `plan` type per Dev Spec `phase-epic-taxonomy-devspec.md` §5.1.2 and §5.5.3.
#
# Covers `test_issue_plan_body_template` called out in issue #516:
#   - `/issue plan` output matches Dev Spec §5.1.2 template
#
# Scope: asserts structural presence in the skill body (the canonical Plan
# body-template block is present, frozen-content marker is present, all §5.1.2
# section headings appear). The skill body IS the specification for the Plan
# body it will render; equating the two is the tightest test we have short of
# an end-to-end run against a real repo (covered by IT-ISSUE-PLAN-01 + MV-04).

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

echo "test_issue_plan_body_template"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] SKILL.md missing: $SKILL"
	exit 1
fi

# --- Plan template presence --------------------------------------------------
# §5.1.2 body shape MUST appear verbatim in the Plan Template section. Check
# for each frozen heading as a line the skill body will emit.

if grep -q '^### Plan Template' "$SKILL"; then
	pass "'### Plan Template' section heading present"
else
	fail "'### Plan Template' section heading missing"
fi

if grep -q '<!-- PLAN-ISSUE v1' "$SKILL"; then
	pass "frozen-content marker '<!-- PLAN-ISSUE v1 -->' present"
else
	fail "frozen-content marker '<!-- PLAN-ISSUE v1 -->' missing"
fi

# The §5.1.2 template requires these headings inside the rendered Plan body.
# Each is embedded in a fenced-code block inside SKILL.md; grep matches them
# regardless of fence context since they appear at column 0 inside the block.
REQUIRED_HEADINGS=(
	'^## Goal$'
	'^## Scope$'
	'^### In scope$'
	'^### Out of scope$'
	'^## Plan-level Definition of Done$'
	'^## Phases$'
	'^## References$'
)

for h in "${REQUIRED_HEADINGS[@]}"; do
	if grep -qE "$h" "$SKILL"; then
		pass "§5.1.2 heading present: ${h#^}"
	else
		fail "§5.1.2 heading missing: ${h#^}"
	fi
done

# --- Creation rules ----------------------------------------------------------
# Dev Spec §5.1.6 mutation rule 1 + §5.5.3 step 5: /issue plan posts NO
# comments at creation (empty comment log is the correct initial state).
if grep -qE 'Post NO comments|no comments|empty comment log' "$SKILL"; then
	pass "'no comments at creation' rule documented"
else
	fail "Dev Spec §5.1.6 rule 1 (no comments at creation) not documented"
fi

# §5.5.3 step 1: naming convention 'Plan: <short name>'.
if grep -q 'Plan: <' "$SKILL"; then
	pass "'Plan: <Name>' naming convention documented"
else
	fail "'Plan: <Name>' naming convention missing"
fi

# AC-1: /issue plan is listed in the usage/type table.
if grep -qE '^\s*/issue plan' "$SKILL"; then
	pass "'/issue plan' listed in usage"
else
	fail "'/issue plan' missing from usage"
fi

# `type::plan` label association.
if grep -q 'type::plan' "$SKILL"; then
	pass "'type::plan' label association documented"
else
	fail "'type::plan' label association missing"
fi

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
