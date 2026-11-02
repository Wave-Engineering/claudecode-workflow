#!/usr/bin/env bash
# test_sqtk_asks_sync.sh — #1430 regression test for scripts/hooks/workflow/sqtk-asks-sync.sh.
#
# The script rebuilds /tmp/claude-statusline-<dev_name>.asks.json (here: $ASKS_DIR) from this
# checkout's open bj:needs squawks. Its contract: it parses the leading ask marker, drops
# answered and retired items, leaves the file alone on a failed fetch, removes it when nothing
# is open, does nothing without an identity, writes atomically, and prints nothing and exits 0
# in every case. A stub `sqtk` serves the list, so no server is needed.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SYNC="$REPO_DIR/scripts/hooks/workflow/sqtk-asks-sync.sh"

echo "test_sqtk_asks_sync"
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
ASKS_DIR="$WORK/asks"
mkdir -p "$REPO/.claude" "$ASKS_DIR"
git -C "$REPO" init -q
printf '{"dev_name":"tester"}\n' >"$REPO/.claude/agent-identity.json"
ASKS="$ASKS_DIR/claude-statusline-tester.asks.json"
MINE="$REPO/.claude/sqtk-mine.json"

# A stub sqtk: log the call, exit $FAKE_RC (default 0), else print $FAKE_BODY.
cat >"$WORK/sqtk" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SQTK_LOG"
[[ "${FAKE_RC:-0}" == 0 ]] || exit "$FAKE_RC"
cat "$FAKE_BODY"
EOF
chmod +x "$WORK/sqtk"
export SQTK_LOG="$WORK/sqtk.log" FAKE_BODY="$WORK/body.json" FAKE_RC=0
export SQTK_ASKS_SQTK="$WORK/sqtk" SQTK_ASKS_DIR="$ASKS_DIR"

mine() { printf '%s\n' "$1" >"$MINE"; }
body() { printf '%s\n' "$1" >"$FAKE_BODY"; }
calls() { [[ -f "$SQTK_LOG" ]] && wc -l <"$SQTK_LOG" | tr -d ' ' || echo 0; }
reset() { rm -f "$ASKS" "$SQTK_LOG"; }
sync_run() { bash "$SYNC" --sync "$REPO" </dev/null; }
post_run() { jq -cn --arg c "$REPO" --arg m "$1" '{cwd: $c, tool_input: {command: $m}}' | bash "$SYNC" --post-tool; }
stop_run() { jq -cn --arg c "$REPO" '{cwd: $c}' | bash "$SYNC" --stop; }
asks() { jq -c '[.asks[] | "\(.seq):\(.kind):\(.blocking)"]' "$ASKS" 2>/dev/null; }

# Every squawk below belongs to this checkout (seqs 1-9), plus one (99) that does not.
mine '[{"list":"bj:needs","seq":1,"id":11},{"list":"bj:needs","seq":2,"id":12},{"list":"bj:needs","seq":3,"id":13},
       {"list":"bj:needs","seq":4,"id":14},{"list":"bj:needs","seq":5,"id":15},{"list":"bj:needs","seq":6,"id":16},
       {"list":"bj:needs","seq":7,"id":17},{"list":"bj:needs","seq":8,"id":18},{"list":"bj:needs","seq":9,"id":19},
       {"list":"cc:triage","seq":1,"id":21}]'

# 1. Each marker, with and without ❗, gives its entry; an unmarked item is 🔔, non-blocking.
reset
body '{"name":"bj:needs","squawks":[
  {"id":11,"seq":1,"state":"open","text":"❓ [a·r] q"},
  {"id":12,"seq":2,"state":"open","text":"❓❗ [a·r] q"},
  {"id":13,"seq":3,"state":"open","text":"🔧 [a·r] do"},
  {"id":14,"seq":4,"state":"open","text":"✅❗ [a·r] ok?"},
  {"id":15,"seq":5,"state":"open","text":"⛔ [a·r] stuck"},
  {"id":16,"seq":6,"state":"open","text":"⛔❗ [a·r] stuck"},
  {"id":17,"seq":7,"state":"open","text":"🔔 [a·r] hi"},
  {"id":18,"seq":8,"state":"open","text":"[a·r] older client, no marker"},
  {"id":19,"seq":9,"state":"open","text":"[a·r] mentions ✅ and ⛔❗ later in the line"},
  {"id":99,"seq":99,"state":"open","text":"⛔ [x·y] somebody else'"'"'s"}]}'
out=$(sync_run)
rc=$?
want='["1:question:false","2:question:true","3:action:false","4:approval:true","5:blocker:true","6:blocker:true","7:unspecified:false","8:unspecified:false","9:unspecified:false"]'
[[ $rc -eq 0 && -z "$out" && "$(asks)" == "$want" ]] && pass "each marker parsed; unmarked and mid-line icons are 🔔 non-blocking; others' seqs ignored" ||
	fail "markers (rc=$rc out='$out' asks=$(asks))"
[[ "$(jq -r '.synced_at | type' "$ASKS")" == number && "$(jq -r 'all(.asks[]; .list == "bj:needs")' "$ASKS")" == true ]] &&
	pass "the file carries synced_at and the list" || fail "file shape"
[[ "$(cat "$SQTK_LOG")" == "show bj:needs --json" ]] && pass "one fetch: sqtk show bj:needs --json" ||
	fail "fetch call ($(cat "$SQTK_LOG"))"

# 2. An answered (confirmed) or retired item drops out.
body '{"name":"bj:needs","squawks":[
  {"id":11,"seq":1,"state":"confirmed","text":"❓ [a·r] q → yes"},
  {"id":12,"seq":2,"state":"retired","text":"❓❗ [a·r] q"},
  {"id":13,"seq":3,"state":"open","text":"🔧 [a·r] do"}]}'
sync_run
[[ "$(asks)" == '["3:action:false"]' ]] && pass "settled items drop out" || fail "settled items (asks=$(asks))"

# 3. A failed fetch leaves the file byte for byte, and exits 0 silent.
cp "$ASKS" "$WORK/before.json"
for rc_try in 1 7; do
	out=$(
		export FAKE_RC=$rc_try
		sync_run
	)
	rc=$?
	[[ $rc -eq 0 && -z "$out" ]] && cmp -s "$ASKS" "$WORK/before.json" && pass "failed fetch (rc $rc_try): file untouched" ||
		fail "failed fetch rc $rc_try (rc=$rc out='$out')"
done
body 'not json at all'
sync_run
cmp -s "$ASKS" "$WORK/before.json" && pass "a body that is not a list: file untouched" || fail "bad body"
body '{"error":"nope"}'
sync_run
cmp -s "$ASKS" "$WORK/before.json" && pass "an error body: file untouched" || fail "error body"

# 4. No open items removes the file.
body '{"name":"bj:needs","squawks":[{"id":13,"seq":3,"state":"recorded","text":"🔧 [a·r] do → #5"}]}'
sync_run
[[ ! -e "$ASKS" ]] && pass "no open items: file removed" || fail "file kept with nothing open"
body '{"name":"bj:needs","squawks":[{"id":13,"seq":3,"state":"open","text":"🔧 [a·r] do"}]}'
sync_run
mine '[{"list":"cc:triage","seq":1,"id":21}]'
reset
touch "$ASKS"
out=$(sync_run)
[[ ! -e "$ASKS" && "$(calls)" == 0 ]] && pass "nothing of mine on bj:needs: file removed, no fetch" ||
	fail "no bj:needs entries (calls=$(calls))"
rm -f "$MINE"
touch "$ASKS"
sync_run
[[ ! -e "$ASKS" ]] && pass "no record of mine: file removed" || fail "no mine file"

# 5. No identity does nothing: no file, no fetch.
mine '[{"list":"bj:needs","seq":3,"id":13}]'
reset
mv "$REPO/.claude/agent-identity.json" "$WORK/identity.json"
out=$(sync_run)
rc=$?
[[ $rc -eq 0 && -z "$out" && -z "$(ls -A "$ASKS_DIR")" && "$(calls)" == 0 ]] && pass "no identity: does nothing" ||
	fail "no identity (rc=$rc ls=$(ls -A "$ASKS_DIR") calls=$(calls))"
mv "$WORK/identity.json" "$REPO/.claude/agent-identity.json"

# 6. Atomic: the write leaves no temp file behind, and the file is whole JSON.
reset
sync_run
leftovers=$(find "$ASKS_DIR" -name '.claude-asks-sync.*' | wc -l | tr -d ' ')
[[ "$leftovers" == 0 ]] && jq -e . "$ASKS" >/dev/null 2>&1 && pass "atomic write: no temp left, valid JSON" ||
	fail "atomic write (leftovers=$leftovers)"
grep -q 'mktemp' "$SYNC" && grep -q 'mv -f' "$SYNC" && pass "the script writes through a temp file and mv" || fail "no temp+mv"

# 7. The PostToolUse trigger: sqtk add / sqtk set run the sync; anything else exits at once.
# shellcheck disable=SC2088  # the tilde is part of the command string under test
for cmd in 'sqtk add bj:needs "x" --kind question' 'sqtk set needs 3 --state retired' 'cd /r && sqtk add needs "y"' '~/.claude/scripts/sqtk set needs 1 --blocking'; do
	reset
	out=$(post_run "$cmd")
	[[ -z "$out" && "$(calls)" == 1 && -e "$ASKS" ]] && pass "post-tool syncs on: $cmd" || fail "post-tool on '$cmd' (calls=$(calls) out='$out')"
done
for cmd in 'ls -la' 'sqtk show needs' 'sqtk mine' 'git commit -m "sqtk adds a flag"' 'echo sqtkset' 'sqtk attach needs 3 x.png'; do
	reset
	out=$(post_run "$cmd")
	rc=$?
	[[ $rc -eq 0 && -z "$out" && "$(calls)" == 0 && ! -e "$ASKS" ]] && pass "post-tool exits at once on: $cmd" ||
		fail "post-tool on '$cmd' (rc=$rc calls=$(calls) out='$out')"
done
reset
out=$(printf 'not json' | bash "$SYNC" --post-tool)
rc=$?
[[ $rc -eq 0 && -z "$out" && "$(calls)" == 0 ]] && pass "post-tool with unreadable stdin: silent exit 0" || fail "post-tool bad stdin"

# 8. The Stop trigger: nothing when the file is absent, a sync when it is there.
reset
out=$(stop_run)
[[ -z "$out" && "$(calls)" == 0 && ! -e "$ASKS" ]] && pass "stop: no asks file, no work" || fail "stop without a file (calls=$(calls))"
printf '{"asks":[{"list":"bj:needs","seq":1,"kind":"question","blocking":false}],"synced_at":1}\n' >"$ASKS"
out=$(stop_run)
[[ -z "$out" && "$(calls)" == 1 && "$(asks)" == '["3:action:false"]' ]] && pass "stop: file present, rebuilt from the squawks" ||
	fail "stop with a file (calls=$(calls) asks=$(asks))"

# 9. An unknown mode does nothing, quietly.
reset
out=$(bash "$SYNC" --bogus </dev/null)
rc=$?
[[ $rc -eq 0 && -z "$out" && "$(calls)" == 0 ]] && pass "unknown mode: silent exit 0" || fail "unknown mode"

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-asks-sync checks passed."
	exit 0
fi
echo "  $FAILS sqtk-asks-sync check(s) FAILED."
exit 1
