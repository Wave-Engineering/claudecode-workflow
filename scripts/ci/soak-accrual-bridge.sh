#!/usr/bin/env bash
# soak-accrual-bridge.sh — accrue dogfood soak from the LIVE :edge ring (#1008).
#
# NO LONGER GATES PROMOTION (#1106). Soak was removed from the mechanical gate:
# this bridge credits only sessions running at the instant of a pass, so a missed
# cron window silently discarded real runtime — the metric measured "was the
# recorder running", not "did this soak". Measured live: the fleet ran containers
# for well over 24h and a 48h look-back credited ZERO, because the bridge had
# never been scheduled and cannot backfill.
#
# The ledger it writes is retained as TELEMETRY (FlightDeck, #854) and the
# profile filter (R-22) still applies. Nothing refuses a promotion on it. If you
# are reading this while trying to make a promotion go green, you are in the
# wrong file — see containers/oakandwave-workflow/promotion_gate.py.
#
# The operator/cron entrypoint that closes the FlightDeck soak loop: it drives the
# flight surgeon over the live aoe sessions and feeds each running dogfood session's
# clean span to the soak ledger the promotion gate reads. Run it periodically during
# a dogfood cutover (or from the cutover supervisor) so `SOAK_HOURS` fills over time
# and `:edge` can auto-promote to `:stable` (R-07/R-08).
#
# ALL logic lives in the tested Python module (project rule — no procedural logic in
# shell/CI YAML): this wrapper only resolves env defaults and execs it. The decisions
# it composes are each unit-proven:
#   * health verdict (running/broken/profile)  — scripts/flight-surgeon/surgeon.py
#   * clean-span → soak record                 — containers/oakandwave-workflow/soak_ledger.py
#   * gather → map → accrue                     — scripts/ci/soak_accrual_bridge.py
#
# SAFETY: accrual is non-destructive and idempotent (soak_ledger watermarks per
# session, so a re-run counts only NEW clean time — never a double-count). Each pass
# credits at most OAW_SOAK_LOOKBACK_HOURS of time, verified clean at "now", so a
# point-in-time health verdict never back-credits un-sampled history or a broken gap
# (see soak_accrual_bridge.py). Pass SOAK_BRIDGE_DRY_RUN=true to preview without writing.
#
# Inputs (env):
#   OAW_SOAK_LEDGER           soak .jsonl ledger to append (default ~/.oaw/soak/ledger.jsonl).
#   OAW_MAJOR                 kit major partitioning sandbox state. DERIVED from the
#                             repo tag via scripts/ci/oaw-major.sh (#1067); no literal
#                             default — a hardcoded major fails silently as empty state.
#   SURGEON_TRANSCRIPTS_ROOT  root the surgeon resolves host-backed SANDBOX transcripts
#                             under (default ~/.oaw/state/$OAW_MAJOR/transcripts). It
#                             must NOT be ~/.claude/projects — that is the live fleet's
#                             store, and the surgeon refuses it (#1064).
#   OAW_SOAK_LOOKBACK_HOURS   bounded per-pass look-back in hours (default 1). SET THIS
#                             TO YOUR CRON CADENCE: it must be >= the interval between
#                             runs (else clean time between passes is under-credited),
#                             and ~= the cadence (a much larger value widens the broken
#                             gap a recovery pass can reach back over). Read by the
#                             Python module via the environment — propagates through exec.
#   SOAK_BRIDGE_DRY_RUN       "true" ⇒ build + print observations, write nothing.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_PY="$HERE/soak_accrual_bridge.py"

OAW_SOAK_LEDGER="${OAW_SOAK_LEDGER:-$HOME/.oaw/soak/ledger.jsonl}"
# Sandbox transcripts, NOT the fleet's ~/.claude/projects — the surgeon refuses
# that root (#1064) and this loop would exit non-zero and accrue ZERO soak,
# defeating #1008. Mirrors dogfood-cutover.sh.
OAW_MAJOR="${OAW_MAJOR:-$("$(dirname "${BASH_SOURCE[0]}")/oaw-major.sh")}"
export OAW_MAJOR # surgeon.py narrows DEFAULT_TRANSCRIPTS_ROOT from this
SURGEON_TRANSCRIPTS_ROOT="${SURGEON_TRANSCRIPTS_ROOT:-$HOME/.oaw/state/$OAW_MAJOR/transcripts}"

cmd=(python3 "$BRIDGE_PY" --ledger "$OAW_SOAK_LEDGER" --transcripts-root "$SURGEON_TRANSCRIPTS_ROOT")
[[ "${SOAK_BRIDGE_DRY_RUN:-false}" == "true" ]] && cmd+=(--dry-run)

exec "${cmd[@]}"
