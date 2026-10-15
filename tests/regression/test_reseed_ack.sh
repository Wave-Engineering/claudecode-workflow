#!/usr/bin/env bash
# test_reseed_ack.sh — #1225 regression test for scripts/hooks/workflow/reseed-ack.sh.
#
# The ack is the kicker's only evidence that a send landed, so it must fire on
# exactly `/reseed revive` and nothing else. A loose match (any prompt, or
# `continue`, the old revive keystroke) would tell the kicker it succeeded when
# the session never received the command.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/hooks/workflow/reseed-ack.sh"

echo "test_reseed_ack"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/.claude"
NONCE="$WORK/.claude/reseed-ack"

# case <label> <prompt> <want: removed|kept>
case_() {
	local label="$1" prompt="$2" want="$3" out
	: >"$NONCE"
	out="$(jq -cn --arg p "$prompt" --arg c "$WORK" '{prompt: $p, cwd: $c}' | bash "$HOOK")"
	local rc=$?
	local got=kept
	[[ -e "$NONCE" ]] || got=removed
	if [[ "$got" == "$want" && $rc -eq 0 && -z "$out" ]]; then
		pass "$label"
	else
		fail "$label (nonce $got, want $want; rc=$rc; stdout='$out')"
	fi
}

case_ "'/reseed revive' acknowledges" "/reseed revive" removed
case_ "surrounding whitespace is tolerated" $'  /reseed revive \n' removed
case_ "'continue' (the old keystroke) does not" "continue" kept
case_ "'/reseed' alone does not" "/reseed" kept
case_ "'/reseed revive now' does not" "/reseed revive now" kept
case_ "an unrelated prompt does not" "please read the seed and revive" kept

rm -f "$NONCE"
out="$(jq -cn --arg c "$WORK" '{prompt: "/reseed revive", cwd: $c}' | bash "$HOOK")"
if [[ $? -eq 0 && -z "$out" ]]; then pass "no nonce → still exit 0, silent"; else fail "no-nonce case misbehaved"; fi
out="$(printf 'not json' | bash "$HOOK")"
if [[ $? -eq 0 && -z "$out" ]]; then pass "garbage stdin → exit 0, silent (never blocks a prompt)"; else fail "garbage stdin misbehaved"; fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS assertion(s) failed"
	exit 1
fi
echo "  all assertions passed"
