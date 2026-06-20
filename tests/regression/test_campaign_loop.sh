#!/usr/bin/env bash
# test_campaign_loop.sh — #749 deterministic campaign loop regression test.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
#   1. node --check on the pure core module + the workflow entrypoint (syntax must hold).
#   2. the pure-core unit tests: parse/rehydrate/route + the runCampaign driver advance/hold
#      behaviour via injected fakes (#749 Test Procedures). Logic lives in the sibling .mjs.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_campaign_loop"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #749 campaign-loop test"
	exit 1
fi

node --check "$REPO_DIR/skills/nextwave/campaign-loop.js"
echo "  [PASS] campaign-loop.js syntax (node --check)"
node --check "$REPO_DIR/skills/nextwave/campaign-workflow.js"
echo "  [PASS] campaign-workflow.js syntax (node --check)"

exec node "$REPO_DIR/tests/regression/campaign_loop.mjs"
