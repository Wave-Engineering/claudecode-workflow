#!/usr/bin/env bash
#
# CI test gate (cc-workflow#795).
#
# Runs the pytest suite so the wave-engine — and all — tests are gated in CI.
# This is the STRUCTURAL fix for #753: the suite rotted to ~195 failures
# precisely because it ran nowhere in CI (validate.yml called only validate.sh,
# which is shell-only). "Config exists != config works" — gating behavior, not
# declarations.
#
# xfailed tests are non-fatal (relocated / pending-rewrite, tracked in #795);
# a genuine failure (or an unexpected error) blocks the gate.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# wave_status / campaign_status / nerf_config live under src/ with no installed
# package — mirror tests/conftest.py's PYTHONPATH injection so module-level
# `from wave_status import ...` resolves in the test process.
export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"

# The full-env-only test_install_check_clean self-skips unless CC_FULL_ENV_TESTS
# is set (skipif in tests/test_install.py, cc-workflow#795) — so it's skipped by
# default here AND on a stock dev box; no runner-level deselect needed, and the
# skip is visible in the test output with its reason.
pytest_args=(tests/ -q)

# DM-05 / DM-06 (Story 2.1, #966): when CC_TEST_REPORTS_DIR is set, additionally
# emit a JUnit XML report and (if pytest-cov is installed) an XML coverage report
# into that dir. Coverage is a COMPLETENESS SIGNAL, not a gate — no
# --cov-fail-under — so report generation never changes this script's pass/fail.
# The block is inert when the env var is unset, so the pre-push test hook and the
# stock `./scripts/ci/test.sh` invocation are byte-for-byte unchanged.
if [[ -n "${CC_TEST_REPORTS_DIR:-}" ]]; then
	mkdir -p "$CC_TEST_REPORTS_DIR"
	pytest_args+=("--junitxml=${CC_TEST_REPORTS_DIR}/junit.xml")
	if python3 -c 'import pytest_cov' >/dev/null 2>&1; then
		pytest_args+=(
			"--cov=src"
			"--cov=containers/oakandwave-workflow"
			"--cov-report=xml:${CC_TEST_REPORTS_DIR}/coverage.xml"
		)
	else
		echo "==> pytest-cov not installed — emitting JUnit only (coverage skipped)" >&2
	fi
fi

echo "==> pytest tests/ (PYTHONPATH=src)"
python3 -m pytest "${pytest_args[@]}"
