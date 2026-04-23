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
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out), "hello world"], env=env)
    assert r.returncode == 0, r.stderr
    assert out.read_text() == "hello world"


def test_stdin_message_round_trips(env, echo_stdin_provider, tmp_path):
    """Text piped via stdin round-trips through vox → provider."""
    env["VOX_PROVIDER"] = str(echo_stdin_provider)
    out = tmp_path / "out.wav"
    r = _run([str(VOX), "--output", str(out)], env=env, stdin="piped-message")
    assert r.returncode == 0, r.stderr
    assert out.read_text() == "piped-message"


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
    """When --output is NOT set, vox creates a tmp wav, plays it, then deletes it."""
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

    played_path = sentinel.read_text()
    assert played_path, "player sentinel empty — player did not run"
    # After vox exits, the tmpfile trap should have removed the audio file.
    assert not Path(played_path).exists(), f"tmpfile {played_path} was not cleaned up"


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
    [SILENT, ESPEAK, OPENAI, PIPER, MACOS_SAY],
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
