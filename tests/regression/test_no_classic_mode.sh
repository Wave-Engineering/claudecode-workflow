#!/usr/bin/env bash
# test_no_classic_mode.sh — regression test for cc-workflow#580.
#
# Wraps scripts/ci/check-no-classic-mode.sh and reports its result in the
# regression-test pass executed by scripts/ci/validate.sh. Validation
# pipelines call this file (matched by tests/regression/*.sh in
# validate.sh's "Regression tests" loop), which in turn calls the shared
# implementation. Keeping the implementation in scripts/ci/ means the same
# script can be invoked manually or from any other workflow without going
# through the test harness.
#
# Implementation: see scripts/ci/check-no-classic-mode.sh.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

exec bash "$REPO_DIR/scripts/ci/check-no-classic-mode.sh"
