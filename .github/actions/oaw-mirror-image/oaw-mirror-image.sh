#!/usr/bin/env bash
# oaw-mirror-image.sh — copy an image digest to a second registry under its tags, never
# re-pushing a version tag, and report the digest-pinned refs (#1326).
#
# The core of the oaw-mirror-image action, and of the kit's own mirror
# (scripts/ci/mirror-oakandwave-image.sh). It replaces the copy-pasted
#   while read r; do docker buildx imagetools create --tag "<dest>:${r##*:}" "$r"; done
# step, which re-pushed every tag, version tags included, on every run.
#
# Tags matching IMMUTABLE_TAG_REGEX are version tags. Each is read on DEST_IMAGE first:
#   absent ("<ref>: not found")  -> pushed
#   already on this digest       -> skipped (an idempotent rerun)
#   on any other digest          -> exit 1, nothing pushed: a version tag is never re-pushed
#   unreadable (any other error) -> exit 1, nothing pushed: absent and present can't be told apart
# Every other tag (latest, X.Y, X, sha-*, stable) is moving, and is pushed.
# Everything to push goes in ONE imagetools create; with nothing to push, none runs.
#
# This touches no GitHub release. That is oaw-release-images, which a caller runs AFTER
# signing, so a release-API failure can never leave a pushed image unsigned.
#
# Inputs (env):
#   SOURCE_DIGEST_REF    registry/image@sha256:... to copy
#   TAGS                 newline-separated refs or bare tags; the part after the last ':' is used
#   DEST_IMAGE           the destination repository, e.g. docker.io/oakandwave/squawkie-talkie
#   IMMUTABLE_TAG_REGEX  default ^[0-9]+\.[0-9]+\.[0-9]+$
# Outputs (GITHUB_OUTPUT):
#   digest               sha256:...
#   release_refs         one DEST_IMAGE:<version tag>@<digest> per version tag (multi-line)
set -euo pipefail

: "${SOURCE_DIGEST_REF:?SOURCE_DIGEST_REF must be set}"
: "${TAGS:?TAGS must be set}"
: "${DEST_IMAGE:?DEST_IMAGE must be set}"
immutable_re="${IMMUTABLE_TAG_REGEX:-^[0-9]+\.[0-9]+\.[0-9]+$}"

digest="${SOURCE_DIGEST_REF#*@}"
if [[ "$SOURCE_DIGEST_REF" != *"@sha256:"* || ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
	echo "  [!] SOURCE_DIGEST_REF must be a digest ref (registry/image@sha256:...): $SOURCE_DIGEST_REF" >&2
	exit 1
fi

# Bare tag names, in order, without duplicates.
names=()
while IFS= read -r line; do
	line="${line//[[:space:]]/}"
	[[ -z "$line" ]] && continue
	if [[ "$line" == *,* ]]; then
		echo "  [!] TAGS is newline-separated, not comma-separated: $line" >&2
		exit 1
	fi
	name="${line##*:}"
	[[ " ${names[*]} " == *" $name "* ]] || names+=("$name")
done <<<"$TAGS"
if [[ ${#names[@]} -eq 0 ]]; then
	echo "  [!] TAGS names no tag" >&2
	exit 1
fi

push=()
release_refs=()
for name in "${names[@]}"; do
	ref="${DEST_IMAGE}:${name}"
	if [[ ! "$name" =~ $immutable_re ]]; then
		push+=(--tag "$ref")
		continue
	fi
	release_refs+=("${ref}@${digest}")
	if inspect_out="$(docker buildx imagetools inspect "$ref" --format '{{json .Manifest}}' 2>&1)"; then
		existing="$(jq -er '.digest' <<<"$inspect_out")" || {
			echo "  [!] could not read the digest of $ref: $inspect_out" >&2
			exit 1
		}
		if [[ "$existing" != "$digest" ]]; then
			echo "  [!] $ref already names $existing, not $digest: a version tag is never re-pushed" >&2
			exit 1
		fi
		echo "==> $ref already names $digest; not re-pushing it"
	elif [[ "$inspect_out" == *"${ref}: not found"* ]]; then # the tag itself, not a blob
		push+=(--tag "$ref")
	else
		echo "  [!] could not read $ref, so can't tell whether it exists: $inspect_out" >&2
		exit 1
	fi
done

if [[ ${#push[@]} -gt 0 ]]; then
	docker buildx imagetools create "${push[@]}" "$SOURCE_DIGEST_REF"
	echo "==> mirrored $SOURCE_DIGEST_REF -> ${push[*]//--tag /}"
else
	echo "==> every tag already names $digest; nothing to push"
fi

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	{
		echo "digest=${digest}"
		echo "release_refs<<OAW_MIRROR_EOF"
		[[ ${#release_refs[@]} -gt 0 ]] && printf '%s\n' "${release_refs[@]}"
		echo "OAW_MIRROR_EOF"
	} >>"$GITHUB_OUTPUT"
fi
if [[ -n "${GITHUB_STEP_SUMMARY:-}" && ${#release_refs[@]} -gt 0 ]]; then
	{
		echo "Release image:"
		# shellcheck disable=SC2016 # the backticks are markdown for the summary, not a substitution
		printf -- '- `%s`\n' "${release_refs[@]}"
	} >>"$GITHUB_STEP_SUMMARY"
fi
