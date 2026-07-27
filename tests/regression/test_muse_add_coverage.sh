#!/usr/bin/env bash
# test_muse_add_coverage.sh — the muse skill spans both movements and keeps each one's
# load-bearing contract.
#
# Movement 1 (conception): the exit checklist touches all four ADD driver categories, keeps
# the scaffold invisible, and never self-confirms the lock. The skeleton IS the exit criteria:
# if a driver is missing, a whole class of wrong-problem miss slips the gate; if the categories
# are surfaced, we've shipped the intake form we set out to avoid.
#
# Movement 2 (shaping, #1044): the skill proposes rather than elicits, is licensed to re-see the
# product, records decisions as a numbered+attributed+reasoned ledger, keeps an open-questions
# register, and stops on the definitional-vs-behavioral test. Each of those is a distinct failure
# mode if dropped: no proposing abandons the Designer at the hardest part; no ledger loses the
# reasoning that makes judgment learnable; no stop test carries undecided identity into /ddd.
#
# The Designer-facing introduction must stay free of the internal vocabulary — the method
# disciplines the agent, not the conversation.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$ROOT/skills/muse/SKILL.md"
INTRO="$ROOT/skills/muse/introduction.md"

pass=0
fail=0
have() { # regex  label  [file=$SKILL]
	if grep -qiE "$1" "${3:-$SKILL}"; then
		echo "  [PASS] $2"
		pass=$((pass + 1))
	else
		echo "  [FAIL] $2 (missing /$1/ in ${3:-$SKILL})"
		fail=$((fail + 1))
	fi
}

lacks() { # regex  label  file  [-i to fold case; default case-SENSITIVE]
	# Case-sensitive by default: the acronym "ADD" must not leak, but the ordinary word "add"
	# is unremarkable prose and must not trip the gate.
	if grep -qE ${4:+"$4"} "$1" "$3"; then
		echo "  [FAIL] $2 (found /$1/ in $3)"
		fail=$((fail + 1))
	else
		echo "  [PASS] $2"
		pass=$((pass + 1))
	fi
}

for f in "$SKILL" "$INTRO"; do
	if [[ ! -f "$f" ]]; then
		echo "  [FAIL] ${f#"$ROOT"/} missing"
		exit 1
	fi
done

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

# ADD is named for the agent — that's what makes the gentle guidance a defined path with real
# exit criteria rather than wandering. Movement 1 shipped the drivers but not the method's name.
have "attribute-driven design" "ADD named as the method (agent-facing context)"

# ── Movement 2 — shaping (#1044) ───────────────────────────────────────────────
# Both movements present AND in order — the ordering is checked, not just asserted in a comment.
# Without the structure the skill reverts to conception-only and the span to /ddd-ready is unowned
# again; with the movements transposed, the agent is told to shape before the problem is confirmed.
have "^# Movement 1" "movement 1 (conception) section present"
have "^# Movement 2" "movement 2 (shaping) section present"

m1_line=$(grep -nE "^# Movement 1" "$SKILL" | head -1 | cut -d: -f1)
m2_line=$(grep -nE "^# Movement 2" "$SKILL" | head -1 | cut -d: -f1)
if [[ -n "$m1_line" && -n "$m2_line" && "$m1_line" -lt "$m2_line" ]]; then
	echo "  [PASS] conception precedes shaping (movement 1 before movement 2)"
	pass=$((pass + 1))
else
	echo "  [FAIL] conception precedes shaping (got M1@${m1_line:-none}, M2@${m2_line:-none})"
	fail=$((fail + 1))
fi

# The gear inversion: movement 2 proposes instead of eliciting. A shaping stage that only asks
# questions abandons the Designer at the hardest part — the shape isn't inside them to extract.
# Anchor on the SECTION HEADING, not the phrase: the preamble mentions proposing too, and matching
# there would let the gear itself be deleted while the gate still passed.
have "^## The shift" "movement 2 proposes rather than elicits (the shift section)"

# Product-level re-see, licensed to reach back and amend the confirmed problem statement (with
# re-confirmation). Suppressing a late re-see is the fatal failure, not the expensive one.
have "re-see" "product-level re-see gear present"
have "amend the problem statement|re-confirmation" "re-see may amend the locked statement, with re-confirmation"

# The decision ledger — all three parts. Any one missing and the ledger stops teaching judgment:
# unnumbered can't be cited, unattributed loses whose call it was, unreasoned is a rule not a lesson.
have "numbered decision" "ledger: decisions are numbered"
have "attribution" "ledger: decisions are attributed"
# The bare alternative /reasoning/ was a false-pass: it also matches the Propose and Re-see gears,
# so the ledger's reasoning bullet could be deleted entirely and the gate still reported PASS.
# The epigram is unique to the bullet — anchor there and nowhere else.
have "a rule; with its reasoning" "ledger: decisions carry their reasoning"
have "append-only" "ledger is append-only — superseded, never edited"

# The open-questions register, and closing a question into the decision that resolved it.
# The closure form is matched as the literal strike-through-to-decision arrow, case-SENSITIVELY:
# a bare /resolved/i also matches "the unresolved middle" over in movement 1, which would let the
# whole register be deleted while the gate still passed.
have "open.questions register" "open-questions register present"
if grep -qE 'RESOLVED (→|->) D-' "$SKILL"; then
	echo "  [PASS] resolved questions close into their decision"
	pass=$((pass + 1))
else
	echo "  [FAIL] resolved questions close into their decision (missing /RESOLVED → D-N/)"
	fail=$((fail + 1))
fi

# The stop test — definitional must be empty, behavioral belongs to /ddd. This is the handoff gate.
have "definitional" "stop test: definitional questions must be closed"
have "behavioral" "stop test: behavioral questions belong to /ddd"

# The artifact contract — path resolved via the tool, not hardcoded, so muse and /ddd agree.
have "ddd_locate_sketchbook" "artifact path resolved via ddd_locate_sketchbook"

# ── The Designer never sees the machinery ──────────────────────────────────────
# introduction.md is the human's first contact. Internal vocabulary leaking into it is exactly
# the intake-form failure the skill exists to avoid.
# Split by case-sensitivity need: the ACRONYM must be matched case-sensitively (or the ordinary
# word "add" trips the gate), but the spelled-out method name has no lowercase collision — folding
# case there catches the likeliest real leak, "attribute-driven design" in ordinary prose.
lacks "\bADD\b" "introduction stays free of the ADD acronym" "$INTRO"
lacks "Attribute.Driven Design" "introduction stays free of the spelled-out method name" "$INTRO" -i
lacks "movement 1|movement 2|quality attributes" "introduction stays free of internal structure" "$INTRO" -i
# The intro is clean of the rest of the machinery today, but nothing pinned that. These are the
# terms most likely to leak on a future edit, because each one is the natural word for the thing
# an author is describing at that moment: "re-see" and "ledger" are movement 2's own names for its
# two load-bearing moves, and "definitional" is half of the stop test. Naming them here means a
# leak fails a test instead of quietly changing what the Designer reads.
lacks "re-see|ledger|definitional" "introduction stays free of movement-2 vocabulary" "$INTRO" -i

echo "  $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
