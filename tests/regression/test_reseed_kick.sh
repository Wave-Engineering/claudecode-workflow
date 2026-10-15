#!/usr/bin/env bash
# test_reseed_kick.sh — #1225 regression test for scripts/reseed-kick.sh.
#
# The kicker replaced a blind `sleep 2; tmux send-keys continue`. Its whole
# value is that it KNOWS whether a send landed, so the tests drive it against a
# fake tmux that drops sends, and assert on what it logs and does — never on
# what it intended:
#   - sends dropped twice, the third acknowledged → stops, logs "acked after 3";
#   - no acknowledgement ever → stops after the schedule, logs FAILED, pages BJ
#     (stubbed) naming the pane, and leaves no nonce behind;
#   - it types exactly `/reseed revive` into the pane it was given.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
KICK="$REPO_DIR/scripts/reseed-kick.sh"

echo "test_reseed_kick"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Fake tmux: records each call; on call number $ACK_ON_CALL it removes the nonce,
# which is what the reseed-ack.sh prompt hook does when the send lands. Any
# earlier call is "dropped" — returns 0, does nothing, exactly like a keystroke
# typed before the TUI is ready.
SHIM="$WORK/shim"
mkdir -p "$SHIM"
cat >"$SHIM/tmux" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TMUX_CALLS"
n=$(wc -l <"$TMUX_CALLS")
if [[ -n "${ACK_ON_CALL:-}" && "$n" -ge "$ACK_ON_CALL" ]]; then
	rm -f "$ACK_ROOT/.claude/reseed-ack"
fi
exit 0
SH
chmod +x "$SHIM/tmux"
cat >"$SHIM/notify" <<'SH'
#!/usr/bin/env bash
printf '%s\n---\n' "$@" >>"$NOTIFIED"
SH
chmod +x "$SHIM/notify"

run_kick() { # <case-dir> <ack-on-call or empty>
	local d="$1"
	mkdir -p "$d/root"
	: >"$d/calls"
	env PATH="$SHIM:$PATH" TMUX_CALLS="$d/calls" ACK_ON_CALL="$2" ACK_ROOT="$d/root" \
		NOTIFIED="$d/notified" RESEED_KICK_BACKOFF="0 0.1 0.1 0.1" \
		RESEED_KICK_LOG="$d/kick.log" RESEED_KICK_NOTIFY="$SHIM/notify" \
		bash "$KICK" "%42" "$d/root"
}

# --- ack on the third send ------------------------------------------------------
C="$WORK/ack3"
run_kick "$C" 3
rc=$?
if [[ $rc -eq 0 ]]; then pass "acked kick exits 0"; else fail "acked kick exited $rc"; fi
if grep -q 'acked after 3$' "$C/kick.log"; then
	pass "logs 'acked after 3'"
else
	fail "log does not say 'acked after 3': $(cat "$C/kick.log")"
fi
if [[ "$(wc -l <"$C/calls")" -eq 3 ]]; then
	pass "stopped sending once acknowledged (3 sends)"
else
	fail "sent $(wc -l <"$C/calls") times, want 3"
fi
if grep -qx -- 'send-keys -t %42 /reseed revive Enter' "$C/calls"; then
	pass "types exactly '/reseed revive' into the given pane"
else
	fail "unexpected tmux call: $(head -1 "$C/calls")"
fi
if [[ ! -e "$C/notified" ]]; then pass "no page on success"; else fail "paged BJ on a success"; fi

# --- never acknowledged -----------------------------------------------------------
C="$WORK/never"
run_kick "$C" ""
rc=$?
if [[ $rc -eq 1 ]]; then pass "unacknowledged kick exits 1"; else fail "unacknowledged kick exited $rc"; fi
if grep -q 'FAILED no ack after 4 send' "$C/kick.log"; then
	pass "logs FAILED after the whole schedule (4 sends)"
else
	fail "log does not record FAILED after 4 sends: $(cat "$C/kick.log")"
fi
if grep -q '%42' "$C/notified" 2>/dev/null; then
	pass "pages BJ, naming the pane"
else
	fail "loud path not taken, or pane not named: $(cat "$C/notified" 2>/dev/null)"
fi
if [[ ! -e "$C/root/.claude/reseed-ack" ]]; then
	pass "no stale nonce left behind"
else
	fail "nonce left behind after FAILED"
fi
if ! grep -q 'sent' "$C/kick.log"; then
	pass "never logs a bare 'sent'"
else
	fail "log claims 'sent': $(cat "$C/kick.log")"
fi

# --- the nonce cannot be written -----------------------------------------------------
# "Nonce absent" is what an ack looks like, so an unwritten nonce would read as an
# instant success with nothing sent. It must be a loud FAILED instead.
C="$WORK/nononce"
mkdir -p "$C/root"
: >"$C/root/.claude" # a FILE where the .claude directory should be
: >"$C/calls"
env PATH="$SHIM:$PATH" TMUX_CALLS="$C/calls" ACK_ON_CALL="" ACK_ROOT="$C/root" \
	NOTIFIED="$C/notified" RESEED_KICK_BACKOFF="0 0.1" \
	RESEED_KICK_LOG="$C/kick.log" RESEED_KICK_NOTIFY="$SHIM/notify" \
	bash "$KICK" "%42" "$C/root"
rc=$?
if [[ $rc -eq 1 ]] && grep -q 'FAILED cannot write nonce' "$C/kick.log" && ! grep -q 'acked' "$C/kick.log"; then
	pass "unwritable nonce → FAILED, never 'acked after 0'"
else
	fail "unwritable nonce: rc=$rc log=$(cat "$C/kick.log" 2>/dev/null)"
fi
if [[ ! -s "$C/calls" ]] && grep -q '%42' "$C/notified" 2>/dev/null; then
	pass "…sends nothing and pages BJ"
else
	fail "unwritable nonce: sent=$(wc -l <"$C/calls") paged=$([[ -e "$C/notified" ]] && echo yes || echo no)"
fi

# --- usage ------------------------------------------------------------------------
RESEED_KICK_LOG="$WORK/usage.log" bash "$KICK" "" "$WORK" >/dev/null 2>&1
if [[ $? -eq 2 ]]; then pass "no pane → usage exit 2"; else fail "no pane did not exit 2"; fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS assertion(s) failed"
	exit 1
fi
echo "  all assertions passed"
