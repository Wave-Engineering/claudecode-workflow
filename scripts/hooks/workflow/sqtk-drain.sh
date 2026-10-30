#!/usr/bin/env bash
# sqtk-drain.sh — CC UserPromptSubmit hook. Tells an agent when its squawks were answered. (#1236)
#
# `sqtk add` records every squawk an agent creates in <repo>/.claude/sqtk-mine.json:
#   [{"list": "bj:needs", "seq": 12, "id": 345, "created_at": "..."}, ...]
# That file is sqtk's contract (squawkie-talkie#141); this hook only reads it.
#
# When BJ scratches an item off (confirmed ✓, rejected ✗, retired ◌, recorded ↗), or types
# an answer after the `→` slot, the author has to find out. What counts as an answer is
# sqtk-answer.jq's rule (#1363): an arrow in the author's own text never does. A Stop hook's systemMessage
# goes to the human, not the agent, so the drain happens here: at the start of the agent's
# next turn, the change is injected into its context as additionalContext, once.
#
# What has already been reported lives in <repo>/.claude/sqtk-seen.json, owned by this
# hook: {"<id>": "<state>|<answer>"}. A squawk is reported again only if its state or its
# answer changes. A squawk whose list was deleted, or that is gone from its list, is first
# recorded as "missing|<first_ts>|<count>", which still counts as open. Only after
# SQTK_DRAIN_GONE_MISSES misses (default 3) spread over SQTK_DRAIN_GONE_AFTER seconds
# (default 86400) does it become "gone|" and stop costing a fetch. So a passing glitch, a
# redeploy or a wrong SQUAWK_URL, can't silently drop an answer. A squawk that comes back
# clears its miss count.
#
# <repo>/.claude/sqtk-baseline.json, also this hook's: {"<id>": "<original text>"}, each of
# the author's squawks as written, taken while the squawk is still pristine (never edited).
# The answer is read against it. An entry is written once and never overwritten, and an item
# whose sqtk-mine.json entry carries its own `.text` needs none.
#
# If sqtk-answer.jq can't be loaded, the hook says so on stderr and exits 3, in both modes,
# rather than report "nothing waiting".
#
# Cost: this runs on every prompt of every session, so the fast paths matter.
#   - No sqtk-mine.json, or no SQUAWK_URL: exit before any network call.
#   - A list whose items have all been reported in a terminal state is not fetched.
#   - At most SQTK_DRAIN_MAX_LISTS lists (default 5) are fetched per prompt, least recently
#     fetched first (<repo>/.claude/sqtk-fetched.json), so every list gets its turn.
#   - Each fetch is capped at SQTK_DRAIN_TIMEOUT seconds (default 2, connect 1), the whole
#     run at SQTK_DRAIN_BUDGET seconds (default 5, under the hook's 10 s timeout), and the
#     first timed-out fetch ends the run: a server that is down is down for every list.
#   - Fetched lists are filtered to this checkout's ids as they arrive, and every payload
#     goes to jq through a file, never argv, so a long shared list can't hit ARG_MAX.
#
# Contract (CC UserPromptSubmit hook):
#   stdin:  JSON with .cwd
#   stdout: nothing, or one hookSpecificOutput JSON object carrying additionalContext
#   exit:   always 0, except 3 when sqtk-answer.jq can't be loaded (non-blocking in
#           UserPromptSubmit). Otherwise it fails open: any error prints nothing and blocks
#           nothing.
#
# `sqtk-drain.sh --pending` is the doorbell's catch-up check: the same fetch and comparison.
# Exit 0 prints the unreported changes as a JSON array; 1 means nothing is waiting. It leaves
# sqtk-seen.json alone, so the hook still reports each change, but it records what it printed
# in <repo>/.claude/sqtk-rung.json and never prints the same change twice. A re-armed
# doorbell therefore can't ring again and again for one answer if the hook doesn't run.

set -uo pipefail

MODE=hook
[[ "${1:-}" == "--pending" ]] && MODE=pending

none() {
	if [[ $MODE == pending ]]; then exit 1; fi
	exit 0
}

INPUT=""
[[ $MODE == hook ]] && INPUT=$(cat 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
HOOK_CWD="${HOOK_CWD:-$(pwd)}"

ROOT=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$HOOK_CWD")
MINE="$ROOT/.claude/sqtk-mine.json"
SEEN="$ROOT/.claude/sqtk-seen.json"
FETCHED="$ROOT/.claude/sqtk-fetched.json"
RUNG="$ROOT/.claude/sqtk-rung.json"
BASELINE="$ROOT/.claude/sqtk-baseline.json"
# sqtk-answer.jq sits beside this hook, in the repo and in the install.
LIB=$(dirname "$(readlink -f "$0")")
BASE="${SQUAWK_URL:-}"
TIMEOUT="${SQTK_DRAIN_TIMEOUT:-2}"
MAX_LISTS="${SQTK_DRAIN_MAX_LISTS:-5}"
BUDGET="${SQTK_DRAIN_BUDGET:-5}"
GONE_MISSES="${SQTK_DRAIN_GONE_MISSES:-3}"
GONE_AFTER="${SQTK_DRAIN_GONE_AFTER:-86400}"
[[ "$GONE_MISSES" =~ ^[0-9]+$ ]] || GONE_MISSES=3
[[ "$GONE_AFTER" =~ ^[0-9]+$ ]] || GONE_AFTER=86400

[[ -s "$MINE" && -n "$BASE" ]] || none
command -v curl >/dev/null 2>&1 || none
jq -e 'type == "array" and length > 0' "$MINE" >/dev/null 2>&1 || none
# Every answer goes through the module, so a missing or broken one is an error, never "none".
jq -n -L "$LIB" 'include "sqtk-answer"; 1' >/dev/null 2>&1 || {
	echo "sqtk-drain: cannot load sqtk-answer.jq from $LIB; squawk answers are not being read" >&2
	exit 3
}

WORK=$(mktemp -d 2>/dev/null) || none
trap 'rm -rf "$WORK"' EXIT

# Read a JSON object state file into $WORK, or start from {} if it is missing or malformed.
load_obj() {
	if [[ -s "$1" ]] && jq -c 'if type == "object" then . else {} end' "$1" >"$2" 2>/dev/null; then
		return 0
	fi
	printf '{}\n' >"$2"
}
load_obj "$SEEN" "$WORK/seen.json"
load_obj "$FETCHED" "$WORK/fetched.json"
load_obj "$BASELINE" "$WORK/baseline.json"

# Lists worth fetching: those holding at least one item not yet reported in a terminal
# state, least recently fetched first.
lists=$(jq -r --slurpfile seen "$WORK/seen.json" --slurpfile fetched "$WORK/fetched.json" '
	def terminal: test("^(confirmed|rejected|retired|recorded|gone)\\|");
	[.[] | select(($seen[0][(.id | tostring)] // "") | terminal | not) | .list]
	| unique | sort_by($fetched[0][.] // 0) | .[]' "$MINE" 2>/dev/null | head -n "$MAX_LISTS") || none
[[ -n "$lists" ]] || none

auth=()
if [[ -n "${SQUAWK_API_TOKEN:-}" ]]; then
	auth=(-H "Authorization: Bearer $SQUAWK_API_TOKEN")
fi

# Fetch each list and keep only this checkout's squawks, one JSON array per line. A list
# squawkie says it doesn't have gets an empty body, so its ids count a miss below. Any other
# 404 (a proxy's, during a redeploy) is an error like any other, and counts nothing.
: >"$WORK/sq.jsonl"
: >"$WORK/done.txt"
start=$SECONDS
n=0
while IFS= read -r list; do
	[[ -n "$list" ]] || continue
	((SECONDS - start < BUDGET)) || break
	n=$((n + 1))
	enc=$(jq -rn --arg s "$list" '$s | @uri')
	code=$(curl -sS --connect-timeout 1 --max-time "$TIMEOUT" "${auth[@]}" -o "$WORK/body.$n" \
		-w '%{http_code}' "${BASE%/}/api/lists/by-name?name=$enc" 2>/dev/null)
	rc=$?
	((rc == 28)) && break
	if ((rc == 0)) && [[ "$code" == 404 ]]; then
		jq -e '.error == "list not found"' "$WORK/body.$n" >/dev/null 2>&1 || continue
		printf '{}\n' >"$WORK/body.$n"
	elif ((rc != 0)) || [[ "$code" != 2* ]]; then
		continue
	fi
	jq -c --arg list "$list" --slurpfile mine "$MINE" '
		($mine[0] | map(.id)) as $ids
		| [(.squawks // [])[] | select(.id as $i | $ids | index($i)) | . + {list: $list}]' \
		"$WORK/body.$n" >>"$WORK/sq.jsonl" 2>/dev/null || continue
	printf '%s\n' "$list" >>"$WORK/done.txt"
done <<<"$lists"
[[ -s "$WORK/done.txt" ]] || none
jq -s 'add // []' "$WORK/sq.jsonl" >"$WORK/sq.json" 2>/dev/null || none
jq -R . "$WORK/done.txt" | jq -s . >"$WORK/done.json" 2>/dev/null || none

# Items whose state or answer changed since the last report. The answer is sqtk-answer.jq's:
# nothing while the squawk is pristine; with the original text, what follows the author's
# own arrows; without it, the text after the last arrow. The original is the mine entry's
# own `.text` when sqtk recorded it, else sqtk-baseline.json. An item on a fetched list that the
# server no longer returns counts a miss (never reported), and turns "gone" only once the
# misses are both many and old. A key of null clears the entry.
now=$(date +%s)
jq -c -L "$LIB" --slurpfile seen "$WORK/seen.json" --slurpfile sq "$WORK/sq.json" \
	--slurpfile got "$WORK/done.json" --slurpfile baseline "$WORK/baseline.json" \
	--argjson now "$now" --argjson misses "$GONE_MISSES" --argjson after "$GONE_AFTER" '
	include "sqtk-answer";
	def terminal: test("^(confirmed|rejected|retired|recorded|gone)\\|");
	[.[] as $m
	 | select($got[0] | index($m.list))
	 | ($seen[0][($m.id | tostring)] // "") as $prev
	 | ([$sq[0][] | select(.id == $m.id)] | first) as $s
	 | (if ($m.text | type) == "string" then $m.text
	    else $baseline[0][($m.id | tostring)] end | strings // null) as $o
	 | if $s == null then
	     select($prev | terminal | not)
	     | ($prev | capture("^missing\\|(?<t>[0-9]+)\\|(?<c>[0-9]+)$") // {t: "\($now)", c: "0"}) as $p
	     | (($p.c | tonumber) + 1) as $c
	     | {id: $m.id, report: false,
	        key: (if $c >= $misses and $now - ($p.t | tonumber) >= $after then "gone|"
	              else "missing|\($p.t)|\($c)" end)}
	   else
	     ($s | sq_answer($o)) as $a
	     | "\($s.state)|\($a)" as $key
	     | if ($s.state != "open" or $a != "") and $prev != $key then
	         {id: $m.id, list: $m.list, seq: $s.seq, state: $s.state, answer: $a, text: $s.text,
	          o: $o, key: $key, report: true}
	       elif ($prev | startswith("missing|")) then {id: $m.id, key: null, report: false}
	       else empty end
	   end]
	' "$MINE" >"$WORK/changes.json" 2>/dev/null || none

# The state files are per-checkout and must never be committed (in a GitLab repo they carry
# session detail that is the partner's). info/exclude is per-clone and untracked, so this adds
# no diff. The `**/` keeps the pattern matching in a session rooted in a subdirectory, and
# the newline check keeps it from fusing with an unterminated last line.
ensure_excluded() {
	git -C "$ROOT" check-ignore -q "$SEEN" 2>/dev/null && return 0
	local excl
	excl=$(git -C "$ROOT" rev-parse --git-path info/exclude 2>/dev/null) || return 0
	[[ "$excl" == /* ]] || excl="$ROOT/$excl"
	mkdir -p "$(dirname "$excl")" 2>/dev/null || return 0
	{
		if [[ -s "$excl" && -n "$(tail -c 1 "$excl" 2>/dev/null)" ]]; then
			printf '\n' >>"$excl"
		fi
		printf '%s\n' '**/.claude/sqtk-*.json' >>"$excl"
	} 2>/dev/null
}

# record <state_file> <changes_file> <base_file>: apply each change's key to the base state
# (a null key deletes the entry) and write the result to the state file, atomically.
record() {
	local tmp="$1.tmp.$$"
	if jq -c --slurpfile ch "$2" '
		reduce $ch[0][] as $c (.; if $c.key == null then del(.[($c.id | tostring)])
			else .[($c.id | tostring)] = $c.key end)' "$3" >"$tmp" 2>/dev/null &&
		mv -f "$tmp" "$1" 2>/dev/null; then
		return 0
	fi
	rm -f "$tmp"
	return 1
}

# Take a baseline for each of my squawks seen pristine that has none: no `.text` on its mine
# entry and no entry in sqtk-baseline.json. An existing entry is never overwritten. Both modes
# do this, before anything is printed.
jq -c -L "$LIB" --slurpfile sq "$WORK/sq.json" --slurpfile baseline "$WORK/baseline.json" '
	include "sqtk-answer";
	[.[] as $m
	 | select(($m.text | type) != "string" and ($baseline[0] | has($m.id | tostring) | not))
	 | ([$sq[0][] | select(.id == $m.id)] | first) as $s
	 | select($s != null and ($s | pristine))
	 | {id: $m.id, key: ($s.text // "")}]' "$MINE" >"$WORK/newbase.json" 2>/dev/null ||
	printf '[]\n' >"$WORK/newbase.json"
if jq -e 'length > 0' "$WORK/newbase.json" >/dev/null 2>&1; then
	ensure_excluded
	record "$BASELINE" "$WORK/newbase.json" "$WORK/baseline.json" || true
fi

if [[ $MODE == pending ]]; then
	load_obj "$RUNG" "$WORK/rung.json"
	jq -c --slurpfile rung "$WORK/rung.json" '
		[.[] | select(.report and ($rung[0][(.id | tostring)] // "") != .key)]' \
		"$WORK/changes.json" >"$WORK/ring.json" 2>/dev/null || exit 1
	jq -e 'length > 0' "$WORK/ring.json" >/dev/null 2>&1 || exit 1
	ensure_excluded
	# If the rung file can't be written, ring anyway: exit 1 would tell the doorbell nothing
	# is waiting, and an idle agent would miss a real answer. A repeat ring is the lesser fault.
	record "$RUNG" "$WORK/ring.json" "$WORK/rung.json" || true
	jq -c 'map(del(.key, .report, .o))' "$WORK/ring.json"
	exit 0
fi

# Remember when each list was fetched, so the next prompt starts with the others.
jq -c --slurpfile got "$WORK/done.json" --argjson now "$now" \
	'reduce $got[0][] as $l (.; .[$l] = $now)' "$WORK/fetched.json" >"$FETCHED.tmp.$$" 2>/dev/null &&
	mv -f "$FETCHED.tmp.$$" "$FETCHED" 2>/dev/null
rm -f "$FETCHED.tmp.$$"

jq -e 'length > 0' "$WORK/changes.json" >/dev/null 2>&1 || exit 0

msg=""
if jq -e 'any(.[]; .report)' "$WORK/changes.json" >/dev/null 2>&1; then
	msg=$(jq -r -L "$LIB" '
		include "sqtk-answer";
		def glyph: {open:"○",confirmed:"✓",rejected:"✗",retired:"◌",recorded:"↗"}[.] // "?";
		def clip: if length > 160 then .[0:157] + "..." else . end;
		map(select(.report))
		| "sqtk: \(length) of your squawks changed since your last turn. Act on each, then carry on:\n"
		  + (map("• [\(.list) #\(.seq)] \(.state | glyph) \(.state)"
			+ (if .answer != "" then ": answered \"\(.answer | clip)\"" else "" end)
			+ " — \(sq_prose(.o) | clip)") | join("\n"))
		' "$WORK/changes.json" 2>/dev/null) || exit 0
fi

ensure_excluded

# Record what was reported before printing, so a crash after this point cannot repeat it
# forever.
record "$SEEN" "$WORK/changes.json" "$WORK/seen.json" || exit 0

[[ -n "$msg" ]] || exit 0
jq -cn --arg m "$msg" '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $m}}'
exit 0
