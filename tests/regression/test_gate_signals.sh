#!/usr/bin/env bash
# test_gate_signals.sh — #687 trust-gate seam regression test.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Two assertions for the #687 seam:
#   1. node --check on the gate helper + the workflow that imports it (syntax must hold).
#   2. the gate-signal invariants: conservativeFail HOLDs (never silent PASS), each signal
#      prompt names its real sdlc-server tool + pass predicate (diff-scoped), the CI signal
#      accepts the GitHub merge-queue shape (#452), and promotion is wave_finalize →
#      pr_merge(skip_train) → delete-branch. Logic lives in the sibling .mjs.
#
# Implementation of (2): tests/regression/gate_signals_roundtrip.mjs

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_gate_signals"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #687 trust-gate test"
	exit 1
fi

node --check "$REPO_DIR/skills/nextwave/gate.js"
echo "  [PASS] gate.js syntax (node --check)"
node --check "$REPO_DIR/skills/nextwave/per-wave-workflow.js"
echo "  [PASS] per-wave-workflow.js syntax (node --check)"

exec node "$REPO_DIR/tests/regression/gate_signals_roundtrip.mjs"
