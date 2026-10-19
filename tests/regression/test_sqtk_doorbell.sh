#!/usr/bin/env bash
# test_sqtk_doorbell.sh — #1236 regression test for scripts/sqtk-doorbell.sh.
#
# The doorbell's exit IS the wake-up, so its exit code must never lie: 0 only for a real
# answer on one of my squawks, and promptly, not at the next heartbeat. curl is stubbed on
# PATH with a fake SSE stream that stays open after its frames, the way the server's does.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
BELL="$REPO_DIR/scripts/sqtk-doorbell.sh"

echo "test_sqtk_doorbell"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
REPO="$WORK/repo"
mkdir -p "$REPO/.claude" "$WORK/bin"
git -C "$REPO" init -q
printf '%s\n' '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]' >"$REPO/.claude/sqtk-mine.json"

# Fake stream: print $FAKE_STREAM's lines, then either hold the connection open
# ($FAKE_HOLD seconds) or exit with $FAKE_RC.
cat >"$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
[[ -n "${FAKE_STREAM:-}" ]] && cat "$FAKE_STREAM"
[[ "${FAKE_HOLD:-0}" != 0 ]] && sleep "$FAKE_HOLD"
exit "${FAKE_RC:-0}"
EOF
chmod +x "$WORK/bin/curl"
export SQUAWK_URL="http://squawk.test" FAKE_STREAM="$WORK/stream" FAKE_HOLD=0 FAKE_RC=0

stream() { printf '%s\n' "$@" >"$FAKE_STREAM"; }
run() { (cd "$REPO" && PATH="$WORK/bin:$PATH" timeout 20 bash "$BELL" 2>/dev/null); }

ev() { # <type> <id> <state> <text>
	jq -cn --arg t "$1" --argjson i "$2" --arg s "$3" --arg x "$4" \
		'"data:" + ({type: $t, squawk: {id: $i, state: $s, text: $x}} | tojson)' -r
}

# 1. An answer on my squawk: exit 0 with the event, promptly, while the stream stays open.
stream ": connected" "" \
	"$(ev squawk.updated 99 confirmed 'not mine')" \
	"$(ev squawk.updated 31 open 'mine, still unanswered →')" \
	"$(ev squawk.created 31 open 'wrong type')" \
	"$(ev squawk.updated 31 confirmed 'mine → yes')"
start=$SECONDS
out=$(FAKE_HOLD=15 run)
rc=$?
took=$((SECONDS - start))
[[ $rc -eq 0 && "$out" == *'"id":31'* && "$out" == *confirmed* ]] && pass "answer on mine: exit 0 with the event" ||
	fail "answer on mine (rc=$rc out='$out')"
[[ $took -lt 5 ]] && pass "exits at once, not at the stream's next write (${took}s)" ||
	fail "held until the stream closed (${took}s)"
# A real SSE stream never ends, so a curl left running after the wake would live forever.
sleep 0.5
if pgrep -f "$WORK/bin/curl" >/dev/null; then
	fail "the stream process was left running after the wake"
	pkill -f "$WORK/bin/curl"
else
	pass "the stream process is gone after the wake"
fi

# 2. An answer after the arrow, state still open, also wakes.
stream "$(ev squawk.updated 31 open 'tag it? → go')"
out=$(run)
[[ $? -eq 0 && "$out" == *go* ]] && pass "open-but-answered wakes" || fail "open-but-answered"

# 3. Only noise, then the stream ends: exit 4, never 0.
stream "$(ev squawk.updated 99 rejected 'not mine')" "$(ev squawk.updated 31 open 'unanswered')"
run >/dev/null
rc=$?
[[ $rc -eq 4 ]] && pass "stream ended without an answer: exit 4" || fail "stream end (rc=$rc)"

# 4. curl timed out (28): exit 3.
stream ": connected"
FAKE_RC=28 run >/dev/null
rc=$?
[[ $rc -eq 3 ]] && pass "timeout: exit 3" || fail "timeout (rc=$rc)"

# 5. Connection refused (7): exit 4.
FAKE_STREAM='' FAKE_RC=7 run >/dev/null
rc=$?
[[ $rc -eq 4 ]] && pass "refused: exit 4" || fail "refused (rc=$rc)"

# 6. Nothing to wait for: exit 2.
(cd "$REPO" && SQUAWK_URL='' PATH="$WORK/bin:$PATH" bash "$BELL" >/dev/null 2>&1)
[[ $? -eq 2 ]] && pass "no SQUAWK_URL: exit 2" || fail "no SQUAWK_URL"
mv "$REPO/.claude/sqtk-mine.json" "$WORK/mine.bak"
run >/dev/null
[[ $? -eq 2 ]] && pass "no sqtk-mine.json: exit 2" || fail "no mine file"
mv "$WORK/mine.bak" "$REPO/.claude/sqtk-mine.json"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-doorbell checks passed."
	exit 0
fi
echo "  $FAILS sqtk-doorbell check(s) FAILED."
exit 1
