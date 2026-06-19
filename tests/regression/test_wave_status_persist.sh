#!/usr/bin/env bash
# test_wave_status_persist.sh — #688 wave-status persistence seam regression test.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Two assertions for the #688 seam:
#   1. node --check on the seam helper + the workflow that imports it (syntax must hold).
#   2. the persist/blob round-trip: loop state → toBlob → write → read → reseed → equal,
#      plus idempotency (replay → byte-identical blob). Logic lives in the sibling .mjs.
#
# Implementation of (2): tests/regression/wave_status_persist_roundtrip.mjs

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_wave_status_persist"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #688 wave-status persist test"
	exit 1
fi

node --check "$REPO_DIR/skills/nextwave/wave-status.js"
echo "  [PASS] wave-status.js syntax (node --check)"
node --check "$REPO_DIR/skills/nextwave/per-wave-workflow.js"
echo "  [PASS] per-wave-workflow.js syntax (node --check)"

exec node "$REPO_DIR/tests/regression/wave_status_persist_roundtrip.mjs"
