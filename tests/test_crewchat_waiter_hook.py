"""#1420: chat delivery that no agent has to arm.

`crewchat-waiter` (mattermost-crew#204) is run by Claude Code from `asyncRewake` hooks on
SessionStart and Stop. The kit's part is the registration, a guard that makes registering it
safe on any host, and docs that stop telling agents to arm the doorbell where the hook is in.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_TEMPLATE = _REPO / "config" / "settings.template.json"
_GUARD = _REPO / "scripts" / "hooks" / "workflow" / "crewchat-waiter.sh"
_CHAT_TOOLS = _REPO / "docs" / "chat-tools.md"
_GUARD_CMD = "~/.claude/scripts/hooks/workflow/crewchat-waiter.sh"
_SYSTEM_PATH = "/usr/bin:/bin"  # no uv tool dir, no crewchat-waiter


def _groups(event: str) -> list[dict]:
    hooks = json.loads(_TEMPLATE.read_text())["hooks"][event]
    return [g for g in hooks if any(h.get("command") == _GUARD_CMD for h in g["hooks"])]


@pytest.mark.parametrize("event", ["SessionStart", "Stop"])
def test_the_template_registers_the_waiter_on_start_and_stop(event: str) -> None:
    """One group, of its own (the template's rule, so the settings merge can't duplicate it),
    asyncRewake so the harness runs it in the background and wakes the model on exit 2, and a
    timeout long enough that the harness never kills a waiter that is simply waiting."""
    [group] = _groups(event)
    [hook] = group["hooks"]
    assert hook["type"] == "command"
    assert hook["asyncRewake"] is True
    assert hook["timeout"] >= 86400
    if event == "SessionStart":
        # startup, resume, /clear and compact all begin a session context that needs a waiter
        assert set(group["matcher"].split("|")) == {"startup", "resume", "clear", "compact"}


def test_the_installer_merge_keeps_the_rewake_flags_and_adds_nothing_twice(tmp_path: Path) -> None:
    """What reaches a host is what `./install` merges, not the template: a merge that dropped
    `asyncRewake` or `timeout` would turn the waiter into a hook that blocks the turn's end, and
    one that appended it again would run two per event."""
    settings = tmp_path / "settings.json"
    settings.write_text('{"hooks": {}}')
    for _ in range(2):
        subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; merge_settings "$2" "$3"',
                "_",
                str(_REPO / "scripts" / "lib" / "settings-merge.sh"),
                str(_TEMPLATE),
                str(settings),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
    merged = json.loads(settings.read_text())["hooks"]
    for event in ("SessionStart", "Stop"):
        ours = [
            h
            for g in merged[event]
            for h in g["hooks"]
            if h.get("command") == _GUARD_CMD
        ]
        assert len(ours) == 1, event
        assert ours[0]["asyncRewake"] is True and ours[0]["timeout"] >= 86400


def test_the_guard_is_executable_and_in_the_hooks_directory() -> None:
    assert _GUARD.is_file()
    assert _GUARD.stat().st_mode & stat.S_IXUSR


def _run_guard(
    tmp_path: Path, *args: str, path: str, stub: Path | None = None
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": path, "HOME": str(home)}
    if stub is not None:
        env["PATH"] = f"{stub.parent}:{path}"
    return subprocess.run(
        ["bash", str(_GUARD), *args], env=env, capture_output=True, text=True, timeout=30
    )


def _stub(directory: Path, body: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "crewchat-waiter"
    path.write_text(f"#!/bin/sh\n{body}\n")
    path.chmod(0o755)
    return path


def test_the_guard_is_silent_where_there_is_no_waiter(tmp_path: Path) -> None:
    """A host without the crewchat daemon: exit 0 and no output. Only exit 2 wakes the model."""
    done = _run_guard(tmp_path, path=_SYSTEM_PATH)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_the_guard_runs_the_waiter_and_passes_its_exit_code(tmp_path: Path) -> None:
    """exec, so the waiter's exit 2 and its stderr (what the model reads) are the hook's own."""
    stub = _stub(tmp_path / "bin", 'echo "wake $*" >&2\nexit 2')
    done = _run_guard(tmp_path, "--x", path=_SYSTEM_PATH, stub=stub)
    assert done.returncode == 2
    assert done.stderr.strip() == "wake --x"
    assert done.stdout == ""


def test_the_guard_finds_a_uv_tool_install_off_the_path(tmp_path: Path) -> None:
    """`uv tool install` puts the binary in ~/.local/bin, which a hook's PATH may not have."""
    _stub(tmp_path / "home" / ".local" / "bin", "exit 2")
    done = _run_guard(tmp_path, path=_SYSTEM_PATH)
    assert done.returncode == 2


def test_the_guard_passes_a_quiet_exit_through(tmp_path: Path) -> None:
    """A second waiter (the Stop hook while one still waits) exits 0: so does the hook."""
    stub = _stub(tmp_path / "bin", "exit 0")
    assert _run_guard(tmp_path, path=_SYSTEM_PATH, stub=stub).returncode == 0


def _doorbell_section() -> str:
    text = _CHAT_TOOLS.read_text()
    start = text.index("## Doorbell: `crewchat-doorbell` or the one-shots")
    return text[start : text.index("### Kiosk review", start)]


def test_the_doorbell_doc_says_nothing_needs_arming_where_the_hook_is_in() -> None:
    section = _doorbell_section()
    assert "there is nothing to arm" in section
    assert "crewchat-waiter.sh" in section and "asyncRewake" in section
    # the fallback survives for a host without the hook, and exit 5 is documented
    assert "hook is not installed" in section
    assert "| 5 |" in section and "already delivers" in section
    assert "except 1 and 5" in section


def test_the_doorbell_doc_matches_the_backend_alarm_change() -> None:
    """mattermost-crew#202: one alarm for an outage over ten minutes, not one event per flip."""
    section = _doorbell_section()
    assert "more than 10 minutes" in section
    assert "The gap is replayed when it reconnects" not in section


@pytest.mark.parametrize(
    "path",
    ["CLAUDE.md", "docs/troubleshooting.md", "docs/skill-reference.md", "skills/disc/SKILL.md"],
)
def test_other_docs_no_longer_tell_agents_to_arm_unconditionally(path: str) -> None:
    text = (_REPO / path).read_text()
    assert "crewchat-waiter" in text or "waiter hook" in text, path
