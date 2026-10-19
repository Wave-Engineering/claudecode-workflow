#!/usr/bin/env bash
# test_sqtk_vendor.sh — #1236: the vendored sqtk matches its pin.
#
# scripts/sqtk is squawkie-talkie's CLI, copied byte-for-byte at the tag in scripts/ci/sqtk.pin
# by scripts/ci/vendor-sqtk.sh. A hand edit here would silently fork the kit's sqtk from
# upstream, so any drift from the recorded sha256 fails. This is offline: it never fetches.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SQTK="$REPO_DIR/scripts/sqtk"
PIN="$REPO_DIR/scripts/ci/sqtk.pin"

echo "test_sqtk_vendor"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

if [[ -f "$PIN" ]]; then pass "pin file present"; else fail "scripts/ci/sqtk.pin missing"; fi
tag=$(sed -n 's/^tag=//p' "$PIN" 2>/dev/null)
want=$(sed -n 's/^sha256=//p' "$PIN" 2>/dev/null)
if [[ "$tag" =~ ^v[0-9] ]]; then pass "pinned to a tag ($tag)"; else fail "pin has no tag ('$tag')"; fi

if [[ -x "$SQTK" ]]; then pass "scripts/sqtk is executable"; else fail "scripts/sqtk missing or not executable"; fi
got=$(sha256sum "$SQTK" 2>/dev/null | cut -d' ' -f1)
if [[ -n "$want" && "$got" == "$want" ]]; then
	pass "scripts/sqtk matches its pin"
else
	fail "scripts/sqtk does not match its pin (got ${got:-none}, want ${want:-none}); re-run scripts/ci/vendor-sqtk.sh $tag"
fi

if bash -n "$SQTK" 2>/dev/null; then pass "scripts/sqtk parses"; else fail "scripts/sqtk has a syntax error"; fi
if "$SQTK" help >/dev/null 2>&1; then pass "sqtk help runs with no config"; else fail "sqtk help failed"; fi

echo
if [[ $FAILS -eq 0 ]]; then
	echo "  All sqtk-vendor checks passed."
	exit 0
fi
echo "  $FAILS sqtk-vendor check(s) FAILED."
exit 1
