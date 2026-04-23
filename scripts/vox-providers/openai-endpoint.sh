#!/usr/bin/env bash
# openai-endpoint.sh — vox provider for any OpenAI-compatible TTS API.
#
# Works with local servers (e.g. kokoro-fastapi, chatterbox, openai-edge-tts)
# or the actual OpenAI TTS endpoint if you have a key.
#
# Contract: VOX_PROVIDER_CONTRACT=1
#   In:  $1 or stdin — text to speak
#   Out: $VOX_OUTPUT_FILE — WAV audio from the endpoint
#
# Required env:
#   VOX_ENDPOINT   — URL, e.g. http://myserver:8004/v1/audio/speech
#
# Optional env:
#   VOX_VOICE      — voice name (default: alloy)
#   VOX_MODEL      — model name (default: tts-1)
#   VOX_API_KEY    — bearer token (if your endpoint requires auth)

set -euo pipefail

: "${VOX_OUTPUT_FILE:?openai-endpoint.sh: VOX_OUTPUT_FILE not set}"
: "${VOX_ENDPOINT:?openai-endpoint.sh: VOX_ENDPOINT not set}"

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
	TEXT="$(cat)"
fi
[[ -n "${TEXT//[$' \t\n\r']/}" ]] || {
	echo "openai-endpoint.sh: empty text" >&2
	exit 1
}

voice="${VOX_VOICE:-alloy}"
model="${VOX_MODEL:-tts-1}"

command -v curl >/dev/null || {
	echo "openai-endpoint.sh: curl required" >&2
	exit 1
}
command -v python3 >/dev/null || {
	echo "openai-endpoint.sh: python3 required (JSON encoding)" >&2
	exit 1
}

payload=$(
	TEXT="$TEXT" MODEL="$model" VOICE="$voice" python3 -c '
import json, os
print(json.dumps({
    "model": os.environ["MODEL"],
    "input": os.environ["TEXT"],
    "voice": os.environ["VOICE"],
    "response_format": "wav",
}))
'
)

auth_args=()
if [[ -n "${VOX_API_KEY:-}" ]]; then
	auth_args=(-H "Authorization: Bearer $VOX_API_KEY")
fi

http_code=$(curl -sS -w '%{http_code}' -o "$VOX_OUTPUT_FILE" \
	-X POST \
	-H "Content-Type: application/json" \
	"${auth_args[@]}" \
	-d "$payload" \
	--connect-timeout 5 \
	--max-time 30 \
	"$VOX_ENDPOINT")

if [[ "$http_code" -ge 400 ]]; then
	echo "openai-endpoint.sh: TTS endpoint returned HTTP $http_code" >&2
	[[ -s "$VOX_OUTPUT_FILE" ]] && head -c 500 "$VOX_OUTPUT_FILE" >&2
	exit 1
fi

[[ -s "$VOX_OUTPUT_FILE" ]] || {
	echo "openai-endpoint.sh: empty response from TTS endpoint" >&2
	exit 1
}
