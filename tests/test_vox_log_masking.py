"""vox's provenance log keeps credentials in ancestor command lines out (#1248).

vox_log records the caller's cmdline and a 6-deep ancestor chain in
~/.claude/logs/vox.jsonl. An ancestor's argv can carry the environment (an aoe tmux
server is started with `-e NAME=value` per variable), so every hop goes through
vox_cmdline, which keeps only the program and its first argument, masked, plus a count
of what it dropped. These tests plant fake credentials in the argv of vox's parent
process and assert they never reach the log, while the hop itself still does.

Driven for real: the parent is `exec -a <argv0> bash -c '<vox ...>; true' inner0 <planted>`,
so its /proc/<ppid>/cmdline is `<argv0> -c <body> inner0 <planted...>` (the trailing `true`
stops bash exec-ing into vox). `exec -a` puts a planted value in a KEPT position (argv[0]);
everything from the body on sits in the dropped positions.
Linux only: without /proc there is no chain to mask.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VOX = REPO_ROOT / "scripts" / "vox"
SILENT = REPO_ROOT / "scripts" / "vox-providers" / "silent.sh"

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="needs /proc")

# Built at runtime so this file holds no detectable credential itself.
SENTINEL = "s3ntinel" + "Value0001"
GH_TOKEN = "ghp_" + "Z" * 18 + "q" * 18
GL_RUNNER = "glrt-" + "R" * 20
BAO_TOKEN = "hvs." + "C" * 24
AWS_KEY = "AKIA" + "TLQ4V2KXR7NWJ3PZ"
BEARER = "eyJ" + "hbGciOiJIUzI1NiJ9" + "x" * 10


def _log_after_vox(tmp_path: Path, argv0: str, planted: list[str]) -> tuple[dict, str]:
    home = tmp_path / "home"
    home.mkdir()
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "VOX_PROVIDER": str(SILENT),
        "VOX_PLAYER": "/bin/true",
        "VOX_LOCK": str(tmp_path / "vox.lock"),
        "VOX_NO_SIGNOFF": "1",
        "VOXCMD": f'"{VOX}" "masking test"; true',
    }
    result = subprocess.run(
        ["bash", "-c", 'exec -a "$0" bash -c "$VOXCMD" inner0 "$@"', argv0, *planted],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    raw = (home / ".claude" / "logs" / "vox.jsonl").read_text()
    return json.loads(raw.splitlines()[-1]), raw


def test_arguments_past_the_first_never_reach_the_log(tmp_path: Path):
    # Every shape the regex-only version's review found leaking, in a dropped position.
    planted = [
        "-e",
        f"FAKE_TOKEN={SENTINEL}",  # an aoe-style `-e NAME=value`
        f'export API_KEY="{SENTINEL}2"',  # a quoted value inside a `bash -c` body
        "--password",
        f"{SENTINEL}3",  # a secret flag and its value as two arguments
        f"PRIVATE-TOKEN: {SENTINEL}4",  # a header with no `=`
        f"Authorization: Bearer {BEARER}",
        f"https://user:{SENTINEL}5@example.invalid/x",  # a URL password
        GH_TOKEN,
        AWS_KEY,
    ]
    entry, raw = _log_after_vox(tmp_path, "parent-shell", planted)
    for secret in (SENTINEL, GH_TOKEN[4:], AWS_KEY, BEARER):
        assert secret not in raw, f"{secret[:6]}… leaked into vox.jsonl"

    # The hop is logged, reduced, not dropped: argv[0], argv[1], and the count of the rest
    # (the body, inner0, and the planted arguments).
    assert entry["caller"] == f"parent-shell -c [+{2 + len(planted)} args]"
    assert entry["chain"][0] == entry["caller"]


@pytest.mark.parametrize(
    ("argv0", "logged", "secret"),
    [
        (f"FAKE_TOKEN={SENTINEL}", "FAKE_TOKEN=<masked>", SENTINEL),
        # Not a leading `-`: bash would take that argv[0] as a login shell and source /etc/profile.
        (f"x--api-key={SENTINEL}", "x--api-key=<masked>", SENTINEL),
        (f'X_API_KEY="{SENTINEL}"', "X_API_KEY=<masked>", SENTINEL),
        (f"X_API_KEY='{SENTINEL}'", "X_API_KEY=<masked>", SENTINEL),
        (f"https://user:{SENTINEL}@example.invalid/x", "https://user:<masked>@example.invalid/x", SENTINEL),
        (GH_TOKEN, "ghp_<masked>", GH_TOKEN[4:]),
        (GL_RUNNER, "glrt-<masked>", GL_RUNNER[5:]),
        (BAO_TOKEN, "hvs.<masked>", BAO_TOKEN[4:]),
        (AWS_KEY, "<masked>", AWS_KEY),
    ],
)
def test_a_kept_argument_is_masked(tmp_path: Path, argv0: str, logged: str, secret: str):
    entry, raw = _log_after_vox(tmp_path, argv0, [])
    assert secret not in raw, f"{secret[:6]}… leaked into vox.jsonl"
    assert entry["caller"] == f"{logged} -c [+2 args]"


def test_a_kept_argument_is_cut_at_160_characters(tmp_path: Path):
    entry, _ = _log_after_vox(tmp_path, "p" * 300, [])
    assert entry["caller"] == "p" * 160 + "… -c [+2 args]"


def test_the_log_is_owner_only(tmp_path: Path):
    # A log written before the fix, under a default 0644 umask, is tightened too.
    logf = tmp_path / "home" / ".claude" / "logs" / "vox.jsonl"
    logf.parent.mkdir(parents=True)
    logf.write_text("")
    logf.chmod(0o644)
    home = tmp_path / "home"
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(tmp_path / "xdg"),
        "VOX_PROVIDER": str(SILENT),
        "VOX_PLAYER": "/bin/true",
        "VOX_LOCK": str(tmp_path / "vox.lock"),
        "VOX_NO_SIGNOFF": "1",
    }
    r = subprocess.run([str(VOX), "mode test"], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert logf.read_text().strip(), "vox wrote no log entry"
    assert stat.S_IMODE(logf.stat().st_mode) == 0o600


def test_ordinary_kept_arguments_are_unchanged(tmp_path: Path):
    entry, _ = _log_after_vox(tmp_path, "./scripts/ci/validate.sh", ["--flag", "value"])
    assert entry["caller"] == "./scripts/ci/validate.sh -c [+4 args]"
    assert "<masked>" not in entry["caller"]
