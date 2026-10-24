#!/usr/bin/env bash
# oaw-release-images.sh — write a release image's digest-pinned refs into its GitHub
# release, as one Images block that a rerun replaces (#1326).
#
# The core of the oaw-release-images action. Run it AFTER the image is mirrored and signed:
# it is a separate step from oaw-mirror-image so that a release-API failure here can never
# stop a signature, and so that the job writing the release needs contents: write while
# the job pushing and signing doesn't.
#
#   release exists, with the block       -> the block is replaced in place; the rest survives
#   release exists, without the block    -> the block is appended
#   release missing ("release not found") -> created with --verify-tag --generate-notes, the
#                                            block above the generated notes. If the create
#                                            loses a race with another job creating it, the
#                                            release is read again and edited instead.
#   release unreadable (any other error) -> exit 1
# A body whose markers aren't each on a line of their own (CRLF is tolerated) is refused
# rather than edited, since replacing from an unmatched begin would drop everything after it.
#
# Inputs (env):
#   RELEASE_TAG        the release's tag, e.g. v0.11.0
#   RELEASE_REFS       newline-separated dest:tag@sha256:... (oaw-mirror-image's release-refs)
#   SOURCE_DIGEST_REF  optional: the source registry/image@sha256:..., listed too
#   GH_TOKEN, GH_REPO  for gh
set -euo pipefail

: "${RELEASE_TAG:?RELEASE_TAG must be set}"

refs=()
while IFS= read -r line; do
	line="${line//[[:space:]]/}"
	[[ -n "$line" ]] && refs+=("$line")
done <<<"${RELEASE_REFS:-}"
if [[ ${#refs[@]} -eq 0 ]]; then
	echo "==> no version tag was mirrored, so nothing to write into release $RELEASE_TAG"
	exit 0
fi
for r in "${refs[@]}"; do
	if [[ ! "$r" =~ @sha256:[0-9a-f]{64}$ ]]; then
		echo "  [!] RELEASE_REFS holds a ref that isn't digest-pinned: $r" >&2
		exit 1
	fi
done

begin="<!-- oaw-mirror-image:begin -->"
end="<!-- oaw-mirror-image:end -->"
block="$(
	echo "$begin"
	echo "### Images"
	# shellcheck disable=SC2016 # markdown backticks, not a substitution
	printf -- '- `%s`\n' "${refs[@]}"
	[[ -n "${SOURCE_DIGEST_REF:-}" ]] && echo "- also \`${SOURCE_DIGEST_REF}\`"
	echo "$end"
)"

notes="$(mktemp)"
trap 'rm -f "$notes"' EXIT

# Edit an existing release whose body is $1: replace the block, or append it.
edit_release() {
	local body="$1" lines
	lines="$(awk -v b="$begin" -v e="$end" '
		{ sub(/\r$/, "") }
		$0 == b { nb++ } $0 == e { ne++ }
		END { print nb + 0, ne + 0 }
	' <<<"$body")"
	if [[ "$lines" == "1 1" ]]; then
		BLOCK="$block" awk -v b="$begin" -v e="$end" '
			{ sub(/\r$/, "") }
			$0 == b { print ENVIRON["BLOCK"]; skip = 1; next }
			$0 == e { skip = 0; next }
			!skip
		' <<<"$body" >"$notes"
	elif [[ "$lines" == "0 0" && "$body" != *"$begin"* && "$body" != *"$end"* ]]; then
		printf '%s\n\n%s\n' "$body" "$block" >"$notes"
	else
		echo "  [!] release $RELEASE_TAG has its Images markers out of shape (begin/end lines: $lines); not editing it" >&2
		exit 1
	fi
	gh release edit "$RELEASE_TAG" --notes-file "$notes" >/dev/null
	echo "==> wrote the Images block into release $RELEASE_TAG"
}

if view_out="$(gh release view "$RELEASE_TAG" --json body -q .body 2>&1)"; then
	edit_release "$view_out"
elif [[ "$view_out" == *"release not found"* ]]; then
	printf '%s\n' "$block" >"$notes"
	if gh release create "$RELEASE_TAG" --verify-tag --generate-notes --notes-file "$notes" >/dev/null; then
		echo "==> created release $RELEASE_TAG with the Images block"
	elif view_out="$(gh release view "$RELEASE_TAG" --json body -q .body 2>&1)"; then
		echo "==> release $RELEASE_TAG appeared while creating it; editing it instead"
		edit_release "$view_out"
	else
		echo "  [!] could not create release $RELEASE_TAG, nor read it afterwards: $view_out" >&2
		exit 1
	fi
else
	echo "  [!] could not read release $RELEASE_TAG: $view_out" >&2
	exit 1
fi
