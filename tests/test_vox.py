"""Tests for scripts/vox and scripts/vox-providers/* — the provider-hook dispatcher.

Exercises the real bash scripts via subprocess.run(). No mocking of the
scripts under test. External boundaries (the provider and player processes)
are stubbed with real executable test fixtures, not mocks.

Isolation:
- Each test sets ``XDG_CONFIG_HOME`` to a tmp_path subdir so nothing touches
  the user's real ``~/.config/vox``.
- ``VOX_PLAYER`` is set to a fixture script for tests that reach playback, so
  no audio is produced and no system player is invoked.
- ``VOX_DISABLED=1`` is used where we only care about the early-exit path.
"""

from __future__ import annotations

import os
import stat
import subprocess
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VOX = REPO_ROOT / "scripts" / "vox"
PROVIDERS_DIR = REPO_ROOT / "scripts" / "vox-providers"
SILENT = PROVIDERS_DIR / "silent.sh"
ESPEAK = PROVIDERS_DIR / "espeak.sh"
OPENAI = PROVIDERS_DIR / "openai-endpoint.sh"
OPENAI_QWEN = PROVIDERS_DIR / "openai-qwen.sh"
PIPER = PROVIDERS_DIR / "piper-local.sh"
MACOS_SAY = PROVIDERS_DIR / "macos-say.sh"

MAGIC = b"\xde\xad\xbe\xef\xca\xfe\xba\xbe"


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _write_executable(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _run(argv: list[str], env: dict[str, str], stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        env=env,
        input=stdin,
        capture_output=True,
        text=True,
    )


def _poll(pred, timeout: float = 45.0, interval: float = 0.05):
    """Return the first truthy value of pred() within `timeout`, else its last.

    Playback is detached by default since #952, so vox returns before the player
    runs; assertions that observe the player's side effects must poll rather than
    read immediately.

    The timeout is generous on purpose: a passing poll returns the moment pred() is
    true, so only a real failure waits it out. At 5s this test failed twice in the
    full pytest lane on a busy shared host (cc-workflow#1232's precheck, 2026-10-18)
    while passing 9/9 alone. The likely cause was the shared /tmp/vox-speak.lock (now
    private, see the env fixture); 45s (BJ) also absorbs heavy load.
    """
    import time

    deadline = time.monotonic() + timeout
    val = pred()
    while not val and time.monotonic() < deadline:
        time.sleep(interval)
        val = pred()
    return val


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """A minimal env that isolates ~/.config/vox to tmp and suppresses any real player.

    The player is replaced with /bin/true so tests that reach playback don't
    error out on systems without audio tools.
    """
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    e = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(xdg),
        "VOX_PLAYER": "/bin/true",
        # A private playback lock, as test_vox_chunking.py and test_vox_playback_budget.py
        # use. The default /tmp/vox-speak.lock is shared with every agent's real speech on
        # the host, so a test's detached player could queue behind seconds of real audio.
        "VOX_LOCK": str(tmp_path / "vox.lock"),
    }
    (tmp_path / "home").mkdir(exist_ok=True)
    return e


@pytest.fixture()
def magic_provider(tmp_path: Path) -> Path:
    """Provider that writes a known magic sequence to $VOX_OUTPUT_FILE."""
    return _write_executable(
        tmp_path / "magic-provider.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
: "${{VOX_OUTPUT_FILE:?}}"
printf '\\xde\\xad\\xbe\\xef\\xca\\xfe\\xba\\xbe' > "$VOX_OUTPUT_FILE"
""",
    )


@pytest.fixture()
def echo_stdin_provider(tmp_path: Path) -> Path:
    """Provider that asserts text is non-empty and writes it to the output file."""
    return _write_executable(
        tmp_path / "echo-provider.sh",
        """#!/usr/bin/env bash
set -euo pipefail
: "${VOX_OUTPUT_FILE:?}"
TEXT="${1:-}"
if [[ -z "$TEXT" ]]; then
    TEXT="$(cat)"
fi
printf '%s' "$TEXT" > "$VOX_OUTPUT_FILE"
""",
    )


@pytest.fixture()
def failing_provider(tmp_path: Path) -> Path:
    """Provider that exits 1 with a distinctive stderr message."""
    return _write_executable(
        tmp_path / "fail-provider.sh",
        """#!/usr/bin/env bash
echo "boom: synthesis is on fire" >&2
exit 1
""",
    )


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------


def test_resolution_vox_provider_env_wins(env, magic_provider, tmp_path):
    """$VOX_PROVIDER beats ~/.config/vox/provider beats bundled silent.sh."""
    home_provider = _write_executable(
        tmp_path / "home-provider.sh",
        """#!/usr/bin/env bash
echo "home-provider should not have run" >&2
exit 99
""",
    )
    cfg = Path(env["XDG_CONFIG_HOME"]) / "vox"
    cfg.mkdir()
    (cfg / "provider").symlink_to(home_provider)

    env["VOX_PROVIDER"] = str(magic_provider)
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hello"], env=env)

    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == MAGIC


def test_resolution_home_config_beats_bundled(env, magic_provider, tmp_path):
    """~/.config/vox/provider beats bundled silent.sh."""
    cfg = Path(env["XDG_CONFIG_HOME"]) / "vox"
    cfg.mkdir()
    (cfg / "provider").symlink_to(magic_provider)

    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hello"], env=env)

    assert r.returncode == 0, r.stderr
    assert out.read_bytes() == MAGIC


def test_resolution_falls_back_to_bundled_silent(env, tmp_path):
    """No $VOX_PROVIDER, no ~/.config/vox/provider → bundled silent.sh runs (exit 0)."""
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hello"], env=env)
    assert r.returncode == 0, r.stderr
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 8000
        # silent.sh writes 800 frames of silence
        assert w.getnframes() == 800
        frames = w.readframes(w.getnframes())
        assert frames == b"\x00\x00" * 800


# ---------------------------------------------------------------------------
# Provider contract
# ---------------------------------------------------------------------------


def test_provider_receives_text_as_argv(env, echo_stdin_provider, tmp_path):
    env["VOX_PROVIDER"] = str(echo_stdin_provider)
    env["VOX_NO_SIGNOFF"] = "1"
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hello world"], env=env)
    assert r.returncode == 0, r.stderr
    assert out.read_text() == "hello world"


def test_stdin_message_round_trips(env, echo_stdin_provider, tmp_path):
    """Text piped via stdin round-trips through vox → provider."""
    env["VOX_PROVIDER"] = str(echo_stdin_provider)
    env["VOX_NO_SIGNOFF"] = "1"
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out)], env=env, stdin="piped-message")
    assert r.returncode == 0, r.stderr
    assert out.read_text() == "piped-message"


def test_signoff_appended_when_enabled(env, echo_stdin_provider, tmp_path):
    """Without VOX_NO_SIGNOFF, vox appends '. This is <speaker>.' to the text."""
    env["VOX_PROVIDER"] = str(echo_stdin_provider)
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hello"], env=env)
    assert r.returncode == 0, r.stderr
    text = out.read_text()
    assert text.startswith("hello")
    assert "This is " in text


def test_provider_failure_surfaces_error(env, failing_provider, tmp_path):
    env["VOX_PROVIDER"] = str(failing_provider)
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hi"], env=env)
    assert r.returncode != 0
    assert "boom: synthesis is on fire" in r.stderr
    assert "provider" in r.stderr and "failed" in r.stderr


def test_empty_message_errors(env, magic_provider, tmp_path):
    env["VOX_PROVIDER"] = str(magic_provider)
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "   "], env=env)
    assert r.returncode != 0
    assert "empty message" in r.stderr


# ---------------------------------------------------------------------------
# Tmpfile cleanup (playback path)
# ---------------------------------------------------------------------------


def test_tmpfile_is_cleaned_up_after_playback(env, magic_provider, tmp_path):
    """When --output is NOT set, vox synthesizes a tmp wav, plays it, then deletes
    it — no leak.

    Playback is DETACHED by default since #952, so vox returns before the player
    finishes. This poll-based version verifies the same property (played, then
    cleaned up) without assuming synchronous completion; the previous form read
    the sentinel the instant vox returned, which now races the detached player.
    """
    # Fixture player that records the audio path it received to a sentinel file.
    sentinel = tmp_path / "played-path"
    player = _write_executable(
        tmp_path / "recording-player.sh",
        f"""#!/usr/bin/env bash
printf '%s' "$1" > "{sentinel}"
""",
    )
    env["VOX_PLAYER"] = str(player)
    env["VOX_PROVIDER"] = str(magic_provider)

    r = _run([str(VOX), "hello"], env=env)
    assert r.returncode == 0, r.stderr

    # Wait for the detached player to record the path it was handed...
    played_path = _poll(lambda: sentinel.read_text() if sentinel.exists() else "")
    assert played_path, "player sentinel empty — player did not run"
    # ...then for the tmpfile to be removed (main + detached-subshell EXIT traps).
    assert _poll(lambda: not Path(played_path).exists()), \
        f"tmpfile {played_path} was not cleaned up"


def test_fg_plays_synchronously(env, magic_provider, tmp_path):
    """--fg blocks until playback finishes, so the player's side effects are
    observable the instant vox returns (the pre-#952 default, now opt-in)."""
    sentinel = tmp_path / "fg-played-path"
    player = _write_executable(
        tmp_path / "fg-recording-player.sh",
        f"""#!/usr/bin/env bash
printf '%s' "$1" > "{sentinel}"
""",
    )
    env["VOX_PLAYER"] = str(player)
    env["VOX_PROVIDER"] = str(magic_provider)

    r = _run([str(VOX), "--fg", "hello"], env=env)
    assert r.returncode == 0, r.stderr
    # No poll: --fg is synchronous, so the sentinel is written before vox returns.
    assert sentinel.read_text(), "player sentinel empty — --fg did not play synchronously"


# ---------------------------------------------------------------------------
# VOX_DISABLED
# ---------------------------------------------------------------------------


def test_vox_disabled_short_circuits(env, failing_provider, tmp_path):
    """VOX_DISABLED=1 exits 0 without touching the provider."""
    env["VOX_DISABLED"] = "1"
    env["VOX_PROVIDER"] = str(failing_provider)  # would fail if invoked
    r = _run([str(VOX), "hello"], env=env)
    assert r.returncode == 0
    # No provider invocation → no "boom" message
    assert "boom" not in r.stderr


# ---------------------------------------------------------------------------
# silent.sh direct invocation
# ---------------------------------------------------------------------------


def test_silent_sh_writes_valid_wav(tmp_path):
    """silent.sh invoked directly produces a valid RIFF WAV."""
    out = tmp_path / "silent.wav"
    r = subprocess.run(
        [str(SILENT), "ignored"],
        env={"PATH": os.environ["PATH"], "VOX_OUTPUT_FILE": str(out)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    header = out.read_bytes()[:4]
    assert header == b"RIFF", f"expected RIFF header, got {header!r}"
    # Parse as WAV to prove structural validity
    with wave.open(str(out), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getsampwidth() == 2
        assert w.getframerate() == 8000


def test_silent_sh_without_output_file_errors(tmp_path):
    r = subprocess.run(
        [str(SILENT), "ignored"],
        env={"PATH": os.environ["PATH"]},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "VOX_OUTPUT_FILE" in r.stderr


# ---------------------------------------------------------------------------
# Shipped examples: shellcheck passes (non-runtime validation)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "provider",
    [SILENT, ESPEAK, OPENAI, OPENAI_QWEN, PIPER, MACOS_SAY],
    ids=lambda p: p.name,
)
def test_shipped_provider_shellcheck_clean(provider):
    """Every shipped provider passes shellcheck."""
    if not provider.exists():
        pytest.fail(f"shipped provider missing: {provider}")
    r = subprocess.run(
        ["shellcheck", str(provider)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.fail(f"shellcheck failed on {provider.name}:\n{r.stdout}{r.stderr}")


# ---------------------------------------------------------------------------
# openai-qwen.sh payload construction
# ---------------------------------------------------------------------------


def _install_fake_curl(tmp_path: Path) -> tuple[Path, Path]:
    """Install a fake `curl` earlier on PATH that captures -d payload for assertions.

    Returns (fake-bin-dir, payload-sentinel-file). The fake curl writes the
    JSON payload it received via `-d <payload>` to FAKE_CURL_PAYLOAD_OUT,
    writes a minimal dummy WAV to the `-o` file so the provider's post-curl
    `[[ -s "$VOX_OUTPUT_FILE" ]]` check passes, and prints "200" on stdout
    so the `%{http_code}` capture succeeds.

    This means the provider's real code path runs end-to-end — argv parsing,
    payload construction, curl invocation — with zero network activity and
    no test-only hooks baked into the provider itself.
    """
    bin_dir = tmp_path / "fake-bin"
    bin_dir.mkdir()
    sentinel = tmp_path / "curl-payload.json"
    fake = bin_dir / "curl"
    fake.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
out_file=""
payload=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        -o) out_file="$2"; shift 2;;
        -d) payload="$2"; shift 2;;
        -X|-H|--connect-timeout|--max-time|-w) shift 2;;
        -sS) shift;;
        *) shift;;
    esac
done
[[ -n "${FAKE_CURL_PAYLOAD_OUT:-}" ]] && printf '%s' "$payload" > "$FAKE_CURL_PAYLOAD_OUT"
[[ -n "$out_file" ]] && printf 'RIFFfakewavdata' > "$out_file"
printf '200'
"""
    )
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir, sentinel


def _run_qwen_payload_capture(
    tmp_path: Path,
    extra_env: dict[str, str],
    text: str = "hello",
) -> dict:
    """Run openai-qwen.sh end-to-end with a fake curl on PATH; return the
    parsed JSON payload the provider would have POSTed.

    The provider's production code path runs unmodified — no `VOX_DEBUG_*`
    hooks, no mocking of the script itself. Only `curl` is replaced, via the
    PATH-interposition pattern.
    """
    import json as _json

    fake_bin, sentinel = _install_fake_curl(tmp_path)
    out_path = tmp_path / "out.wav"
    env = {
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "VOX_OUTPUT_FILE": str(out_path),
        "VOX_ENDPOINT": "http://example.invalid/v1/audio/speech",
        "FAKE_CURL_PAYLOAD_OUT": str(sentinel),
        **extra_env,
    }
    r = subprocess.run(
        [str(OPENAI_QWEN), text],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert r.returncode == 0, f"provider exited {r.returncode}: {r.stderr}"
    assert sentinel.exists(), "fake curl did not capture payload"
    return _json.loads(sentinel.read_text())


def test_openai_qwen_omits_emotion_when_unset(tmp_path):
    payload = _run_qwen_payload_capture(tmp_path, extra_env={})
    assert "emotion" not in payload, f"emotion field leaked: {payload}"
    assert payload["model"] == "tts-1"
    assert payload["voice"] == "alloy"
    assert payload["input"] == "hello"
    assert payload["response_format"] == "wav"


def test_openai_qwen_omits_emotion_when_empty_string(tmp_path):
    payload = _run_qwen_payload_capture(tmp_path, extra_env={"VOX_EMOTION": ""})
    assert "emotion" not in payload, f"emotion='' should be omitted, got: {payload}"


def test_openai_qwen_includes_emotion_when_set(tmp_path):
    payload = _run_qwen_payload_capture(
        tmp_path,
        extra_env={"VOX_EMOTION": "cheerful"},
    )
    assert payload.get("emotion") == "cheerful"


def test_openai_qwen_includes_free_form_emotion(tmp_path):
    """qwen3-tts accepts natural-language emotion prompts, not just single tokens."""
    phrase = "the speaker's voice is very young and warm"
    payload = _run_qwen_payload_capture(
        tmp_path,
        extra_env={"VOX_EMOTION": phrase},
    )
    assert payload.get("emotion") == phrase


def test_openai_qwen_honors_voice_and_model_overrides(tmp_path):
    payload = _run_qwen_payload_capture(
        tmp_path,
        extra_env={"VOX_VOICE": "clone:Stephi", "VOX_MODEL": "qwen3-tts"},
    )
    assert payload["voice"] == "clone:Stephi"
    assert payload["model"] == "qwen3-tts"


def test_openai_qwen_errors_without_endpoint(tmp_path):
    out = tmp_path / "out.wav"
    r = subprocess.run(
        [str(OPENAI_QWEN), "hi"],
        env={"PATH": os.environ["PATH"], "VOX_OUTPUT_FILE": str(out)},
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "VOX_ENDPOINT" in r.stderr


def test_openai_qwen_errors_without_output_file(tmp_path):
    r = subprocess.run(
        [str(OPENAI_QWEN), "hi"],
        env={
            "PATH": os.environ["PATH"],
            "VOX_ENDPOINT": "http://example.invalid/",
        },
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0
    assert "VOX_OUTPUT_FILE" in r.stderr


# --- vox --setup --pick=openai-qwen ---


def test_setup_accepts_openai_qwen_pick(env, tmp_path):
    r = _run(
        [str(VOX), "--setup", "--non-interactive", "--pick", "openai-qwen"],
        env=env,
    )
    assert r.returncode == 0, r.stderr
    link = Path(env["XDG_CONFIG_HOME"]) / "vox" / "provider"
    assert link.is_symlink()
    assert link.resolve() == OPENAI_QWEN.resolve()


# ---------------------------------------------------------------------------
# --setup --non-interactive
# ---------------------------------------------------------------------------


def test_setup_non_interactive_creates_symlink(env, tmp_path):
    r = _run(
        [str(VOX), "--setup", "--non-interactive", "--pick", "silent"],
        env=env,
    )
    assert r.returncode == 0, r.stderr

    link = Path(env["XDG_CONFIG_HOME"]) / "vox" / "provider"
    assert link.is_symlink(), f"{link} is not a symlink"
    target = link.resolve()
    assert target == SILENT.resolve(), f"{link} → {target}, expected {SILENT}"


def test_setup_non_interactive_requires_pick(env):
    r = _run([str(VOX), "--setup", "--non-interactive"], env=env)
    assert r.returncode != 0
    assert "requires --pick" in r.stderr


def test_setup_rejects_unknown_pick(env):
    r = _run(
        [str(VOX), "--setup", "--non-interactive", "--pick", "nonesuch"],
        env=env,
    )
    assert r.returncode != 0
    assert "nonesuch" in r.stderr


def test_setup_accepts_equals_form_pick(env, tmp_path):
    """`--pick=<name>` (equals form, per docs) works the same as `--pick <name>`."""
    r = _run(
        [str(VOX), "--setup", "--non-interactive", "--pick=silent"],
        env=env,
    )
    assert r.returncode == 0, r.stderr
    link = Path(env["XDG_CONFIG_HOME"]) / "vox" / "provider"
    assert link.resolve() == SILENT.resolve()


def test_setup_is_idempotent(env, tmp_path):
    r1 = _run([str(VOX), "--setup", "--non-interactive", "--pick", "silent"], env=env)
    assert r1.returncode == 0, r1.stderr
    r2 = _run([str(VOX), "--setup", "--non-interactive", "--pick", "espeak"], env=env)
    assert r2.returncode == 0, r2.stderr
    link = Path(env["XDG_CONFIG_HOME"]) / "vox" / "provider"
    assert link.resolve() == ESPEAK.resolve(), "re-running setup should update the symlink"


# ---------------------------------------------------------------------------
# Wake noise preamble: VOX_WAKE / ~/.config/vox/wake (#1254)
# ---------------------------------------------------------------------------
#
# A provider writes a real 1.0 s WAV; a capture player copies what vox hands it.
# The wake noise is 0.5 s, so the captured duration says whether it was prepended.

TONE_RATE = 24000


def _tone_frames() -> bytes:
    """1.0 s of a 440 Hz tone, 24 kHz mono s16: what the tone provider writes."""
    import math

    return b"".join(
        int(8000 * math.sin(2 * math.pi * 440 * i / TONE_RATE)).to_bytes(2, "little", signed=True)
        for i in range(TONE_RATE)
    )


@pytest.fixture()
def tone_provider(tmp_path: Path) -> Path:
    frames = tmp_path / "tone.raw"
    frames.write_bytes(_tone_frames())
    return _write_executable(
        tmp_path / "tone-provider.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
: "${{VOX_OUTPUT_FILE:?}}"
python3 - "$VOX_OUTPUT_FILE" <<'PY'
import sys, wave
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate({TONE_RATE})
    w.writeframes(open("{frames}", "rb").read())
PY
""",
    )


@pytest.fixture()
def wake_env(env, tone_provider, tmp_path):
    """Foreground, no sign-off, no log, the tone provider and a capture player."""
    capture = tmp_path / "captured.wav"
    player = _write_executable(tmp_path / "capture-player.sh", f'#!/usr/bin/env bash\ncp "$1" "{capture}"\n')
    e = dict(env)
    e.update(
        {
            "VOX_PROVIDER": str(tone_provider),
            "VOX_PLAYER": str(player),
            "VOX_FOREGROUND": "1",
            "VOX_NO_SIGNOFF": "1",
            "VOX_NO_LOG": "1",
        }
    )
    return e, capture


def _wav(path: Path) -> tuple[float, bytes]:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate(), w.readframes(w.getnframes())


def _wake_file(env: dict[str, str], content: str) -> None:
    d = Path(env["XDG_CONFIG_HOME"]) / "vox"
    d.mkdir(parents=True, exist_ok=True)
    (d / "wake").write_text(content)


def test_wake_default_prepends_noise(wake_env):
    e, capture = wake_env
    r = _run([str(VOX), "hello"], env=e)
    assert r.returncode == 0, r.stderr
    dur, _ = _wav(capture)
    assert dur == pytest.approx(1.5, abs=0.01)


def test_wake_env_none_skips_noise(wake_env):
    e, capture = wake_env
    r = _run([str(VOX), "hello"], env={**e, "VOX_WAKE": "none"})
    assert r.returncode == 0, r.stderr
    dur, frames = _wav(capture)
    assert dur == pytest.approx(1.0, abs=0.01)
    assert frames == _tone_frames(), "with none, the provider's audio must reach the player untouched"


def test_wake_config_file_none_skips_noise(wake_env):
    e, capture = wake_env
    _wake_file(e, "none\n")
    r = _run([str(VOX), "hello"], env=e)
    assert r.returncode == 0, r.stderr
    assert _wav(capture)[0] == pytest.approx(1.0, abs=0.01)


def test_wake_env_beats_config_file(wake_env):
    e, capture = wake_env
    _wake_file(e, "none\n")
    r = _run([str(VOX), "hello"], env={**e, "VOX_WAKE": "noise"})
    assert r.returncode == 0, r.stderr
    assert _wav(capture)[0] == pytest.approx(1.5, abs=0.01)


def test_wake_unknown_value_warns_and_uses_noise(wake_env):
    e, capture = wake_env
    r = _run([str(VOX), "hello"], env={**e, "VOX_WAKE": "bogus"})
    assert r.returncode == 0, r.stderr
    assert "unknown wake setting 'bogus' (want noise|none); using noise" in r.stderr
    assert r.stderr.count("unknown wake setting") == 1
    assert _wav(capture)[0] == pytest.approx(1.5, abs=0.01)


def test_wake_unknown_value_warns_on_the_background_path(wake_env):
    """A long message plays from a subshell whose stderr is discarded; the warning must come first."""
    e, capture = wake_env
    e = {k: v for k, v in e.items() if k != "VOX_FOREGROUND"}
    e.update({"VOX_WAKE": "bogus", "VOX_CHUNK_CHARS": "12"})
    r = _run([str(VOX), "One two three. Four five six."], env=e)
    assert r.returncode == 0, r.stderr
    assert "playing in the background" in r.stderr, "the message must take the background path"
    assert r.stderr.count("unknown wake setting 'bogus' (want noise|none); using noise") == 1
    assert _poll(capture.exists), "the background player never ran"


@pytest.mark.parametrize("wake", [None, "noise", "none"])
def test_wake_output_mode_unaffected(wake_env, tmp_path, wake):
    """--output never prepends the noise, whatever the setting (regression guard)."""
    e, capture = wake_env
    if wake is not None:
        e = {**e, "VOX_WAKE": wake}
    out = tmp_path / "memo.wav"
    r = _run([str(VOX), "--output", str(out), "hello"], env=e)
    assert r.returncode == 0, r.stderr
    dur, frames = _wav(out)
    assert dur == pytest.approx(1.0, abs=0.01)
    assert frames == _tone_frames()
    assert not capture.exists(), "--output must not play"
