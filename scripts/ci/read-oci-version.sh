#!/usr/bin/env bash
# read-oci-version.sh — print the release version a digest carries, or refuse (#1359).
#
# Usage: read-oci-version.sh <registry/image@sha256:...>
#
# Reads org.opencontainers.image.version off every platform's config and prints it
# when it is X.Y.Z. The one rule for both callers: promote-oakandwave-image.sh (GHCR
# :stable) and mirror-oakandwave-image.sh (Docker Hub), so the two registries can
# never disagree about which digests count as a release (#1324).
#
# Exit: 0 and the bare version on stdout; 1 on a ref that is not a digest, an
# unreadable label, platforms that disagree, or a version that is not X.Y.Z.

set -euo pipefail

ref="${1:?usage: read-oci-version.sh <registry/image@sha256:...>}"

if [[ "$ref" != *"@sha256:"* || ! "${ref#*@}" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "  [!] not a digest ref (registry/image@sha256:...): $ref" >&2
	exit 1
fi

# The label, from every platform's config. A single-platform image's .Image is one config;
# an index's is a map of platform -> config. Every platform must carry the same version.
version="$(docker buildx imagetools inspect "$ref" --format '{{json .Image}}' |
	jq -er '
		(if has("config") then [.] else [.[]] end)
		| map(.config.Labels["org.opencontainers.image.version"] // "")
		| unique
		| if length == 1 then .[0] else error("platforms disagree on the version label") end
	')" || {
	echo "  [!] could not read org.opencontainers.image.version off $ref" >&2
	exit 1
}
if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
	echo "  [!] $ref has version label '$version', not X.Y.Z: only a release is promoted or mirrored" >&2
	exit 1
fi

printf '%s\n' "$version"
