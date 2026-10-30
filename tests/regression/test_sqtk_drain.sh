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

# Stub curl: log the call, then exit $FAKE_RC, or write $FAKE_BODY to -o's file (stdout
# without -o) and print $FAKE_CODE (default 200) for -w, as real curl does.
cat >"$WORK/bin/curl" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$CURL_LOG"
[[ "${FAKE_RC:-0}" == 0 ]] || exit "$FAKE_RC"
out="" fmt=""
while (($#)); do
	case "$1" in
	-o) out="$2"; shift ;;
	-w) fmt="$2"; shift ;;
	esac
	shift
done
if [[ -n "$out" ]]; then cat "$FAKE_BODY" >"$out"; else cat "$FAKE_BODY"; fi
[[ -z "$fmt" ]] || printf '%s' "${FAKE_CODE:-200}"
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
BASELINE="$REPO/.claude/sqtk-baseline.json"
reset() { rm -f "$SEEN" "$CURL_LOG" "$BASELINE" "$REPO/.claude/sqtk-fetched.json" "$REPO/.claude/sqtk-rung.json"; }

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

# 12. An info/exclude with no final newline keeps its last pattern intact.
REPO2="$WORK/repo2"
mkdir -p "$REPO2/.claude"
git -C "$REPO2" init -q
printf 'last-pattern' >"$REPO2/.git/info/exclude"
printf '%s\n' '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]' >"$REPO2/.claude/sqtk-mine.json"
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"retired","text":"tag v9?"}]}'
jq -cn --arg c "$REPO2" '{cwd: $c, prompt: "x"}' | PATH="$WORK/bin:$PATH" bash "$HOOK" >/dev/null
if grep -qx 'last-pattern' "$REPO2/.git/info/exclude" && grep -qxF '**/.claude/sqtk-*.json' "$REPO2/.git/info/exclude"; then
	pass "unterminated exclude: both patterns intact"
else
	fail "unterminated exclude fused ($(tr '\n' '|' <"$REPO2/.git/info/exclude"))"
fi

# 13. A long shared list (over ARG_MAX's 128 KB per argument) still reports.
mine '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]'
reset
jq -cn '{name: "bj:needs", squawks: ([range(1000) | {id: (. + 1000), seq: (. + 10), state: "open",
	text: ("another agent squawk, padded " + ("x" * 300))}] + [{id: 31, seq: 3, state: "confirmed", text: "tag v9? →"}])}' >"$FAKE_BODY"
out=$(run)
c=$(ctx "$out")
[[ $(wc -c <"$FAKE_BODY") -gt 131072 && "$c" == *"✓ confirmed"* ]] && pass "list over 128 KB: still reports" ||
	fail "long list (size=$(wc -c <"$FAKE_BODY") ctx='$c')"

# 14. Display text keeps everything before the LAST arrow.
reset
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"retired","text":"v65 → v66 broke the gate → let it go"}]}'
c=$(ctx "$(run)")
[[ "$c" == *"— v65 → v66 broke the gate"* ]] && pass "display text cut at the last arrow" ||
	fail "display text (ctx='$c')"

# 15. More pending lists than SQTK_DRAIN_MAX_LISTS: they take turns.
mine '[{"list":"a","seq":1,"id":51,"created_at":"t"},{"list":"b","seq":1,"id":52,"created_at":"t"},{"list":"c","seq":1,"id":53,"created_at":"t"}]'
reset
body '{"name":"x","squawks":[{"id":51,"seq":1,"state":"open","text":"a?"},{"id":52,"seq":1,"state":"open","text":"b?"},{"id":53,"seq":1,"state":"open","text":"c?"}]}'
SQTK_DRAIN_MAX_LISTS=2 run >/dev/null
first=$(grep -o 'name=[a-z]*' "$CURL_LOG" | tr '\n' ' ')
sleep 1
rm -f "$CURL_LOG"
SQTK_DRAIN_MAX_LISTS=2 run >/dev/null
second=$(grep -o 'name=[a-z]*' "$CURL_LOG" | head -n 1)
[[ "$first" == "name=a name=b " && "$second" == "name=c" ]] && pass "lists rotate past the cap" ||
	fail "rotation (first='$first' second='$second')"

seen_of() { jq -r --arg i "$1" '.[$i] // empty' "$SEEN" 2>/dev/null; }

# 16. A deleted list (squawkie's own 404) counts a miss, silently, and is still fetched.
#     Only many misses over time make it gone; then it is never fetched again.
mine '[{"list":"gone-list","seq":1,"id":61,"created_at":"t"}]'
reset
body '{"error":"list not found"}'
out=$(FAKE_CODE=404 run)
[[ -z "$out" && "$(seen_of 61)" == missing\|*\|1 ]] && pass "404 list: one miss, silent" ||
	fail "404 list (out='$out' seen=$(cat "$SEEN" 2>/dev/null))"
rm -f "$CURL_LOG"
FAKE_CODE=404 run >/dev/null
FAKE_CODE=404 run >/dev/null
[[ "$(calls)" == 2 && "$(seen_of 61)" == missing\|*\|3 ]] && pass "recent misses: still open, still fetched" ||
	fail "recent misses (calls=$(calls) seen=$(cat "$SEEN" 2>/dev/null))"
FAKE_CODE=404 SQTK_DRAIN_GONE_AFTER=0 run >/dev/null
[[ "$(seen_of 61)" == "gone|" ]] && pass "many old misses: marked gone" ||
	fail "old misses (seen=$(cat "$SEEN" 2>/dev/null))"
rm -f "$CURL_LOG"
run >/dev/null
[[ "$(calls)" == 0 ]] && pass "gone list: not fetched again" || fail "gone list refetched (calls=$(calls))"

# 16b. A 404 that isn't squawkie's (a proxy during a redeploy) counts nothing.
reset
body '<html>404 Not Found</html>'
FAKE_CODE=404 SQTK_DRAIN_GONE_MISSES=0 SQTK_DRAIN_GONE_AFTER=0 run >/dev/null
[[ ! -s "$SEEN" ]] && pass "foreign 404: no miss recorded" || fail "foreign 404 (seen=$(cat "$SEEN" 2>/dev/null))"

# 17. A squawk missing from its (fetched) list counts a miss; when it comes back, the
#     miss is cleared.
mine '[{"list":"bj:needs","seq":9,"id":71,"created_at":"t"}]'
reset
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"open","text":"other"}]}'
run >/dev/null
[[ "$(seen_of 71)" == missing\|*\|1 ]] && pass "vanished squawk: one miss" ||
	fail "vanished squawk (seen=$(cat "$SEEN" 2>/dev/null))"
body '{"name":"bj:needs","squawks":[{"id":71,"seq":9,"state":"open","text":"back again →"}]}'
run >/dev/null
[[ -z "$(seen_of 71)" ]] && pass "squawk back: miss cleared" || fail "miss not cleared (seen=$(cat "$SEEN" 2>/dev/null))"

# 18. A timed-out fetch (curl 28) ends the run: one call, not one per list.
mine '[{"list":"a","seq":1,"id":51,"created_at":"t"},{"list":"b","seq":1,"id":52,"created_at":"t"},{"list":"c","seq":1,"id":53,"created_at":"t"}]'
reset
out=$(FAKE_RC=28 run)
rc=$?
[[ $rc -eq 0 && -z "$out" && "$(calls)" == 1 ]] && pass "timeout: stops after the first fetch" ||
	fail "timeout (rc=$rc calls=$(calls))"

# 19. --pending (the doorbell's catch-up): exit 1 with nothing waiting; exit 0 printing the
#     change when something is, without touching the seen file. It never prints the same
#     change twice, so a re-armed doorbell can't loop on it, and the hook still reports it.
mine '[{"list":"bj:needs","seq":3,"id":31,"created_at":"t"}]'
reset
pending() { (cd "$REPO" && PATH="$WORK/bin:$PATH" bash "$HOOK" --pending) >"$WORK/pending.out"; }
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"open","text":"tag v9? →"}]}'
pending
rc=$?
[[ $rc -eq 1 && ! -s "$WORK/pending.out" ]] && pass "--pending, nothing waiting: exit 1" ||
	fail "--pending none (rc=$rc)"
body '{"name":"bj:needs","squawks":[{"id":31,"seq":3,"state":"confirmed","text":"tag v9? →"}]}'
pending
rc=$?
[[ $rc -eq 0 && "$(jq -r '.[0].state' "$WORK/pending.out" 2>/dev/null)" == confirmed && ! -s "$SEEN" ]] &&
	pass "--pending, answer waiting: exit 0, prints it, seen untouched" ||
	fail "--pending waiting (rc=$rc out=$(cat "$WORK/pending.out") seen=$(cat "$SEEN" 2>/dev/null))"
pending
rc=$?
[[ $rc -eq 1 ]] && pass "--pending again: the same change is not rung twice" || fail "--pending re-rang (rc=$rc)"
c=$(ctx "$(run)")
[[ "$c" == *"✓ confirmed"* ]] && pass "after --pending, the hook still reports it" || fail "post-pending report (ctx='$c')"

# 20. An arrow in the author's own text is never an answer (#1363). A fresh squawk with a
#     prose arrow (triage #22's shape) is silent, and the drain takes its baseline: the
#     original text.
base_of() { jq -r --arg i "$1" '.[$i] // empty' "$BASELINE" 2>/dev/null; }
mine '[{"list":"cc:triage","seq":5,"id":81,"created_at":"t"}]'
reset
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"issue #23 → 2979849633","created_at":"t1","updated_at":"t1"}]}'
out=$(run)
[[ -z "$out" && "$(base_of 81)" == "issue #23 → 2979849633" ]] && pass "fresh prose-arrow squawk: silent, baseline recorded" ||
	fail "fresh prose-arrow squawk (out='$out' baseline=$(cat "$BASELINE" 2>/dev/null))"
git -C "$REPO" check-ignore -q "$BASELINE" && pass "baseline file is under the sqtk-*.json exclude" ||
	fail "baseline file not excluded"

# 20b. Once baselined, an edit to the last segment of the prose, with no new arrow, is still
#      silent.
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"issue #23 → 2979849633 (edited)","created_at":"t1","updated_at":"t2"}]}'
out=$(run)
[[ -z "$out" ]] && pass "baselined prose edit: silent" || fail "baselined prose edit (out='$out')"

# 20c. An arrow added after the author's text is the answer, and the shown text keeps the
#      prose arrow.
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"issue #23 → 2979849633 → yes","created_at":"t1","updated_at":"t3"}]}'
c=$(ctx "$(run)")
[[ "$c" == *'answered "yes"'* && "$c" == *"— issue #23 → 2979849633"* ]] &&
	pass "baselined appended answer: reported" || fail "baselined appended answer (ctx='$c')"

# 20c2. An edit left of an author arrow is the one accepted false positive: the text after
#       the last arrow reads as an answer.
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"issue #24 → 2979849633","created_at":"t1","updated_at":"t4"}]}'
c=$(ctx "$(run)")
[[ "$c" == *'answered "2979849633"'* ]] && pass "baselined earlier-segment edit: read by the last arrow" ||
	fail "baselined earlier-segment edit (ctx='$c')"

# 20d. A baseline is never overwritten.
reset
printf '{"81":"x → y"}\n' >"$BASELINE"
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"a → b","created_at":"t1","updated_at":"t1"}]}'
run >/dev/null
[[ "$(base_of 81)" == "x → y" ]] && pass "existing baseline not overwritten" ||
	fail "baseline overwritten ($(cat "$BASELINE" 2>/dev/null))"

# 20e. A numeric baseline (an older shape) is unknown: the last-arrow rule.
reset
printf '{"81":1}\n' >"$BASELINE"
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"x→y → #12","created_at":"t1","updated_at":"t2"}]}'
c=$(ctx "$(run)")
[[ "$c" == *'answered "#12"'* ]] && pass "numeric baseline: last-arrow rule" || fail "numeric baseline (ctx='$c')"

# 21. The mine entry's own .text is the baseline, with no baseline file.
mine '[{"list":"cc:triage","seq":6,"id":82,"created_at":"t","text":"campaign→main fix"}]'
reset
body '{"name":"cc:triage","squawks":[{"id":82,"seq":6,"state":"open","text":"campaign→main fixes","created_at":"t1","updated_at":"t2"}]}'
out=$(run)
[[ -z "$out" && ! -e "$BASELINE" ]] && pass "mine .text is the baseline: prose arrow silent, no file" ||
	fail "mine .text prose (out='$out' baseline=$(cat "$BASELINE" 2>/dev/null))"
body '{"name":"cc:triage","squawks":[{"id":82,"seq":6,"state":"open","text":"campaign→main fix → go","created_at":"t1","updated_at":"t3"}]}'
c=$(ctx "$(run)")
[[ "$c" == *'answered "go"'* ]] && pass "mine .text is the baseline: appended answer reported" ||
	fail "mine .text answer (ctx='$c')"

# 22. An item answered before #1363 has no baseline: the same answer string as before, so its
#     seen key matches and it is not re-reported.
mine '[{"list":"cc:triage","seq":7,"id":83,"created_at":"t"}]'
reset
printf '{"83":"open|b"}\n' >"$SEEN"
body '{"name":"cc:triage","squawks":[{"id":83,"seq":7,"state":"open","text":"a → b","created_at":"t1","updated_at":"t2"}]}'
out=$(run)
[[ -z "$out" && ! -e "$BASELINE" ]] && pass "legacy answered item not re-reported" ||
	fail "legacy answered item (out='$out')"

# 23. --pending takes baselines too, and still says nothing is waiting.
mine '[{"list":"cc:triage","seq":5,"id":81,"created_at":"t"}]'
reset
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"open","text":"campaign→main fix","created_at":"t1","updated_at":"t1"}]}'
pending
rc=$?
[[ $rc -eq 1 && "$(base_of 81)" == "campaign→main fix" ]] && pass "--pending also records baselines" ||
	fail "--pending baseline (rc=$rc baseline=$(cat "$BASELINE" 2>/dev/null))"

# 24. Without sqtk-answer.jq the drain fails loudly, in both modes: exit 3 and a stderr
#     line, never the "nothing waiting" path (exit 0 silent, or --pending's exit 1).
mkdir -p "$WORK/nolib"
cp "$HOOK" "$WORK/nolib/sqtk-drain.sh"
body '{"name":"cc:triage","squawks":[{"id":81,"seq":5,"state":"confirmed","text":"campaign→main fix"}]}'
reset
out=$(jq -cn --arg c "$REPO" '{cwd: $c, prompt: "x"}' | PATH="$WORK/bin:$PATH" bash "$WORK/nolib/sqtk-drain.sh" 2>"$WORK/nolib.err")
rc=$?
[[ $rc -eq 3 && -z "$out" ]] && grep -q 'cannot load sqtk-answer.jq' "$WORK/nolib.err" &&
	pass "no module: hook mode exits 3, says so" || fail "no module, hook (rc=$rc out='$out' err=$(cat "$WORK/nolib.err"))"
out=$(cd "$REPO" && PATH="$WORK/bin:$PATH" bash "$WORK/nolib/sqtk-drain.sh" --pending 2>"$WORK/nolib.err")
rc=$?
[[ $rc -eq 3 && -z "$out" ]] && grep -q 'cannot load sqtk-answer.jq' "$WORK/nolib.err" &&
	pass "no module: --pending exits 3, says so" || fail "no module, --pending (rc=$rc out='$out' err=$(cat "$WORK/nolib.err"))"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-drain checks passed."
	exit 0
fi
echo "  $FAILS sqtk-drain check(s) FAILED."
exit 1
