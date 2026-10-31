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
#   - it types exactly `/reseed revive` into the pane it was given, through
#     pane-send.sh: clear the line, type literally, then Enter, in one call (#1366);
#   - #1244, #1400: the revive in the transcript acks (a Skill `reseed revive`, or
#     the seed named by any tool and then a Skill `engage reload`), while a read of
#     the seed alone or followed by a plain `engage`, the hook's notice and
#     pre-clear entries do not; a
#     busy session gets no stacked sends, an idle unrevived one gets one send per
#     idle spell, a session that goes live late still gets the live wait, and a
#     live session pages only if it never revives.

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
printf '%s' "${NOTIFY_BJ_REPO_ROOT-<unset>}" >"$NOTIFIED.repo_root"
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
if grep -qx -- "send-keys -t %42 C-e$(printf ' C-u%.0s' $(seq 32)) ; send-keys -t %42 -l /reseed revive ; send-keys -t %42 Enter" "$C/calls"; then
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
# notify-bj.sh posts as the checkout's agent, so the page must carry the project root (#1348).
if [[ "$(cat "$C/notified.repo_root" 2>/dev/null)" == "$C/root" ]]; then
	pass "the page carries NOTIFY_BJ_REPO_ROOT = the project root"
else
	fail "NOTIFY_BJ_REPO_ROOT was '$(cat "$C/notified.repo_root" 2>/dev/null)', want $C/root"
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

# --- #1244, #1400: the revive in the transcript is an ack --------------------------------
# No send ever lands (ACK_ON_CALL empty), so only the transcript can acknowledge.
# Timestamps are pinned far from the kick's start, so no case depends on a second
# boundary: 2099 is "after the kick started", 2000 is "before /clear".
entry() { # <timestamp> <tool name> <input json>
	jq -cn --arg t "$1" --arg n "$2" --argjson i "$3" \
		'{type: "assistant", timestamp: $t, message: {content: [{type: "tool_use", name: $n, input: $i}]}}'
}
LATER="2099-01-01T00:00:00.000Z"
BEFORE="2000-01-01T00:00:00.000Z"
SEED_CAT='{"command": "cat .claude/reseed-revive.md"}'
SEED_READ='{"file_path": "/p/.claude/reseed-revive.md"}'
ENGAGE='{"skill": "engage", "args": "reload"}'

run_kick_t() { # <case-dir> <transcript> [<ack-on-call>]   env KB overrides the backoff, LW the live wait
	local d="$1"
	mkdir -p "$d/root"
	: >"$d/calls"
	env PATH="$SHIM:$PATH" TMUX_CALLS="$d/calls" ACK_ON_CALL="${3:-}" ACK_ROOT="$d/root" \
		NOTIFIED="$d/notified" RESEED_KICK_BACKOFF="${KB:-0 0.1 0.1 0.1}" \
		RESEED_KICK_LIVE_WAIT="${LW:-2}" RESEED_KICK_POLL=1 \
		RESEED_KICK_LOG="$d/kick.log" RESEED_KICK_NOTIFY="$SHIM/notify" \
		bash "$KICK" "%42" "$d/root" "$2"
}

# A Bash `cat` of the seed, then /engage: the revive done by hand, by any tool.
C="$WORK/seedread"
mkdir -p "$C"
{
	entry "$LATER" Bash "$SEED_CAT"
	entry "$LATER" Skill "$ENGAGE"
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked (revive seen) after 0' "$C/kick.log"; then
	pass "seed read then /engage in the transcript acks, with no prompt submitted"
else
	fail "seed read + engage: rc=$rc log=$(cat "$C/kick.log")"
fi
if [[ ! -s "$C/calls" && ! -e "$C/notified" && ! -e "$C/root/.claude/reseed-ack" ]]; then
	pass "…sends nothing, pages nobody, removes the nonce"
else
	fail "seed read + engage: sent=$(wc -l <"$C/calls") paged=$([[ -e "$C/notified" ]] && echo yes || echo no)"
fi

# #1400, the incident: a peer message woke the turn right after /clear, which read
# the seed, answered the peer and ended. That is not a revive: no ack from the
# transcript, so the idle session gets its one send, and the nonce acks it.
C="$WORK/readonly"
mkdir -p "$C"
{
	entry "$LATER" Read "$SEED_READ"
	jq -cn --arg t "$LATER" '{type: "assistant", timestamp: $t,
		message: {stop_reason: "end_turn", content: [{type: "text", text: "answered the peer"}]}}'
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl" 1
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked after 1$' "$C/kick.log" && [[ "$(wc -l <"$C/calls")" -eq 1 ]]; then
	pass "a seed read alone is not a revive: the idle session gets one send, which acks"
else
	fail "read only: rc=$rc sends=$(wc -l <"$C/calls") log=$(cat "$C/kick.log")"
fi

# A plain /engage after the seed read is a fresh session onboarding, not the
# revive (/reseed revive runs /engage reload): no ack, one send once idle.
C="$WORK/plainengage"
mkdir -p "$C"
{
	entry "$LATER" Read "$SEED_READ"
	entry "$LATER" Skill '{"skill": "engage"}'
	jq -cn --arg t "$LATER" '{type: "assistant", timestamp: $t,
		message: {stop_reason: "end_turn", content: [{type: "text", text: "answered the peer"}]}}'
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl" 1
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked after 1$' "$C/kick.log" && [[ "$(wc -l <"$C/calls")" -eq 1 ]]; then
	pass "a plain /engage after the seed read is not a revive: one send, which acks"
else
	fail "plain engage: rc=$rc sends=$(wc -l <"$C/calls") log=$(cat "$C/kick.log")"
fi

# Order matters: /engage before the seed is named is not the revive.
C="$WORK/engagefirst"
mkdir -p "$C"
{
	entry "$LATER" Skill "$ENGAGE"
	entry "$LATER" Read "$SEED_READ"
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 ]] && ! grep -q 'acked' "$C/kick.log"; then
	pass "/engage before the seed read does not ack"
else
	fail "engage first: rc=$rc log=$(cat "$C/kick.log")"
fi

# A Skill-tool revive (#1244's first report).
C="$WORK/skill"
mkdir -p "$C"
entry "$LATER" Skill '{"skill": "reseed", "args": "revive"}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked (revive seen)' "$C/kick.log"; then
	pass "Skill(reseed, revive) acks"
else
	fail "Skill revive: rc=$rc log=$(cat "$C/kick.log")"
fi

# The SessionStart notice names the seed too; it is not the agent reading it.
C="$WORK/notice"
mkdir -p "$C"
jq -cn --arg t "$LATER" '{type: "attachment", timestamp: $t,
	attachment: {type: "hook_success", content: "[RESEED AUTO-REVIVE] … /p/.claude/reseed-revive.md"}}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 ]] && grep -q 'FAILED no ack after 4 send' "$C/kick.log"; then
	pass "the hook's own notice naming the seed does not ack"
else
	fail "notice: rc=$rc log=$(cat "$C/kick.log")"
fi

# A pre-clear tool call on the seed (the /reseed that wrote it) does not ack.
C="$WORK/preclear"
mkdir -p "$C"
entry "$BEFORE" Write '{"file_path": "/p/.claude/reseed-revive.md", "content": "x"}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 ]] && grep -q 'FAILED no ack after 4 send' "$C/kick.log"; then
	pass "a tool call from before the kick started does not ack"
else
	fail "pre-clear: rc=$rc log=$(cat "$C/kick.log")"
fi

# A live session (a turn a peer message started) that has not read the seed yet:
# no sends stack up behind it, and the revive during the wait acks. The revive is
# appended once the kicker logs that it entered the live wait, never on a timer: a
# timed append misses a short wait on a loaded box (#1410). The 30 s wait only
# bounds a broken run; a passing one acks at the first poll after the append.
C="$WORK/livelater"
mkdir -p "$C"
entry "$LATER" Bash '{"command": "echo answering a peer"}' >"$C/t.jsonl"
(
	for _ in $(seq 300); do
		grep -q 'session live after 0 send(s); waiting up to 30s' "$C/kick.log" 2>/dev/null && break
		sleep 0.1
	done
	{
		entry "$LATER" Read "$SEED_READ"
		entry "$LATER" Skill "$ENGAGE"
	} >>"$C/t.jsonl"
) &
LW=30 run_kick_t "$C" "$C/t.jsonl"
rc=$?
wait
if grep -q 'session live after 0 send(s); waiting up to 30s for the revive' "$C/kick.log"; then
	pass "the kicker logs entering the live wait"
else
	fail "no live-wait line: log=$(cat "$C/kick.log")"
fi
if [[ $rc -eq 0 ]] && grep -q 'acked (revive seen) after 0 (session was live' "$C/kick.log"; then
	pass "live session: waits, then acks on the revive"
else
	fail "live then read: rc=$rc log=$(cat "$C/kick.log")"
fi
if [[ ! -s "$C/calls" ]]; then
	pass "…types nothing into a live session"
else
	fail "typed $(wc -l <"$C/calls") send(s) into a live session"
fi

# A live session that never reads the seed is a real failure: page after the wait.
C="$WORK/livenever"
mkdir -p "$C"
entry "$LATER" Bash '{"command": "echo answering a peer"}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 ]] && grep -q 'FAILED session live but no revive seen' "$C/kick.log" &&
	grep -q '%42' "$C/notified" 2>/dev/null && [[ ! -e "$C/root/.claude/reseed-ack" ]]; then
	pass "live session that never reads the seed → FAILED, pages, no nonce left"
else
	fail "live never: rc=$rc log=$(cat "$C/kick.log")"
fi

# The peer turn ended (end_turn) and the agent never revived: the session is idle,
# so ONE send goes in, and it lands (ack on call 1). Not a silent 10-minute wait.
C="$WORK/idleunrevived"
mkdir -p "$C"
jq -cn --arg t "$LATER" '{type: "assistant", timestamp: $t,
	message: {stop_reason: "end_turn", content: [{type: "text", text: "answered the peer"}]}}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl" 1
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked after 1$' "$C/kick.log" && [[ "$(wc -l <"$C/calls")" -eq 1 ]]; then
	pass "idle session that has not revived gets one send, which acks"
else
	fail "idle unrevived: rc=$rc sends=$(wc -l <"$C/calls") log=$(cat "$C/kick.log")"
fi

# The session is idle and the one send is dropped: still one send per idle spell, not
# a send every poll.
C="$WORK/idledropped"
mkdir -p "$C"
cp "$WORK/idleunrevived/t.jsonl" "$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 && "$(wc -l <"$C/calls")" -eq 1 ]] && grep -q 'FAILED session live' "$C/kick.log"; then
	pass "…one send per idle spell, then the live-session FAILED"
else
	fail "idle dropped: rc=$rc sends=$(wc -l <"$C/calls") log=$(cat "$C/kick.log")"
fi

# A turn that has only sent its first request (api-request-shape, no reply yet) is
# busy: no sends stack behind it.
C="$WORK/shapeonly"
mkdir -p "$C"
jq -cn --arg t "$LATER" '{type: "api-request-shape", timestamp: $t, shape: "x"}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 && ! -s "$C/calls" ]] && grep -q 'FAILED session live' "$C/kick.log"; then
	pass "a request in flight (shape entry only) is busy: zero sends"
else
	fail "shape only: rc=$rc sends=$(wc -l <"$C/calls") log=$(cat "$C/kick.log")"
fi

# A second turn (a notification right after a turn ended) is busy from its
# request, not only from its first reply: end_turn then api-request → zero sends.
C="$WORK/nextturn"
mkdir -p "$C"
{
	jq -cn --arg t "$LATER" '{type: "assistant", timestamp: $t,
		message: {stop_reason: "end_turn", content: [{type: "text", text: "done"}]}}'
	jq -cn --arg t "$LATER" '{type: "api-request", timestamp: $t, querySource: "repl_main_thread"}'
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 1 && ! -s "$C/calls" ]] && grep -q 'FAILED session live' "$C/kick.log"; then
	pass "a request in flight after end_turn is busy: zero sends"
else
	fail "next turn: rc=$rc sends=$(wc -l <"$C/calls") log=$(cat "$C/kick.log")"
fi

# A side query (another querySource) after end_turn is not a turn: still idle.
C="$WORK/sidequery"
mkdir -p "$C"
{
	head -1 "$WORK/nextturn/t.jsonl"
	jq -cn --arg t "$LATER" '{type: "api-request", timestamp: $t, querySource: "session_title"}'
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl" 1
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked after 1$' "$C/kick.log"; then
	pass "a side-query api-request does not make an idle session busy"
else
	fail "side query: rc=$rc log=$(cat "$C/kick.log")"
fi

# A turn ended by an API error (synthetic stop_sequence) is idle, not busy forever.
C="$WORK/apierror"
mkdir -p "$C"
jq -cn --arg t "$LATER" '{type: "assistant", timestamp: $t, isApiErrorMessage: true,
	message: {stop_reason: "stop_sequence", content: [{type: "text", text: "API Error: 529"}]}}' >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl" 1
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked after 1$' "$C/kick.log"; then
	pass "a turn ended by an API error is idle: one send, which acks"
else
	fail "api error: rc=$rc log=$(cat "$C/kick.log")"
fi

# A refused send (tmux exit non-zero) does not use up the idle spell: it retries.
C="$WORK/tmuxfail"
mkdir -p "$C/root" "$C/shim"
cat >"$C/shim/tmux" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TMUX_CALLS"
exit 1
SH
chmod +x "$C/shim/tmux"
: >"$C/calls"
cp "$WORK/apierror/t.jsonl" "$C/t.jsonl"
env PATH="$C/shim:$SHIM:$PATH" TMUX_CALLS="$C/calls" ACK_ON_CALL="" ACK_ROOT="$C/root" \
	NOTIFIED="$C/notified" RESEED_KICK_BACKOFF="0 0.1 0.1 0.1" \
	RESEED_KICK_LIVE_WAIT=1 RESEED_KICK_POLL=1 \
	RESEED_KICK_LOG="$C/kick.log" RESEED_KICK_NOTIFY="$SHIM/notify" \
	bash "$KICK" "%42" "$C/root" "$C/t.jsonl"
if [[ "$(wc -l <"$C/calls")" -gt 1 ]]; then
	pass "a refused idle send is retried, not counted as served"
else
	fail "refused send: $(wc -l <"$C/calls") attempt(s), want > 1"
fi

# The session goes live DURING the final wait (after all 4 sends): it must enter
# the live wait, not page "no ack after 4 send(s)". The entry is written by the
# 4th send itself (a fake tmux that appends it on its 4th call), and a send only
# follows a check, so the entry lands after the 4th check by construction, in the
# final wait. No timer: a timed write missed that window on a loaded box (#1410).
C="$WORK/latelive"
mkdir -p "$C/root" "$C/shim"
cat >"$C/shim/tmux" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TMUX_CALLS"
if [[ "$(wc -l <"$TMUX_CALLS")" -eq 4 ]]; then
	jq -cn --arg t "$LIVE_TS" '{type: "api-request-shape", timestamp: $t, shape: "x"}' >>"$LIVE_T"
fi
exit 0
SH
chmod +x "$C/shim/tmux"
: >"$C/calls"
: >"$C/t.jsonl"
env PATH="$C/shim:$SHIM:$PATH" TMUX_CALLS="$C/calls" LIVE_T="$C/t.jsonl" LIVE_TS="$LATER" \
	ACK_ON_CALL="" ACK_ROOT="$C/root" NOTIFIED="$C/notified" RESEED_KICK_BACKOFF="0 0.1 0.1 0.1" \
	RESEED_KICK_LIVE_WAIT=2 RESEED_KICK_POLL=1 \
	RESEED_KICK_LOG="$C/kick.log" RESEED_KICK_NOTIFY="$SHIM/notify" \
	bash "$KICK" "%42" "$C/root" "$C/t.jsonl"
rc=$?
# Exactly 4 sends: the entry made every later check read the session as busy.
if [[ $rc -eq 1 && "$(wc -l <"$C/calls")" -eq 4 ]] && grep -q 'FAILED session live' "$C/kick.log" &&
	! grep -q 'FAILED no ack' "$C/kick.log"; then
	pass "a session that goes live during the final wait gets the live wait, not 'no ack'"
else
	fail "late live: rc=$rc log=$(cat "$C/kick.log")"
fi

# A fractional poll would be an arithmetic syntax error in the wait loop; it must
# fall back to the default (5 s) and still reach a clean FAILED.
C="$WORK/fracpoll"
mkdir -p "$C/root"
: >"$C/calls"
cp "$WORK/shapeonly/t.jsonl" "$C/t.jsonl"
env PATH="$SHIM:$PATH" TMUX_CALLS="$C/calls" ACK_ON_CALL="" ACK_ROOT="$C/root" \
	NOTIFIED="$C/notified" RESEED_KICK_BACKOFF="0 0.1" \
	RESEED_KICK_LIVE_WAIT=1 RESEED_KICK_POLL=0.5 \
	RESEED_KICK_LOG="$C/kick.log" RESEED_KICK_NOTIFY="$SHIM/notify" \
	bash "$KICK" "%42" "$C/root" "$C/t.jsonl" 2>"$C/stderr"
rc=$?
if [[ $rc -eq 1 && ! -s "$C/stderr" ]] && grep -q 'FAILED session live but no revive seen after 5s' "$C/kick.log"; then
	pass "RESEED_KICK_POLL=0.5 falls back to 5 s, no arithmetic error"
else
	fail "fractional poll: rc=$rc stderr=$(cat "$C/stderr") log=$(cat "$C/kick.log")"
fi

# A half-written last line must not hide a hit before it.
C="$WORK/partial"
mkdir -p "$C"
{
	entry "$LATER" Bash "$SEED_CAT"
	entry "$LATER" Skill "$ENGAGE"
	printf '{"type": "assistant", "timest'
} >"$C/t.jsonl"
run_kick_t "$C" "$C/t.jsonl"
rc=$?
if [[ $rc -eq 0 ]] && grep -q 'acked (revive seen)' "$C/kick.log"; then
	pass "a truncated last transcript line does not mask the revive"
else
	fail "partial: log=$(cat "$C/kick.log")"
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
