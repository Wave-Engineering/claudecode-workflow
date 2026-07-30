#!/usr/bin/env bash
# doorbell-oneshot.sh — one-shot arming wrapper for `discord-watcher doorbell` (#1055)
#
# Blocks until at least one deliverable Discord message arrives, prints every
# `[doorbell] ...` line the watcher has produced by that moment, and exits.
#
# WHY THIS EXISTS
# ---------------
# The watcher's README and its own `--help` both tell you to arm the doorbell with
# Claude Code's `Monitor` primitive:
#
#     Monitor({ command: "discord-watcher doorbell", persistent: true })
#
# That primitive is gated OFF under several common conditions. All of the following
# were read out of the 2.1.220 bundle (2026-07-27); minified symbol names are
# regenerated per build, so this records the behavior, not the identifiers.
#
# `Monitor.isEnabled()` resolves the server-side feature flag `tengu_amber_sentinel`,
# which DEFAULTS TO FALSE, and both local override paths are compiled out: the
# settings override returns unconditionally, and the CLAUDE_INTERNAL_FC_OVERRIDES env
# read sits after an unconditional `return` — unreachable dead code. The flag can only
# come from the feature service, and that lookup SHORT-CIRCUITS TO FALSE before it
# consults the cache when any of these hold:
#
#     - provider is not first-party (Bedrock, Vertex / Google Cloud Agent Platform,
#       Microsoft Foundry) — unless CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST is set
#     - gateway auth is in use
#     - CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC / DISABLE_TELEMETRY / DO_NOT_TRACK
#     - DISABLE_GROWTHBOOK
#
# So an Anthropic-authenticated session with telemetry disabled ALSO has no Monitor —
# the auth path is not the whole story. On a third-party provider `--channels` is
# unavailable too, which is why a Bedrock-backed session is exactly the case this
# wrapper exists for: no Monitor to fall back to, and no channels either. The two are
# separately gated, though (Channels is admin-enabled on Team/Enterprise plans), so
# diagnose them independently rather than inferring one from the other.
#
# Where Monitor is missing, the only background-process mechanism available notifies
# the agent when a task **exits** — and `discord-watcher doorbell` is a persistent
# poll loop that never exits. Armed that way the doorbell line lands in a file nobody
# reads and the agent is never woken: silent deafness, the exact failure the doorbell
# exists to prevent.
#
# So this wrapper inverts it: make the EXIT be the doorbell. One batch of messages,
# one exit, one task-completion notification, one agent turn. Re-arm for the next.
#
# THE EXIT CODE IS THE SIGNAL — so it must never lie
# --------------------------------------------------
# Because the whole design rests on "process exited ⇒ a message arrived", an exit 0
# that carries no message is worse than a crash: the agent re-arms immediately and
# spins. Every non-message way the read can end therefore gets its OWN code, and a
# dead watcher (bad token, baseline-init failure) is reported loudly with its
# captured stderr as exit 4.
#
# A watcher older than v1.6.0 is NOT that case, and must be caught before we ever
# read. It has no unknown-subcommand handler — `argv[2] === "doorbell"` simply fails
# and control falls through to `main()`, the full MCP stdio server, which installs a
# poll interval and never exits. So an old binary invoked as `doorbell` HANGS rather
# than failing; with the default TIMEOUT=0 that is an unbounded silent wait, the very
# deafness this script exists to prevent. Hence the capability probe below, which
# needs its own `timeout` because `doorbell --help` hangs on an old binary too.
#
# WHY NOT `discord-watcher doorbell | head -1`
# -------------------------------------------
# Because it leaks an orphaned poller. Bun ignores SIGPIPE and swallows the write
# error, so closing the read end does NOT terminate the child — verified still
# alive 20s after `head` exited, polling Discord forever. Re-arming that way would
# accumulate a poller per message. We therefore read through a fifo and kill the
# child by PID.
#
# WHY IT DRAINS INSTEAD OF READING EXACTLY ONE LINE
# -------------------------------------------------
# A single poll can yield several deliverable messages. Reading one line and killing
# the watcher would discard the rest — and they are NOT recoverable: the re-armed
# instance seeds its cursor to the latest message per channel AND marks it delivered,
# so it starts *past* them. One line per exit would therefore silently lose messages,
# which is the same class of failure this script exists to prevent. So once the first
# line lands we drain whatever else is already buffered before exiting.
#
# KNOWN LIMIT — the drain covers one channel, not a whole cycle.
# The watcher emits a channel's messages back-to-back with no awaits between them, so
# a same-channel burst lands well inside the drain window. Between channels it sleeps
# 50-150ms of jitter and then makes an HTTP round trip, so messages in DIFFERENT
# channels in the same cycle usually fall outside the window; and because cleanup
# kills the watcher mid-cycle, channels it had not yet polled are never fetched at
# all. Those are lost the same unrecoverable way. DRAIN_SECONDS widens the window to
# trade wall-clock for coverage, but it cannot close the gap — only a cycle-boundary
# signal from the watcher could. Raise it if you are addressed across many channels.
#
# PREREQUISITE — must be launched from the project root
# ----------------------------------------------------
# The watcher resolves agent identity from `CLAUDE_PROJECT_DIR ?? process.cwd()`
# and reads `<root>/.claude/agent-identity.json`. With identity unresolved,
# `shouldDeliverMessage` FAILS CLOSED: the loop polls normally and delivers
# nothing. Run from the project root, or export CLAUDE_PROJECT_DIR.
#
# Usage:
#   doorbell-oneshot.sh                 # block until a message, print it, exit
#   TIMEOUT=1800 doorbell-oneshot.sh    # give up after N seconds (exit 3)
#   DRAIN_SECONDS=2 doorbell-oneshot.sh # widen the post-first-line drain window
#   DEBUG=1 doorbell-oneshot.sh         # also forward the watcher's stderr (identity
#                                       # confirmation, poll diagnostics)
#
# Exit codes: 0 = one or more doorbell lines emitted; 2 = precondition failure
#             (bash too old, watcher missing or pre-v1.6.0, bad TIMEOUT/DRAIN_SECONDS,
#             temp-dir setup); 3 = TIMEOUT elapsed with no message; 4 = watcher exited
#             without emitting a line.
set -uo pipefail

# bash 4.0 is a hard requirement, and both features it provides fail SILENTLY on 3.2
# (stock /usr/bin/bash on macOS): fractional `read -t` is rejected outright, so the
# drain would no-op and quietly truncate multi-message polls; and a timed-out read
# returns 1 instead of >128, so every timeout would be misreported as a dead watcher.
# Two silent wrong answers — so refuse loudly instead.
if ((BASH_VERSINFO[0] < 4)); then
	echo "doorbell-oneshot: needs bash >= 4 (this is $BASH_VERSION)." >&2
	echo "  Fractional 'read -t' and the >128 timeout status are 4.0+ features;" >&2
	echo "  on 3.2 the drain and the timeout both fail silently. macOS: brew install bash." >&2
	exit 2
fi

WATCHER="${WATCHER:-$HOME/.local/bin/discord-watcher}"
TIMEOUT="${TIMEOUT:-0}"
DRAIN_SECONDS="${DRAIN_SECONDS:-0.2}"
DEBUG="${DEBUG:-0}"

if [[ ! -x "$WATCHER" ]]; then
	echo "doorbell-oneshot: watcher not found or not executable: $WATCHER" >&2
	exit 2
fi

# Probe the capability rather than inferring it from a read that fails. An old watcher
# does not reject `doorbell` — it falls through to the MCP server and never exits, so
# without this the script would simply hang. `timeout` is load-bearing: `--help` hangs
# on an old binary too, for the same reason.
if ! timeout 5 "$WATCHER" doorbell --help 2>/dev/null | grep -q 'doorbell'; then
	echo "doorbell-oneshot: $WATCHER does not implement the 'doorbell' subcommand." >&2
	echo "  It needs discord-watcher v1.6.0 or newer. An older binary silently falls" >&2
	echo "  through to the MCP server and hangs instead of failing, so this is checked" >&2
	echo "  up front rather than diagnosed from a stalled read." >&2
	exit 2
fi

# Validate TIMEOUT before use. `[[ "$TIMEOUT" -gt 0 ]]` evaluates arithmetically, so
# a plausible typo like TIMEOUT=30s is a syntax error that makes the test FALSE and
# silently selects the unbounded branch — the caller asks for a bound and gets an
# infinite block, the very failure the bound was for.
if [[ ! "$TIMEOUT" =~ ^[0-9]+$ ]]; then
	echo "doorbell-oneshot: TIMEOUT must be a whole number of seconds, got: $TIMEOUT" >&2
	exit 2
fi

# DRAIN_SECONDS goes straight to `read -t`, which rejects a malformed value and returns
# non-zero — indistinguishable from "nothing left to drain", i.e. a silently skipped
# drain. Fractional is allowed here (unlike TIMEOUT) because that is the useful range.
if [[ ! "$DRAIN_SECONDS" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
	echo "doorbell-oneshot: DRAIN_SECONDS must be a number of seconds, got: $DRAIN_SECONDS" >&2
	exit 2
fi

# Warn (do not fail) when identity is unresolvable — the watcher would fail closed
# and this script would just hang, which reads as "no messages" rather than "deaf".
IDENTITY_ROOT="${CLAUDE_PROJECT_DIR:-$PWD}"
if [[ ! -f "$IDENTITY_ROOT/.claude/agent-identity.json" ]]; then
	echo "doorbell-oneshot: WARNING no $IDENTITY_ROOT/.claude/agent-identity.json —" >&2
	echo "  the delivery gate fails closed on unresolved identity, so NOTHING will" >&2
	echo "  be delivered. Run from the project root or set CLAUDE_PROJECT_DIR." >&2
fi

# A private directory rather than `mktemp -u` + mkfifo: no TOCTOU window on the
# name, and `rm -rf` cleans the fifo and the stderr capture together.
WORKDIR=$(mktemp -d "${TMPDIR:-/tmp}/doorbell.XXXXXX") || {
	echo "doorbell-oneshot: could not create a temp directory" >&2
	exit 2
}
FIFO="$WORKDIR/doorbell-fifo"
ERRLOG="$WORKDIR/watcher-stderr"
mkfifo "$FIFO" || {
	rm -rf "$WORKDIR"
	echo "doorbell-oneshot: could not create the fifo at $FIFO" >&2
	exit 2
}

# Capture the watcher's stderr rather than discarding it: it is where a dead-watcher
# diagnosis lives, and where the identity state_change line the skill tells you to
# check appears.
"$WATCHER" doorbell >"$FIFO" 2>"$ERRLOG" &
CHILD=$!

cleanup() {
	# shellcheck disable=SC2317  # invoked indirectly via `trap cleanup EXIT` below
	kill "$CHILD" 2>/dev/null
	# shellcheck disable=SC2317  # ditto — reap the killed child before removing its fifo
	wait "$CHILD" 2>/dev/null
	# shellcheck disable=SC2317  # ditto
	rm -rf "$WORKDIR"
}
trap cleanup EXIT
# Signal handlers must EXIT. A bare `trap cleanup TERM` runs the handler, returns,
# and lets the interrupted `read` fall through to the success path — making task
# cancellation indistinguishable from a delivered message.
trap 'exit 130' INT
trap 'exit 143' TERM

dump_watcher_stderr() {
	[[ -s "$ERRLOG" ]] || return 0
	echo "doorbell-oneshot: --- watcher stderr ---" >&2
	cat "$ERRLOG" >&2
	echo "doorbell-oneshot: --- end watcher stderr ---" >&2
}

# Open the fifo ONCE on fd 3. Reopening per read would race the writer and could
# lose buffered lines between the first read and the drain.
exec 3<"$FIFO"

LINE=""
rc=0
if [[ "$TIMEOUT" -gt 0 ]]; then
	IFS= read -r -t "$TIMEOUT" LINE <&3 || rc=$?
else
	IFS= read -r LINE <&3 || rc=$?
fi

# read distinguishes its two failure modes by code: >128 means the -t deadline
# elapsed, anything else non-zero means EOF — the watcher closed the pipe.
if ((rc > 128)); then
	echo "doorbell-oneshot: no message within ${TIMEOUT}s" >&2
	exit 3
elif ((rc != 0)) || [[ -z "$LINE" ]]; then
	echo "doorbell-oneshot: watcher exited without emitting a doorbell line." >&2
	echo "  The 'doorbell' subcommand is present, so this is a genuinely failed watcher" >&2
	echo "  (bad token, baseline init, crash) rather than an old binary." >&2
	dump_watcher_stderr
	exit 4
fi

# Validate the shape before calling it a doorbell. The watcher's other mode writes
# JSON-RPC frames to stdout, and reporting one of those as a delivered message would
# be a false doorbell — the failure this script's exit contract exists to rule out.
if [[ "$LINE" != '[doorbell] '* ]]; then
	echo "doorbell-oneshot: stdout did not carry a doorbell line. Got:" >&2
	printf '  %s\n' "$LINE" >&2
	dump_watcher_stderr
	exit 4
fi

printf '%s\n' "$LINE"

# Drain what this channel's poll already produced. A short deadline, not a blocking
# read: the point is "what is buffered now", not "wait for the next message". See the
# KNOWN LIMIT note in the header — this does not span channels within a cycle.
while IFS= read -r -t "$DRAIN_SECONDS" LINE <&3; do
	[[ "$LINE" == '[doorbell] '* ]] && printf '%s\n' "$LINE"
done

exec 3<&-

[[ "$DEBUG" == "1" ]] && dump_watcher_stderr

exit 0
