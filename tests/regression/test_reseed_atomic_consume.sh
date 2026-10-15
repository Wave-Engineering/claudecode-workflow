#!/usr/bin/env bash
# test_reseed_atomic_consume.sh — #1225 regression test for reseed-revive.sh.
#
# The double-revive of 2026-08-31 came from the SessionStart{clear} hook firing
# twice. The hook now claims the armed file with an atomic mv, so however many
# copies run at once, exactly one proceeds. Each round fires two copies
# concurrently against one armed file and counts how many launched a kicker
# (stubbed) and printed the revive pointer.
#
# Also pinned here, because they are the other half of "the hook no longer
# drives the revive itself": it never prints the seed body, a stale armed file
# gets a pointer and no kick, and a missing seed says so.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/hooks/workflow/reseed-revive.sh"

echo "test_reseed_atomic_consume"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
P="$WORK/proj"
mkdir -p "$P/.claude"
printf 'SEED-BODY-MARKER\n' >"$P/.claude/reseed-revive.md"

# Kicker stub: records each launch.
STUB="$WORK/kick-stub.sh"
printf '#!/usr/bin/env bash\nprintf "%%s\\n" "$*" >>"%s/launches"\n' "$WORK" >"$STUB"
chmod +x "$STUB"

arm() { printf '{"armed_at": "x", "tmux_pane": "%%7"}' >"$P/.claude/reseed-armed.json"; }
input() { jq -cn --arg c "$P" '{cwd: $c, source: "clear"}'; }

# Wait (briefly) for detached stub launches to land.
settle() {
	local _
	for _ in $(seq 1 20); do
		[[ -f "$WORK/launches" && "$(wc -l <"$WORK/launches")" -ge "$1" ]] && return
		sleep 0.1
	done
}

ROUNDS=15
bad=0
for r in $(seq 1 "$ROUNDS"); do
	rm -f "$WORK/launches" "$WORK"/out.*
	arm
	input | RESEED_KICK_BIN="$STUB" bash "$HOOK" >"$WORK/out.a" 2>/dev/null &
	input | RESEED_KICK_BIN="$STUB" bash "$HOOK" >"$WORK/out.b" 2>/dev/null &
	wait
	settle 1
	sleep 0.2 # a second (wrong) launch would land in this window
	revived=$(cat "$WORK"/out.* | grep -c 'RESEED AUTO-REVIVE')
	launched=$(wc -l <"$WORK/launches" 2>/dev/null || echo 0)
	if [[ "$revived" -ne 1 || "$launched" -ne 1 ]]; then
		bad=$((bad + 1))
		echo "    round $r: revived=$revived launched=$launched"
	fi
done
if [[ $bad -eq 0 ]]; then
	pass "two concurrent runs → exactly one proceeds ($ROUNDS rounds)"
else
	fail "$bad of $ROUNDS rounds did not have exactly one winner"
fi

leftovers=("$P"/.claude/reseed-armed*)
if [[ -e "${leftovers[0]}" ]]; then
	fail "armed (or claimed) file left behind: ${leftovers[*]}"
else
	pass "armed file fully consumed, no .claimed leftovers"
fi

if grep -q 'SEED-BODY-MARKER' "$WORK"/out.*; then
	fail "the hook injected the seed body"
else
	pass "the seed body is never injected (pointer only)"
fi
if grep -q -- '%7' "$WORK/launches" && grep -q "$P" "$WORK/launches"; then
	pass "kicker launched with the recorded pane and the project root"
else
	fail "kicker args wrong: $(cat "$WORK/launches")"
fi

# --- stale: pointer, no kick ---------------------------------------------------
rm -f "$WORK/launches"
arm
touch -d '10 minutes ago' "$P/.claude/reseed-armed.json"
out="$(input | RESEED_KICK_BIN="$STUB" bash "$HOOK" 2>/dev/null)"
sleep 0.3
if [[ "$out" == *"RESEED PENDING"* && "$out" == *"/reseed revive"* && ! -e "$WORK/launches" ]]; then
	pass "stale armed file → pointer to /reseed revive, no kick"
else
	fail "stale case wrong (out='$out', launched=$([[ -e "$WORK/launches" ]] && echo yes || echo no))"
fi

# --- missing seed ----------------------------------------------------------------
rm -f "$P/.claude/reseed-revive.md"
arm
out="$(input | RESEED_KICK_BIN="$STUB" bash "$HOOK" 2>/dev/null)"
if [[ "$out" == *"missing"* && ! -e "$P/.claude/reseed-armed.json" ]]; then
	pass "missing seed → says so, armed file consumed"
else
	fail "missing-seed case wrong: '$out'"
fi

# --- not armed: silent no-op -------------------------------------------------------
out="$(input | RESEED_KICK_BIN="$STUB" bash "$HOOK" 2>/dev/null)"
if [[ $? -eq 0 && -z "$out" ]]; then pass "not armed → silent no-op"; else fail "not-armed printed '$out'"; fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS assertion(s) failed"
	exit 1
fi
echo "  all assertions passed"
