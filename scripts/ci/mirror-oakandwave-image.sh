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
# A version tag is never re-pushed. Read it first:
#   absent ("not found")    -> push it with :stable, in the same imagetools create
#   already on this digest  -> skip it (an idempotent rerun); :stable is still pushed
#   on any other digest     -> exit 1 and push nothing
#   unreadable (any other inspect error) -> exit 1: absent and present can't be told apart
#
# Inputs (env):
#   SRC_DIGEST       the GHCR digest ref to mirror (registry/image@sha256:...)
#   DOCKERHUB_IMAGE  docker.io/oakandwave/oakandwave-workflow
#   STABLE_TAG       stable
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

version_tag="${DOCKERHUB_IMAGE}:${version}"
tags=(--tag "${DOCKERHUB_IMAGE}:${STABLE_TAG}")
if inspect_out="$(docker buildx imagetools inspect "$version_tag" --format '{{json .Manifest}}' 2>&1)"; then
	existing="$(jq -er '.digest' <<<"$inspect_out")" || {
		echo "  [!] could not read the digest of $version_tag: $inspect_out" >&2
		exit 1
	}
	if [[ "$existing" != "$digest" ]]; then
		echo "  [!] $version_tag already names $existing, not $digest: a version tag is never re-pushed" >&2
		exit 1
	fi
	echo "==> $version_tag already names $digest; not re-pushing it"
elif [[ "$inspect_out" == *"not found"* ]]; then
	tags+=(--tag "$version_tag")
else
	echo "  [!] could not read $version_tag, so can't tell whether it exists: $inspect_out" >&2
	exit 1
fi

docker buildx imagetools create "${tags[@]}" "$SRC_DIGEST"

version_ref="${version_tag}@${digest}"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	{
		echo "version=${version}"
		echo "version_ref=${version_ref}"
	} >>"$GITHUB_OUTPUT"
fi
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
	# shellcheck disable=SC2016 # the backticks are markdown for the summary, not a substitution
	printf 'Docker Hub release image: `%s`\n' "$version_ref" >>"$GITHUB_STEP_SUMMARY"
fi
echo "==> mirrored ${SRC_DIGEST} -> ${DOCKERHUB_IMAGE}:${STABLE_TAG}"
echo "==> release image: ${version_ref}"
