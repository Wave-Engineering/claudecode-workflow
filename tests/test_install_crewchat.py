"""scripts/install-crewchat.sh: the crewchat thin MCP is registered only where the
crewchat daemon runs (#1330, K-1).

`uv` and `claude` are stubs on a sandboxed PATH that record every call, and the daemon
socket is a real unix socket bound in a temp dir (or absent, or unwritable). The script
must:
- leave everything untouched without a usable socket, and say why;
- install the pinned tag and register `crewchat` with one;
- never use jq on ~/.claude.json (registration goes through `claude mcp`);
- report drift in `check` exactly when the state is wrong.
"""

from __future__ import annotations

import os
import socket
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "install-crewchat.sh"

_UV_STUB = r"""#!/usr/bin/env bash
state="$STUB_DIR/uv-state"; echo "uv $*" >>"$STUB_DIR/calls"
case "$1 $2" in
"tool list") [[ -f "$state" ]] && cat "$state" ;;
"tool install") echo "crewchat-clients v0.1.0" >"$state"; echo "- crewchat-mcp" >>"$state"
	mkdir -p "$STUB_DIR/bin-tools"; printf '#!/bin/sh\n' >"$STUB_DIR/bin-tools/crewchat-mcp"
	chmod +x "$STUB_DIR/bin-tools/crewchat-mcp" ;;
"tool dir") echo "$STUB_DIR/bin-tools" ;;
"tool uninstall") rm -f "$state" ;;
esac
"""

_CLAUDE_STUB = r"""#!/usr/bin/env bash
reg="$STUB_DIR/registered"; echo "claude $*" >>"$STUB_DIR/calls"
case "$1 $2" in
"mcp get") [[ -f "$reg" ]] ;;
"mcp add") echo "$*" >"$reg" ;;
"mcp remove") rm -f "$reg" ;;
esac
"""


@pytest.fixture()
def stubs(tmp_path: Path) -> Path:
    d = tmp_path / "stubs"
    (d / "path").mkdir(parents=True)
    for name, body in (("uv", _UV_STUB), ("claude", _CLAUDE_STUB)):
        p = d / "path" / name
        p.write_text(body)
        p.chmod(0o755)
    return d


@pytest.fixture()
def live_socket(tmp_path: Path):
    path = tmp_path / "crewchat.sock"
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(path))
    yield path
    s.close()


def _run(stubs: Path, sock: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["STUB_DIR"] = str(stubs)
    env["CREWCHAT_SOCKET"] = str(sock)
    # The stubs, then the system essentials only, so no real uv or claude is found.
    env["PATH"] = f"{stubs / 'path'}:/usr/bin:/bin"
    return subprocess.run(
        ["bash", str(_SCRIPT), *args], env=env, capture_output=True, text=True, check=False
    )


def _calls(stubs: Path) -> str:
    f = stubs / "calls"
    return f.read_text() if f.exists() else ""


def test_no_socket_skips_and_touches_nothing(stubs: Path, tmp_path: Path) -> None:
    r = _run(stubs, tmp_path / "absent.sock", "install")
    assert r.returncode == 0, r.stderr
    assert "skipped, no crewchat daemon" in r.stdout
    assert "Chat stays on disc-server" in r.stdout
    assert _calls(stubs) == "", "no uv or claude call may happen without a daemon"


def test_unwritable_socket_skips(stubs: Path, live_socket: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root can write any socket")
    live_socket.chmod(0)
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0, r.stderr
    assert "not writable" in r.stdout
    assert _calls(stubs) == ""


def test_socket_present_installs_pinned_tag_and_registers(stubs: Path, live_socket: Path) -> None:
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = _calls(stubs)
    assert (
        "uv tool install --force "
        "git+https://github.com/Wave-Engineering/mattermost-crew@v0.1.0"
        "#subdirectory=packages/clients" in calls
    )
    assert f"claude mcp add -s user crewchat -- {stubs}/bin-tools/crewchat-mcp" in calls
    assert "registered as crewchat" in r.stdout


def test_reinstall_at_same_version_skips_uv_install(stubs: Path, live_socket: Path) -> None:
    _run(stubs, live_socket, "install")
    (stubs / "calls").unlink()
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0
    assert "uv tool install" not in _calls(stubs)
    assert "claude mcp add" in _calls(stubs)


def test_dry_run_changes_nothing(stubs: Path, live_socket: Path) -> None:
    r = _run(stubs, live_socket, "install", "--dry-run")
    assert r.returncode == 0
    assert "(dry-run)" in r.stdout
    calls = _calls(stubs)
    assert "uv tool install" not in calls and "mcp add" not in calls


def test_check_states(stubs: Path, live_socket: Path, tmp_path: Path) -> None:
    # No daemon, nothing registered: not applicable, no drift.
    r = _run(stubs, tmp_path / "absent.sock", "check")
    assert r.returncode == 0 and "not applicable" in r.stdout
    # Daemon present, not installed: drift.
    r = _run(stubs, live_socket, "check")
    assert r.returncode == 1 and "not installed" in r.stdout
    # Installed and registered: clean.
    _run(stubs, live_socket, "install")
    r = _run(stubs, live_socket, "check")
    assert r.returncode == 0 and "(registered)" in r.stdout, r.stdout
    # Registered but the daemon has gone: drift, because the skills would pick a dead path.
    r = _run(stubs, tmp_path / "absent.sock", "check")
    assert r.returncode == 1 and "registered, but no crewchat daemon" in r.stdout


def test_uninstall_removes_registration_and_tool(stubs: Path, live_socket: Path) -> None:
    _run(stubs, live_socket, "install")
    r = _run(stubs, live_socket, "uninstall")
    assert r.returncode == 0
    assert not (stubs / "registered").exists()
    assert not (stubs / "uv-state").exists()


def test_never_edits_claude_json_directly() -> None:
    text = _SCRIPT.read_text()
    code = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("#"))
    assert "claude.json" not in code, "register through `claude mcp`, never by editing the file"
    assert "jq" not in code


def test_script_is_executable() -> None:
    assert _SCRIPT.stat().st_mode & stat.S_IXUSR
