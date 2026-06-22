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

echo "==> pytest tests/ (PYTHONPATH=src)"
python3 -m pytest tests/ -q
