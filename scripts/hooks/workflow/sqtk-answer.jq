# sqtk-answer.jq — the one definition of a squawk's answer, for the kit's sqtk hooks. (#1363)
#
# Load it with `jq -L <this dir> 'include "sqtk-answer"; …'`. sqtk-drain.sh, sqtk-banner.sh
# and sqtk-doorbell.sh all read answers through it.
#
# squawkie has no answer field. An answer is stored in-band: BJ types it after the squawk's
# `→` slot, and an agent records an item with `sqtk set --text "<text> → #N"`. So an arrow
# in the author's own prose ("campaign→main") must never be read as the start of an answer.
# The answer is what was added after the author's text, measured by arrow count:
#   1. pristine: created_at == updated_at, so the squawk was never edited and holds no answer;
#   2. baseline known: P is the number of prose arrows in the author's original text (see
#      prose_arrows). The answer is everything after the (P+1)-th arrow of the current text,
#      so BJ's edits to the prose make no answer, and an answer may hold arrows of its own;
#   3. baseline unknown: the old rule, everything after the last arrow. An item answered
#      before #1363 has no baseline, and this keeps its answer string, so it is not
#      re-reported.
# The baseline P comes from the item's sqtk-mine.json `.text` once sqtk records it, else from
# <repo>/.claude/sqtk-baseline.json, which sqtk-drain.sh fills while the squawk is pristine.

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

# Input: a squawk; $p is its baseline (a number) or null. Its answer, or "".
def sq_answer($p):
	if pristine then ""
	elif $p != null then (.text // "") | answer_after($p)
	else (.text // "") | legacy_answer end;

# Input: a squawk; $p as above. The author's text, for display.
def sq_prose($p):
	(.text // "") as $t
	| if pristine then $t | sub("\\s*(→\\s*)?$"; "")
	  elif $p != null then $t | split("→") | .[:$p + 1] | join("→") | gsub("\\s+$"; "")
	  else $t | split("→") | (if length > 1 then .[:-1] | join("→") else .[0] // "" end)
	    | gsub("\\s+$"; "") end;
