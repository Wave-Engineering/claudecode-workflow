#!/usr/bin/env bash
# test_lock_find_in_sync.sh — the prose copies of the lock predicate match it (#1358).
#
# gate.js and the /precheck fallback cannot source scripts/ci/lock-predicate.sh,
# so gen-lock-find.sh writes their find and main-scan lines from it. This pins
# that the committed copies are in sync, and that --check is not vacuous: a copy
# with one lock name dropped from gate.js must fail, naming gate.js.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GEN="$REPO_DIR/scripts/ci/gen-lock-find.sh"
fail=0

echo "test_lock_find_in_sync"
echo "──────────────────────────────────────────"

# 1. green at HEAD
out="$(bash "$GEN" --check 2>&1)"
rc=$?
if [[ $rc -eq 0 ]]; then
	echo "  [PASS] the prose copies match lock-predicate.sh"
else
	echo "  [FAIL] drift at HEAD (rc=$rc) — run: scripts/ci/gen-lock-find.sh"
	printf '%s\n' "$out" | sed 's/^/    /'
	fail=1
fi

# 2. red on a mutated copy: drop yarn.lock from gate.js's find
T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT
mkdir -p "$T/scripts/ci" "$T/skills/nextwave" "$T/skills/precheck"
cp "$REPO_DIR/scripts/ci/gen-lock-find.sh" "$REPO_DIR/scripts/ci/lock-predicate.sh" "$T/scripts/ci/"
cp "$REPO_DIR/skills/nextwave/gate.js" "$T/skills/nextwave/"
cp "$REPO_DIR/skills/precheck/SKILL.md" "$T/skills/precheck/"
sed -i "s/ -o -name 'yarn.lock'//" "$T/skills/nextwave/gate.js"
if cmp -s "$REPO_DIR/skills/nextwave/gate.js" "$T/skills/nextwave/gate.js"; then
	echo "  [FAIL] the mutation changed nothing; the red case proves nothing"
	fail=1
else
	out="$(bash "$T/scripts/ci/gen-lock-find.sh" --check "$T" 2>&1)"
	rc=$?
	if [[ $rc -eq 1 ]] && grep -q 'DRIFT skills/nextwave/gate.js' <<<"$out"; then
		echo "  [PASS] a drifted gate.js find fails --check, naming gate.js"
	else
		echo "  [FAIL] a drifted gate.js find must exit 1 naming gate.js (rc=$rc)"
		printf '%s\n' "$out" | sed 's/^/    /'
		fail=1
	fi
fi

if [[ $fail -eq 0 ]]; then
	echo "  all lock-find checks passed"
else
	exit 1
fi
