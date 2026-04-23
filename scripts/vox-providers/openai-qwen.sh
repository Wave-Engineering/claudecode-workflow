#!/usr/bin/env bash
# openai-qwen.sh — vox provider for OpenAI-extended TTS servers (e.g. qwen3-tts).
#
# Identical wire protocol to openai-endpoint.sh (POST JSON to
# /v1/audio/speech, receive WAV body) but sends an optional VOX_EMOTION
# field in the payload that qwen3-tts and Chatterbox-over-HTTP both
# recognize. Strict OpenAI endpoints (api.openai.com) will reject or
# ignore the extra field — use openai-endpoint.sh for those instead.
#
# Contract: VOX_PROVIDER_CONTRACT=1
#   In:  $1 or stdin — text to speak
#   Out: $VOX_OUTPUT_FILE — WAV audio from the endpoint
#
# Required env:
#   VOX_ENDPOINT   — URL, e.g. http://myserver:8004/v1/audio/speech
#
# Optional env (canonical OpenAI spec):
#   VOX_VOICE      — voice name (default: alloy)
#   VOX_MODEL      — model name (default: tts-1)
#   VOX_API_KEY    — bearer token (if your endpoint requires auth)
#
# Optional env (qwen/extended):
#   VOX_EMOTION    — free-form emotion prompt. Unset or empty → field omitted.
#                    Examples: "cheerful", "the speaker's voice is very young",
#                    "angry and loud". Server-dependent semantics.

set -euo pipefail

: "${VOX_OUTPUT_FILE:?openai-qwen.sh: VOX_OUTPUT_FILE not set}"
: "${VOX_ENDPOINT:?openai-qwen.sh: VOX_ENDPOINT not set}"

TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
	TEXT="$(cat)"
fi
[[ -n "${TEXT//[$' \t\n\r']/}" ]] || {
	echo "openai-qwen.sh: empty text" >&2
	exit 1
}

voice="${VOX_VOICE:-alloy}"
model="${VOX_MODEL:-tts-1}"
emotion="${VOX_EMOTION:-}"

command -v curl >/dev/null || {
	echo "openai-qwen.sh: curl required" >&2
	exit 1
}
command -v python3 >/dev/null || {
	echo "openai-qwen.sh: python3 required (JSON encoding)" >&2
	exit 1
}

# Extend the payload: VOX_EMOTION becomes payload["emotion"] iff set.
# Unset or empty → field omitted entirely (MUST, per the contract — don't
# send "emotion": "" or "emotion": null).
payload=$(
	TEXT="$TEXT" MODEL="$model" VOICE="$voice" EMOTION="$emotion" python3 -c '
import json, os
payload = {
    "model": os.environ["MODEL"],
    "input": os.environ["TEXT"],
    "voice": os.environ["VOICE"],
    "response_format": "wav",
}
emotion = os.environ.get("EMOTION", "")
if emotion:
    payload["emotion"] = emotion
print(json.dumps(payload))
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
	echo "openai-qwen.sh: TTS endpoint returned HTTP $http_code" >&2
	[[ -s "$VOX_OUTPUT_FILE" ]] && head -c 500 "$VOX_OUTPUT_FILE" >&2
	exit 1
fi

[[ -s "$VOX_OUTPUT_FILE" ]] || {
	echo "openai-qwen.sh: empty response from TTS endpoint" >&2
	exit 1
}
