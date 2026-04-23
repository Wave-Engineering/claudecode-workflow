#!/usr/bin/env bash
# silent.sh — vox provider that writes 0.1s of silence.
#
# Safe no-op default. Used by `vox` when no other provider is configured, so a
# fresh clone never errors on missing TTS setup. Also useful as `VOX_PROVIDER`
# during tests.
#
# Contract: VOX_PROVIDER_CONTRACT=1
#   In:  $1 (ignored) or stdin (ignored)
#   Out: $VOX_OUTPUT_FILE — valid 16-bit mono 8kHz WAV, 0.1s of silence

set -euo pipefail

: "${VOX_OUTPUT_FILE:?silent.sh: VOX_OUTPUT_FILE not set}"

python3 - <<'PY'
import os, wave
out = os.environ["VOX_OUTPUT_FILE"]
with wave.open(out, "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(8000)
    w.writeframes(b"\x00\x00" * 800)  # 0.1s at 8kHz mono
PY
