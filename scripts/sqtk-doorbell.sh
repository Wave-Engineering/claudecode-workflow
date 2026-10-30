#!/usr/bin/env bash
# sqtk-doorbell.sh — one-shot: block until one of THIS repo's squawks is answered, then exit. (#1236)
#
# A busy agent learns about answers from sqtk-drain.sh at the start of its next turn. An
# idle agent has no next turn, so this wakes it. Run it as a background task. Its EXIT is
# the doorbell: one answer, one exit, one task notification, one turn. The drain hook then
# reports what changed. Re-arm after each wake. (The same inversion as crewchat-doorbell,
# for the same reason: on Bedrock there is no Monitor primitive, and only a task's exit
# notifies the agent.)
#
#   Bash({ command: "~/.claude/scripts/sqtk-doorbell.sh", run_in_background: true })
#
# It listens on squawkie's SSE feed (GET /api/stream) for a `squawk.updated` event on one of
# the ids in <repo>/.claude/sqtk-mine.json, where the squawk is no longer open or has an
# answer. The answer is hooks/workflow/sqtk-answer.jq's (#1363): an arrow in the author's own
# text never counts. Each squawk's baseline comes from its mine entry's `.text`, else from
# <repo>/.claude/sqtk-baseline.json (the drain hook's). Ids the drain hook has already
# reported in a terminal state (<repo>/.claude/sqtk-seen.json) are left out. The id set and
# baselines are read once at arming time, so re-arm after adding new squawks.
#
# An answer can land between the drain hook's run at the start of a turn and the arming of
# this doorbell at its end. So once the stream is live (squawkie writes `: connected` on
# subscribe; an older server gets 2 s), it runs `sqtk-drain.sh --pending` once. Anything
# unreported rings at once, carrying the changes. Anything later arrives on the stream, so no
# answer falls between. --pending never hands back a change it has already rung for, so a
# re-arm after a catch-up waits for something new rather than ringing again.
#
# THE EXIT CODE IS THE SIGNAL, so it never lies:
#   0  one of my squawks was answered (the event's JSON is on stdout, or
#      {"type":"sqtk.catch-up","changes":[...]} when the answer landed before the stream
#      opened; each change has id, list, seq, state, answer and text)
#   2  nothing to wait for: no SQUAWK_URL, no sqtk-mine.json, or every id in it is settled
#   3  SQTK_DOORBELL_TIMEOUT seconds passed with no answer (default 0 = wait forever)
#   4  the stream could not be opened, or it ended (server restart, network drop).
#      This is NOT an answer: re-arm after a pause, don't spin.
#
# Config (env): SQUAWK_URL (required), SQUAWK_API_TOKEN (optional), SQTK_DOORBELL_TIMEOUT.

set -uo pipefail

BASE="${SQUAWK_URL:-}"
TIMEOUT="${SQTK_DOORBELL_TIMEOUT:-0}"

ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
MINE="$ROOT/.claude/sqtk-mine.json"
SEEN="$ROOT/.claude/sqtk-seen.json"
BASELINE="$ROOT/.claude/sqtk-baseline.json"
# The drain hook and sqtk-answer.jq sit beside this script in the repo and in the install
# (~/.claude/scripts/).
HERE=$(dirname "$(readlink -f "$0")")
DRAIN="${SQTK_DRAIN:-$HERE/hooks/workflow/sqtk-drain.sh}"
LIB="$HERE/hooks/workflow"

[[ -n "$BASE" ]] || {
	echo "sqtk-doorbell: SQUAWK_URL is not set" >&2
	exit 2
}
command -v curl >/dev/null 2>&1 || {
	echo "sqtk-doorbell: curl not found" >&2
	exit 4
}
seen='{}'
if [[ -s "$SEEN" ]]; then
	seen=$(jq -c 'if type == "object" then . else {} end' "$SEEN" 2>/dev/null) || seen='{}'
fi
ids=$(jq -c --argjson seen "$seen" '
	def terminal: test("^(confirmed|rejected|retired|recorded|gone)\\|");
	[.[] | select(($seen[(.id | tostring)] // "") | terminal | not) | .id | numbers]' \
	"$MINE" 2>/dev/null) || ids='[]'
[[ "$ids" != "[]" ]] || {
	echo "sqtk-doorbell: nothing open to wait for in $MINE" >&2
	exit 2
}
# bl = {"<id>": P}: the mine entry's own `.text` wins over the drain's baseline file.
load_baselines() {
	local baseline='{}'
	if [[ -s "$BASELINE" ]]; then
		baseline=$(jq -c 'if type == "object" then . else {} end' "$BASELINE" 2>/dev/null) || baseline='{}'
	fi
	bl=$(jq -c -L "$LIB" --argjson base "$baseline" '
		include "sqtk-answer";
		reduce (.[] | select((.text | type) == "string")) as $m ($base;
			.[($m.id | tostring)] = ($m.text | prose_arrows))' "$MINE" 2>/dev/null) || bl="$baseline"
}
load_baselines

auth=()
if [[ -n "${SQUAWK_API_TOKEN:-}" ]]; then
	auth=(-H "Authorization: Bearer $SQUAWK_API_TOKEN")
fi
max=()
if [[ "$TIMEOUT" =~ ^[1-9][0-9]*$ ]]; then
	max=(--max-time "$TIMEOUT")
fi

# Read the stream through a process substitution rather than a pipe, so a match can kill
# curl at once. A pipe would hold the exit until curl's next write hit SIGPIPE, which is
# up to squawkie's ~25 s heartbeat. curl's own status then tells a timeout (28) from a
# dropped or refused stream.
exec 3< <(exec curl -fsSN "${auth[@]}" "${max[@]}" -H 'Accept: text/event-stream' \
	"${BASE%/}/api/stream" 2>/dev/null)
curl_pid=$!

# Exit 0 with the event if this stream line answers one of my squawks.
ring_if_answer() {
	[[ "$1" == data:* ]] || return 0
	local ev="${1#data:}"
	if jq -e -L "$LIB" --argjson ids "$ids" --argjson bl "$bl" '
		include "sqtk-answer";
		.type == "squawk.updated" and (.squawk.id as $i | $ids | index($i)) != null
		and (.squawk.state != "open"
			or (.squawk | sq_answer($bl[(.id | tostring)] | numbers // null)) != "")' <<<"$ev" >/dev/null 2>&1; then
		kill "$curl_pid" 2>/dev/null
		printf '%s\n' "$ev"
		exit 0
	fi
}

stream_ended() {
	wait "$curl_pid" 2>/dev/null
	local rc=$?
	[[ $rc == 28 ]] && exit 3
	echo "sqtk-doorbell: the stream ended or could not be opened (curl exit $rc)" >&2
	exit 4
}

# Catch up once the stream is live: after its first line (normally `: connected`), or 2 s.
line=""
IFS= read -r -t 2 line <&3
first_rc=$?
if [[ -x "$DRAIN" ]] && pending=$(cd "$ROOT" && "$DRAIN" --pending 2>/dev/null); then
	kill "$curl_pid" 2>/dev/null
	jq -c '{type: "sqtk.catch-up", changes: .}' <<<"$pending" 2>/dev/null ||
		printf '%s\n' '{"type":"sqtk.catch-up","changes":[]}'
	exit 0
fi
# The catch-up is often the first drain to see a squawk added this turn, and it takes that
# squawk's baseline. Read the baselines again, or its updates would get the last-arrow rule.
load_baselines
# 0 is a line; above 128 is the 2 s timeout with the stream still open; anything else is EOF.
if ((first_rc == 0)); then
	ring_if_answer "$line"
elif ((first_rc <= 128)); then
	stream_ended
fi

while IFS= read -r line <&3; do
	ring_if_answer "$line"
done
stream_ended
