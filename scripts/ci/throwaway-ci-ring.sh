#!/usr/bin/env bash
# throwaway-ci-ring.sh — the E2E-01 throwaway-CI ring (Story 2.2 / #967,
# Dev Spec §6.3, R-05/R-23/R-24).
#
# Pull the candidate FROM THE REGISTRY BY DIGEST — never a local build (R-23) —
# verify its provenance (OCI labels + registry permissions + cosign signature +
# syft SBOM), install from zero, run the smoke suite, tear down. Any verification
# or smoke failure exits non-zero, which fails the digest and blocks it from
# promotion (R-05/R-23).
#
# Ordering is load-bearing (R-24, AC2): every provenance check — signature, SBOM,
# pullability/permissions, labels — runs BEFORE the smoke suite. Signature and
# SBOM are verified registry-side first, so we never pull bytes we have not
# attested; the pull that follows is both the permissions proof and the
# install-from-zero (a fresh registry pull, no local build in sight).
#
# This is the automated companion to the operator runbook
# docs/contained-workflow/deployment-verification.md (DM-12), which performs the
# same §1–§5 checks by hand. Keep the two in step.
#
# All ring logic lives here, not in the workflow YAML (project rule: No Procedural
# Logic in CI/CD YAML); .github/workflows/oakandwave-workflow-image.yml calls this
# in one line from the `smoke` job (needs: build).
#
# Inputs (env):
#   DIGEST_REF                  the immutable pin registry/image@sha256:… to test
#                               (required; the build job emits it as digest_ref).
#   COSIGN_CERT_IDENTITY_REGEXP cosign --certificate-identity-regexp: the workflow
#                               identity that must have signed the digest. Default
#                               derives from GITHUB_REPOSITORY (the image workflow
#                               path). A bare verify that ignores identity is not
#                               sufficient — anyone can sign a public digest.
#   COSIGN_OIDC_ISSUER          cosign --certificate-oidc-issuer (default: GitHub
#                               Actions OIDC).
#   SMOKE_SUITE                 pytest target for the smoke suite (default: the
#                               image toolchain oracle tests/contained-workflow/
#                               test_image.py). Run with OAKANDWAVE_REQUIRE_IMAGE
#                               so a missing/broken image is a hard fail, never a
#                               silent skip — that is what makes a red smoke block
#                               the digest.
#   RING_SKIP_TEARDOWN          "true" leaves the pulled image in place (debug).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"

# --- 0. Guard: a real registry DIGEST, never a local build (R-23) -------------
# This runs before any tool is required, so the guard is unit-testable without
# docker/cosign present.
: "${DIGEST_REF:?DIGEST_REF must be set (registry/image@sha256:...)}"

if [[ "$DIGEST_REF" != *"@sha256:"* ]]; then
	echo "  [!] refusing to test a non-digest ref: $DIGEST_REF" >&2
	echo "      E2E-01 tests the registry artifact BY DIGEST, never a local" >&2
	echo "      build or a moving tag (R-23)." >&2
	exit 1
fi

repo_slug="${GITHUB_REPOSITORY:-Wave-Engineering/claudecode-workflow}"
cert_identity_regexp="${COSIGN_CERT_IDENTITY_REGEXP:-https://github.com/${repo_slug}/.github/workflows/oakandwave-workflow-image.yml@.*}"
oidc_issuer="${COSIGN_OIDC_ISSUER:-https://token.actions.githubusercontent.com}"
smoke_suite="${SMOKE_SUITE:-$REPO_DIR/tests/contained-workflow/test_image.py}"

# --- Required tooling ---------------------------------------------------------
for tool in docker cosign python3; do
	command -v "$tool" >/dev/null 2>&1 || {
		echo "  [!] $tool not found on PATH — the ring needs it" >&2
		exit 1
	}
done

# --- Teardown: drop the pulled candidate on any exit (install-from-zero means
# nothing lingers between runs) ------------------------------------------------
teardown() {
	[[ "${RING_SKIP_TEARDOWN:-false}" == "true" ]] && return 0
	docker image rm "$DIGEST_REF" >/dev/null 2>&1 || true
}
trap teardown EXIT

echo "==> E2E-01 throwaway-CI ring against $DIGEST_REF"

# --- 1. cosign signature (R-24) — verified registry-side, before we pull ------
# Identity-bound: the signer must be THIS repo's image workflow via GitHub OIDC.
echo "[ring] verify-signature (cosign, identity-bound)"
cosign verify \
	--certificate-identity-regexp "$cert_identity_regexp" \
	--certificate-oidc-issuer "$oidc_issuer" \
	"$DIGEST_REF" >/dev/null

# --- 2. syft SBOM (R-24) — SPDX attestation bound to the digest ---------------
echo "[ring] verify-sbom (cosign attestation, spdxjson)"
cosign verify-attestation \
	--type spdxjson \
	--certificate-identity-regexp "$cert_identity_regexp" \
	--certificate-oidc-issuer "$oidc_issuer" \
	"$DIGEST_REF" >/dev/null

# --- 3. registry permissions + install-from-zero (R-24) -----------------------
# A successful pull from a clean local store proves the candidate is
# fleet-pullable AND installs the release from zero (the image digest IS the
# release, R-05) — no local build involved (R-23).
echo "[ring] verify-pullable (docker pull — permissions + install-from-zero)"
docker pull "$DIGEST_REF" >/dev/null

# --- 4. OCI provenance labels (R-24) ------------------------------------------
# All four provenance facts — semver, source, revision, created — present and
# non-empty on the PULLED image (the same producer test_provenance.py checks).
echo "[ring] verify-labels (OCI provenance)"
labels_json="$(docker image inspect --format '{{json .Config.Labels}}' "$DIGEST_REF")"
missing=()
for key in \
	org.opencontainers.image.version \
	org.opencontainers.image.source \
	org.opencontainers.image.revision \
	org.opencontainers.image.created; do
	value="$(printf '%s' "$labels_json" | python3 -c 'import json,sys; print((json.load(sys.stdin) or {}).get(sys.argv[1]) or "")' "$key")"
	[[ -n "$value" ]] || missing+=("$key")
done
if [[ ${#missing[@]} -gt 0 ]]; then
	echo "  [!] missing/empty OCI provenance label(s): ${missing[*]}" >&2
	echo "      labels on digest: $labels_json" >&2
	exit 1
fi

# --- 5. smoke suite (R-05) — ONLY after every provenance check has passed -----
# The smoke suite is the image toolchain oracle run against the pulled DIGEST.
# OAKANDWAVE_REQUIRE_IMAGE turns a missing/broken image into a hard failure
# (never a skip), so a red smoke reliably blocks the digest from promotion.
echo "[ring] smoke (install-from-zero toolchain oracle against the digest)"
OAKANDWAVE_IMAGE="$DIGEST_REF" \
	OAKANDWAVE_REQUIRE_IMAGE=1 \
	python3 -m pytest "$smoke_suite" -q

echo "==> ring PASS: $DIGEST_REF is provenance-clean and smoked green"
