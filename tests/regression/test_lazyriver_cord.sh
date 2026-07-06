#!/usr/bin/env bash
# test_lazyriver_cord.sh — #844: unit test for the /lazyriver coded escalation cord.
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Asserts river.js#cordCheck: leg-cap (default 10) and 2-consecutive-zero-finding-legs
# (diminishing), with leg-cap winning when both fire. See lazyriver_cord.test.mjs.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_lazyriver_cord"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the cord unit test"
	exit 1
fi

node "$REPO_DIR/tests/regression/lazyriver_cord.test.mjs"
echo "  all cord checks passed"
