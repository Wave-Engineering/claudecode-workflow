"""A subprocess environment whose every per-user location sits under a sandbox HOME.

WHY (2026-10-29). Overriding HOME alone is not a sandbox. uv finds its tool dir through
XDG_DATA_HOME (and UV_TOOL_DIR) before it falls back to HOME, and an agent's environment
carries the real ``XDG_DATA_HOME=/home/<user>/.local/share``. So
``test_uninstall_removes_artifacts`` ran ``uninstall.sh`` -> ``install-crewchat.sh
uninstall`` -> the REAL ``uv tool uninstall crewchat-clients``, and wiped the fleet's
crewchat clients at 06:06Z. Every test that runs ``install``, ``uninstall.sh`` or
``install-crewchat.sh`` with a real PATH builds its environment here.
"""

from __future__ import annotations

import os
from pathlib import Path


def sandbox_env(home: Path) -> dict[str, str]:
    """``os.environ`` with HOME, the XDG dirs and uv's tool dirs all inside ``home``."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["XDG_DATA_HOME"] = str(home / ".local" / "share")
    env["XDG_CONFIG_HOME"] = str(home / ".config")
    env["XDG_STATE_HOME"] = str(home / ".local" / "state")
    env["XDG_BIN_HOME"] = str(home / ".local" / "bin")
    env["UV_TOOL_DIR"] = str(home / ".local" / "share" / "uv" / "tools")
    env["UV_TOOL_BIN_DIR"] = str(home / ".local" / "bin")
    return env
