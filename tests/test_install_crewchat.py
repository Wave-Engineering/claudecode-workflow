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
import re
import socket
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPT = _REPO / "scripts" / "install-crewchat.sh"
# The pinned tag, read from the script, so a pin bump touches one test (`test_pin`), not all.
_PIN = re.search(r'^CREWCHAT_TAG="(v[^"]+)"$', _SCRIPT.read_text(), re.MULTILINE)
assert _PIN, "install-crewchat.sh must set CREWCHAT_TAG"
_TAG = _PIN.group(1)

# The lock pins mcp 1.30.0 (behind a marker, as uv writes some) and pydantic-core. An install
# leaves `freeze`, what `uv pip list --format freeze` answers; STUB_INSTALLED_MCP stands in for
# a resolver that ignored the constraints. Freeze spells pydantic_core with an underscore, so the
# comparison has to normalise names.
_UV_STUB = r"""#!/usr/bin/env bash
state="$STUB_DIR/uv-state"; env="$STUB_DIR/tools/crewchat-clients"
echo "uv $*" >>"$STUB_DIR/calls"
case "$1 $2" in
"tool list") [[ -f "$state" ]] && cat "$state" ;;
"tool install") [[ -n "${STUB_INSTALL_FAIL:-}" ]] && exit 1
	for a in "$@"; do [[ "$a" == git+*@v* ]] && ver="${a##*@v}" && ver="${ver%%#*}"; done
	echo "crewchat-clients v${ver:?no pinned tag in the install spec}" >"$state"
	echo "- crewchat-mcp" >>"$state"; echo "- crewchat-doorbell" >>"$state"
	mkdir -p "$STUB_DIR/bin-tools" "$env/bin"; printf '#!/bin/sh\n' >"$STUB_DIR/bin-tools/crewchat-mcp"
	chmod +x "$STUB_DIR/bin-tools/crewchat-mcp"
	if [[ -z "${STUB_NO_DOORBELL:-}" ]]; then
		printf '#!/bin/sh\n[ "$1" = --help ] && exit "${STUB_DOORBELL_HELP_RC:-0}"\nexit 1\n' \
			>"$STUB_DIR/bin-tools/crewchat-doorbell"
		chmod +x "$STUB_DIR/bin-tools/crewchat-doorbell"
	fi
	printf 'mcp==%s\npydantic_core==2.50.1\n' "${STUB_INSTALLED_MCP:-1.30.0}" >"$env/freeze" ;;
"tool dir") if [[ "${3:-}" == --bin ]]; then echo "$STUB_DIR/bin-tools"; else echo "$STUB_DIR/tools"; fi ;;
"tool uninstall") rm -f "$state"; rm -rf "$env" ;;
"pip list") [[ -f "$env/freeze" ]] && cat "$env/freeze" ;;
export*) [[ -n "${STUB_EXPORT_FAIL:-}" ]] && exit 2
	while [[ $# -gt 0 ]]; do [[ "$1" == -o ]] && out="$2"; shift; done
	printf 'mcp==1.30.0 ; python_full_version >= "3.12"\npydantic-core==2.50.1\n' >"$out" ;;
esac
"""

_GIT_STUB = r"""#!/usr/bin/env bash
echo "git $*" >>"$STUB_DIR/calls"
[[ -n "${STUB_GIT_FAIL:-}" ]] && exit 128
[[ " $* " == *" clone "* ]] && mkdir -p "${@: -1}"
exit 0
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
    for name, body in (("uv", _UV_STUB), ("claude", _CLAUDE_STUB), ("git", _GIT_STUB)):
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


def _run(
    stubs: Path, sock: Path, *args: str, **extra_env: str
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(extra_env)
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


def _mutations(stubs: Path) -> list[str]:
    """Calls that change state. Read-only probes (`mcp get`, `tool list`) are allowed."""
    changing = ("uv tool install", "uv tool uninstall", "claude mcp add", "claude mcp remove")
    return [line for line in _calls(stubs).splitlines() if line.startswith(changing)]


def test_no_socket_skips_and_touches_nothing(stubs: Path, tmp_path: Path) -> None:
    r = _run(stubs, tmp_path / "absent.sock", "install")
    assert r.returncode == 0, r.stderr
    assert "skipped, no crewchat daemon" in r.stdout
    assert "Chat stays on disc-server" in r.stdout
    assert _mutations(stubs) == [], "nothing may be installed or registered without a daemon"


def test_unwritable_socket_skips(stubs: Path, live_socket: Path) -> None:
    if os.geteuid() == 0:
        pytest.skip("root can write any socket")
    live_socket.chmod(0)
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0, r.stderr
    assert "not writable" in r.stdout
    assert _mutations(stubs) == []


def test_socket_present_installs_pinned_tag_and_registers(stubs: Path, live_socket: Path) -> None:
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0, r.stdout + r.stderr
    calls = _calls(stubs)
    # SSH, never HTTPS: the repo is private and git to github.com never uses a token.
    assert (
        f"git -c advice.detachedHead=false clone -q --depth 1 --branch {_TAG} "
        "ssh://git@github.com/Wave-Engineering/mattermost-crew.git" in calls
    )
    assert "uv export -q --directory" in calls and "--frozen --package crewchat-clients" in calls
    # Constrained by the lock (#1332): a bare git-URL install re-resolves and took mcp 2.x.
    assert re.search(
        r"uv tool install -q --force --constraints \S+/constraints\.txt "
        r"git\+ssh://git@github\.com/Wave-Engineering/mattermost-crew\.git@"
        + re.escape(_TAG)
        + r"#subdirectory=packages/clients",
        calls,
    ), calls
    assert "https://" not in calls
    kept = stubs / "tools" / "crewchat-clients" / "kit-constraints.txt"
    assert "mcp==1.30.0" in kept.read_text(), "the lock's pins are kept for `check`"
    assert f"claude mcp add -s user crewchat -- {stubs}/bin-tools/crewchat-mcp" in calls
    assert "registered as crewchat" in r.stdout


@pytest.mark.parametrize("failure", ["STUB_GIT_FAIL", "STUB_EXPORT_FAIL"])
def test_no_lock_installs_nothing(stubs: Path, live_socket: Path, failure: str) -> None:
    r = _run(stubs, live_socket, "install", **{failure: "1"})
    assert r.returncode == 1
    assert f"couldn't export {_TAG}'s lock" in r.stdout
    assert _mutations(stubs) == [], "an unconstrained install is never the fallback"


def test_install_refuses_to_register_off_lock_environment(stubs: Path, live_socket: Path) -> None:
    r = _run(stubs, live_socket, "install", STUB_INSTALLED_MCP="2.3.0")
    assert r.returncode == 1
    assert "mcp is 2.3.0, the lock pins 1.30.0; not registering" in r.stdout
    assert "claude mcp add" not in _calls(stubs)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        ({"STUB_INSTALLED_MCP": "2.3.0"}, "mcp is 2.3.0, the lock pins 1.30.0"),
        ({"STUB_EXPORT_FAIL": "1"}, f"couldn't export {_TAG}'s lock"),
        ({"STUB_INSTALL_FAIL": "1"}, f"installing crewchat-clients {_TAG} failed"),
    ],
)
def test_failed_repair_removes_existing_registration(
    stubs: Path, live_socket: Path, failure: dict[str, str], message: str
) -> None:
    # A host registered by the first K-1 script: the reinstall that should repair it fails.
    _run(stubs, live_socket, "install")
    (stubs / "tools" / "crewchat-clients" / "kit-constraints.txt").unlink()
    r = _run(stubs, live_socket, "install", **failure)
    assert r.returncode == 1
    assert message in r.stdout
    assert not (stubs / "registered").exists(), "a broken shim must not stay registered"
    assert "removed the crewchat registration" in r.stdout


def test_check_reports_off_lock_environment(stubs: Path, live_socket: Path) -> None:
    _run(stubs, live_socket, "install")
    freeze = stubs / "tools" / "crewchat-clients" / "freeze"
    freeze.write_text(freeze.read_text().replace("mcp==1.30.0", "mcp==2.3.0"))
    r = _run(stubs, live_socket, "check")
    assert r.returncode == 1 and "mcp is 2.3.0, the lock pins 1.30.0" in r.stdout


def test_install_without_recorded_constraints_is_drift_and_repaired(
    stubs: Path, live_socket: Path
) -> None:
    # The state the first K-1 script left: right version, no lock record.
    _run(stubs, live_socket, "install")
    (stubs / "tools" / "crewchat-clients" / "kit-constraints.txt").unlink()
    r = _run(stubs, live_socket, "check")
    assert r.returncode == 1 and "installed without the lock's constraints" in r.stdout
    (stubs / "calls").unlink()
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0, r.stdout
    assert "uv tool install -q --force --constraints" in _calls(stubs)
    assert _run(stubs, live_socket, "check").returncode == 0


def test_install_removes_stale_registration_when_daemon_gone(
    stubs: Path, live_socket: Path, tmp_path: Path
) -> None:
    _run(stubs, live_socket, "install")
    assert (stubs / "registered").exists()
    r = _run(stubs, tmp_path / "absent.sock", "install")
    assert r.returncode == 0
    assert not (stubs / "registered").exists(), "a stale registration must not survive"
    assert "removed the stale crewchat registration" in r.stdout
    # And --check is clean again: the drift install pointed at is gone.
    assert _run(stubs, tmp_path / "absent.sock", "check").returncode == 0


def test_dry_run_reports_but_keeps_stale_registration(
    stubs: Path, live_socket: Path, tmp_path: Path
) -> None:
    _run(stubs, live_socket, "install")
    r = _run(stubs, tmp_path / "absent.sock", "install", "--dry-run")
    assert r.returncode == 0, r.stderr
    assert "(dry-run) claude mcp remove" in r.stdout
    assert (stubs / "registered").exists()


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
    assert r.returncode == 0 and "(registered; crewchat-doorbell runs)" in r.stdout, r.stdout
    # Registered but the daemon has gone: drift, because the skills would pick a dead path.
    r = _run(stubs, tmp_path / "absent.sock", "check")
    assert r.returncode == 1 and "registered, but no crewchat daemon" in r.stdout


def test_pin() -> None:
    # K-2 (#1336) needs v0.2.1: crewchat-doorbell drops a repeated event_id, so exit 0 is
    # always a new event, and the kiosk review's event_id carries the transcript's generation.
    assert _TAG == "v0.2.1"


def test_install_without_doorbell_does_not_register(stubs: Path, live_socket: Path) -> None:
    r = _run(stubs, live_socket, "install", STUB_NO_DOORBELL="1")
    assert r.returncode == 1
    assert "crewchat-doorbell missing after install; not registering" in r.stdout
    assert not (stubs / "registered").exists(), "chat_send without a doorbell is a deaf agent"


def test_install_with_broken_doorbell_removes_registration(
    stubs: Path, live_socket: Path
) -> None:
    _run(stubs, live_socket, "install")
    assert (stubs / "registered").exists()
    (stubs / "calls").unlink()
    r = _run(stubs, live_socket, "install", STUB_DOORBELL_HELP_RC="1")
    assert r.returncode == 1
    # At the pinned version, a doorbell that won't run is a broken environment: a reinstall
    # is tried, and when that doesn't fix it the registration goes.
    assert "uv tool install -q --force" in _calls(stubs)
    assert "crewchat-doorbell --help failed" in r.stdout
    assert not (stubs / "registered").exists()


def test_reinstall_repairs_missing_doorbell(stubs: Path, live_socket: Path) -> None:
    _run(stubs, live_socket, "install")
    (stubs / "bin-tools" / "crewchat-doorbell").unlink()
    (stubs / "calls").unlink()
    r = _run(stubs, live_socket, "install")
    assert r.returncode == 0, r.stdout
    assert "uv tool install -q --force" in _calls(stubs)
    assert "registered as crewchat (crewchat-mcp, crewchat-doorbell)" in r.stdout


@pytest.mark.parametrize("breakage", ["missing", "broken"])
def test_check_flags_unusable_doorbell(stubs: Path, live_socket: Path, breakage: str) -> None:
    _run(stubs, live_socket, "install")
    env: dict[str, str] = {}
    if breakage == "missing":
        (stubs / "bin-tools" / "crewchat-doorbell").unlink()
    else:
        env["STUB_DOORBELL_HELP_RC"] = "1"
    r = _run(stubs, live_socket, "check", **env)
    assert r.returncode == 1
    assert ("crewchat-doorbell missing" if breakage == "missing" else "--help failed") in r.stdout


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
