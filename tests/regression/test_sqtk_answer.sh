#!/usr/bin/env bash
# test_sqtk_answer.sh — #1363 regression test for scripts/hooks/workflow/sqtk-answer.jq.
#
# The module is the one rule for what counts as an answer on a squawk. An arrow in the
# author's own text must never read as BJ's answer: a pristine squawk holds none, and with a
# baseline only what follows an added arrow counts. Without a baseline the old last-arrow
# rule stands, so items answered before #1363 keep their answer string.

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

eq "pristine prose arrow is not an answer" "" \
	'{text: "campaign→main fix", created_at: "t", updated_at: "t"} | sq_answer(null)'
eq "pristine with a baseline is still not an answer" "" \
	'{text: "ask → yes", created_at: "t", updated_at: "t"} | sq_answer(0)'
eq "edited prose with baseline is not an answer" "" \
	'{text: "campaign→main fixes", created_at: "t", updated_at: "u"} | sq_answer(1)'
eq "appended arrow after baseline is the answer" "yes" \
	'{text: "campaign→main fix → yes", created_at: "t", updated_at: "u"} | sq_answer(1)'
eq "slot answer" "yes" \
	'{text: "ask → yes", created_at: "t", updated_at: "u"} | sq_answer("ask →" | prose_arrows)'
eq "recorded ref reads answered" "#12" '{text: "x→y → #12"} | sq_answer(1)'
eq "recorded ref after a slot reads answered" "#12" \
	'{text: "ask → → #12"} | sq_answer("ask →" | prose_arrows)'
eq "answer keeps its own arrows" "a → b" '{text: "ask → a → b"} | sq_answer(0)'
eq "no baseline keeps the legacy rule" "b" \
	'{text: "a → b", created_at: "t", updated_at: "u"} | sq_answer(null)'
eq "missing timestamps are not pristine" "b" '{text: "a → b"} | sq_answer(null)'
eq "one missing timestamp is not pristine" "b" '{text: "a → b", created_at: "t"} | sq_answer(null)'
eq "missing timestamps fall through to the baseline" "" '{text: "a → b"} | sq_answer(1)'
eq "prose_arrows counts the slot out" "1 1 0 0" \
	'[("a → b →", "a → b", "ask", "") | prose_arrows] | map(tostring) | join(" ")'
eq "prose_arrows ignores trailing whitespace after the slot" "0" '"ask →  " | prose_arrows'
eq "pristine prose drops the slot" "ask" \
	'{text: "ask →  ", created_at: "t", updated_at: "t"} | sq_prose(null)'
eq "pristine prose keeps a prose arrow" "campaign→main" \
	'{text: "campaign→main", created_at: "t", updated_at: "t"} | sq_prose(null)'
eq "baselined prose keeps the author's arrows" "issue #23 → 2979849633" \
	'{text: "issue #23 → 2979849633 → yes"} | sq_prose(1)'
eq "legacy prose is all but the last part" "a → b" '{text: "a → b → c"} | sq_prose(null)'
eq "no text is empty, not an error" "|" '{} | "\(sq_answer(null))|\(sq_prose(null))"'

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-answer checks passed."
	exit 0
fi
echo "  $FAILS sqtk-answer check(s) FAILED."
exit 1
