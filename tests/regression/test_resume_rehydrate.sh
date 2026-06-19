#!/usr/bin/env bash
# test_resume_rehydrate.sh — #686 resumability + idempotency seam regression test.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Two assertions for the #686 seam:
#   1. node --check on the seam helper + the workflow that imports it (syntax must hold).
#   2. the rehydrate/idempotency round-trip: mid-run loop state → blob → rehydrate → equal
#      (skip-on-resume), idempotent reseed (fixed point), corrupt-blob → safe cold start, and
#      the idempotent worktree-setup + 3-point-cleanup git-command shapes. Logic lives in the
#      sibling .mjs.
#
# What this CANNOT cover (needs a live sdlc-server): the full live kill-and-resume integration
# test. The HOW-TO for that manual gate is documented at the bottom of the sibling .mjs.
#
# Implementation of (2): tests/regression/resume_rehydrate_roundtrip.mjs

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

echo "test_resume_rehydrate"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #686 resume + idempotency test"
	exit 1
fi

node --check "$REPO_DIR/skills/nextwave/resume.js"
echo "  [PASS] resume.js syntax (node --check)"
node --check "$REPO_DIR/skills/nextwave/per-wave-workflow.js"
echo "  [PASS] per-wave-workflow.js syntax (node --check)"

exec node "$REPO_DIR/tests/regression/resume_rehydrate_roundtrip.mjs"
