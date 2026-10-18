"""Tests for scripts/hooks/nerf/session-start-compact.sh.

The hook runs right after a compaction, before the statusline has redrawn. nerf
reads the context reading the statusline persists, so the newest reading on
disk is the pre-compaction figure. The hook must pass `--not-before <epoch>`
so nerf shows `ctx ?` instead of repainting that figure as current
(mcp-server-nerf#32; the regression cc-workflow#555 originally fixed).

Driven for real: the hook script runs as a subprocess against a stub NERF_BIN
that records its argv.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "nerf" / "session-start-compact.sh"


def _stub_nerf(tmp_path: Path) -> tuple[Path, Path]:
    argv_log = tmp_path / "argv.log"
    stub = tmp_path / "nerf-server"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{argv_log}"\n')
    stub.chmod(0o755)
    return stub, argv_log


def _run_hook(tmp_path: Path, stdin: dict) -> list[str]:
    stub, argv_log = _stub_nerf(tmp_path)
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(stdin),
        capture_output=True,
        text=True,
        env={"NERF_BIN": str(stub), "PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return argv_log.read_text().splitlines()


def test_passes_not_before_with_session_id(tmp_path: Path):
    start = int(time.time())
    argv = _run_hook(tmp_path, {"session_id": "abc-123", "source": "compact"})

    assert argv[:3] == ["refresh-indicator", "--session-id", "abc-123"]
    assert "--not-before" in argv
    not_before = int(argv[argv.index("--not-before") + 1])
    assert start <= not_before <= int(time.time())


def test_passes_not_before_without_session_id(tmp_path: Path):
    argv = _run_hook(tmp_path, {"source": "compact"})

    assert argv[0] == "refresh-indicator"
    assert "--session-id" not in argv
    assert "--not-before" in argv
    assert argv[argv.index("--not-before") + 1].isdigit()
