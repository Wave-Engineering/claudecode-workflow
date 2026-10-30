"""godspeed's ASK checkpoint pages BJ through notify-bj.sh beside it (#1348).

The regression suites drive the real hook with GODSPEED_NOTIFY_DISABLED=1, so nothing else
runs this path. Here godspeed-lookback.sh is copied next to a stub notify-bj.sh that records
its argv and NOTIFY_BJ_REPO_ROOT. `_godspeed_notify ASK <d>` must call it with the vox line
and the post, pass the project root through, and say so on stderr when the stub fails: a
silent failure would look exactly like a delivered page.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_GODSPEED = _REPO / "scripts" / "godspeed-lookback.sh"

_NOTIFY_STUB = r"""#!/usr/bin/env bash
printf '%s\n' "$@" >"$STUB_DIR/notify.argv"
printf '%s' "${NOTIFY_BJ_REPO_ROOT-<unset>}" >"$STUB_DIR/notify.repo_root"
echo "stub notify stderr" >&2
exit "${STUB_NOTIFY_RC:-0}"
"""


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shutil.copy2(_GODSPEED, bindir / "godspeed-lookback.sh")
    stub = bindir / "notify-bj.sh"
    stub.write_text(_NOTIFY_STUB)
    stub.chmod(stub.stat().st_mode | stat.S_IXUSR)
    project = tmp_path / "project"
    (project / ".claude").mkdir(parents=True)
    (project / ".claude" / "agent-identity.json").write_text(
        '{"dev_name": "testfish", "dev_avatar": "🐟", "dev_team": "oaw"}'
    )
    return tmp_path


def _notify(sandbox: Path, rc: int) -> subprocess.CompletedProcess[str]:
    env = {k: v for k, v in os.environ.items() if k not in ("CI", "GODSPEED_NOTIFY_DISABLED")}
    env.update(
        STUB_DIR=str(sandbox),
        STUB_NOTIFY_RC=str(rc),
        CLAUDE_PROJECT_DIR=str(sandbox / "project"),
    )
    script = sandbox / "bin" / "godspeed-lookback.sh"
    return subprocess.run(
        ["bash", "-c", f'source "{script}"; _godspeed_notify ASK 7'],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_ask_pages_through_notify_bj_with_the_project_root(sandbox: Path) -> None:
    proc = _notify(sandbox, rc=0)
    assert proc.returncode == 0, proc.stderr
    argv = (sandbox / "notify.argv").read_text().splitlines()
    assert len(argv) == 2, argv
    assert argv[0].startswith("Hey BJ, godspeed mandate checkpoint")
    assert "**Godspeed checkpoint** — mandate at d=7/N=" in argv[1]
    assert "**testfish** 🐟 (oaw)" in argv[1]
    assert (sandbox / "notify.repo_root").read_text() == str(sandbox / "project")
    assert "notify failed" not in proc.stderr


def test_a_failed_page_is_reported_not_swallowed(sandbox: Path) -> None:
    proc = _notify(sandbox, rc=1)
    assert proc.returncode == 0, "the hook must not fail because the page did"
    assert "godspeed: notify failed: stub notify stderr" in proc.stderr


def test_a_missing_notifier_is_reported(sandbox: Path) -> None:
    (sandbox / "bin" / "notify-bj.sh").unlink()
    proc = _notify(sandbox, rc=0)
    assert proc.returncode == 0
    assert "notify-bj.sh not found" in proc.stderr
    assert not (sandbox / "notify.argv").exists()
