#!/usr/bin/env bash
# test_sqtk_drain.sh — #1236 regression test for scripts/hooks/workflow/sqtk-drain.sh.
#
# The drain hook is how an agent learns that BJ answered its squawk. It must report a
# change exactly once, stay silent otherwise, never fetch a list whose items are all
# settled, and fail open: a dead server or a broken file prints nothing and exits 0.
# curl is stubbed on PATH, so no server is needed.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/hooks/workflow/sqtk-drain.sh"

echo "test_sqtk_drain"
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

# Stub curl: log the call, print $FAKE_BODY's contents, exit $FAKE_RC.
cat >"$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CURL_LOG"
[[ "${FAKE_RC:-0}" == 0 ]] || exit "$FAKE_RC"
cat "$FAKE_BODY"
EOF
chmod +x "$WORK/bin/curl"

export CURL_LOG="$WORK/curl.log" FAKE_BODY="$WORK/body.json" FAKE_RC=0
export SQUAWK_URL="http://squawk.test"
MINE="$REPO/.claude/sqtk-mine.json"
SEEN="$REPO/.claude/sqtk-seen.json"

mine() { printf '%s\n' "$1" >"$MINE"; }
body() { printf '%s\n' "$1" >"$FAKE_BODY"; }
run() { jq -cn --arg c "$REPO" '{cwd: $c, prompt: "x"}' | PATH="$WORK/bin:$PATH" bash "$HOOK"; }
calls() { [[ -f "$CURL_LOG" ]] && wc -l <"$CURL_LOG" | tr -d ' ' || echo 0; }
reset() { rm -f "$SEEN" "$CURL_LOG"; }

ctx() { jq -r '.hookSpecificOutput.additionalContext // empty' <<<"$1" 2>/dev/null; }

# 1. No sqtk-mine.json: silent, no fetch.
reset
out=$(run)
rc=$?
[[ $rc -eq 0 && -z "$out" && "$(calls)" == 0 ]] && pass "no mine file: silent, no fetch" ||
	fail "no mine file (rc=$rc out='$out' calls=$(calls))"

# 2. No SQUAWK_URL: silent, no fetch.
mine '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]'
reset
out=$(SQUAWK_URL='' run)
[[ -z "$out" && "$(calls)" == 0 ]] && pass "no SQUAWK_URL: silent, no fetch" ||
	fail "no SQUAWK_URL (out='$out' calls=$(calls))"

# 3. Still open, no answer: silent, nothing recorded.
reset
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"open","text":"[bf·cc] tag v9? →"}]}'
out=$(run)
[[ -z "$out" && ! -s "$SEEN" ]] && pass "open and unanswered: silent" ||
	fail "open and unanswered (out='$out')"

# 4. Answered after the arrow: reported once, with the answer.
reset
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"open","text":"[bf·cc] tag v9? → yes, cut it"}]}'
out=$(run)
c=$(ctx "$out")
[[ "$c" == *"[bj:needs #3]"* && "$c" == *'answered "yes, cut it"'* ]] && pass "answer reported" ||
	fail "answer reported (ctx='$c')"
out=$(run)
[[ -z "$out" ]] && pass "same answer: not reported again" || fail "same answer repeated (out='$out')"

# 5. Then confirmed: reported once more, as the new state.
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"confirmed","text":"[bf·cc] tag v9? → yes, cut it"}]}'
out=$(run)
c=$(ctx "$out")
[[ "$c" == *"✓ confirmed"* ]] && pass "state change reported" || fail "state change (ctx='$c')"

# 6. Every item settled in a terminal state: the list is not fetched again.
rm -f "$CURL_LOG"
out=$(run)
[[ -z "$out" && "$(calls)" == 0 ]] && pass "settled list: not fetched" ||
	fail "settled list fetched (calls=$(calls))"

# 7. An arrow in the prose is not an answer; only the last one is the slot.
mine '[{"list":"cc:triage","seq":1,"id":41,"created_at":"t"}]'
reset
body '{"name":"cc:triage","squawks":[{"id":41,"seq":1,"state":"open","text":"v65 → v66 broke the gate →"}]}'
out=$(run)
[[ -z "$out" ]] && pass "prose arrow is not an answer" || fail "prose arrow read as answer (out='$out')"

# 8. Another agent's squawk on the same list is never reported.
body '{"name":"cc:triage","squawks":[{"id":41,"seq":1,"state":"open","text":"mine →"},{"id":99,"seq":2,"state":"rejected","text":"theirs"}]}'
reset
out=$(run)
[[ -z "$out" ]] && pass "others' squawks ignored" || fail "reported another agent's squawk (out='$out')"

# 9. Fails open: server down, malformed body, malformed mine file.
mine '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]'
reset
out=$(FAKE_RC=7 run)
rc=$?
[[ $rc -eq 0 && -z "$out" ]] && pass "server down: silent, exit 0" || fail "server down (rc=$rc out='$out')"
body 'not json'
out=$(run)
rc=$?
[[ $rc -eq 0 && -z "$out" ]] && pass "malformed body: silent, exit 0" || fail "malformed body (rc=$rc)"
mine '{not json'
out=$(run)
rc=$?
[[ $rc -eq 0 && -z "$out" ]] && pass "malformed mine file: silent, exit 0" || fail "malformed mine (rc=$rc)"

# 10. A corrupt seen file is treated as empty, not as a reason to go quiet forever.
mine '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]'
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"rejected","text":"tag v9?"}]}'
printf 'garbage' >"$SEEN"
rm -f "$CURL_LOG"
out=$(run)
c=$(ctx "$out")
[[ "$c" == *"✗ rejected"* ]] && pass "corrupt seen file: still reports" || fail "corrupt seen (ctx='$c')"

# 11. The state files are git-ignored per clone, and the entry is written only once.
if git -C "$REPO" check-ignore -q "$SEEN" && git -C "$REPO" check-ignore -q "$MINE"; then
	pass "sqtk state files are ignored"
else
	fail "sqtk state files are not ignored"
fi
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"open","text":"tag v9? → later"}]}'
run >/dev/null
n=$(grep -c 'sqtk-' "$REPO/.git/info/exclude")
[[ "$n" == 1 ]] && pass "exclude entry written once" || fail "exclude entry count $n"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-drain checks passed."
	exit 0
fi
echo "  $FAILS sqtk-drain check(s) FAILED."
exit 1
