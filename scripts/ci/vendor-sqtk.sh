#!/usr/bin/env bash
# vendor-sqtk.sh <tag> — vendor squawkie-talkie's sqtk CLI into the kit at a pinned tag. (#1236)
#
# Writes scripts/sqtk byte-for-byte from Wave-Engineering/squawkie-talkie at <tag>, and
# records the tag and its sha256 in scripts/ci/sqtk.pin. ./install links scripts/sqtk onto PATH
# (and the image runs ./install), so this is the only place the kit's sqtk comes from.
#
# Never edit scripts/sqtk by hand. Fix it upstream, tag, and re-run this script.
# tests/regression/test_sqtk_vendor.sh fails if the file no longer matches its pin.

set -euo pipefail

TAG="${1:?usage: vendor-sqtk.sh <tag>, e.g. v1.4.0}"
[[ "$TAG" =~ ^v[0-9] ]] || {
	echo "vendor-sqtk: '$TAG' does not look like a release tag" >&2
	exit 2
}

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
URL="https://raw.githubusercontent.com/Wave-Engineering/squawkie-talkie/${TAG}/sqtk"
OUT="$REPO_DIR/scripts/sqtk"
PIN="$REPO_DIR/scripts/ci/sqtk.pin"

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
curl -fsSL "$URL" -o "$tmp"
head -1 "$tmp" | grep -q '^#!' || {
	echo "vendor-sqtk: $URL is not a script" >&2
	exit 1
}

sha="$(sha256sum "$tmp" | cut -d' ' -f1)"
install -m 0755 "$tmp" "$OUT"
printf 'tag=%s\nsha256=%s\nsource=%s\n' "$TAG" "$sha" "$URL" >"$PIN"
echo "vendored sqtk $TAG ($sha) -> scripts/sqtk"
