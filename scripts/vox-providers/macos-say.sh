#!/usr/bin/env bash
# macos-say.sh — vox provider using macOS say(1) + afconvert for WAV output.
#
# Contract: VOX_PROVIDER_CONTRACT=1
#   In:  $1 or stdin — text to speak
#   Out: $VOX_OUTPUT_FILE — WAV audio (say writes AIFF; afconvert converts)
#
# Optional env:
#   VOX_VOICE      — say(1) voice name (see `say -v ?` for the list)

set -euo pipefail

: "${VOX_OUTPUT_FILE:?macos-say.sh: VOX_OUTPUT_FILE not set}"

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
	TEXT="$(cat)"
fi
[[ -n "${TEXT//[$' \t\n\r']/}" ]] || {
	echo "macos-say.sh: empty text" >&2
	exit 1
}

command -v say >/dev/null || {
	echo "macos-say.sh: say(1) not found (macOS only)" >&2
	exit 1
}
command -v afconvert >/dev/null || {
	echo "macos-say.sh: afconvert not found (macOS only)" >&2
	exit 1
}

voice_args=()
if [[ -n "${VOX_VOICE:-}" ]]; then
	voice_args=(-v "$VOX_VOICE")
fi

tmp_aiff="$(mktemp).aiff"
trap 'rm -f "$tmp_aiff"' EXIT

say "${voice_args[@]}" -o "$tmp_aiff" "$TEXT"
afconvert -f WAVE -d LEI16 "$tmp_aiff" "$VOX_OUTPUT_FILE"
