#!/usr/bin/env bash
# test_dispatch_ceiling.sh — #824 (Story 1.2, Plan #822) IT-02: per-wave DISPATCH enforcement.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Proves the wave `dispatch` hint (/prepwaves #823) is actually ENFORCED by the executor, not
# documentation-only (the wave-1a review-gate finding). Assertions:
#   1. node --check on the dispatch seam + the Workflow source that calls it (syntax must hold).
#   2. WIRING GUARD (source + bundle): per-wave-workflow.js calls applyDispatchCeiling on the
#      planned flight-group, and campaign-workflow.js threads `dispatch` into the per-wave args —
#      so the enforcement path can't silently vanish (mirrors the #748 producer-wiring guard).
#   3. the behavioral contract (fan → parallel group; serialize/serialize-preferred/absent →
#      single-file; ceiling never widens; CT-01 absent → serialize). Logic lives in the sibling .mjs.
#
# Implementation of (3): tests/regression/dispatch_ceiling.mjs

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NW="skills/nextwave"

echo "test_dispatch_ceiling"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #824 dispatch-ceiling test"
	exit 1
fi

# 1. syntax
node --check "$REPO_DIR/$NW/dispatch.js"
echo "  [PASS] dispatch.js syntax (node --check)"
node --check "$REPO_DIR/$NW/per-wave-workflow.js"
echo "  [PASS] per-wave-workflow.js syntax (node --check)"

# 2. WIRING GUARD — the loop must actually CALL the ceiling (source AND the runnable bundle), and
#    the campaign launcher must thread dispatch into the per-wave args. Assert in both so a
#    re-bundle drift or a lost edit is caught, not just the pure function existing.
for f in "$NW/per-wave-workflow.js" "$NW/per-wave-workflow.bundled.js"; do
	if ! grep -q "applyDispatchCeiling(planned" "$REPO_DIR/$f"; then
		echo "  [FAIL] $f does not apply applyDispatchCeiling() to the planned group — dispatch is unenforced"
		exit 1
	fi
done
echo "  [PASS] per-wave-workflow applies the dispatch ceiling (source + bundle)"

for f in "$NW/campaign-workflow.js" "$NW/campaign-workflow.bundled.js"; do
	if ! grep -q "dispatch: wave.dispatch" "$REPO_DIR/$f"; then
		echo "  [FAIL] $f does not thread wave.dispatch into the per-wave args — dispatch never reaches the engine"
		exit 1
	fi
done
echo "  [PASS] campaign launcher threads dispatch into per-wave args (source + bundle)"

# 3. behavioral contract (the ceiling itself)
exec node "$REPO_DIR/tests/regression/dispatch_ceiling.mjs"
