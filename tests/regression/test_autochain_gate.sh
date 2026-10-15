#!/usr/bin/env bash
# test_autochain_gate.sh — #1224 regression test for scripts/autochain-gate.sh.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
#
# The gate lifts /precheck's human STOP, so the property under test is that it
# FAILS CLOSED: exactly one case answers "approved" (state file present, valid,
# unexpired, issue listed) and every other case — including the subtle ones —
# answers "not-approved". The subtle ones are why this file exists:
#   - `"issues": [true]` — in Python `1 in [True]` is True, so a type-blind check
#     would approve issue #1 from a corrupt list;
#   - an approval quote carrying `$(...)` must be STORED, never executed — which is
#     why it is read from a file and the inline-argument form is refused;
#   - an interpreter that will not start, or that prints "approved" and then exits
#     non-zero, must not read as a pass;
#   - an approval must not outlive its chain: expired, consumed and disarmed all
#     read "not-approved".

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE="$REPO_DIR/scripts/autochain-gate.sh"

echo "test_autochain_gate"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
R="$WORK/repo"
mkdir -p "$R"
git -C "$R" init -q
STATE="$R/.claude/autochain-active.json"

# expect <label> <want-exit> <want-prefix> -- cmd...
expect() {
	local label="$1" want_rc="$2" want_prefix="$3"
	shift 4
	local out rc
	out="$("$@" 2>/dev/null)"
	rc=$?
	if [[ "$rc" == "$want_rc" && "$out" == "$want_prefix"* ]]; then
		pass "$label"
	else
		fail "$label (rc=$rc out='$out', want rc=$want_rc prefix='$want_prefix')"
	fi
}

# ts_hours_ago <h> — an armed_at timestamp h hours in the past (negative = future)
ts_hours_ago() {
	python3 -c 'import datetime,sys; print((datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=float(sys.argv[1]))).strftime("%Y-%m-%dT%H:%M:%SZ"))' "$1"
}

# write_state <armed_at> — a valid chain {epic 5, issues [7, 9]} armed at that time
write_state() {
	printf '{"epic": 5, "issues": [7, 9], "approval": "yes", "armed_at": "%s"}' "$1" >"$STATE"
}

# --- check fails closed ------------------------------------------------------
expect "check with no state file → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7
expect "check with a non-integer issue → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" abc

mkdir -p "$R/.claude"
printf '{ not json' >"$STATE"
expect "malformed JSON → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7

printf '{"epic": 5, "issues": [7], "armed_at": "%s"}' "$(ts_hours_ago 0)" >"$STATE"
expect "no approval quote in state → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7

printf '{"epic": 5, "issues": [true], "approval": "yes", "armed_at": "%s"}' "$(ts_hours_ago 0)" >"$STATE"
expect "issues:[true] does not approve #1 (bool is not an int)" 1 "not-approved" -- bash "$GATE" check "$R" 1

printf '[1, 2, 3]' >"$STATE"
expect "non-object JSON → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 1

# A python3 that will not start must not read as a pass — nor one that prints the
# approving line and then fails.
SHIM="$WORK/shim"
mkdir -p "$SHIM"
printf '#!/bin/sh\nexit 1\n' >"$SHIM/python3"
chmod +x "$SHIM/python3"
write_state "$(ts_hours_ago 0)"
expect "broken interpreter → not-approved" 1 "not-approved" -- env PATH="$SHIM:$PATH" bash "$GATE" check "$R" 7
printf '#!/bin/sh\ncat >/dev/null\necho "approved 5 armed_at=x"\nexit 1\n' >"$SHIM/python3"
expect "interpreter prints approved then exits non-zero → not-approved" 1 "not-approved" -- env PATH="$SHIM:$PATH" bash "$GATE" check "$R" 7

# --- the approval expires -----------------------------------------------------
printf '{"epic": 5, "issues": [7], "approval": "yes"}' >"$STATE"
expect "no armed_at → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7
write_state "not-a-time"
expect "unparseable armed_at → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7
write_state "$(ts_hours_ago 13)"
expect "armed 13h ago, default TTL 12h → expired" 1 "not-approved" -- bash "$GATE" check "$R" 7
expect "armed 13h ago, AUTOCHAIN_TTL_HOURS=24 → approved" 0 "approved 5" -- env AUTOCHAIN_TTL_HOURS=24 bash "$GATE" check "$R" 7
expect "AUTOCHAIN_TTL_HOURS=0 → not-approved" 1 "not-approved" -- env AUTOCHAIN_TTL_HOURS=0 bash "$GATE" check "$R" 7
expect "AUTOCHAIN_TTL_HOURS=junk → not-approved" 1 "not-approved" -- env AUTOCHAIN_TTL_HOURS=junk bash "$GATE" check "$R" 7
write_state "$(ts_hours_ago -1)"
expect "armed_at an hour in the future → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7
write_state "$(ts_hours_ago 11)"
expect "armed 11h ago → approved" 0 "approved 5" -- bash "$GATE" check "$R" 7
rm -f "$STATE"

# --- arm refuses bad input and writes nothing --------------------------------
APPROVAL="$WORK/approval.txt"
printf 'go' >"$APPROVAL"
: >"$WORK/empty.txt"
printf '  \n\t\n' >"$WORK/blank.txt"
expect "arm with an inline quote (old form) → refused" 2 "" -- bash "$GATE" arm "$R" 5 "go" 7
expect "arm with a missing approval file → refused" 2 "" -- bash "$GATE" arm "$R" 5 --approval-file "$WORK/nope.txt" 7
expect "arm with an empty approval file → refused" 2 "" -- bash "$GATE" arm "$R" 5 --approval-file "$WORK/empty.txt" 7
expect "arm with a whitespace-only approval file → refused" 2 "" -- bash "$GATE" arm "$R" 5 --approval-file "$WORK/blank.txt" 7
expect "arm with non-integer issue → refused" 2 "" -- bash "$GATE" arm "$R" 5 --approval-file "$APPROVAL" 7 x
expect "arm with non-integer epic → refused" 2 "" -- bash "$GATE" arm "$R" five --approval-file "$APPROVAL" 7
expect "arm with no issues → refused" 2 "" -- bash "$GATE" arm "$R" 5 --approval-file "$APPROVAL"
if [[ -e "$STATE" ]]; then fail "a refused arm wrote a state file"; else pass "refused arms wrote nothing"; fi
if git -C "$R" check-ignore -q .claude/autochain-active.json; then
	fail "a refused arm still wrote the exclude entry"
else
	pass "refused arms left info/exclude alone"
fi

# --- the one approving path ---------------------------------------------------
# shellcheck disable=SC2016  # the literal $(...) is the point: it must NOT run
QUOTE='go — "run it", `ls` $(touch '"$WORK"'/PWNED)'
printf '%s' "$QUOTE" >"$APPROVAL"
expect "arm with a valid chain" 0 "armed" -- bash "$GATE" arm "$R" 5 --approval-file "$APPROVAL" 7 9
expect "listed issue → approved <epic>" 0 "approved 5 armed_at=" -- bash "$GATE" check "$R" 9
expect "unlisted issue → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 8

if [[ -e "$WORK/PWNED" ]]; then
	fail "the approval quote was EXECUTED"
else
	pass "approval quote was not executed"
fi
stored="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["approval"])' "$STATE")"
if [[ "$stored" == "$QUOTE" ]]; then pass "approval quote stored verbatim"; else fail "approval quote altered: '$stored'"; fi
if [[ "$(bash "$GATE" check "$R" 9 | sed -n 2p)" == "approval: $QUOTE" ]]; then
	pass "check shows the approval quote for the checklist"
else
	fail "check does not show the approval quote on line 2"
fi

# --- the state file never reaches version control ----------------------------
if git -C "$R" check-ignore -q .claude/autochain-active.json; then
	pass "state file is git-ignored after arm"
else
	fail "state file is NOT ignored"
fi
if [[ -z "$(git -C "$R" status --porcelain)" ]]; then
	pass "no tracked-file diff (ignore went to info/exclude, not .gitignore)"
else
	fail "arm left a visible diff: $(git -C "$R" status --porcelain | tr '\n' ' ')"
fi
bash "$GATE" arm "$R" 5 --approval-file "$APPROVAL" 7 9 >/dev/null 2>&1
if [[ "$(grep -c 'autochain-active.json' "$(git -C "$R" rev-parse --path-format=absolute --git-path info/exclude)")" == 1 ]]; then
	pass "re-arming does not duplicate the exclude entry"
else
	fail "exclude entry duplicated on re-arm"
fi

# --- consume narrows the approval as issues land ------------------------------
expect "consume #7" 0 "consumed #7" -- bash "$GATE" consume "$R" 7
expect "consumed issue → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7
expect "remaining issue still approved" 0 "approved 5" -- bash "$GATE" check "$R" 9
expect "consume an unlisted issue → not-listed, exit 0" 0 "not-listed" -- bash "$GATE" consume "$R" 8
expect "consume the last issue disarms" 0 "consumed #9 — chain complete" -- bash "$GATE" consume "$R" 9
if [[ -e "$STATE" ]]; then fail "state file survived the last consume"; else pass "last consume removed the state file"; fi
expect "consume with no chain → not-listed, exit 0" 0 "not-listed" -- bash "$GATE" consume "$R" 9
printf '{ not json' >"$STATE"
expect "consume on a corrupt state → exit 2" 2 "" -- bash "$GATE" consume "$R" 9
if [[ -e "$STATE" ]]; then fail "corrupt state survived a failed consume"; else pass "a failed consume disarms (fail closed)"; fi

# --- disarm -------------------------------------------------------------------
bash "$GATE" arm "$R" 5 --approval-file "$APPROVAL" 7 >/dev/null 2>&1
expect "disarm" 0 "disarmed" -- bash "$GATE" disarm "$R"
expect "after disarm → not-approved" 1 "not-approved" -- bash "$GATE" check "$R" 7

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS assertion(s) failed"
	exit 1
fi
echo "  all assertions passed"
