#!/usr/bin/env bash
# piper-local.sh — vox provider using local piper binary.
#
# piper: https://github.com/rhasspy/piper
#
# Contract: VOX_PROVIDER_CONTRACT=1
#   In:  $1 or stdin — text to speak
#   Out: $VOX_OUTPUT_FILE — WAV audio from piper
#
# Required env:
#   VOX_PIPER_MODEL   — path to .onnx voice model

set -euo pipefail

: "${VOX_OUTPUT_FILE:?piper-local.sh: VOX_OUTPUT_FILE not set}"
: "${VOX_PIPER_MODEL:?piper-local.sh: VOX_PIPER_MODEL not set (path to .onnx)}"

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
	TEXT="$(cat)"
fi
[[ -n "${TEXT//[$' \t\n\r']/}" ]] || {
	echo "piper-local.sh: empty text" >&2
	exit 1
}

command -v piper >/dev/null || {
	echo "piper-local.sh: piper not installed (see https://github.com/rhasspy/piper)" >&2
	exit 1
}

printf '%s\n' "$TEXT" | piper --model "$VOX_PIPER_MODEL" --output_file "$VOX_OUTPUT_FILE"
