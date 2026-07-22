#!/usr/bin/env bash
# sign-oakandwave-image.sh — attach a cosign signature and a syft SBOM to the
# pushed oakandwave-workflow digest (Story 2.1 / #966, R-24).
#
# Runs after build-oakandwave-image.sh. Both provenance artifacts bind to the
# *digest*, never a moving tag, so the signature/SBOM the throwaway-CI ring
# verifies (Story 2.2, E2E-01) attest the exact bytes that were built and will be
# promoted (R-23).
#
# Keyless (Fulcio/Rekor) signing: no long-lived key material. In GitHub Actions
# this consumes the workflow's OIDC token (permissions: id-token: write). cosign
# and syft are installed by the workflow via their `uses:` installer actions; this
# script only orchestrates them, keeping the CI/CD YAML free of procedural logic.
#
# Inputs (env):
#   DIGEST_REF   the immutable pin `registry/image@sha256:…` to sign + SBOM
#                (required; build-oakandwave-image.sh emits it as `digest_ref=`).
#   COSIGN_YES   passed through as `cosign --yes` (default: true — non-interactive CI).

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

echo "==> cosign attest SBOM -> $DIGEST_REF"
cosign attest "${cosign_yes[@]}" \
	--predicate "$sbom_file" \
	--type spdxjson \
	"$DIGEST_REF"

echo "==> signature + SBOM attached to $DIGEST_REF"
