#!/usr/bin/env bash
# test_sqtk_answer.sh — #1363 regression test for scripts/hooks/workflow/sqtk-answer.jq.
#
# The module is the one rule for what counts as an answer on a squawk. An arrow in the
# author's own text must never read as BJ's answer: a pristine squawk holds none, and with
# the original text O only what follows an added arrow counts, while the segments left of
# O's arrows are unchanged. Without O the old last-arrow rule stands, so items answered
# before #1363 keep their answer string.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LIB="$REPO_DIR/scripts/hooks/workflow"

echo "test_sqtk_answer"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

# eq <name> <want> <jq program over the module>: the program's raw output must equal want.
eq() {
	local got
	got=$(jq -nr -L "$LIB" "include \"sqtk-answer\"; $3" 2>&1)
	if [[ "$got" == "$2" ]]; then pass "$1"; else fail "$1 (want '$2', got '$got')"; fi
}

# edited <current text> <O, as a jq expression>: an edited squawk's answer.
edited() { printf '{text: %s, created_at: "t", updated_at: "u"} | sq_answer(%s)' "$(jq -n --arg t "$1" '$t')" "$2"; }
O='"campaign→main fix"'

eq "pristine prose arrow is not an answer" "" \
	'{text: "campaign→main fix", created_at: "t", updated_at: "t"} | sq_answer(null)'
eq "pristine with O is still not an answer" "" \
	'{text: "ask → yes", created_at: "t", updated_at: "t"} | sq_answer("ask →")'

# The six cases of the rule, against O = "campaign→main fix" (P = 1).
eq "an edit to O's last segment is not an answer" "" "$(edited "campaign→main fixes" "$O")"
eq "an edit across O's arrow reads the last arrow" "yes" "$(edited "campaign to main fix → yes" "$O")"
eq "a last-segment edit then an answer" "yes" "$(edited "campaign→main fixes → yes" "$O")"
eq "an appended answer" "ship it" "$(edited "campaign→main fix → ship it" "$O")"
eq "an answer keeps its own arrows" "a → b" "$(edited "campaign→main fix → a → b" "$O")"
eq "the accepted false positive: an earlier-segment edit" "main fix" "$(edited "campaigns→main fix" "$O")"

eq "segments compare trimmed" "yes" "$(edited "campaign  →main fix → yes" "$O")"
eq "an edit to the slot's segment, then an answer" "yes" \
	"$(edited "v65 → v67 broke the gate → yes" '"v65 → v66 broke the gate →"')"
eq "an edit to the slot's segment alone is not an answer" "" \
	"$(edited "v65 → v67 broke the gate →" '"v65 → v66 broke the gate →"')"
eq "slot answer" "yes" "$(edited "ask → yes" '"ask →"')"
eq "recorded ref after a slot reads answered" "#12" '{text: "ask → → #12"} | sq_answer("ask →")'
eq "a deleted author arrow reads the last arrow" "b" "$(edited "a → b" '"x → y → z"')"
eq "a numeric O is unknown: last arrow" "#12" '{text: "x→y → #12"} | sq_answer(1)'
eq "no O keeps the legacy rule" "b" \
	'{text: "a → b", created_at: "t", updated_at: "u"} | sq_answer(null)'
eq "missing timestamps are not pristine" "b" '{text: "a → b"} | sq_answer(null)'
eq "one missing timestamp is not pristine" "b" '{text: "a → b", created_at: "t"} | sq_answer(null)'
eq "missing timestamps fall through to O" "" '{text: "a → b"} | sq_answer("a → b")'
eq "prose_arrows counts the slot out" "1 1 0 0" \
	'[("a → b →", "a → b", "ask", "") | prose_arrows] | map(tostring) | join(" ")'
eq "prose_arrows ignores trailing whitespace after the slot" "0" '"ask →  " | prose_arrows'
eq "pristine prose drops the slot" "ask" \
	'{text: "ask →  ", created_at: "t", updated_at: "t"} | sq_prose(null)'
eq "pristine prose keeps a prose arrow" "campaign→main" \
	'{text: "campaign→main", created_at: "t", updated_at: "t"} | sq_prose(null)'
eq "prose with O keeps the author's arrows" "issue #23 → 2979849633" \
	'{text: "issue #23 → 2979849633 → yes"} | sq_prose("issue #23 → 2979849633")'
eq "legacy prose is all but the last part" "a → b" '{text: "a → b → c"} | sq_prose(null)'
eq "no text is empty, not an error" "|" '{} | "\(sq_answer(null))|\(sq_prose(null))"'

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-answer checks passed."
	exit 0
fi
echo "  $FAILS sqtk-answer check(s) FAILED."
exit 1
