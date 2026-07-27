#!/usr/bin/env bash
# test_doorbell_oneshot.sh — #1055: the one-shot doorbell wrapper's contract.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
#
# scripts/doorbell-oneshot.sh exists because the arming instruction printed by the watcher's own
# README and --help (`Monitor({command: "discord-watcher doorbell", persistent: true})`) does not
# work in clients that have no `Monitor` primitive: their background-task mechanism notifies only
# on process EXIT, and `doorbell` is a loop that never exits. The wrapper inverts that — one batch
# of messages, one exit, one notification.
#
# Every failure mode this guards is SILENT: the watcher polls normally and delivers nothing, so a
# regression reads as "no messages" rather than as breakage. Hence asserting on the script text
# where a live Discord round-trip would be needed — that is not hermetic and cannot run in CI.
# Everything that CAN be exercised with a stub watcher is exercised behaviorally.
#
# Guards asserted:
#   1. bash -n on the wrapper (syntax must hold) + the executable bit (it is invoked directly).
#   2. The child is killed by PID. Bun ignores SIGPIPE and swallows the write error, so a
#      `| head -1` shape leaves an orphaned poller alive — verified still polling 20s after the
#      reader exited. Re-arming that way accumulates one leaked poller per message.
#   3. No `| head -` pipeline in the wrapper — the specific shape trap #2 describes.
#   4. A cleanup trap removes the working dir, so re-arming does not litter $TMPDIR.
#   5. The identity precondition is checked and WARNED about. Identity resolves from
#      CLAUDE_PROJECT_DIR ?? cwd; unresolved → the delivery gate fails closed → total silence.
#   6. TIMEOUT is honored with a distinct non-zero exit, and a non-numeric TIMEOUT is REJECTED
#      rather than silently selecting the unbounded branch ([[ -gt ]] is arithmetic, so
#      TIMEOUT=30s makes the test false and blocks forever — the opposite of what was asked).
#   7. A watcher that exits without emitting a line yields exit 4, never a blank exit 0. The whole
#      design rests on "exited ⇒ a message arrived"; a false exit 0 makes the agent re-arm
#      instantly and spin.
#   8. The fifo is opened ONCE on a fd and drained, so a multi-message poll is not truncated to
#      its first line. Dropped lines are unrecoverable — the re-armed watcher seeds its cursor
#      past them and marks them delivered. Drain width is configurable (DRAIN_SECONDS) because
#      the default cannot span a cross-channel burst; that residual gap is documented, not fixed.
#  10. A pre-v1.6.0 watcher is caught by an up-front capability probe. It does NOT error on an
#      unknown subcommand — `doorbell` falls through to the MCP server and never exits — so the
#      un-probed shape is an unbounded silent hang, not an exit-4. The probe itself must be
#      `timeout`-bounded because `--help` hangs on such a binary too.
#  11. Only a line with the `[doorbell] ` prefix counts as a message. The watcher's other mode
#      writes JSON-RPC frames to stdout, and reporting one as delivered is a false doorbell.
#   9. skills/disc/SKILL.md routes `doorbell`, warns that Monitor may be unavailable, and invokes
#      the wrapper by BARE NAME. A relative `scripts/...` path only resolves inside the
#      cc-workflow source tree and breaks the skill everywhere else — the #569 regression class
#      (see test_skill_uses_installed_binaries.sh); it also contradicts the wrapper's own
#      requirement to run from the target project's root.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WRAPPER="$REPO_DIR/scripts/doorbell-oneshot.sh"
SKILL="$REPO_DIR/skills/disc/SKILL.md"

FAILS=0
# `pass` closes the assertion group above it, so it must not print when that group already
# failed — several groups make multiple assertions before their single verdict line, and an
# unconditional pass would print [FAIL] and [PASS] for the SAME check. Comparing against the
# failure count at the previous verdict keeps the two mutually exclusive with no bookkeeping at
# the ~20 call sites.
LAST_FAILS=0
pass() {
	((FAILS == LAST_FAILS)) && echo "  [PASS] $1"
	LAST_FAILS=$FAILS
}
fail() {
	echo "  [FAIL] $1" >&2
	FAILS=$((FAILS + 1))
}

# A private TMPDIR for every stub run. The litter check must scan only what THIS test created:
# globbing shared /tmp would fail whenever another agent legitimately holds a live doorbell, which
# is the wrapper's intended production use on a box that routinely runs several agents.
SANDBOX="$(mktemp -d)"
trap 'rm -rf "$SANDBOX"' EXIT

# --- 1. syntax + executable ---------------------------------------------------
if [[ ! -f "$WRAPPER" ]]; then
	echo "  [FAIL] missing $WRAPPER" >&2
	exit 1
fi
bash -n "$WRAPPER" || fail "bash -n failed on doorbell-oneshot.sh"
pass "doorbell-oneshot.sh syntax (bash -n)"
[[ -x "$WRAPPER" ]] || fail "doorbell-oneshot.sh is not executable (it is invoked directly)"
pass "doorbell-oneshot.sh is executable"

# --- 2/3. the child is killed by PID, never left to SIGPIPE -------------------
# Strip comments before asserting on CODE: the wrapper's own header explains the `| head -1`
# trap in prose, and matching that prose would pass (or fail) on documentation rather than
# behavior. Every grep below therefore reads $WRAPPER_CODE, not $WRAPPER.
WRAPPER_CODE="$(grep -vE '^[[:space:]]*#' "$WRAPPER")"

grep -Eq "kill[[:space:]]+\"\\\$CHILD\"" <<<"$WRAPPER_CODE" ||
	fail "wrapper must kill its child by PID — Bun ignores SIGPIPE, so a closed pipe leaks a poller"
pass "child poller is killed by PID (not left to SIGPIPE)"

grep -Eq '\|[[:space:]]*head[[:space:]]+-' <<<"$WRAPPER_CODE" &&
	fail "wrapper pipes to 'head -' — that shape leaks an orphaned poller (Bun ignores SIGPIPE)"
pass "no '| head -' pipeline (the leak shape) in the wrapper"

# --- 4. temp state is cleaned up on every exit path ---------------------------
grep -Eq 'trap[[:space:]]+cleanup[[:space:]]+EXIT' <<<"$WRAPPER_CODE" ||
	fail "wrapper must trap cleanup on EXIT so the fifo/workdir are removed"
grep -Eq "rm[[:space:]]+-rf[[:space:]]+\"\\\$WORKDIR\"" <<<"$WRAPPER_CODE" ||
	fail "cleanup must rm the working directory (fifo + stderr capture)"
pass "workdir removed via cleanup trap (re-arming leaves no litter)"

# Signal handlers must terminate. A bare `trap cleanup TERM` runs the handler, returns, and lets
# the interrupted read fall through to the success path — cancellation would look like delivery.
grep -Eq "trap[[:space:]]+'exit[[:space:]]+[0-9]+'[[:space:]]+INT" <<<"$WRAPPER_CODE" ||
	fail "INT handler must exit, or a cancelled task falls through to the success path"
grep -Eq "trap[[:space:]]+'exit[[:space:]]+[0-9]+'[[:space:]]+TERM" <<<"$WRAPPER_CODE" ||
	fail "TERM handler must exit, or a cancelled task falls through to the success path"
pass "INT/TERM handlers exit (cancellation is not mistaken for delivery)"

# --- 5. the fail-closed identity precondition is surfaced --------------------
grep -q 'agent-identity.json' <<<"$WRAPPER_CODE" ||
	fail "wrapper must check for .claude/agent-identity.json — unresolved identity fails CLOSED (silent)"
grep -q 'CLAUDE_PROJECT_DIR' <<<"$WRAPPER_CODE" ||
	fail "wrapper must honor CLAUDE_PROJECT_DIR (identity root, immune to cwd drift)"
grep -q 'WARNING' <<<"$WRAPPER_CODE" ||
	fail "the deaf case must announce itself — silent hang is indistinguishable from 'no messages'"
pass "identity precondition checked + warned (deaf case is not silent)"

# The watcher's stderr must be captured, not discarded: it carries the identity state_change line
# the skill tells operators to check, and the dead-watcher diagnosis.
# shellcheck disable=SC2016  # matching the literal text `2>"$ERRLOG"` in the wrapper — no expansion
grep -Eq '2>"\$ERRLOG"' <<<"$WRAPPER_CODE" ||
	fail "watcher stderr must be captured (identity confirmation + dead-watcher diagnosis)"
# Scope this to the line that STARTS THE POLLER (the one redirecting into the fifo). The wrapper
# legitimately discards stderr elsewhere — on kill/wait, and on the capability probe, whose stderr
# is noise by design — so a bare `WATCHER + 2>/dev/null` match would flag correct code.
#
# NOTE the first grep must NOT be -q: -q writes nothing, so piping it into a second grep feeds an
# always-empty stream and the fail becomes unreachable. That vacuous form shipped here once — the
# one assertion class mutation testing cannot catch, since deleting it changes nothing.
# shellcheck disable=SC2016  # matching the literal text `>"$FIFO"` in the wrapper — no expansion
if grep -E '>"\$FIFO"' <<<"$WRAPPER_CODE" | grep -qE '2>[[:space:]]*/dev/null'; then
	fail "the doorbell poller's stderr must not be discarded (it carries identity + diagnosis)"
fi
pass "watcher stderr is captured, not discarded"

# --- 6. TIMEOUT: distinct exit code, and non-numeric input rejected -----------
# shellcheck disable=SC2016  # matching the literal text `read -r -t "$TIMEOUT"` — no expansion
grep -Eq 'read -r -t "\$TIMEOUT"' <<<"$WRAPPER_CODE" || fail "TIMEOUT must bound the read"
grep -Eq 'exit 3' <<<"$WRAPPER_CODE" || fail "timeout must exit with a distinct non-zero code (3)"
grep -Eq '\^\[0-9\]\+\$' <<<"$WRAPPER_CODE" ||
	fail "TIMEOUT must be validated as an integer — [[ -gt ]] is arithmetic, so 'TIMEOUT=30s' would silently block forever"
pass "TIMEOUT bounds the wait, with a distinct exit code and integer validation"

# bash 3.2 (stock macOS) breaks BOTH mechanisms silently: fractional `read -t` is rejected, so
# the drain no-ops and truncates multi-message polls; and a timed-out read returns 1 instead of
# >128, so every timeout is misreported as a dead watcher. Two silent wrong answers — refuse.
grep -Eq 'BASH_VERSINFO\[0\][[:space:]]*<[[:space:]]*4' <<<"$WRAPPER_CODE" ||
	fail "wrapper must refuse bash < 4 — fractional read -t and the >128 timeout status are 4.0+"
pass "bash >= 4 enforced (3.2 would break the drain and the timeout, both silently)"

# DRAIN_SECONDS feeds `read -t` directly; a malformed value returns non-zero, which is
# indistinguishable from "nothing left to drain" — a silently skipped drain.
grep -q 'DRAIN_SECONDS' <<<"$WRAPPER_CODE" ||
	fail "the drain window must be configurable — the default cannot span cross-channel bursts"
grep -Eq '\^\[0-9\]\+\(\\\.\[0-9\]\+\)\?\$' <<<"$WRAPPER_CODE" ||
	fail "DRAIN_SECONDS must be validated as a number, or a typo silently skips the drain"
pass "DRAIN_SECONDS is configurable and validated"

# Behavioral: a stub watcher that emits nothing and stays alive → exit 3.
# `exec sleep` so the PID the wrapper kills IS the sleep; a plain `sleep` would be orphaned for
# ten minutes after every validate.sh run.
QUIET_DIR="$SANDBOX/quiet"
mkdir -p "$QUIET_DIR/.claude"
echo '{"dev_name":"stub","dev_team":"test"}' >"$QUIET_DIR/.claude/agent-identity.json"
cat >"$QUIET_DIR/discord-watcher" <<'STUB'
#!/usr/bin/env bash
# Emits nothing, exits only when killed — stands in for a quiet poll loop.
# Answers the capability probe so it reads as a v1.6.0+ binary.
if [[ "${2:-}" == "--help" ]]; then
	echo "usage: discord-watcher doorbell"
	exit 0
fi
exec sleep 600
STUB
chmod +x "$QUIET_DIR/discord-watcher"
(cd "$QUIET_DIR" && TMPDIR="$QUIET_DIR" WATCHER="$QUIET_DIR/discord-watcher" TIMEOUT=2 "$WRAPPER" >/dev/null 2>&1)
rc=$?
[[ "$rc" -eq 3 ]] || fail "expected exit 3 on TIMEOUT with no message, got $rc"
pass "quiet watcher + TIMEOUT → exit 3 (behavioral)"

# The stub run must not leave its fifo/workdir behind — scanning only ITS TMPDIR.
if compgen -G "$QUIET_DIR/doorbell.*" >/dev/null; then
	fail "a doorbell workdir survived the timeout path"
fi
pass "no workdir survives the timeout path (behavioral)"

# Behavioral: non-numeric TIMEOUT is rejected up front (exit 2), not silently unbounded.
(cd "$QUIET_DIR" && TMPDIR="$QUIET_DIR" WATCHER="$QUIET_DIR/discord-watcher" TIMEOUT=30s timeout 10 "$WRAPPER" >/dev/null 2>&1)
rc=$?
[[ "$rc" -eq 2 ]] || fail "expected exit 2 on non-numeric TIMEOUT, got $rc (124 = it blocked, the bug)"
pass "non-numeric TIMEOUT → exit 2, never an unbounded wait (behavioral)"

# --- 7. a watcher that dies without emitting → exit 4, never a blank exit 0 ---
DEAD_DIR="$SANDBOX/dead"
mkdir -p "$DEAD_DIR/.claude"
echo '{"dev_name":"stub","dev_team":"test"}' >"$DEAD_DIR/.claude/agent-identity.json"
cat >"$DEAD_DIR/discord-watcher" <<'STUB'
#!/usr/bin/env bash
# A v1.6.0+ binary (answers the probe) that then dies without emitting — bad token,
# baseline-init failure, crash. NOT the old-version case: an old binary hangs instead,
# which is why the wrapper probes capability separately (see guard 10).
if [[ "${2:-}" == "--help" ]]; then
	echo "usage: discord-watcher doorbell"
	exit 0
fi
echo "doorbell: Fatal: baseline init failed (401 Unauthorized)" >&2
exit 1
STUB
chmod +x "$DEAD_DIR/discord-watcher"
out="$(cd "$DEAD_DIR" && TMPDIR="$DEAD_DIR" WATCHER="$DEAD_DIR/discord-watcher" timeout 10 "$WRAPPER" 2>/dev/null)"
rc=$?
[[ "$rc" -eq 4 ]] || fail "dead watcher must exit 4, got $rc (0 = the false-doorbell hot-loop bug)"
[[ -z "$out" ]] || fail "dead watcher must emit no stdout line, got: $out"
pass "watcher exits without a line → exit 4, empty stdout (behavioral)"

# And its stderr must be surfaced — that is the only diagnosis the caller gets.
err="$(cd "$DEAD_DIR" && TMPDIR="$DEAD_DIR" WATCHER="$DEAD_DIR/discord-watcher" timeout 10 "$WRAPPER" 2>&1 >/dev/null)"
grep -q '401 Unauthorized' <<<"$err" ||
	fail "the dead watcher's own stderr must be replayed to the caller"
pass "dead watcher's stderr is replayed (diagnosable, not silent)"

# --- 10. a pre-v1.6.0 watcher is caught by the probe, not by hanging -----------
# The real old binary has no unknown-subcommand handler: `doorbell` falls through to the
# MCP server, which never exits. So `doorbell --help` hangs too, and the wrapper's probe
# must bound it. Without the probe this case is an unbounded silent wait at TIMEOUT=0 —
# the exact deafness the feature exists to prevent. exit 124 here would mean the wrapper
# hung and `timeout` killed it: the bug.
OLD_DIR="$SANDBOX/old"
mkdir -p "$OLD_DIR/.claude"
echo '{"dev_name":"stub","dev_team":"test"}' >"$OLD_DIR/.claude/agent-identity.json"
cat >"$OLD_DIR/discord-watcher" <<'STUB'
#!/usr/bin/env bash
# Pre-v1.6.0 shape: every argv falls through to the MCP server and never exits —
# including `doorbell --help`.
exec sleep 600
STUB
chmod +x "$OLD_DIR/discord-watcher"
(cd "$OLD_DIR" && TMPDIR="$OLD_DIR" WATCHER="$OLD_DIR/discord-watcher" timeout 20 "$WRAPPER" >/dev/null 2>&1)
rc=$?
[[ "$rc" -eq 2 ]] || fail "pre-v1.6.0 watcher must fail the probe with exit 2, got $rc (124 = it hung, the bug)"
pass "pre-v1.6.0 watcher → exit 2 from the capability probe, never a hang (behavioral)"

# shellcheck disable=SC2016  # matching the literal text `timeout 5 "$WATCHER" …` — no expansion
grep -Eq 'timeout 5 "\$WATCHER" doorbell --help' <<<"$WRAPPER_CODE" ||
	fail "the capability probe must bound --help with timeout — it hangs on an old binary too"
pass "capability probe bounds --help with timeout"

# --- 11. a non-doorbell stdout line is not reported as a message --------------
# The watcher's other mode writes JSON-RPC frames to stdout. Printing one of those as a
# doorbell and exiting 0 would be a false doorbell.
JUNK_DIR="$SANDBOX/junk"
mkdir -p "$JUNK_DIR/.claude"
echo '{"dev_name":"stub","dev_team":"test"}' >"$JUNK_DIR/.claude/agent-identity.json"
cat >"$JUNK_DIR/discord-watcher" <<'STUB'
#!/usr/bin/env bash
if [[ "${2:-}" == "--help" ]]; then
	echo "usage: discord-watcher doorbell"
	exit 0
fi
echo '{"jsonrpc":"2.0","method":"notifications/claude/channel","params":{}}'
exec sleep 600
STUB
chmod +x "$JUNK_DIR/discord-watcher"
out="$(cd "$JUNK_DIR" && TMPDIR="$JUNK_DIR" WATCHER="$JUNK_DIR/discord-watcher" timeout 20 "$WRAPPER" 2>/dev/null)"
rc=$?
[[ "$rc" -eq 4 ]] || fail "a non-doorbell stdout line must not be reported as a message (exit 4), got $rc"
[[ -z "$out" ]] || fail "a non-doorbell line must not be printed to stdout, got: $out"
pass "non-doorbell stdout → exit 4, nothing printed (behavioral)"

# --- 8. a multi-message poll is drained, not truncated to one line ------------
# shellcheck disable=SC2016  # matching the literal text `exec 3<"$FIFO"` — no expansion
grep -Eq 'exec 3<"\$FIFO"' <<<"$WRAPPER_CODE" ||
	fail "the fifo must be opened once on a fd — reopening races the writer and can lose buffered lines"
pass "fifo opened once on a fd (drain reads the same stream)"

BURST_DIR="$SANDBOX/burst"
mkdir -p "$BURST_DIR/.claude"
echo '{"dev_name":"stub","dev_team":"test"}' >"$BURST_DIR/.claude/agent-identity.json"
cat >"$BURST_DIR/discord-watcher" <<'STUB'
#!/usr/bin/env bash
# Three deliverable messages in one poll, then keep polling like the real thing.
if [[ "${2:-}" == "--help" ]]; then
	echo "usage: discord-watcher doorbell"
	exit 0
fi
echo "[doorbell] #a channel_id=1 msg_id=1 from X: first"
echo "[doorbell] #a channel_id=1 msg_id=2 from X: second"
echo "[doorbell] #a channel_id=1 msg_id=3 from X: third"
exec sleep 600
STUB
chmod +x "$BURST_DIR/discord-watcher"
out="$(cd "$BURST_DIR" && TMPDIR="$BURST_DIR" WATCHER="$BURST_DIR/discord-watcher" timeout 20 "$WRAPPER" 2>/dev/null)"
rc=$?
[[ "$rc" -eq 0 ]] || fail "a delivered burst must exit 0, got $rc"
lines="$(grep -c '^\[doorbell\]' <<<"$out")"
[[ "$lines" -eq 3 ]] || fail "expected all 3 buffered doorbell lines, got $lines — the rest are unrecoverable"
pass "multi-message poll drained: all 3 lines emitted, exit 0 (behavioral)"

# --- 9. the skill routes doorbell, flags the Monitor trap, uses a bare name ---
if [[ ! -f "$SKILL" ]]; then
	echo "  [FAIL] missing $SKILL" >&2
	exit 1
fi
grep -q 'doorbell' "$SKILL" || fail "skills/disc/SKILL.md must route the doorbell subcommand"
grep -q 'Monitor' "$SKILL" ||
	fail "SKILL.md must warn that Monitor (the README's arming instruction) may be unavailable"
grep -q 'doorbell-oneshot.sh' "$SKILL" || fail "SKILL.md must point at the one-shot wrapper"
pass "skills/disc/SKILL.md routes doorbell + flags the Monitor trap"

# #569 class: a relative scripts/ path only resolves in the cc-workflow source tree. ./install
# symlinks scripts/* onto PATH, so the invocation must be the bare name.
#
# Anchor on a path BOUNDARY (line start, whitespace, or backtick). Matching `scripts/…` anywhere
# would also flag the legitimate absolute Cellar path `~/.claude/scripts/doorbell-oneshot.sh`,
# failing the skill for documenting where the file lives — a false positive that would train the
# next author to delete the guard rather than the defect.
grep -Eq '(^|[[:space:]`])(\./)?scripts/doorbell-oneshot\.sh' "$SKILL" &&
	fail "SKILL.md must invoke doorbell-oneshot.sh by bare name, not a relative scripts/ path (#569 class)"
pass "SKILL.md invokes the wrapper by bare name (works outside cc-workflow)"

grep -q 'exit 4' "$SKILL" ||
	fail "SKILL.md must document exit 4 — a pre-v1.6.0 watcher is the reachable case"
pass "SKILL.md documents the exit-code contract including exit 4"

echo ""
if ((FAILS > 0)); then
	echo "  $FAILS doorbell one-shot wrapper check(s) FAILED"
	exit 1
fi
echo "  all doorbell one-shot wrapper checks passed"
