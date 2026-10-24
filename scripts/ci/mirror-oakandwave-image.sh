#!/usr/bin/env bash
# mirror-oakandwave-image.sh — copy the promoted GHCR digest to Docker Hub as :stable
# AND as its immutable :X.Y.Z version tag (#1324).
#
# Used by .github/workflows/oakandwave-workflow-mirror.yml, after resolve-stable-digest.sh.
# Before #1324 the mirror pushed :stable alone, so once :stable moved, the previous
# release's digest had no name on Docker Hub.
#
# The version comes from the image's own org.opencontainers.image.version label, not from
# a workflow input: the workflow stays input-free, so the public brand still can't be
# pointed at an arbitrary digest (#1038 review).
#
# Only a release is mirrored: a :stable whose label isn't X.Y.Z (a branch build promoted by
# hand reads like 8.14.0-3-g9334c4b) exits 1, and Docker Hub keeps its previous :stable.
#
# The copy itself is the shared oaw-mirror-image action's core (#1326), which the fleet's
# other images use too: a version tag is pushed only when absent, skipped when it already
# names this digest, and refused (nothing pushed) when it names another or can't be read.
#
# Inputs (env):
#   SRC_DIGEST       the GHCR digest ref to mirror (registry/image@sha256:...)
#   DOCKERHUB_IMAGE  docker.io/oakandwave/oakandwave-workflow
#   STABLE_TAG       stable
# It touches no GitHub release: the workflow's release-notes job does, after the re-sign.
# Outputs (GITHUB_OUTPUT):
#   version          the X.Y.Z read off the image
#   version_ref      DOCKERHUB_IMAGE:X.Y.Z@sha256:... (also written to GITHUB_STEP_SUMMARY)
set -euo pipefail

: "${SRC_DIGEST:?SRC_DIGEST must be set}"
: "${DOCKERHUB_IMAGE:?DOCKERHUB_IMAGE must be set}"
: "${STABLE_TAG:?STABLE_TAG must be set}"

digest="${SRC_DIGEST#*@}"
if [[ "$SRC_DIGEST" != *"@sha256:"* || ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "  [!] SRC_DIGEST must be a digest ref (registry/image@sha256:...): $SRC_DIGEST" >&2
	exit 1
fi

# The label, from every platform's config. A single-platform image's .Image is one config;
# an index's is a map of platform -> config. Every platform must carry the same version.
version="$(docker buildx imagetools inspect "$SRC_DIGEST" --format '{{json .Image}}' |
	jq -er '
		(if has("config") then [.] else [.[]] end)
		| map(.config.Labels["org.opencontainers.image.version"] // "")
		| unique
		| if length == 1 then .[0] else error("platforms disagree on the version label") end
	')" || {
	echo "  [!] could not read org.opencontainers.image.version off $SRC_DIGEST" >&2
	exit 1
}
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "  [!] $SRC_DIGEST has version label '$version', not X.Y.Z: only a release is mirrored" >&2
	exit 1
fi

core="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)/.github/actions/oaw-mirror-image/oaw-mirror-image.sh"
SOURCE_DIGEST_REF="$SRC_DIGEST" \
	TAGS="$(printf '%s\n%s\n' "$STABLE_TAG" "$version")" \
	DEST_IMAGE="$DOCKERHUB_IMAGE" \
	IMMUTABLE_TAG_REGEX='^[0-9]+\.[0-9]+\.[0-9]+$' \
	bash "$core"

version_ref="${DOCKERHUB_IMAGE}:${version}@${digest}"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	{
		echo "version=${version}"
		echo "version_ref=${version_ref}"
	} >>"$GITHUB_OUTPUT"
fi
echo "==> release image: ${version_ref}"
