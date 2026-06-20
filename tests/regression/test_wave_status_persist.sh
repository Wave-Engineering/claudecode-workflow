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

# #748 — lock the cross-wave trajectory producer wiring so STEP 3 cannot silently vanish.
# The terminal persist seam MUST instruct the agent to upsert the trajectory entry via the
# DEPLOYED 'wave-status' console command (NOT 'python3 -m wave_status', which only resolves
# inside the kit repo — the producer runs in the target clone). Assert in BOTH source + bundle.
for f in "skills/nextwave/wave-status.js" "skills/nextwave/per-wave-workflow.bundled.js"; do
	if ! grep -q "wave-status trajectory-append" "$REPO_DIR/$f"; then
		echo "  [FAIL] $f missing the #748 'wave-status trajectory-append' producer wiring (STEP 3)"
		exit 1
	fi
	if grep -q "python3 -m wave_status trajectory-append" "$REPO_DIR/$f"; then
		echo "  [FAIL] $f uses 'python3 -m wave_status trajectory-append' — won't resolve in the target clone; use the deployed console command"
		exit 1
	fi
done
echo "  [PASS] #748 trajectory producer wiring present (wave-status console cmd, source + bundle)"

exec node "$REPO_DIR/tests/regression/wave_status_persist_roundtrip.mjs"
