#!/usr/bin/env bash
# test_kahuna_devspec_structure.sh
#
# Structural tests for docs/kahuna-devspec.md.
#
# Anchors acceptance criteria for cc-workflow#508 (Story 1.1 of the
# phase-epic-taxonomy Plan):
#
#   AC-1 [R-04]: "## Terminology" heading present before "## 1."
#   AC-2 [R-04]: Six primitives defined with relations and non-relations
#   AC-3 [CP-01]: Zero unqualified "epic" occurrences in pipeline-operational
#                 contexts (every surviving occurrence is annotated)
#
# Usage:
#     bash tests/docs/test_kahuna_devspec_structure.sh
#
# Exit codes:
#     0 — all tests pass
#     1 — one or more tests fail
#
# The script prints a terse "PASS"/"FAIL" line per test and a summary line.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DOC="$REPO_DIR/docs/kahuna-devspec.md"

if [[ ! -f "$DOC" ]]; then
	echo "FAIL: docs/kahuna-devspec.md not found at $DOC"
	exit 1
fi

PASS=0
FAIL=0

pass() {
	echo "PASS: $1"
	PASS=$((PASS + 1))
}

fail() {
	echo "FAIL: $1"
	[[ -n "${2:-}" ]] && echo "       $2"
	FAIL=$((FAIL + 1))
}

# -----------------------------------------------------------------------------
# test_kahuna_devspec_terminology_section
#
# Asserts "## Terminology" heading appears in the document and appears BEFORE
# the first "## 1." heading (the §1 anchor).
# -----------------------------------------------------------------------------
test_kahuna_devspec_terminology_section() {
	local term_line sec1_line
	term_line=$(grep -n '^## Terminology$' "$DOC" | head -1 | cut -d: -f1)
	sec1_line=$(grep -n '^## 1\.' "$DOC" | head -1 | cut -d: -f1)

	if [[ -z "$term_line" ]]; then
		fail "test_kahuna_devspec_terminology_section" "'## Terminology' heading not found"
		return
	fi

	if [[ -z "$sec1_line" ]]; then
		fail "test_kahuna_devspec_terminology_section" "'## 1.' heading not found"
		return
	fi

	if ((term_line < sec1_line)); then
		pass "test_kahuna_devspec_terminology_section (Terminology at line $term_line; §1 at line $sec1_line)"
	else
		fail "test_kahuna_devspec_terminology_section" \
			"'## Terminology' (line $term_line) is NOT before '## 1.' (line $sec1_line)"
	fi
}

# -----------------------------------------------------------------------------
# test_kahuna_devspec_six_primitives
#
# Asserts each of the six primitive names appears in the Terminology section
# as a table row (bold marker, e.g., **Plan**).
# -----------------------------------------------------------------------------
test_kahuna_devspec_six_primitives() {
	local primitive missing=()
	for primitive in Plan Phase Wave Story Flight Epic; do
		if ! grep -qE "^\| \*\*${primitive}\*\* \|" "$DOC"; then
			missing+=("$primitive")
		fi
	done

	if ((${#missing[@]} == 0)); then
		pass "test_kahuna_devspec_six_primitives (all six primitives defined as table rows)"
	else
		fail "test_kahuna_devspec_six_primitives" "missing primitives: ${missing[*]}"
	fi
}

# -----------------------------------------------------------------------------
# test_kahuna_devspec_no_unqualified_epic
#
# Grep for unqualified 'epic' in pipeline-operational contexts. Every surviving
# occurrence MUST be either (a) inside the Terminology section, or (b) qualified
# with a PM-layer annotation (`type::epic`, `epic::N`, "PM-layer", "historically",
# or inside a reference to the phase-epic-taxonomy Dev Spec / memory file).
#
# The check operates line-by-line: for each line containing `\bepic\b` (case-
# insensitive), if the line is (i) inside the Terminology section (between the
# '## Terminology' heading and the '## 1.' heading), or (ii) contains one of
# the qualification tokens, the occurrence is considered qualified. Otherwise
# the test fails with the offending line.
# -----------------------------------------------------------------------------
test_kahuna_devspec_no_unqualified_epic() {
	local term_start term_end
	term_start=$(grep -n '^## Terminology$' "$DOC" | head -1 | cut -d: -f1)
	term_end=$(grep -n '^## 1\.' "$DOC" | head -1 | cut -d: -f1)

	if [[ -z "$term_start" || -z "$term_end" ]]; then
		fail "test_kahuna_devspec_no_unqualified_epic" \
			"cannot locate Terminology section boundaries (start=$term_start end=$term_end)"
		return
	fi

	local offenders=()
	local lineno content
	# Read the full file; inspect each line that contains 'epic' (case-insensitive).
	while IFS= read -r lineno; do
		content=$(sed -n "${lineno}p" "$DOC")

		# Skip lines inside the Terminology section (term_start .. term_end - 1).
		if ((lineno >= term_start && lineno < term_end)); then
			continue
		fi

		# Qualification tokens — any match means the line explicitly contextualizes
		# 'epic' as PM-layer / legacy / external-reference.
		if echo "$content" | grep -qE 'type::epic|epic::N|PM-layer|historically|pre-taxonomy|phase-epic-taxonomy|plan_phase_epic_taxonomy|taxonomy leak|Plan/Phase/Epic'; then
			continue
		fi

		offenders+=("$lineno: $content")
	done < <(grep -ni '\bepic\b' "$DOC" | cut -d: -f1)

	if ((${#offenders[@]} == 0)); then
		pass "test_kahuna_devspec_no_unqualified_epic (zero unqualified occurrences)"
	else
		fail "test_kahuna_devspec_no_unqualified_epic" "${#offenders[@]} unqualified occurrence(s):"
		local offender
		for offender in "${offenders[@]}"; do
			echo "       $offender"
		done
	fi
}

# -----------------------------------------------------------------------------
# test_kahuna_devspec_no_epic_id_in_handler_contracts
#
# Asserts the handler-contract examples in §5.1 use `plan_id`, not `epic_id`.
# The only `epic_id` token permitted in the whole document is the one inside
# the Terminology historical note (line explicitly marked "Historical note").
# -----------------------------------------------------------------------------
test_kahuna_devspec_no_epic_id_in_handler_contracts() {
	local offenders=()
	local lineno content
	while IFS= read -r lineno; do
		content=$(sed -n "${lineno}p" "$DOC")
		# Allow epic_id ONLY inside the historical-note line.
		if echo "$content" | grep -qiE 'historical note|historically'; then
			continue
		fi
		offenders+=("$lineno: $content")
	done < <(grep -n 'epic_id' "$DOC" | cut -d: -f1)

	if ((${#offenders[@]} == 0)); then
		pass "test_kahuna_devspec_no_epic_id_in_handler_contracts"
	else
		fail "test_kahuna_devspec_no_epic_id_in_handler_contracts" \
			"${#offenders[@]} epic_id reference(s) outside historical note:"
		local offender
		for offender in "${offenders[@]}"; do
			echo "       $offender"
		done
	fi
}

# -----------------------------------------------------------------------------
# Run all tests
# -----------------------------------------------------------------------------
test_kahuna_devspec_terminology_section
test_kahuna_devspec_six_primitives
test_kahuna_devspec_no_unqualified_epic
test_kahuna_devspec_no_epic_id_in_handler_contracts

echo ""
echo "──────────────────────────────────────────"
echo "Summary: $PASS passed, $FAIL failed"
echo "──────────────────────────────────────────"

if ((FAIL > 0)); then
	exit 1
fi
exit 0
