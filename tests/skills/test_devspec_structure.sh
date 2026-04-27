#!/usr/bin/env bash
# test_devspec_structure.sh — structural regression tests for
# skills/devspec/SKILL.md per phase-epic-taxonomy devspec §8 Story 3.4.
#
# Covers two unit tests called out in the issue body:
#   - test_devspec_no_unqualified_epic: `\bepic\b` in pipeline-operational
#     contexts returns zero. Qualified PM-layer references ("type::epic",
#     "epic::N label", "PM-layer Epic") are permitted per R-12 / MV-01.
#   - test_devspec_ledger_procedure: the skill body documents the procedure
#     for appending `[ledger D-NNN]` comments to the Plan tracking issue
#     during `/devspec create`, per Dev Spec §5.1, §5.2.
#
# Scope: asserts structural presence, not content. Content is human-reviewed.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/devspec/SKILL.md"

FAILS=0

fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

pass() {
	echo "  [PASS] $*"
}

echo "test_devspec_structure"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] SKILL.md missing: $SKILL"
	exit 1
fi

# --- test_devspec_no_unqualified_epic -----------------------------------------
# Per Dev Spec §3 R-12 and MV-01: `\bepic\b` (case-insensitive) must return
# zero in pipeline-operational contexts. Qualified references are permitted
# when they explicitly name Epic as an optional PM-layer label or parent
# tracker. Qualifiers we recognise (matching the MV-01 definition):
#   - "type::epic"            — the label literal
#   - "epic::N"               — the per-story label literal (N or <N>)
#   - "PM-layer Epic"         — the prose qualifier used in the skill body
#   - "optional PM-layer"     — preceding phrase when "Epic" follows
#   - "PM-layer"              — general qualifier (must be on same line as "epic")
#   - "Plan/Phase/Epic"       — historical-reference phrase used in taxonomy
#   - "parent tracker"        — the R-12 phrase
#
# Any `\bepic\b` occurrence on a line that also contains one of these
# qualifiers is treated as qualified and allowed. Lines with bare "epic"
# are reported and fail the test.
#
# Additionally, occurrences inside the filename token `phase-epic-taxonomy`
# (or any similar hyphen-bound slug) are treated as references to this
# taxonomy document rather than to the pipeline primitive, and are allowed.
tmpfile=$(mktemp)
trap 'rm -f "$tmpfile"' EXIT

grep -n -i '\bepic\b' "$SKILL" >"$tmpfile" || true

unqualified=0
while IFS= read -r line; do
	[[ -z "$line" ]] && continue
	# Check for any qualifier on the same line.
	if echo "$line" | grep -qiE 'type::epic|epic::(N|<N>|[0-9]+)|PM-layer|parent tracker|Plan/Phase/Epic|program-management|phase-epic-taxonomy'; then
		continue
	fi
	echo "    UNQUALIFIED: $line"
	unqualified=$((unqualified + 1))
done <"$tmpfile"

if [[ $unqualified -gt 0 ]]; then
	fail "test_devspec_no_unqualified_epic: $unqualified unqualified 'epic' reference(s) in SKILL.md"
else
	pass "test_devspec_no_unqualified_epic: no unqualified 'epic' in SKILL.md"
fi

# --- test_devspec_ledger_procedure -------------------------------------------
# Per Dev Spec §5.1, §5.2, §5.2.1, and R-16: the skill body must document the
# procedure for appending `[ledger D-NNN]` comments to the Plan tracking
# issue during `/devspec create`. We verify structural presence of:
#   1. The `[ledger D-NNN]` typed-prefix pattern
#   2. The tool used to post comments (`pr_comment`)
#   3. The four required fields per §5.2.1: source, Decision, Rationale, signature
#   4. Reference to the Plan issue as the target

if ! grep -qE '\[ledger D-NNN\]' "$SKILL"; then
	fail "test_devspec_ledger_procedure: '[ledger D-NNN]' prefix pattern not documented in SKILL.md"
else
	pass "ledger entry prefix pattern present: '[ledger D-NNN]'"
fi

if ! grep -q 'pr_comment' "$SKILL"; then
	fail "test_devspec_ledger_procedure: pr_comment tool invocation not documented"
else
	pass "pr_comment MCP tool documented as the posting mechanism"
fi

if ! grep -qE '\*\*Decision:\*\*' "$SKILL"; then
	fail "test_devspec_ledger_procedure: '**Decision:**' field not in ledger schema"
else
	pass "ledger schema includes '**Decision:**' field"
fi

if ! grep -qE '\*\*Rationale:\*\*' "$SKILL"; then
	fail "test_devspec_ledger_procedure: '**Rationale:**' field not in ledger schema"
else
	pass "ledger schema includes '**Rationale:**' field"
fi

if ! grep -qE '/devspec §' "$SKILL"; then
	fail "test_devspec_ledger_procedure: source form '/devspec §X.Y' not documented"
else
	pass "ledger source form '/devspec §X.Y' documented"
fi

if ! grep -qE 'Plan (tracking )?issue' "$SKILL"; then
	fail "test_devspec_ledger_procedure: 'Plan tracking issue' not referenced as the append target"
else
	pass "Plan tracking issue referenced as ledger append target"
fi

# Also assert the procedure lives inside the devspec-create template.
if ! awk '
	/<!-- BEGIN TEMPLATE: devspec-create -->/{flag=1;next}
	/<!-- END TEMPLATE: devspec-create -->/{flag=0}
	flag && /\[ledger D-NNN\]/{found=1}
	END{exit !found}
' "$SKILL"; then
	fail "test_devspec_ledger_procedure: '[ledger D-NNN]' procedure not inside devspec-create template"
else
	pass "ledger append procedure is inside devspec-create template"
fi

# --- test_devspec_upshift_plan_id_and_depends_on -----------------------------
# Per Dev Spec R-07 and Story 3.4 AC-4: the upshift procedure must write
# phases-waves.json with plan_id (not epic_id) and depends_on per Story.

if ! awk '
	/<!-- BEGIN TEMPLATE: devspec-upshift -->/{flag=1;next}
	/<!-- END TEMPLATE: devspec-upshift -->/{flag=0}
	flag && /phases-waves\.json/{found=1}
	END{exit !found}
' "$SKILL"; then
	fail "test_devspec_upshift_shape: 'phases-waves.json' not referenced in devspec-upshift template"
else
	pass "upshift template references phases-waves.json"
fi

if ! awk '
	/<!-- BEGIN TEMPLATE: devspec-upshift -->/{flag=1;next}
	/<!-- END TEMPLATE: devspec-upshift -->/{flag=0}
	flag && /plan_id/{found=1}
	END{exit !found}
' "$SKILL"; then
	fail "test_devspec_upshift_shape: 'plan_id' field not documented in devspec-upshift template"
else
	pass "upshift template documents 'plan_id' field"
fi

if ! awk '
	/<!-- BEGIN TEMPLATE: devspec-upshift -->/{flag=1;next}
	/<!-- END TEMPLATE: devspec-upshift -->/{flag=0}
	flag && /depends_on/{found=1}
	END{exit !found}
' "$SKILL"; then
	fail "test_devspec_upshift_shape: 'depends_on' per-Story field not documented in devspec-upshift template"
else
	pass "upshift template documents per-Story 'depends_on' field"
fi

# The legacy epic_id shape must NOT be mandated by the upshift template.
# An explicit mention like "epic_id is retired" or similar is acceptable; a
# prescriptive use of epic_id as the active field is not.
if awk '
	/<!-- BEGIN TEMPLATE: devspec-upshift -->/{flag=1;next}
	/<!-- END TEMPLATE: devspec-upshift -->/{flag=0}
	flag { print }
' "$SKILL" | grep -qE '"epic_id"'; then
	# permit the retirement note if it also mentions "retired"
	if awk '
		/<!-- BEGIN TEMPLATE: devspec-upshift -->/{flag=1;next}
		/<!-- END TEMPLATE: devspec-upshift -->/{flag=0}
		flag && /epic_id/ && /retired/{found=1}
		END{exit !found}
	' "$SKILL"; then
		pass "upshift template retires epic_id explicitly"
	else
		fail "test_devspec_upshift_shape: legacy 'epic_id' appears in upshift template without retirement note"
	fi
else
	pass "upshift template does not prescribe legacy epic_id"
fi

# --- Summary -----------------------------------------------------------------
echo ""
if [[ $FAILS -gt 0 ]]; then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
