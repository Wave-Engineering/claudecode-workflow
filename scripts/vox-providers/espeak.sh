#!/usr/bin/env bash
# espeak.sh — vox provider using espeak-ng (or espeak). Zero network deps.
#
# Install on Debian/Ubuntu: sudo apt install espeak-ng
#
# Contract: VOX_PROVIDER_CONTRACT=1
#   In:  $1 or stdin — text to speak
#   Out: $VOX_OUTPUT_FILE — WAV audio from espeak
#
# Optional env:
#   VOX_VOICE      — espeak voice name (e.g. en-us, en-gb)

set -euo pipefail

: "${VOX_OUTPUT_FILE:?espeak.sh: VOX_OUTPUT_FILE not set}"

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
	TEXT="$(cat)"
fi
[[ -n "${TEXT//[$' \t\n\r']/}" ]] || {
	echo "espeak.sh: empty text" >&2
	exit 1
}

bin=""
if command -v espeak-ng >/dev/null; then
	bin="espeak-ng"
elif command -v espeak >/dev/null; then
	bin="espeak"
else
	echo "espeak.sh: espeak-ng or espeak required (sudo apt install espeak-ng)" >&2
	exit 1
fi

voice_args=()
if [[ -n "${VOX_VOICE:-}" ]]; then
	voice_args=(-v "$VOX_VOICE")
fi

"$bin" "${voice_args[@]}" -w "$VOX_OUTPUT_FILE" "$TEXT"
