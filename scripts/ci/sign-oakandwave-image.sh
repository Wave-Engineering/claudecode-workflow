#!/usr/bin/env bash
# sign-oakandwave-image.sh — attach a cosign signature and a syft SBOM to the
# pushed oakandwave-workflow digest (Story 2.1 / #966, R-24).
#
# Runs after build-oakandwave-image.sh. Both provenance artifacts bind to the
# *digest*, never a moving tag, so the signature/SBOM the throwaway-CI ring
# verifies (Story 2.2, E2E-01) attest the exact bytes that were built and will be
# promoted (R-23).
#
# Keyless (Fulcio) signing: no long-lived key material. In GitHub Actions this
# consumes the workflow's OIDC token (permissions: id-token: write). The image
# SIGNATURE goes to the public rekor tlog (small, publicly auditable); the syft
# SBOM ATTESTATION is bound to an RFC3161 TSA timestamp and kept OFF the public
# tlog (its predicate exceeds rekor's body limit for a ~10 GB image — #995).
# cosign and syft are installed by the workflow via their `uses:` installer
# actions (cosign pinned to v2.x — see the workflow — because v3 dropped the
# --tlog-upload lever); this script only orchestrates them, keeping the CI/CD
# YAML free of procedural logic.
#
# Inputs (env):
#   DIGEST_REF       the immutable pin `registry/image@sha256:…` to sign + SBOM
#                    (required; build-oakandwave-image.sh emits it as `digest_ref=`).
#   COSIGN_YES       passed through as `cosign --yes` (default: true — non-interactive CI).
#   TSA_SERVER_URL   RFC3161 TSA endpoint for the SBOM attestation timestamp
#                    (default: https://timestamp.sigstore.dev/api/v1/timestamp).

set -euo pipefail

: "${DIGEST_REF:?DIGEST_REF must be set (registry/image@sha256:...)}"

if [[ "$DIGEST_REF" != *"@sha256:"* ]]; then
	echo "  [!] refusing to sign a non-digest ref: $DIGEST_REF" >&2
	echo "      (sign the immutable digest, never a moving tag — R-23)" >&2
	exit 1
fi

for tool in cosign syft; do
	command -v "$tool" >/dev/null 2>&1 || {
		echo "  [!] $tool not found on PATH — install it before signing" >&2
		exit 1
	}
done

cosign_yes=()
[[ "${COSIGN_YES:-true}" == "true" ]] && cosign_yes=(--yes)

# --- cosign: keyless signature attached to the digest -------------------------
echo "==> cosign sign (keyless) $DIGEST_REF"
cosign sign "${cosign_yes[@]}" "$DIGEST_REF"

# --- syft: generate an SPDX SBOM, cosign: attest it to the digest -------------
sbom_file="$(mktemp -t oakandwave-sbom.XXXXXX.spdx.json)"
trap 'rm -f "$sbom_file"' EXIT

echo "==> syft SBOM (spdx-json) for $DIGEST_REF"
syft "$DIGEST_REF" -o spdx-json="$sbom_file"

# The SBOM predicate for this ~10 GB image exceeds rekor.sigstore.dev's request
# body ceiling, so uploading it to the PUBLIC transparency log fails on every run
# (#995 — the image workflow had never gone green). R-24 requires the SBOM be
# attached to the digest and verifiable by the ring — NOT that it live in the
# public tlog — so skip rekor (--tlog-upload=false) and bind a trusted RFC3161
# timestamp from Sigstore's public TSA instead. The signature above stays in
# rekor (small, publicly transparent); only the bulky SBOM attestation moves off
# it. The ring's verify-attestation matches: --insecure-ignore-tlog +
# --use-signed-timestamps against the TSA cert chain.
echo "==> cosign attest SBOM -> $DIGEST_REF (TSA-timestamped, off the public rekor tlog)"
cosign attest "${cosign_yes[@]}" \
	--predicate "$sbom_file" \
	--type spdxjson \
	--tlog-upload=false \
	--timestamp-server-url="${TSA_SERVER_URL:-https://timestamp.sigstore.dev/api/v1/timestamp}" \
	"$DIGEST_REF"

echo "==> signature (rekor) + SBOM (TSA) attached to $DIGEST_REF"
