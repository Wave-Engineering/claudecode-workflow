#!/usr/bin/env bash
# test_identity_collision_hook.sh — #1366 regression test for
# scripts/hooks/workflow/identity-collision-warn.sh.
#
# The SessionStart hook warns only on `older` (another live session holds this
# checkout's identity), names the Dev-Name and the pids, and is silent otherwise.
# identity-claimants.sh is stubbed through IDENTITY_CLAIMANTS_BIN.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/hooks/workflow/identity-collision-warn.sh"
TEMPLATE="$REPO_DIR/config/settings.template.json"

echo "test_identity_collision_hook"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
CWD="$WORK/checkout"
mkdir -p "$CWD/.claude"
printf '{"dev_name":"null-island","dev_avatar":"x","dev_team":"oaw"}\n' >"$CWD/.claude/agent-identity.json"

STUB="$WORK/claimants"
cat >"$STUB" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$STUB_CALLS"
printf '%s\n' "$STUB_OUT"
[[ "$STUB_OUT" == older* ]] && exit 3
exit 0
SH
chmod +x "$STUB"

hook() { # <cwd> <stub output>
	: >"$WORK/calls"
	out="$(printf '{"cwd":"%s","source":"startup"}' "$1" |
		IDENTITY_CLAIMANTS_BIN="$STUB" STUB_OUT="$2" STUB_CALLS="$WORK/calls" \
			IDENTITY_COLLISION_LOG="$WORK/log" bash "$HOOK")"
	rc=$?
}

hook "$CWD" "older 77"
if [[ $rc -eq 0 && "$out" == "[IDENTITY COLLISION]"* && "$out" == *null-island* && "$out" == *"pid 77"* ]]; then
	pass "hook warns on older"
else
	fail "hook on older: rc=$rc out=$out"
fi

for v in none "younger 88" "unknown no-proc"; do
	hook "$CWD" "$v"
	if [[ $rc -eq 0 && -z "$out" ]]; then pass "hook silent on '$v'"; else fail "hook on '$v': rc=$rc out=$out"; fi
done

mkdir -p "$WORK/bare"
hook "$WORK/bare" "older 77"
if [[ $rc -eq 0 && -z "$out" && ! -s "$WORK/calls" ]]; then
	pass "hook silent without identity file"
else
	fail "no identity file: rc=$rc out=$out calls=$(cat "$WORK/calls")"
fi

if jq -e '.hooks.SessionStart | any(.matcher == "startup|resume" and
	any(.hooks[]; .command == "~/.claude/scripts/hooks/workflow/identity-collision-warn.sh"))' \
	"$TEMPLATE" >/dev/null; then
	pass "template wires the hook"
else
	fail "settings.template.json has no startup|resume group running identity-collision-warn.sh"
fi

echo
if [[ $FAILS -eq 0 ]]; then
	echo "test_identity_collision_hook: all passed"
	exit 0
fi
echo "test_identity_collision_hook: $FAILS failed"
exit 1
