#!/usr/bin/env bash
# resolve-stable-digest.sh — resolve the GHCR :stable moving tag to its immutable
# digest (the source for the Docker Hub mirror), and derive the matching Docker Hub
# digest ref (same content-addressed sha) for the re-sign.
#
# Used by .github/workflows/oakandwave-workflow-mirror.yml. The mirror copies the
# EXACT digest (not the moving tag) so the digest signed on Docker Hub is provably
# the digest promoted on GHCR (R-23: the digest tested is the digest promoted is the
# digest published).
#
# Inputs (env):
#   GHCR_IMAGE            ghcr.io/wave-engineering/oakandwave-workflow
#   DOCKERHUB_IMAGE       docker.io/oakandwave/oakandwave-workflow
#   STABLE_TAG            the moving tag to resolve (stable)
#   STABLE_DIGEST_INPUT   test/DI seam ONLY — a pinned GHCR digest ref used verbatim as the
#                         source instead of resolving :stable. Deliberately NOT wired to any
#                         workflow input: the mirror workflow always resolves the live :stable
#                         so the public brand can never be pointed at an arbitrary/:edge digest
#                         (#1038 review). This seam only lets the resolver be unit-tested
#                         without a live registry.
# Outputs (GITHUB_OUTPUT):
#   digest_ref            the GHCR source digest ref to mirror
#   dockerhub_digest_ref  the Docker Hub digest ref to re-sign (same sha)
set -euo pipefail

: "${GHCR_IMAGE:?GHCR_IMAGE must be set}"
: "${DOCKERHUB_IMAGE:?DOCKERHUB_IMAGE must be set}"
: "${STABLE_TAG:?STABLE_TAG must be set}"

if [[ -n "${STABLE_DIGEST_INPUT:-}" ]]; then
	src_ref="$STABLE_DIGEST_INPUT"
	if [[ "$src_ref" != *"@sha256:"* ]]; then
		echo "  [!] STABLE_DIGEST_INPUT must be a digest ref (registry/image@sha256:...): $src_ref" >&2
		exit 1
	fi
else
	# Resolve the moving :stable tag to its immutable manifest digest.
	digest="$(docker buildx imagetools inspect "${GHCR_IMAGE}:${STABLE_TAG}" --format '{{.Manifest.Digest}}')"
	if [[ "$digest" != sha256:* ]]; then
		echo "  [!] could not resolve ${GHCR_IMAGE}:${STABLE_TAG} to a sha256 digest (got: '$digest')" >&2
		exit 1
	fi
	src_ref="${GHCR_IMAGE}@${digest}"
fi

# The Docker Hub copy is content-addressed identical, so it shares the same sha.
sha="${src_ref#*@}"
dockerhub_ref="${DOCKERHUB_IMAGE}@${sha}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	{
		echo "digest_ref=${src_ref}"
		echo "dockerhub_digest_ref=${dockerhub_ref}"
	} >>"$GITHUB_OUTPUT"
fi

echo "==> source (GHCR):       ${src_ref}"
echo "==> dest   (Docker Hub): ${dockerhub_ref}"
