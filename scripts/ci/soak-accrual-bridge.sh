#!/usr/bin/env bash
# soak-accrual-bridge.sh — accrue dogfood soak from the LIVE :edge ring (#1008).
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
# session, so a re-run counts only NEW clean time — never a double-count). Pass
# SOAK_BRIDGE_DRY_RUN=true to preview the observations without writing the ledger.
#
# Inputs (env):
#   OAW_SOAK_LEDGER           soak .jsonl ledger to append (default ~/.oaw/soak/ledger.jsonl).
#   SURGEON_TRANSCRIPTS_ROOT  root the surgeon resolves host-backed transcripts under
#                             (default ~/.claude/projects).
#   SOAK_BRIDGE_DRY_RUN       "true" ⇒ build + print observations, write nothing.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BRIDGE_PY="$HERE/soak_accrual_bridge.py"

OAW_SOAK_LEDGER="${OAW_SOAK_LEDGER:-$HOME/.oaw/soak/ledger.jsonl}"
SURGEON_TRANSCRIPTS_ROOT="${SURGEON_TRANSCRIPTS_ROOT:-$HOME/.claude/projects}"

cmd=(python3 "$BRIDGE_PY" --ledger "$OAW_SOAK_LEDGER" --transcripts-root "$SURGEON_TRANSCRIPTS_ROOT")
[[ "${SOAK_BRIDGE_DRY_RUN:-false}" == "true" ]] && cmd+=(--dry-run)

exec "${cmd[@]}"
