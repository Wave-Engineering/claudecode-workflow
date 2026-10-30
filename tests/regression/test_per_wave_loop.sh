#!/usr/bin/env bash
# test_per_wave_loop.sh — the per-wave Workflow's loop and gate, executed (#1210).
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Runs the BUNDLED per-wave Workflow under node with stubbed agents (per_wave_harness.mjs) and pins
# that a failed plan or reconcile agent is a legal exit (gate SKIPPED, a named haltReason, a held
# terminal record), not a TypeError, and that every other dereferenced agent result tolerates null.
#
# Implementation: tests/regression/per_wave_loop.mjs

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_per_wave_loop"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #1210 per-wave loop test"
	exit 1
fi

node "$REPO_DIR/scripts/ci/wf-syntax-check.mjs" "$REPO_DIR/skills/nextwave/per-wave-workflow.bundled.js"
echo "  [PASS] per-wave-workflow.bundled.js syntax (wf-syntax-check)"

exec node "$REPO_DIR/tests/regression/per_wave_loop.mjs"
