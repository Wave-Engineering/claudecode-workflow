#!/usr/bin/env bash
# test_muse_add_coverage.sh — the muse conception skill's exit checklist touches all four
# ADD driver categories, keeps the scaffold invisible, and never self-confirms the lock.
# The skeleton IS the exit criteria: if a driver is missing, a whole class of wrong-problem
# miss slips the gate; if the categories are surfaced, we've shipped the intake form we set
# out to avoid.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$ROOT/skills/muse/SKILL.md"

pass=0
fail=0
have() { # regex  label
	if grep -qiE "$1" "$SKILL"; then
		echo "  [PASS] $2"
		pass=$((pass + 1))
	else
		echo "  [FAIL] $2 (missing /$1/)"
		fail=$((fail + 1))
	fi
}

if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] skills/muse/SKILL.md missing"
	exit 1
fi

# All four ADD drivers named in the exit checklist. Anchor on the parenthetical LABEL form
# — unique to the checklist bullets — so a driver whose phrase also appears in the surrounding
# prose (e.g. "quality attributes" in the never-recite example) can't false-pass if its bullet
# is dropped. The gate must fail when a driver leaves the checklist, not merely the document.
have '\(functional purpose' "driver: functional purpose"
have '\(quality attributes' "driver: quality attributes"
have '\(constraints' "driver: constraints"
have '\(stakeholders' "driver: stakeholders / concerns"

# The scaffold stays invisible — the skill must forbid surfacing the categories.
have "never recited|never name these" "scaffold invisible: categories never surfaced to the Designer"

# The quality-attribute leg is called out as the sharpest reframe-guard (the -ility miss).
have "\-ilit|sharpest" "quality-attribute guard against the wrong-problem miss"

# The human holds the lock — the skill never self-confirms.
have "self-confirm|holds the lock|confirm it yourself" "the human holds the lock"

echo "  $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
