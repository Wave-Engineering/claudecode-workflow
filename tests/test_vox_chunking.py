"""Tests for vox long-message chunking and failure diagnostics (#1214).

TTS synthesis can run slower than realtime, so a long message used to die
mid-synth under a caller's `timeout` (or the provider's own HTTP cap) with
nothing played and nothing said about why. vox now:

- splits long text into parts of at most VOX_CHUNK_CHARS, one provider call
  each, concatenated into one clip — the sign-off only on the LAST part;
- detaches synth + playback for multi-part speech so no caller timeout can
  kill it, with an immediate stderr notice;
- explains provider failures and caller-timeout kills on stderr.

Real scripts via subprocess; the provider and player are real executable
fixtures that record what they were given.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import time
import wave
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VOX = REPO_ROOT / "scripts" / "vox"

LONG = (
    "The deploy finished and every check came back green. "
    "The new build is live on the cluster now. "
    "I also rotated the stale certificates on the ingress. "
    "Nothing else needs your attention tonight, so feel free to ignore the dashboard."
)


def _exe(path: Path, body: str) -> Path:
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _poll(pred, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    val = pred()
    while not val and time.monotonic() < deadline:
        time.sleep(0.05)
        val = pred()
    return val


@pytest.fixture()
def env(tmp_path: Path) -> dict[str, str]:
    xdg = tmp_path / "xdg"
    xdg.mkdir()
    (tmp_path / "home").mkdir()
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "XDG_CONFIG_HOME": str(xdg),
        "VOX_PLAYER": "/bin/true",
        "VOX_LOCK": str(tmp_path / "vox.lock"),
        "VOX_NO_LOG": "1",
    }


@pytest.fixture()
def calls(tmp_path: Path) -> Path:
    return tmp_path / "calls.jsonl"


@pytest.fixture()
def wav_provider(tmp_path: Path, calls: Path) -> Path:
    """Records each text it is asked to speak; writes 0.1s of silence as WAV."""
    return _exe(
        tmp_path / "wav-provider.sh",
        f"""#!/usr/bin/env bash
set -euo pipefail
python3 - "$1" <<'PY'
import json, os, sys, wave
with open({str(calls)!r}, "a") as f:
    f.write(json.dumps(sys.argv[1]) + "\\n")
with wave.open(os.environ["VOX_OUTPUT_FILE"], "wb") as w:
    w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
    w.writeframes(b"\\x00\\x00" * 800)
PY
""",
    )


def _calls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _run(argv, env, timeout=30):
    return subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)


def test_short_message_is_one_call_with_signoff(env, wav_provider, calls, tmp_path):
    env["VOX_PROVIDER"] = str(wav_provider)
    out = tmp_path / "o.wav"
    r = _run([str(VOX), "-o", str(out), "Tests are green"], env)
    assert r.returncode == 0, r.stderr
    got = _calls(calls)
    assert len(got) == 1
    assert got[0].startswith("Tests are green. This is ")


def test_long_message_splits_signoff_only_on_last(env, wav_provider, calls, tmp_path):
    env["VOX_PROVIDER"] = str(wav_provider)
    env["VOX_CHUNK_CHARS"] = "100"
    out = tmp_path / "o.wav"
    r = _run([str(VOX), "-o", str(out), LONG], env)
    assert r.returncode == 0, r.stderr
    got = _calls(calls)
    assert len(got) >= 3
    assert all(len(c) <= 100 for c in got[:-1])
    assert sum("This is " in c for c in got) == 1
    assert "This is " in got[-1]
    # Parts are split on sentence boundaries and nothing is lost.
    assert all(c.rstrip().endswith((".", "!", "?")) for c in got[:-1])
    body = " ".join(got)
    for sentence in LONG.split(". "):
        assert sentence.rstrip(".") in body
    # One concatenated clip: 0.1s per part.
    with wave.open(str(out)) as w:
        assert w.getnframes() == 800 * len(got)


def test_oversized_sentence_splits_on_words(env, wav_provider, calls, tmp_path):
    env["VOX_PROVIDER"] = str(wav_provider)
    env["VOX_CHUNK_CHARS"] = "40"
    env["VOX_NO_SIGNOFF"] = "1"
    text = "one two three four five six seven eight nine ten eleven twelve thirteen fourteen"
    r = _run([str(VOX), "-o", str(tmp_path / "o.wav"), text], env)
    assert r.returncode == 0, r.stderr
    got = _calls(calls)
    assert len(got) >= 2
    assert all(len(c) <= 40 for c in got)
    assert " ".join(got) == text


def test_chunking_disabled_with_zero(env, wav_provider, calls, tmp_path):
    env["VOX_PROVIDER"] = str(wav_provider)
    env["VOX_CHUNK_CHARS"] = "0"
    r = _run([str(VOX), "-o", str(tmp_path / "o.wav"), LONG], env)
    assert r.returncode == 0, r.stderr
    assert len(_calls(calls)) == 1


def test_long_message_detaches_and_plays_once(env, wav_provider, calls, tmp_path):
    played = tmp_path / "played.log"
    player = _exe(
        tmp_path / "player.sh",
        f'#!/usr/bin/env bash\necho "$1" >> {played}\n',
    )
    env["VOX_PROVIDER"] = str(wav_provider)
    env["VOX_PLAYER"] = str(player)
    env["VOX_CHUNK_CHARS"] = "100"
    r = _run([str(VOX), LONG], env)
    assert r.returncode == 0, r.stderr
    assert "split into" in r.stderr and "parts" in r.stderr
    assert _poll(lambda: played.exists() and played.read_text().strip())
    time.sleep(0.3)
    assert len(played.read_text().splitlines()) == 1
    assert len(_calls(calls)) >= 3


def test_provider_timeout_is_explained(env, tmp_path):
    prov = _exe(
        tmp_path / "timeout-provider.sh",
        '#!/usr/bin/env bash\necho "curl: (28) Operation timed out after 30001 milliseconds" >&2\nexit 28\n',
    )
    env["VOX_PROVIDER"] = str(prov)
    r = _run([str(VOX), "--fg", "hello there"], env)
    assert r.returncode == 1
    assert "synthesis failed on part 1/1" in r.stderr
    assert "(28) Operation timed out" in r.stderr
    assert "TIMED OUT" in r.stderr
    assert "1-2 short sentences" in r.stderr


def test_detached_failure_goes_to_error_log(env, tmp_path):
    prov = _exe(
        tmp_path / "fail-provider.sh",
        '#!/usr/bin/env bash\necho "curl: (28) Operation timed out" >&2\nexit 28\n',
    )
    errlog = tmp_path / "vox-errors.log"
    env["VOX_PROVIDER"] = str(prov)
    env["VOX_CHUNK_CHARS"] = "100"
    env["VOX_ERR_LOG"] = str(errlog)
    r = _run([str(VOX), LONG], env)
    assert r.returncode == 0
    assert str(errlog) in r.stderr
    assert _poll(lambda: errlog.exists() and "TIMED OUT" in errlog.read_text())


def test_caller_timeout_kill_is_explained(env, tmp_path):
    prov = _exe(tmp_path / "slow-provider.sh", "#!/usr/bin/env bash\nsleep 20\n")
    env["VOX_PROVIDER"] = str(prov)
    r = _run(["timeout", "1", str(VOX), "a short message"], env)
    assert r.returncode == 124
    assert "killed by SIGTERM" in r.stderr
    assert "caller timeout" in r.stderr
    assert "part 1/1" in r.stderr


def test_host_forward_provider_is_not_chunked(env, tmp_path):
    """host-forward.sh spools text for the host vox (which chunks); don't split here."""
    spool = tmp_path / "spool"
    spool.mkdir()
    env["VOX_PROVIDER"] = str(REPO_ROOT / "scripts" / "vox-providers" / "host-forward.sh")
    env["VOX_CHUNK_CHARS"] = "100"
    env["OAW_VOX_SPOOL"] = str(spool)
    r = _run([str(VOX), "--fg", LONG], env)
    assert r.returncode == 0, r.stderr
    assert "split into" not in r.stderr
    assert len(list(spool.glob("*.msg"))) == 1


def test_caller_timeout_kill_cleans_temp_files(env, tmp_path):
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()
    prov = _exe(tmp_path / "slow-provider.sh", "#!/usr/bin/env bash\nsleep 20\n")
    env["VOX_PROVIDER"] = str(prov)
    env["TMPDIR"] = str(tmpdir)
    env["VOX_LOCK"] = str(tmp_path / "vox.lock")
    r = _run(["timeout", "1", str(VOX), "a short message"], env)
    assert r.returncode == 124
    assert list(tmpdir.iterdir()) == []
