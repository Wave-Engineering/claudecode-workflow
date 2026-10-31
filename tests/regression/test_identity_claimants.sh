#!/usr/bin/env bash
# test_identity_claimants.sh — #1366 regression test for scripts/identity-claimants.sh.
#
# Two live sessions in one checkout share one identity. The helper reads the process
# table: another claude of this user, with the same cwd, started earlier → `older`
# (exit 3); started later → `younger`; none → `none`. Driven against a fake proc tree
# (IDENTITY_PROC_ROOT) with a known self (IDENTITY_SELF_START_PID).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CLAIM="$REPO_DIR/scripts/identity-claimants.sh"

echo "test_identity_claimants"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
ROOT="$WORK/checkout"
OTHER="$WORK/worktree"
mkdir -p "$ROOT" "$OTHER"

# proc <tree> <pid> <ppid> <comm> <start> <cwd> [<argv>]
proc() {
	local d="$1/$2" zeros argv
	mkdir -p "$d"
	printf '%s\n' "$4" >"$d/comm"
	read -ra argv <<<"${7:-$4}"
	printf '%s\0' "${argv[@]}" >"$d/cmdline"
	printf 'Name:\t%s\nPPid:\t%s\n' "$4" "$3" >"$d/status"
	zeros="$(printf '0 %.0s' $(seq 17))"
	# Fields after ')': state(3) ppid(4), 17 more (5-21), then starttime (22).
	printf '%s (%s) S %s %s%s 0 0\n' "$2" "$4" "$3" "$zeros" "$5" >"$d/stat"
	ln -s "$6" "$d/cwd"
}

run() { # <tree> [self-start-pid]
	out="$(IDENTITY_PROC_ROOT="$1" IDENTITY_SELF_START_PID="${2:-200}" bash "$CLAIM" "$ROOT")"
	rc=$?
}

check() { # <label> <want-out> <want-rc>
	if [[ "$out" == "$2" && $rc -eq $3 ]]; then pass "$1"; else fail "$1: got '$out' rc=$rc, want '$2' rc=$3"; fi
}

# self: claude 100 (start 5000, cwd ROOT); the shell the helper starts from is 200.
base() {
	local t="$WORK/$1"
	proc "$t" 100 1 claude 5000 "$ROOT"
	proc "$t" 200 100 bash 5100 "$ROOT"
	printf '%s' "$t"
}

t="$(base alone)"
run "$t"
check "none when alone" "none" 0

t="$(base older)"
proc "$t" 300 1 claude 4000 "$ROOT"
run "$t"
check "older claimant refuses" "older 300" 3

t="$(base younger)"
proc "$t" 300 1 claude 6000 "$ROOT"
run "$t"
check "younger claimant keeps" "younger 300" 0

t="$(base self)"
run "$t"
if [[ "$out" != *100* ]]; then pass "self is excluded"; else fail "self listed: $out"; fi

t="$(base worktree)"
proc "$t" 300 1 claude 4000 "$OTHER"
run "$t"
check "worktree is not a claimant" "none" 0

t="$(base nonclaude)"
proc "$t" 300 1 bash 4000 "$ROOT"
run "$t"
check "non-claude process ignored" "none" 0

t="$(base node)"
proc "$t" 300 1 node 4000 "$ROOT" "node /usr/lib/node_modules/@anthropic-ai/claude-code/cli.js"
run "$t"
check "node-launched cli counts" "older 300" 3

t="$(base spaces)"
proc "$t" 300 1 "(a b) c" 4000 "$ROOT" "claude"
# The comm has spaces and a ')', so only the argv makes it a claude; its start must still parse.
printf '%s\0' node /x/claude-code/cli.js >"$t/300/cmdline"
# Field 21 is 9999: a parse that splits at the FIRST ')' shifts by one, reads 9999 as the
# start time, and wrongly says younger.
printf '300 ((a b) c) S 1 %s9999 4000 0 0\n' "$(printf '0 %.0s' $(seq 16))" >"$t/300/stat"
run "$t"
check "comm with spaces parses start time" "older 300" 3

# A nested `claude -p` (300) run from the session (100) in the same checkout: the parent
# is older, but it is this run's own ancestor, not a rival.
t="$WORK/nested"
proc "$t" 100 1 claude 5000 "$ROOT"
proc "$t" 200 100 bash 5100 "$ROOT"
proc "$t" 300 200 claude 5200 "$ROOT"
proc "$t" 400 300 bash 5300 "$ROOT"
run "$t" 400
check "nested claude's parent session is not a claimant" "none" 0

# The same nesting beside a real older rival (50): the rival is still reported.
proc "$t" 50 1 claude 4000 "$ROOT"
run "$t" 400
check "nested run still sees a real older rival" "older 50" 3

run "$WORK/missing"
check "unknown without proc" "unknown no-proc" 0

t="$WORK/noself"
proc "$t" 200 1 bash 5100 "$ROOT"
run "$t"
check "unknown when self not found" "unknown self-not-found" 0

echo
if [[ $FAILS -eq 0 ]]; then
	echo "test_identity_claimants: all passed"
	exit 0
fi
echo "test_identity_claimants: $FAILS failed"
exit 1
