#!/usr/bin/env bash
# oaw-sign-image.sh — the fleetwide reusable core of OaW image signing: a keyless
# cosign signature + (optionally) a syft SBOM attestation, both bound to an immutable
# digest. Bundled inside the `oaw-sign-image` composite action so any OaW repo can sign
# via a SHA-pinned `uses:` without copy-pasting this logic. Generalized from cc-workflow's
# scripts/ci/sign-oakandwave-image.sh (#966/#995).
#
# Inputs (env — supplied by action.yml):
#   DIGEST_REF     registry/image@sha256:… to sign (required; never a moving tag — R-23).
#   ATTACH_SBOM    "true" (default) ⇒ also generate + attest a syft SPDX SBOM.
#   SBOM_TLOG      "true" (default) ⇒ upload the SBOM attestation to the public rekor tlog.
#                  "false" ⇒ keep the SBOM OFF rekor and bind an RFC3161 TSA timestamp
#                  instead — needed only when the SBOM predicate exceeds rekor's request
#                  body ceiling (large images, e.g. cc-workflow's ~10 GB image, #995). The
#                  SIGNATURE itself always goes to rekor (small, publicly transparent).
#   TSA_SERVER_URL RFC3161 TSA endpoint used when SBOM_TLOG=false
#                  (default: https://timestamp.sigstore.dev/api/v1/timestamp).
#   COSIGN_YES     "true" (default) ⇒ cosign --yes (non-interactive CI).
set -euo pipefail

: "${DIGEST_REF:?DIGEST_REF must be set (registry/image@sha256:...)}"

if [[ "$DIGEST_REF" != *"@sha256:"* ]]; then
	echo "  [!] refusing to sign a non-digest ref: $DIGEST_REF" >&2
	echo "      (sign the immutable digest, never a moving tag — R-23)" >&2
	exit 1
fi

command -v cosign >/dev/null 2>&1 || {
	echo "  [!] cosign not found on PATH — the composite action installs it" >&2
	exit 1
}

cosign_yes=()
[[ "${COSIGN_YES:-true}" == "true" ]] && cosign_yes=(--yes)

# --- cosign: keyless signature attached to the digest (always to rekor) -------
echo "==> cosign sign (keyless) $DIGEST_REF"
cosign sign "${cosign_yes[@]}" "$DIGEST_REF"

# --- syft SBOM + cosign attest (optional; rekor or TSA per SBOM_TLOG) ----------
if [[ "${ATTACH_SBOM:-true}" == "true" ]]; then
	command -v syft >/dev/null 2>&1 || {
		echo "  [!] syft not found on PATH (ATTACH_SBOM=true) — the composite action installs it" >&2
		exit 1
	}
	sbom_file="$(mktemp -t oaw-sbom.XXXXXX.spdx.json)"
	trap 'rm -f "$sbom_file"' EXIT

	echo "==> syft SBOM (spdx-json) for $DIGEST_REF"
	syft "$DIGEST_REF" -o spdx-json="$sbom_file"

	attest_args=(--predicate "$sbom_file" --type spdxjson)
	if [[ "${SBOM_TLOG:-true}" == "true" ]]; then
		echo "==> cosign attest SBOM -> $DIGEST_REF (public rekor tlog)"
	else
		# Large-image path (#995): SBOM predicate exceeds rekor's body ceiling, so keep it
		# off the public tlog and bind a trusted RFC3161 TSA timestamp instead.
		echo "==> cosign attest SBOM -> $DIGEST_REF (TSA-timestamped, off the public rekor tlog)"
		attest_args+=(--tlog-upload=false)
		attest_args+=(--timestamp-server-url="${TSA_SERVER_URL:-https://timestamp.sigstore.dev/api/v1/timestamp}")
	fi
	cosign attest "${cosign_yes[@]}" "${attest_args[@]}" "$DIGEST_REF"
fi

sbom_note="no SBOM"
if [[ "${ATTACH_SBOM:-true}" == "true" ]]; then
	sbom_note="SBOM=$([[ "${SBOM_TLOG:-true}" == "true" ]] && echo rekor || echo TSA)"
fi
echo "==> signed $DIGEST_REF (signature=rekor, ${sbom_note})"
