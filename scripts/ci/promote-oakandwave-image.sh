#!/usr/bin/env bash
# promote-oakandwave-image.sh — the mechanical promotion gate + exact-digest
# retag (Story 2.3 / #968, Dev Spec §4.4 / §5.6, R-07/R-23).
#
# Promotion is a two-part contract:
#
#   1. A mechanical conjunction over FlightDeck + CI must be green — throwaway-CI
#      E2E-01 pass, dogfood soak met, zero quarantines, zero open Sev-1 (R-07).
#   2. The operator ACK confirms the green gate; promotion then retags the EXACT
#      digest E2E-01 tested `:edge → :stable` — no rebuild, same bytes (R-23).
#
# The DECISION lives in the unit-tested gate module
# (containers/oakandwave-workflow/promotion_gate.py): this wrapper only *gathers*
# the four signals and, on a green+ACK'd verdict, performs the retag. Keeping the
# conjunction in Python (not in this shell, and never in CI/CD YAML) is what makes
# "no code path promotes without all conditions green" a tested guarantee.
#
# Fail-closed: any signal that is missing, unknown, or malformed is RED. A red
# gate — or a green gate with no ACK — exits non-zero and retags nothing. The ACK
# can only confirm an already-green gate; it can never substitute for a red
# condition (PC-6: promotion is mechanical, not a feeling).
#
# Signals (env). The soak / quarantine / Sev-1 conditions are FlightDeck (#854)
# telemetry; the throwaway-CI condition is E2E-01's result. Each is injected here
# so a caller (the E2E-02 promotion cycle, or the operator runbook) supplies them
# from the live sources. An optional GATE_SIGNALS_CMD DI-seam (mirrors the emit
# script's FLIGHTDECK_EMIT_CMD) is sourced first to populate them from a
# FlightDeck query; if it is unset or yields nothing, the corresponding condition
# stays RED.
#
#   DIGEST_REF          the candidate digest to promote, registry/image@sha256:…
#                       (required; the build job emits it, the ring tests it).
#   OPERATOR_ACK        "true" ⇒ the operator confirms the green gate (default:
#                       false ⇒ no promotion even when the gate is green).
#   GATE_SIGNALS_CMD    optional command emitting `KEY=VALUE` lines (a FlightDeck
#                       query seam); its output is sourced before reading signals.
#   OAW_SOAK_LEDGER     optional path to the soak `.jsonl` ledger. When set (and
#   OAW_QUARANTINE_LEDGER  GATE_SIGNALS_CMD is unset), the gate's SOAK_HOURS /
#                       QUARANTINE_COUNT are computed from these ledgers through the
#                       PROFILE FILTER (containers/oakandwave-workflow/profiles.py):
#                       dev-mode runs and breakages are excluded, so they never
#                       accrue soak nor trip the zero-quarantines condition (R-22 —
#                       the gate half of the profile filter; the surgeon is the
#                       probe half). This is how "the gate filters on the label" is
#                       wired end-to-end, not merely available as a library.
#   THROWAWAY_CI_PASSED E2E-01 smoke result for DIGEST_REF (true/false).
#   THROWAWAY_CI_DIGEST the digest E2E-01 tested (defaults to DIGEST_REF; the gate
#                       still requires it to equal the promotion target — R-23).
#   SOAK_HOURS          accrued dogfood soak hours.
#   SOAK_REQUIRED_HOURS soak hours required (default 24).
#   QUARANTINE_COUNT    quarantines during soak (0 to pass).
#   OPEN_SEV1_COUNT     open Sev-1 (0 to pass).
#   STABLE_TAG          moving tag to publish (default: stable).
#   PROMOTE_DRY_RUN     "true" ⇒ evaluate the gate + print the retag, do NOT push.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
GATE_PY="$REPO_DIR/containers/oakandwave-workflow/promotion_gate.py"

: "${DIGEST_REF:?DIGEST_REF must be set (registry/image@sha256:...)}"

PROFILES_PY="$REPO_DIR/containers/oakandwave-workflow/profiles.py"

# --- Profile-filtered telemetry: the gate half of R-22 ------------------------
# When soak/quarantine ledgers are supplied and no explicit GATE_SIGNALS_CMD is
# set, default the signal seam to the profile filter: profiles.py folds the
# ledgers into SOAK_HOURS / QUARANTINE_COUNT while EXCLUDING dev-mode records, so
# a dev-mode session cannot inflate soak and a dev-mode breakage cannot fail the
# gate (R-22). Explicitly-set GATE_SIGNALS_CMD wins (an operator can still inject
# a live FlightDeck query).
if [[ -z "${GATE_SIGNALS_CMD:-}" && (-n "${OAW_SOAK_LEDGER:-}" || -n "${OAW_QUARANTINE_LEDGER:-}") ]]; then
	GATE_SIGNALS_CMD="python3 $(printf '%q' "$PROFILES_PY") --emit gate-signals"
	[[ -n "${OAW_SOAK_LEDGER:-}" ]] && GATE_SIGNALS_CMD+=" --soak-ledger $(printf '%q' "$OAW_SOAK_LEDGER")"
	[[ -n "${OAW_QUARANTINE_LEDGER:-}" ]] && GATE_SIGNALS_CMD+=" --quarantine-ledger $(printf '%q' "$OAW_QUARANTINE_LEDGER")"
fi

# --- Optional FlightDeck-query seam: populate signal env from its KV output ---
if [[ -n "${GATE_SIGNALS_CMD:-}" ]]; then
	while IFS= read -r kv; do
		[[ "$kv" == *=* ]] || continue
		export "${kv?}"
	done < <(eval "$GATE_SIGNALS_CMD" || true)
fi

# --- Assemble the gate CLI invocation (fail-closed: omit ⇒ the gate reads red) -
gate_args=(--target-digest "$DIGEST_REF")

[[ -n "${THROWAWAY_CI_PASSED:-}" ]] && gate_args+=(--ci-passed "$THROWAWAY_CI_PASSED")
# The digest E2E-01 tested defaults to the promotion target; the gate still
# enforces they are equal (R-23), so a caller cannot silently widen this.
gate_args+=(--ci-digest "${THROWAWAY_CI_DIGEST:-$DIGEST_REF}")
[[ -n "${SOAK_HOURS:-}" ]] && gate_args+=(--soak-hours "$SOAK_HOURS")
gate_args+=(--soak-required-hours "${SOAK_REQUIRED_HOURS:-24}")
[[ -n "${QUARANTINE_COUNT:-}" ]] && gate_args+=(--quarantines "$QUARANTINE_COUNT")
[[ -n "${OPEN_SEV1_COUNT:-}" ]] && gate_args+=(--open-sev1 "$OPEN_SEV1_COUNT")
[[ "${OPERATOR_ACK:-false}" == "true" ]] && gate_args+=(--ack)

echo "==> evaluating the mechanical promotion gate for $DIGEST_REF"

# The gate CLI prints the digest-to-promote on stdout and exits 0 ONLY when the
# conjunction is green AND the ACK confirms it; otherwise it exits non-zero and
# prints the red summary to stderr. `set -e` turns a red gate into a hard stop,
# so nothing below (the retag) runs unless the gate said promote.
promoted_digest="$(python3 "$GATE_PY" "${gate_args[@]}")"

if [[ -z "$promoted_digest" ]]; then
	echo "  [!] gate returned no digest — refusing to promote" >&2
	exit 1
fi

# Belt-and-suspenders (R-23): the digest we retag must be the digest the gate
# blessed, which is the digest E2E-01 tested. They are the same object; assert it.
if [[ "$promoted_digest" != "$DIGEST_REF" ]]; then
	echo "  [!] gate blessed $promoted_digest but target is $DIGEST_REF — aborting" >&2
	exit 1
fi

# --- Retag the EXACT digest :edge → :stable — no rebuild (R-07/R-23) -----------
# `docker buildx imagetools create --tag <repo>:stable <repo>@sha256:…` points the
# moving :stable tag at the *same manifest digest*. Because the digest is
# unchanged, the cosign signature and syft SBOM (both digest-bound) remain valid
# for :stable — the fleet pulls the exact bytes E2E-01 tested and the operator
# ACK'd.
image_repo="${promoted_digest%@*}"
stable_ref="${image_repo}:${STABLE_TAG:-stable}"

if [[ "${PROMOTE_DRY_RUN:-false}" == "true" ]]; then
	echo "==> [dry-run] would retag $promoted_digest → $stable_ref"
	exit 0
fi

command -v docker >/dev/null 2>&1 || {
	echo "  [!] docker not found — needed to retag the digest to :stable" >&2
	exit 1
}

echo "==> promote: retag $promoted_digest → $stable_ref (exact digest, no rebuild)"
docker buildx imagetools create --tag "$stable_ref" "$promoted_digest"

echo "==> promoted: $stable_ref now points at the digest E2E-01 tested"
