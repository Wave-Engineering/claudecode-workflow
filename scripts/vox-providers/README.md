# vox providers

A **vox provider** is any executable that converts text to a WAV file. `vox` resolves one at runtime via the hook pattern; ship-zero defaults, user owns the provider.

## Contract (VOX_PROVIDER_CONTRACT=1)

A provider:
- Reads text from `$1`, or from stdin if `$1` is empty
- Writes a WAV audio file to `$VOX_OUTPUT_FILE` (path chosen by the caller)
- Exits **0** on success, **non-zero** on failure (stderr is captured)
- May read any `VOX_*` env var for its own config (voice, endpoint, model, …)

That's the whole contract. Any language works.

## Resolution order (from `vox`)

First match wins:

1. `$VOX_PROVIDER` — explicit path
2. `~/.config/vox/provider` — user's pick (usually a symlink to one of the examples)
3. `scripts/vox-providers/silent.sh` — bundled fallback (writes 0.1s silence)

The silent fallback means **missing config never errors** — vox stays safe to call from a fresh clone.

## Bundled examples

Each is a copy-and-adapt template. They ship executable so `vox --setup --pick=<name>` can symlink them directly.

| File | Backend | Required env |
|---|---|---|
| `silent.sh` | no-op (valid WAV of 0.1s silence) | — |
| `openai-endpoint.sh` | OpenAI-compatible TTS API (POST JSON, WAV response) | `VOX_ENDPOINT`, `VOX_VOICE`, `VOX_MODEL` |
| `openai-qwen.sh` | OpenAI-extended TTS (qwen3-tts, Chatterbox-over-HTTP, any server that accepts extra payload fields) — adds optional `emotion` field | `VOX_ENDPOINT`, `VOX_VOICE`, `VOX_MODEL`, optional `VOX_EMOTION` |
| `piper-local.sh` | local [piper](https://github.com/rhasspy/piper) binary | `VOX_PIPER_MODEL` (path to `.onnx`) |
| `espeak.sh` | `espeak` / `espeak-ng` (zero-deps fallback) | — |
| `macos-say.sh` | macOS `say(1)` + `afconvert` for WAV | — |

## Setup

### Interactive

```bash
vox --setup
```

Pick a provider. A symlink lands at `~/.config/vox/provider`.

### Manual

```bash
cp scripts/vox-providers/openai-endpoint.sh ~/.config/vox/provider
chmod +x ~/.config/vox/provider
$EDITOR ~/.config/vox/provider          # set VOX_ENDPOINT, VOX_VOICE
```

Using a symlink instead of a copy (so example changes flow in on `git pull`):

```bash
mkdir -p ~/.config/vox
ln -sf "$(pwd)/scripts/vox-providers/openai-endpoint.sh" ~/.config/vox/provider
export VOX_ENDPOINT="http://your-server:8004/v1/audio/speech"
export VOX_VOICE="your-voice-name"
```

### Scripted (non-interactive)

```bash
vox --setup --non-interactive --pick=silent
```

## Player hook (same pattern)

`vox` also resolves a player via `$VOX_PLAYER` → `~/.config/vox/player` → autodetect (`afplay`/`paplay`/`aplay`/`ffplay`). A custom player is any executable that takes an audio file path as `$1`.

## Writing your own provider

Minimal skeleton:

```bash
#!/usr/bin/env bash
set -euo pipefail
: "${VOX_OUTPUT_FILE:?}"
TEXT="${1:-$(cat)}"
[[ -n "${TEXT//[$' \t\n\r']/}" ]] || { echo "empty text" >&2; exit 1; }

# ... synthesize $TEXT into $VOX_OUTPUT_FILE ...
```

### Extending the JSON payload (HTTP backends)

Many OpenAI-compatible servers accept additional fields beyond the canonical `{model, input, voice, response_format}` set — `emotion`, `speed`, `pitch`, `style`, custom `metadata`, etc. Handle these via **new `VOX_*` env vars**, not by baking flags into `VOX_COMMAND`. The pattern:

```python
# inside your provider's payload builder
payload = {
    "model": os.environ["MODEL"],
    "input": os.environ["TEXT"],
    "voice": os.environ["VOICE"],
    "response_format": "wav",
}
emotion = os.environ.get("EMOTION", "")
if emotion:
    payload["emotion"] = emotion     # include only when set
```

**Two rules the contract enforces:**

1. **MAY honor, MUST ignore.** Providers whose backend doesn't support a field MUST silently ignore it. `espeak.sh` doesn't use `VOX_EMOTION`; that's fine — it must not error when it sees one set.
2. **Unset = field omitted.** When `VOX_EMOTION` is unset or empty, the provider MUST NOT send `"emotion": ""` or `"emotion": null`. Omit the key entirely. This keeps extended-field payloads compatible with strict endpoints.

See `openai-qwen.sh` for a worked example: same wire protocol as `openai-endpoint.sh` but includes `emotion` in the payload when `VOX_EMOTION` is set. Prefer copying that one when your server accepts extended fields; copy `openai-endpoint.sh` when you need strict OpenAI-spec compliance.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| silent playback | `silent.sh` is the active provider | run `vox --setup` and pick a real backend |
| "provider '...' failed" | your provider exited non-zero | run the provider directly, inspect stderr |
| "no audio player found" | no `afplay`/`aplay`/`paplay`/`ffplay` on `$PATH` | install one, or set `$VOX_PLAYER` |
| network TTS hangs | unreachable endpoint | set `VOX_DISABLED=1` for this session, or pick `silent`/`espeak` |

## Disable cleanly

`VOX_DISABLED=1 vox "anything"` exits 0 with no audio. Use for CI, remote sessions, or temporarily silencing announcements without un-configuring.

## Contract version

The `VOX_PROVIDER_CONTRACT=1` marker means: "this provider follows version 1 of the contract described above." Future versions may add fields; providers built against v1 should keep working as long as v1 is supported.
