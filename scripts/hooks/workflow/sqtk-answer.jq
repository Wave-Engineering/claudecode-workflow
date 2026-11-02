# sqtk-answer.jq — the one definition of a squawk's answer, for the kit's sqtk hooks. (#1363)
#
# Load it with `jq -L <this dir> 'include "sqtk-answer"; …'`. sqtk-drain.sh, sqtk-banner.sh
# and sqtk-doorbell.sh all read answers through it. Each one fails loudly if it can't load.
#
# squawkie has no answer field. An answer is stored in-band: BJ types it after the squawk's
# `→` slot, and an agent records an item with `sqtk set --text "<text> → #N"`. So an arrow
# in the author's own prose ("campaign→main") must never be read as the start of an answer.
# What was added after the author's text is measured against O, the author's original text:
#   1. pristine: created_at == updated_at, so the squawk was never edited and holds no answer;
#   2. O known: P is O's number of prose arrows (see prose_arrows). Compare the first P
#      segments, the text to the LEFT of each author arrow, trimmed, between the current text
#      and O. If they are equal, the answer is everything after the (P+1)-th arrow of the
#      current text, and "" while it has only P arrows. So an edit to O's last segment makes
#      no answer, and an answer may hold arrows of its own. If they differ, BJ rewrote the
#      prose around an arrow, and the answer is read by rule 3;
#   3. O unknown (or a segment differs): everything after the last arrow. An item answered
#      before #1363 has no O, and this keeps its answer string, so it is not re-reported.
# The one false positive accepted: an edit to a segment left of an author arrow, with no
# answer added, reads the text after the last arrow as an answer. O = "campaign→main fix"
# edited to "campaigns→main fix" reads answered "main fix".
# O comes from the item's sqtk-mine.json `.text` once sqtk records it, else from
# <repo>/.claude/sqtk-baseline.json, which sqtk-drain.sh fills while the squawk is pristine.
# Any value there but a string (an older numeric entry) is unknown: rule 3.

# Ask markers (#1430). The contract is squawkie-talkie#163's: change both or neither. An item on
# `bj:needs` starts with a kind icon, then `❗` exactly when it is blocking and not a blocker,
# then a space, then the rest of the text. No marker means an unspecified, non-blocking ask. The
# icons are single code points with no variation selector.
def ask_icons: {"❓": "question", "🔧": "action", "✅": "approval", "⛔": "blocker", "🔔": "unspecified"};

# Input: text. {kind, blocking, marker, rest}: `marker` is the leading marker with its
# separating space ("" when there is none) and `rest` the text after it. A blocker is always
# blocking. An icon not followed (after an optional `❗`) by a space is just text.
def ask_split:
	(.[0:1]) as $c
	| ask_icons[$c] as $kind
	| (.[1:]) as $a
	| ($a[0:1] == "❗") as $b
	| (if $b then $a[1:] else $a end) as $r
	| if $kind != null and $r[0:1] == " " then
		{kind: $kind, blocking: ($b or $kind == "blocker"),
		 marker: ($c + (if $b then "❗" else "" end) + " "), rest: $r[1:]}
	  else {kind: "unspecified", blocking: false, marker: "", rest: .} end;

# Input: an author's original text. Its arrows, less a closing `→` (the answer slot).
def prose_arrows:
	((split("→") | length - 1) - (if gsub("\\s+$"; "") | endswith("→") then 1 else 0 end))
	| if . < 0 then 0 else . end;

# Input: a squawk. True when it carries both timestamps and they are equal.
def pristine: .created_at != null and .updated_at != null and .created_at == .updated_at;

# Input: text. Everything after the last arrow (rule 3).
def legacy_answer: split("→") | if length > 1 then .[-1] | gsub("^\\s+|\\s+$"; "") else "" end;

# Input: text. Everything after the ($p+1)-th arrow (rule 2).
def answer_after($p):
	split("→") as $x
	| if ($x | length) > $p + 1 then $x[$p + 1:] | join("→") | gsub("^[\\s→]+|\\s+$"; "")
	  else "" end;

# Input: text; $o is O or null. O's P when the text keeps O's first P segments, else null.
def kept_arrows($o):
	if ($o | type) != "string" then null
	else ($o | prose_arrows) as $p
	  | def head: split("→") | .[:$p] | map(gsub("^\\s+|\\s+$"; ""));
	  if (head | length) == $p and head == ($o | head) then $p else null end
	end;

# Input: an answer; $i is the squawk's last editor's initials. True when the answer is nothing
# but that editor's own tag, "(CER)" or "(CER) (CER)": a signature, not an answer (#1421). It
# shows up when `sqtk show`'s display suffix is copied back into `--text`. A different tag
# ("(ok)") or any other text is an answer, and a human's "(ok)" is safe because the editor
# whose tag it must be is the squawk's last one.
def only_editor_tags($i):
	($i | type) == "string" and ($i | test("^[A-Za-z0-9]{1,3}$"))
	and test("^(\\(" + $i + "\\)\\s*)+$");

# Input: a squawk; $o is its original text, or null. Its answer, or "". The ask marker is not
# part of the author's prose (#1430): it is stripped from both texts first, so reclassifying an
# ask (`sqtk set --kind`) is never read as an edit to a segment left of an arrow.
def sq_answer($o):
	((.text // "") | ask_split.rest) as $t
	| ($o | if type == "string" then ask_split.rest else . end) as $o
	| .initials as $i
	| if pristine then ""
	  else ((($t | kept_arrows($o)) as $p
	  | if $p != null then $t | answer_after($p) else $t | legacy_answer end)
	  | if only_editor_tags($i) then "" else . end)
	  end;

# Input: a squawk; $o as above. The author's text, for display, with its ask marker kept
# in front (the icon is worth showing) but out of the arrow comparison.
def sq_prose($o):
	((.text // "") | ask_split) as $s
	| $s.rest as $t
	| ($o | if type == "string" then ask_split.rest else . end) as $o
	| $s.marker + (if pristine then $t | sub("\\s*(→\\s*)?$"; "")
	  else ($t | kept_arrows($o)) as $p
	  | if $p != null then $t | split("→") | .[:$p + 1] | join("→") | gsub("\\s+$"; "")
	    else $t | split("→") | (if length > 1 then .[:-1] | join("→") else .[0] // "" end)
	      | gsub("\\s+$"; "") end
	  end);
