#!/usr/bin/env bash
# test_merge_result.sh — cc-workflow#1211 merge-result CI rule regression test.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
#   1. node --check on the shared module (syntax must hold).
#   2. the pure-predicate unit tests: mergeResultVerdict() over ci_wait_run answers and direct
#      GitLab /merge reads. Logic lives in the sibling .mjs.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_merge_result"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #1211 merge-result test"
	exit 1
fi

node --check "$REPO_DIR/skills/nextwave/merge-result.js"
echo "  [PASS] merge-result.js syntax (node --check)"

exec node "$REPO_DIR/tests/regression/merge_result.mjs"
