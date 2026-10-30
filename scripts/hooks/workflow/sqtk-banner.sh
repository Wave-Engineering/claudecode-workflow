#!/usr/bin/env bash
# sqtk-banner.sh — CC Stop hook, OPT-IN per session. Shows BJ his open squawks. (#1236)
#
# The successor to the Stop-hook wait list (~/Documents/stop-hook-wait-list.md): at the end
# of each turn, print the open items of one squawk list (default `bj:needs`) as a
# systemMessage. That goes to the human, so BJ sees what is waiting on him without scrolling
# a busy session. The agents' side of the loop is sqtk-drain.sh.
#
# Wire it only into the sessions BJ chooses, in that project's gitignored
# .claude/settings.local.json, never in the shared settings template. Otherwise every agent
# on the machine prints the same banner:
#
#   {"hooks": {"Stop": [{"hooks": [{"type": "command", "timeout": 10,
#     "command": "~/.claude/scripts/hooks/workflow/sqtk-banner.sh"}]}]}}
#
# Config (env):
#   SQUAWK_URL          the instance (REQUIRED; unset prints nothing)
#   SQTK_BANNER_LIST    the list to show (default bj:needs)
#   SQTK_BANNER_HUMAN   who it is waiting on (default BJ)
#   SQTK_DRAIN_TIMEOUT  the fetch cap in seconds (default 3)
#
# Design (the wait list's lessons):
#   - systemMessage, never `decision: block`: the banner must not stop a turn or loop it.
#   - Silent when nothing is open; an empty banner every turn trains the eye to skip it.
#   - It fails open: any error prints nothing and exits 0. The one exception is a missing or
#     broken sqtk-answer.jq: that prints a one-line warning, since no answer can be read.
#   - The first line of each item only, clipped; the detail lives in squawkie.
#   - An item answered but still open is marked "(answered)". The author drains it. The
#     answer is sqtk-answer.jq's (#1363). The banner shows every agent's items and has no
#     baselines for them, so a pristine squawk is never answered, and an edited one is read
#     after its last `→`.

set -uo pipefail

BASE="${SQUAWK_URL:-}"
LIST="${SQTK_BANNER_LIST:-bj:needs}"
HUMAN="${SQTK_BANNER_HUMAN:-BJ}"
TIMEOUT="${SQTK_DRAIN_TIMEOUT:-3}"

[[ -n "$BASE" ]] || exit 0
command -v curl >/dev/null 2>&1 || exit 0
LIB=$(dirname "$(readlink -f "$0")")
if ! jq -n -L "$LIB" 'include "sqtk-answer"; 1' >/dev/null 2>&1; then
	jq -cn --arg m "⚠ sqtk-banner: cannot load sqtk-answer.jq from $LIB; open squawks are not shown" \
		'{systemMessage: $m}' 2>/dev/null
	exit 0
fi

auth=()
if [[ -n "${SQUAWK_API_TOKEN:-}" ]]; then
	auth=(-H "Authorization: Bearer $SQUAWK_API_TOKEN")
fi

enc=$(jq -rn --arg s "$LIST" '$s | @uri' 2>/dev/null) || exit 0
body=$(curl -fsS --max-time "$TIMEOUT" "${auth[@]}" \
	"${BASE%/}/api/lists/by-name?name=$enc" 2>/dev/null) || exit 0

jq -c -L "$LIB" --arg list "$LIST" --arg human "$HUMAN" '
	include "sqtk-answer";
	def clip: if length > 110 then .[0:107] + "..." else . end;
	[(.squawks // [])[] | select(.state == "open")] | sort_by(.seq) as $open
	| if ($open | length) == 0 then empty else
		{systemMessage: ("⏳ Waiting on \($human) (\($open | length)) in \($list):\n"
			+ ($open | map("• #\(.seq) \(sq_prose(null) | split("\n")[0] | gsub("\\s+$"; "") | clip)"
				+ (if sq_answer(null) != "" then "  (answered)" else "" end)) | join("\n")))}
	  end' <<<"$body" 2>/dev/null || true
exit 0
