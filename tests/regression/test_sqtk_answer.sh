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

# The last editor's own tag is a signature, not an answer (#1421). It lands after the arrow when
# `sqtk show`'s display suffix is copied back into --text. The tag must be the squawk's last
# editor's, so a human's "(ok)" is still an answer.
signed() { printf '{text: %s, initials: %s, created_at: "t", updated_at: "u"} | sq_answer(null)' "$(jq -n --arg t "$1" '$t')" "$(jq -n --arg i "$2" '$i')"; }
eq "the editor's own tag alone is no answer" "" "$(signed "deploy now? →  (CER)" CER)"
eq "the editor's tag repeated is no answer" "" "$(signed "deploy now? →  (CER)  (CER)" CER)"
eq "another editor's short tag is an answer" "(ok)" "$(signed "deploy now? → (ok)" BJ)"
eq "text with the editor's tag is an answer" "yes (CER)" "$(signed "deploy now? → yes (CER)" CER)"
eq "someone else's initials as a tag are an answer" "(CER)" "$(signed "deploy now? → (CER)" BJ)"
eq "no recorded editor: no tag rule" "(CER)" \
	'{text: "deploy now? → (CER)", created_at: "t", updated_at: "u"} | sq_answer(null)'
eq "initials that are not initials are never a tag rule" "(a.b)" "$(signed "deploy now? → (a.b)" a.b)"

# Ask markers (#1430): the leading icon[❗] is not the author's prose.
# ask_split <text> -> "kind blocking marker|rest".
split() { jq -nrj -L "$LIB" --arg t "$1" 'include "sqtk-answer"; $t | ask_split | "\(.kind) \(.blocking) [\(.marker)]|\(.rest)"'; }
chk() {
	local got
	got=$(split "$2")
	if [[ "$got" == "$3" ]]; then pass "$1"; else fail "$1 (want '$3', got '$got')"; fi
}
chk "ask_split: ❓" "❓ [a·r] q" "question false [❓ ]|[a·r] q"
chk "ask_split: ❓❗" "❓❗ [a·r] q" "question true [❓❗ ]|[a·r] q"
chk "ask_split: 🔧" "🔧 x" "action false [🔧 ]|x"
chk "ask_split: ✅❗" "✅❗ x" "approval true [✅❗ ]|x"
chk "ask_split: ⛔ is always blocking" "⛔ x" "blocker true [⛔ ]|x"
chk "ask_split: ⛔❗ is the same blocker" "⛔❗ x" "blocker true [⛔❗ ]|x"
chk "ask_split: 🔔" "🔔 x" "unspecified false [🔔 ]|x"
chk "ask_split: no marker is 🔔, non-blocking, text intact" "[a·r] plain" "unspecified false []|[a·r] plain"
chk "ask_split: an icon later in the line is no marker" "[a·r] ✅ done ⛔" "unspecified false []|[a·r] ✅ done ⛔"
chk "ask_split: an icon with no space after it is no marker" "✅done" "unspecified false []|✅done"
chk "ask_split: ❗ alone is no marker" "❗ x" "unspecified false []|❗ x"
chk "ask_split: empty text" "" "unspecified false []|"

M='"🔔 [a·r] ship it? →"'
eq "marker: pristine is still no answer" "" \
	'{text: "🔔 [a·r] ship it? → yes", created_at: "t", updated_at: "t"} | sq_answer(null)'
eq "marker: an appended answer is read against O with the same marker" "yes" \
	"{text: \"🔔 [a·r] ship it? → yes\", created_at: \"t\", updated_at: \"u\"} | sq_answer($M)"
eq "marker: an answer on an ask that was reclassified (O had a different marker)" "yes" \
	"{text: \"❓❗ [a·r] ship it? → yes\", created_at: \"t\", updated_at: \"u\"} | sq_answer($M)"
eq "marker: reclassifying alone (no answer) is no answer" "" \
	"{text: \"❓❗ [a·r] ship it? →\", created_at: \"t\", updated_at: \"u\"} | sq_answer($M)"
eq "marker: reclassifying an ask with a prose arrow is no answer" "" \
	'{text: "⛔ [a·r] v65→v66 broke it →", created_at: "t", updated_at: "u"} | sq_answer("🔔 [a·r] v65→v66 broke it →")'
eq "marker: the editor's own tag after a marked ask is no answer" "" \
	'{text: "✅❗ [a·r] ok? →  (CER)", initials: "CER", created_at: "t", updated_at: "u"} | sq_answer("✅❗ [a·r] ok? →")'
eq "marker: an answer with no O (legacy) still reads the last arrow" "yes" \
	'{text: "❓ [a·r] ok? → yes"} | sq_answer(null)'
eq "marker: sq_prose keeps the marker in front" "❓❗ [a·r] ok?" \
	'{text: "❓❗ [a·r] ok? → yes"} | sq_prose("❓❗ [a·r] ok? →")'
eq "marker: sq_prose of a pristine marked ask" "🔔 [a·r] ok?" \
	'{text: "🔔 [a·r] ok? →", created_at: "t", updated_at: "t"} | sq_prose(null)'
eq "marker: sq_prose keeps the author's arrows after a reclassify" "⛔ [a·r] v65→v66" \
	'{text: "⛔ [a·r] v65→v66 → yes"} | sq_prose("🔔 [a·r] v65→v66")'

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-answer checks passed."
	exit 0
fi
echo "  $FAILS sqtk-answer check(s) FAILED."
exit 1
