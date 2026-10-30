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
# Stub the drain's --pending catch-up: exit $FAKE_PENDING (default 1, nothing waiting), and
# on 0 print one waiting change, as the real one does.
cat >"$WORK/bin/drain" <<'EOF'
#!/usr/bin/env bash
[[ "$1" == --pending ]] && printf 'called\n' >>"$DRAIN_LOG"
# As the real one does, the catch-up may take a baseline (it runs in the repo root).
[[ -z "${FAKE_TAKE_BASELINE:-}" ]] || printf '%s\n' "$FAKE_TAKE_BASELINE" >.claude/sqtk-baseline.json
[[ "${FAKE_PENDING:-1}" == 0 ]] && printf '%s\n' '[{"id":31,"list":"bj:needs","seq":3,"state":"confirmed","answer":"","text":"tag v9? →"}]'
exit "${FAKE_PENDING:-1}"
EOF
chmod +x "$WORK/bin/drain"
export SQUAWK_URL="http://squawk.test" FAKE_STREAM="$WORK/stream" FAKE_HOLD=0 FAKE_RC=0
export SQTK_DRAIN="$WORK/bin/drain" DRAIN_LOG="$WORK/drain.log"

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

# 7. Every id already settled in a terminal state (incl. gone): nothing open, exit 2.
printf '%s\n' '{"31":"confirmed|"}' >"$REPO/.claude/sqtk-seen.json"
run >/dev/null
[[ $? -eq 2 ]] && pass "all settled: exit 2" || fail "all settled (rc=$?)"
printf '%s\n' '{"31":"gone|"}' >"$REPO/.claude/sqtk-seen.json"
run >/dev/null
[[ $? -eq 2 ]] && pass "all gone: exit 2" || fail "all gone"
printf '%s\n' '{"31":"open|maybe"}' >"$REPO/.claude/sqtk-seen.json"
stream "$(ev squawk.updated 31 open 'tag it? → go')"
run >/dev/null
[[ $? -eq 0 ]] && pass "seen but not terminal: still waited on" || fail "non-terminal seen"
rm -f "$REPO/.claude/sqtk-seen.json"

# 8. An answer that landed before the stream opened: the catch-up rings at once, after the
#    stream's first line, while the stream would otherwise hold.
stream ": connected"
rm -f "$DRAIN_LOG"
start=$SECONDS
out=$(FAKE_PENDING=0 FAKE_HOLD=15 run)
rc=$?
took=$((SECONDS - start))
[[ $rc -eq 0 && "$out" == *sqtk.catch-up* && $took -lt 5 ]] && pass "missed answer: catch-up rings at once" ||
	fail "catch-up (rc=$rc out='$out' ${took}s)"
[[ "$(jq -r '.changes[0].state' <<<"$out" 2>/dev/null)" == confirmed ]] &&
	pass "the catch-up carries the change itself" || fail "catch-up payload (out='$out')"
pkill -f "$WORK/bin/curl" 2>/dev/null
stream ": connected" "$(ev squawk.updated 31 confirmed 'mine → yes')"
rm -f "$DRAIN_LOG"
out=$(run)
[[ $? -eq 0 && "$out" == *'"id":31'* && "$(wc -l <"$DRAIN_LOG")" == 1 ]] &&
	pass "nothing missed: catch-up runs once, then the stream answers" || fail "catch-up then stream (out='$out')"

# 9. An arrow in the author's own text never rings (#1363). evt adds the timestamps.
evt() { # <id> <state> <text> <created_at> <updated_at>
	jq -cn --argjson i "$1" --arg s "$2" --arg x "$3" --arg c "$4" --arg u "$5" -r \
		'"data:" + ({type: "squawk.updated", squawk: {id: $i, state: $s, text: $x, created_at: $c, updated_at: $u}} | tojson)'
}
stream "$(evt 31 open 'campaign→main' t1 t1)"
run >/dev/null
rc=$?
[[ $rc -eq 4 ]] && pass "pristine prose arrow: no ring" || fail "pristine prose arrow rang (rc=$rc)"
printf '%s\n' '{"31":1}' >"$REPO/.claude/sqtk-baseline.json"
stream "$(evt 31 open 'campaign→main fixes' t1 t2)"
run >/dev/null
rc=$?
[[ $rc -eq 4 ]] && pass "baselined prose edit: no ring" || fail "baselined prose edit rang (rc=$rc)"
stream "$(evt 31 open 'campaign→main fix → go' t1 t3)"
out=$(run)
rc=$?
[[ $rc -eq 0 && "$out" == *go* ]] && pass "baselined appended answer: rings" || fail "baselined answer (rc=$rc out='$out')"
rm -f "$REPO/.claude/sqtk-baseline.json"

# 9b. A squawk added this turn has no baseline at arming. The catch-up takes it, and the
#     doorbell reads it before the stream: a prose edit after that does not ring.
stream ": connected" "$(evt 31 open 'campaign→main fixes' t1 t2)"
FAKE_TAKE_BASELINE='{"31":1}' run >/dev/null
rc=$?
[[ $rc -eq 4 ]] && pass "baseline taken by the catch-up: prose edit, no ring" ||
	fail "catch-up baseline ignored (rc=$rc)"
rm -f "$REPO/.claude/sqtk-baseline.json"

# 10. The mine entry's own .text is the baseline at arming.
printf '%s\n' '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t","text":"campaign→main fix"}]' >"$REPO/.claude/sqtk-mine.json"
stream "$(evt 31 open 'campaign→main fixes' t1 t2)"
run >/dev/null
rc=$?
[[ $rc -eq 4 ]] && pass "mine .text baseline: prose edit, no ring" || fail "mine .text prose edit rang (rc=$rc)"
stream "$(evt 31 open 'campaign→main fix → go' t1 t3)"
run >/dev/null
rc=$?
[[ $rc -eq 0 ]] && pass "mine .text baseline: appended answer rings" || fail "mine .text answer (rc=$rc)"
printf '%s\n' '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]' >"$REPO/.claude/sqtk-mine.json"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-doorbell checks passed."
	exit 0
fi
echo "  $FAILS sqtk-doorbell check(s) FAILED."
exit 1
