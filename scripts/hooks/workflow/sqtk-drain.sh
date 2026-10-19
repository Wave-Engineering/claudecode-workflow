#!/usr/bin/env bash
# sqtk-drain.sh — CC UserPromptSubmit hook. Tells an agent when its squawks were answered. (#1236)
#
# `sqtk add` records every squawk an agent creates in <repo>/.claude/sqtk-mine.json:
#   [{"list": "bj:needs", "seq": 12, "id": 345, "created_at": "..."}, ...]
# That file is sqtk's contract (squawkie-talkie#141); this hook only reads it.
#
# When BJ scratches an item off (confirmed ✓, rejected ✗, retired ◌, recorded ↗), or types
# an answer after a trailing `→`, the author has to find out. A Stop hook's systemMessage
# goes to the human, not the agent, so the drain happens here: at the start of the agent's
# next turn, the change is injected into its context as additionalContext, once.
#
# What has already been reported lives in <repo>/.claude/sqtk-seen.json, owned by this
# hook: {"<id>": "<state>|<answer>"}. A squawk is reported again only if its state or its
# answer changes.
#
# Cost: this runs on every prompt of every session, so the fast paths matter.
#   - No sqtk-mine.json, or no SQUAWK_URL: exit before any network call.
#   - A list whose items have all been reported in a terminal state is not fetched.
#   - Each fetch is capped at SQTK_DRAIN_TIMEOUT seconds (default 3), and at most
#     SQTK_DRAIN_MAX_LISTS lists (default 5) are fetched per prompt.
#
# Contract (CC UserPromptSubmit hook):
#   stdin:  JSON with .cwd
#   stdout: nothing, or one hookSpecificOutput JSON object carrying additionalContext
#   exit:   always 0. It fails open: any error prints nothing and blocks nothing.

set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
HOOK_CWD="${HOOK_CWD:-$(pwd)}"

ROOT=$(git -C "$HOOK_CWD" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$HOOK_CWD")
MINE="$ROOT/.claude/sqtk-mine.json"
SEEN="$ROOT/.claude/sqtk-seen.json"
BASE="${SQUAWK_URL:-}"
TIMEOUT="${SQTK_DRAIN_TIMEOUT:-3}"
MAX_LISTS="${SQTK_DRAIN_MAX_LISTS:-5}"

[[ -s "$MINE" && -n "$BASE" ]] || exit 0
command -v curl >/dev/null 2>&1 || exit 0
jq -e 'type == "array" and length > 0' "$MINE" >/dev/null 2>&1 || exit 0

seen='{}'
if [[ -s "$SEEN" ]]; then
	seen=$(jq -c 'if type == "object" then . else {} end' "$SEEN" 2>/dev/null) || seen='{}'
fi

# Lists worth fetching: those holding at least one item not yet reported in a terminal state.
lists=$(jq -r --argjson seen "$seen" '
	def terminal: test("^(confirmed|rejected|retired|recorded)\\|");
	[.[] | select(($seen[(.id | tostring)] // "") | terminal | not) | .list]
	| unique | .[]' "$MINE" 2>/dev/null | head -n "$MAX_LISTS") || exit 0
[[ -n "$lists" ]] || exit 0

auth=()
if [[ -n "${SQUAWK_API_TOKEN:-}" ]]; then
	auth=(-H "Authorization: Bearer $SQUAWK_API_TOKEN")
fi

# Every fetched list's squawks, merged into one array.
squawks='[]'
while IFS= read -r list; do
	[[ -n "$list" ]] || continue
	enc=$(jq -rn --arg s "$list" '$s | @uri')
	body=$(curl -fsS --max-time "$TIMEOUT" "${auth[@]}" \
		"${BASE%/}/api/lists/by-name?name=$enc" 2>/dev/null) || continue
	squawks=$(jq -c --argjson acc "$squawks" --arg list "$list" \
		'$acc + [(.squawks // [])[] | . + {list: $list}]' <<<"$body" 2>/dev/null) || continue
done <<<"$lists"

# Items whose state or answer changed since the last report. The answer slot is the text
# after the LAST arrow on the squawk; an arrow earlier in the prose is not an answer.
changes=$(jq -c --argjson seen "$seen" --argjson sq "$squawks" '
	def answer: (split("→") | if length > 1 then .[-1] | gsub("^\\s+|\\s+$"; "") else "" end);
	[.[] as $m
	 | ($sq[] | select(.id == $m.id)) as $s
	 | ($s.text | answer) as $a
	 | "\($s.state)|\($a)" as $key
	 | select(($s.state != "open" or $a != "") and ($seen[($m.id | tostring)] // "") != $key)
	 | {id: $m.id, list: $m.list, seq: $s.seq, state: $s.state, answer: $a, text: $s.text, key: $key}]
	' "$MINE" 2>/dev/null) || exit 0
[[ "$(jq 'length' <<<"$changes" 2>/dev/null)" =~ ^[1-9] ]] || exit 0

msg=$(jq -r '
	def glyph: {open:"○",confirmed:"✓",rejected:"✗",retired:"◌",recorded:"↗"}[.] // "?";
	def clip: if length > 160 then .[0:157] + "..." else . end;
	"sqtk: \(length) of your squawks changed since your last turn. Act on each, then carry on:\n"
	+ (map("• [\(.list) #\(.seq)] \(.state | glyph) \(.state)"
		+ (if .answer != "" then ": answered \"\(.answer | clip)\"" else "" end)
		+ " — \(.text | split("→")[0] | gsub("\\s+$"; "") | clip)") | join("\n"))
	' <<<"$changes" 2>/dev/null) || exit 0

# The seen file is per-checkout state and must never be committed (in a GitLab repo it
# carries session detail that is Analogic's). info/exclude is per-clone and untracked, so this
# adds no diff. The `**/` keeps the pattern matching in a session rooted in a subdirectory.
if ! git -C "$ROOT" check-ignore -q "$SEEN" 2>/dev/null; then
	excl=$(git -C "$ROOT" rev-parse --git-path info/exclude 2>/dev/null) &&
		{ [[ "$excl" == /* ]] || excl="$ROOT/$excl"; } &&
		mkdir -p "$(dirname "$excl")" 2>/dev/null &&
		printf '%s\n' '**/.claude/sqtk-*.json' >>"$excl" 2>/dev/null
fi

# Record what was reported before printing, so a crash after this point cannot repeat it
# forever. Atomic: write a temp file, then rename.
tmp="$SEEN.tmp.$$"
if jq -c --argjson ch "$changes" 'reduce $ch[] as $c (.; .[($c.id | tostring)] = $c.key)' \
	<<<"$seen" >"$tmp" 2>/dev/null; then
	mv -f "$tmp" "$SEEN" 2>/dev/null || {
		rm -f "$tmp"
		exit 0
	}
else
	rm -f "$tmp"
	exit 0
fi

jq -cn --arg m "$msg" '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $m}}'
exit 0
