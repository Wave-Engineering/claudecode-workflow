#!/usr/bin/env bash
# sqtk-doorbell.sh — one-shot: block until one of THIS repo's squawks is answered, then exit. (#1236)
#
# A busy agent learns about answers from sqtk-drain.sh at the start of its next turn. An
# idle agent has no next turn, so this wakes it. Run it as a background task. Its EXIT is
# the doorbell: one answer, one exit, one task notification, one turn. The drain hook then
# reports what changed. Re-arm after each wake. (The same inversion as doorbell-oneshot.sh,
# for the same reason: on Bedrock there is no Monitor primitive, and only a task's exit
# notifies the agent.)
#
#   Bash({ command: "~/.claude/scripts/sqtk-doorbell.sh", run_in_background: true })
#
# It listens on squawkie's SSE feed (GET /api/stream) for a `squawk.updated` event on one of
# the ids in <repo>/.claude/sqtk-mine.json, where the squawk is no longer open or has an
# answer after its last `→`. The id set is read once at arming time, so re-arm after adding
# new squawks.
#
# THE EXIT CODE IS THE SIGNAL, so it never lies:
#   0  one of my squawks was answered (the event's JSON is on stdout)
#   2  nothing to wait for: no SQUAWK_URL, no sqtk-mine.json, or no ids in it
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

[[ -n "$BASE" ]] || {
	echo "sqtk-doorbell: SQUAWK_URL is not set" >&2
	exit 2
}
command -v curl >/dev/null 2>&1 || {
	echo "sqtk-doorbell: curl not found" >&2
	exit 4
}
ids=$(jq -c '[.[].id | numbers]' "$MINE" 2>/dev/null) || ids='[]'
[[ "$ids" != "[]" ]] || {
	echo "sqtk-doorbell: no squawks to wait for in $MINE" >&2
	exit 2
}

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

while IFS= read -r line <&3; do
	[[ "$line" == data:* ]] || continue
	ev="${line#data:}"
	if jq -e --argjson ids "$ids" '
		def answer: (split("→") | if length > 1 then .[-1] | gsub("^\\s+|\\s+$"; "") else "" end);
		.type == "squawk.updated" and (.squawk.id as $i | $ids | index($i)) != null
		and (.squawk.state != "open" or (.squawk.text | answer) != "")' <<<"$ev" >/dev/null 2>&1; then
		kill "$curl_pid" 2>/dev/null
		printf '%s\n' "$ev"
		exit 0
	fi
done

wait "$curl_pid" 2>/dev/null
rc=$?
[[ $rc == 28 ]] && exit 3
echo "sqtk-doorbell: the stream ended or could not be opened (curl exit $rc)" >&2
exit 4
