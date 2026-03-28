"""Tests for scripts/afk-notify Stop hook.

Exercises the real afk-notify script via subprocess, mocking only true
external boundaries: loginctl (system service), discord-bot (external API),
claude (external API), vox (external TTS service), and git (filesystem).

All tests pipe JSON payloads to the real script and verify behavior through
exit codes, file mutations, and captured stdout/stderr from mock wrappers.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent
_AFK_NOTIFY = str(_REPO_DIR / "scripts" / "afk-notify")

_HAS_BASH = shutil.which("bash") is not None
_HAS_JQ = shutil.which("jq") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_JQ = pytest.mark.skipif(not _HAS_JQ, reason="jq not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sandbox(tmp_path: Path) -> Path:
    """Create a sandbox with mock commands and agent identity file.

    Layout::

        tmp/
          bin/          <- prepended to PATH (mock commands go here)
          project/      <- fake project root (git init)
          agent.json    <- agent identity file
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    project_dir = tmp_path / "project"
    project_dir.mkdir()

    # Initialize a git repo so git rev-parse --show-toplevel works
    subprocess.run(
        ["git", "init"],
        cwd=str(project_dir),
        capture_output=True,
        check=True,
    )

    return tmp_path


def _write_agent_file(sandbox: Path, extra: dict | None = None) -> Path:
    """Write agent identity JSON keyed to the sandbox project root.

    Returns the path to the identity file.
    """
    project_root = str(sandbox / "project")
    dir_hash = subprocess.run(
        ["bash", "-c", f"echo -n '{project_root}' | md5sum | cut -d' ' -f1"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    agent_data = {
        "dev_team": "cc-workflow",
        "dev_name": "test-agent",
        "dev_avatar": ":robot_face:",
    }
    if extra:
        agent_data.update(extra)

    agent_file = Path(f"/tmp/claude-agent-{dir_hash}.json")
    agent_file.write_text(json.dumps(agent_data))
    return agent_file


def _create_mock(bin_dir: Path, name: str, script: str) -> Path:
    """Create a mock executable in bin_dir."""
    mock_path = bin_dir / name
    mock_path.write_text(script)
    mock_path.chmod(mock_path.stat().st_mode | stat.S_IEXEC)
    return mock_path


def _make_env(sandbox: Path) -> dict[str, str]:
    """Build environment with sandbox bin/ prepended to PATH."""
    env = os.environ.copy()
    bin_dir = str(sandbox / "bin")
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env


def _run_afk_notify(
    payload: dict,
    sandbox: Path,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    """Run afk-notify with the given JSON payload on stdin.

    Returns (returncode, stdout, stderr).
    """
    if env is None:
        env = _make_env(sandbox)

    result = subprocess.run(
        ["bash", _AFK_NOTIFY],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestLoopGuard:
    """Exit 0 immediately when stop_hook_active is true."""

    def test_exits_zero_when_stop_active(self, sandbox: Path) -> None:
        payload = {
            "stop_hook_active": True,
            "last_assistant_message": "I finished the work.",
            "cwd": str(sandbox / "project"),
        }
        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

    def test_exits_zero_when_stop_active_string(self, sandbox: Path) -> None:
        """String 'true' should also trigger the loop guard."""
        payload = {
            "stop_hook_active": "true",
            "last_assistant_message": "I finished the work.",
            "cwd": str(sandbox / "project"),
        }
        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestUnlockedNoop:
    """Exit 0 when the desktop is unlocked (LockedHint != yes)."""

    def test_exits_zero_when_unlocked(self, sandbox: Path) -> None:
        # Mock loginctl to report unlocked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "no"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Done refactoring.",
            "cwd": str(sandbox / "project"),
        }
        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestNoIdentity:
    """Exit 0 when agent identity file is missing."""

    def test_exits_zero_when_no_identity(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        # Do NOT create the agent identity file
        # Ensure any old one is removed
        project_root = str(sandbox / "project")
        dir_hash = subprocess.run(
            ["bash", "-c", f"echo -n '{project_root}' | md5sum | cut -d' ' -f1"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        agent_file = Path(f"/tmp/claude-agent-{dir_hash}.json")
        if agent_file.exists():
            agent_file.unlink()

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Done.",
            "cwd": str(sandbox / "project"),
        }
        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestEmptyMessage:
    """Exit 0 when last_assistant_message is empty."""

    def test_exits_zero_when_empty_message(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        # Create agent identity
        agent_file = _write_agent_file(sandbox)

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "",
            "cwd": str(sandbox / "project"),
        }
        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestEmptyCwd:
    """Exit 0 when cwd is missing from input."""

    def test_exits_zero_when_no_cwd(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Done.",
        }
        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestThreadCreation:
    """Creates Discord thread on first invocation and reuses on subsequent."""

    def test_creates_thread_and_posts(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        # Mock discord-bot: create-thread returns thread ID, send succeeds
        log_file = sandbox / "discord-bot.log"
        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            f'echo "$@" >> "{log_file}"\n'
            'if [[ "$1" == "create-thread" ]]; then\n'
            '    echo "Created thread: test-agent — cc-workflow (999888777)"\n'
            'fi\n',
        )

        # Mock claude to return a summary
        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\n'
            'echo "The agent completed the refactoring task successfully."\n',
        )

        # Mock vox to create a dummy wav file
        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\n'
            'while [[ $# -gt 0 ]]; do\n'
            '    case "$1" in\n'
            '        --output) touch "$2"; shift 2;;\n'
            '        *) shift;;\n'
            '    esac\n'
            'done\n',
        )

        agent_file = _write_agent_file(sandbox)

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "I completed the refactoring of the module.",
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify discord-bot was called with create-thread
        log_content = log_file.read_text()
        assert "create-thread" in log_content, (
            f"Expected discord-bot create-thread call. Log: {log_content}"
        )
        # Verify discord-bot send was called
        assert "send" in log_content, (
            f"Expected discord-bot send call. Log: {log_content}"
        )

        # Verify thread_id was written back to agent file
        updated_agent = json.loads(agent_file.read_text())
        assert "thread_id" in updated_agent, (
            f"thread_id not written to agent file. Contents: {updated_agent}"
        )
        assert updated_agent["thread_id"] == "999888777", (
            f"Expected thread_id 999888777, got {updated_agent['thread_id']}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()

    def test_reuses_existing_thread(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        # Mock discord-bot: send only (no create-thread needed)
        log_file = sandbox / "discord-bot.log"
        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            f'echo "$@" >> "{log_file}"\n',
        )

        # Mock claude
        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\n'
            'echo "Summary of work done."\n',
        )

        # Mock vox (fail — to test text-only fallback)
        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\nexit 1\n',
        )

        # Create agent file WITH existing thread_id
        agent_file = _write_agent_file(sandbox, {"thread_id": "111222333"})

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Tests are passing now.",
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify create-thread was NOT called (thread_id already existed)
        log_content = log_file.read_text()
        assert "create-thread" not in log_content, (
            f"create-thread should not be called when thread_id exists. Log: {log_content}"
        )
        # Verify send was called with existing thread_id
        assert "send" in log_content, (
            f"Expected discord-bot send call. Log: {log_content}"
        )
        assert "111222333" in log_content, (
            f"Expected existing thread_id in send call. Log: {log_content}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestHaikuFallback:
    """Falls back to truncated text when claude/Haiku is unavailable."""

    def test_fallback_on_haiku_failure(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        # Mock discord-bot
        log_file = sandbox / "discord-bot.log"
        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            f'echo "$@" >> "{log_file}"\n'
            'if [[ "$1" == "create-thread" ]]; then\n'
            '    echo "Created thread (555666777)"\n'
            'fi\n',
        )

        # Mock claude to FAIL (simulates Haiku unavailable)
        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\nexit 1\n',
        )

        # Mock vox to fail
        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\nexit 1\n',
        )

        agent_file = _write_agent_file(sandbox)

        # Create a long message (> 200 chars) to test truncation
        long_msg = "A" * 250

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": long_msg,
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify discord-bot send was called (fallback summary was used)
        log_content = log_file.read_text()
        assert "send" in log_content, (
            f"Expected discord-bot send call with fallback summary. Log: {log_content}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestVoiceMemoAttach:
    """Posts with voice memo when vox succeeds, text-only when it fails."""

    def test_attach_when_vox_succeeds(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        log_file = sandbox / "discord-bot.log"
        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            f'echo "$@" >> "{log_file}"\n'
            'if [[ "$1" == "create-thread" ]]; then\n'
            '    echo "Created thread (444555666)"\n'
            'fi\n',
        )

        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\n'
            'echo "Summary text."\n',
        )

        # Mock vox to create a file
        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\n'
            'while [[ $# -gt 0 ]]; do\n'
            '    case "$1" in\n'
            '        --output) echo "audio" > "$2"; shift 2;;\n'
            '        *) shift;;\n'
            '    esac\n'
            'done\n',
        )

        agent_file = _write_agent_file(sandbox)

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Deployment complete.",
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify --attach was used
        log_content = log_file.read_text()
        assert "--attach" in log_content, (
            f"Expected --attach flag in discord-bot send call. Log: {log_content}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()

    def test_text_only_when_vox_fails(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        log_file = sandbox / "discord-bot.log"
        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            f'echo "$@" >> "{log_file}"\n'
            'if [[ "$1" == "create-thread" ]]; then\n'
            '    echo "Created thread (333444555)"\n'
            'fi\n',
        )

        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\n'
            'echo "Summary text."\n',
        )

        # Mock vox to FAIL
        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\nexit 1\n',
        )

        agent_file = _write_agent_file(sandbox)

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Tests passed.",
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify send was called but WITHOUT --attach
        log_content = log_file.read_text()
        assert "send" in log_content, (
            f"Expected discord-bot send call. Log: {log_content}"
        )
        assert "--attach" not in log_content, (
            f"--attach should not be present when vox fails. Log: {log_content}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMessageSigning:
    """Messages are signed with agent identity."""

    def test_signed_message_format(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        # Mock discord-bot that captures the message content
        # discord-bot send <thread_id> <message> — $3 is the message body
        msg_file = sandbox / "sent-message.txt"
        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "create-thread" ]]; then\n'
            '    echo "Created thread (777888999)"\n'
            'elif [[ "$1" == "send" ]]; then\n'
            f'    echo "$3" > "{msg_file}"\n'
            'fi\n',
        )

        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\n'
            'echo "Agent finished the work."\n',
        )

        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\nexit 1\n',
        )

        agent_file = _write_agent_file(sandbox)

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "All done.",
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify the message was signed correctly
        assert msg_file.exists(), "discord-bot send was not called"
        sent_msg = msg_file.read_text()
        assert "**test-agent**" in sent_msg, (
            f"Expected dev_name in signature. Got: {sent_msg}"
        )
        assert ":robot_face:" in sent_msg, (
            f"Expected dev_avatar in signature. Got: {sent_msg}"
        )
        assert "cc-workflow" in sent_msg, (
            f"Expected dev_team in signature. Got: {sent_msg}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMemoCleanup:
    """Temp audio file is cleaned up after posting."""

    def test_memo_file_deleted_after_post(self, sandbox: Path) -> None:
        # Mock loginctl to report locked
        _create_mock(
            sandbox / "bin",
            "loginctl",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "show-session" ]]; then\n'
            '    echo "yes"\n'
            'else\n'
            '    echo "  42 1000 $USER seat0 "\n'
            'fi\n',
        )

        _create_mock(
            sandbox / "bin",
            "discord-bot",
            '#!/usr/bin/env bash\n'
            'if [[ "$1" == "create-thread" ]]; then\n'
            '    echo "Created thread (123456789)"\n'
            'fi\n',
        )

        _create_mock(
            sandbox / "bin",
            "claude",
            '#!/usr/bin/env bash\n'
            'echo "Summary."\n',
        )

        # Mock vox to create a real file
        _create_mock(
            sandbox / "bin",
            "vox",
            '#!/usr/bin/env bash\n'
            'while [[ $# -gt 0 ]]; do\n'
            '    case "$1" in\n'
            '        --output) echo "audio-data" > "$2"; shift 2;;\n'
            '        *) shift;;\n'
            '    esac\n'
            'done\n',
        )

        agent_file = _write_agent_file(sandbox)

        # Compute the expected memo file path
        project_root = str(sandbox / "project")
        dir_hash = subprocess.run(
            ["bash", "-c", f"echo -n '{project_root}' | md5sum | cut -d' ' -f1"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        memo_path = Path(f"/tmp/afk-memo-{dir_hash}.wav")

        payload = {
            "stop_hook_active": False,
            "last_assistant_message": "Work complete.",
            "cwd": str(sandbox / "project"),
        }

        rc, out, err = _run_afk_notify(payload, sandbox)
        assert rc == 0, f"Expected exit 0, got {rc}. stderr: {err}"

        # Verify memo file was cleaned up
        assert not memo_path.exists(), (
            f"Memo file should be deleted after posting: {memo_path}"
        )

        # Cleanup
        if agent_file.exists():
            agent_file.unlink()


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestSettingsTemplate:
    """Stop hook is wired in config/settings.template.json."""

    def test_stop_hook_present(self) -> None:
        settings_path = _REPO_DIR / "config" / "settings.template.json"
        settings = json.loads(settings_path.read_text())

        assert "hooks" in settings, "hooks key missing from settings template"
        assert "Stop" in settings["hooks"], "Stop hook missing from settings template"

        stop_hooks = settings["hooks"]["Stop"]
        assert len(stop_hooks) > 0, "Stop hook array is empty"

        # Find the afk-notify hook
        afk_hook = None
        for matcher_block in stop_hooks:
            for hook in matcher_block.get("hooks", []):
                if "afk-notify" in hook.get("command", ""):
                    afk_hook = hook
                    break

        assert afk_hook is not None, (
            "afk-notify command not found in Stop hooks"
        )
        assert afk_hook["type"] == "command", (
            f"Expected type 'command', got '{afk_hook['type']}'"
        )
        assert afk_hook["command"] == "~/.local/bin/afk-notify", (
            f"Expected command '~/.local/bin/afk-notify', got '{afk_hook['command']}'"
        )


@_SKIP_NO_BASH
class TestScriptIsExecutable:
    """scripts/afk-notify exists and is executable."""

    def test_executable(self) -> None:
        script_path = _REPO_DIR / "scripts" / "afk-notify"
        assert script_path.exists(), "scripts/afk-notify does not exist"
        assert os.access(str(script_path), os.X_OK), (
            "scripts/afk-notify is not executable"
        )


@_SKIP_NO_BASH
class TestInstallDiscovery:
    """install.sh auto-discovers afk-notify in scripts/."""

    def test_install_discovers_script(self) -> None:
        """Verify afk-notify appears in the scripts/ directory as a plain
        file (not a directory), which is what install.sh iterates."""
        script_path = _REPO_DIR / "scripts" / "afk-notify"
        assert script_path.is_file(), (
            "afk-notify must be a plain file in scripts/ for install.sh discovery"
        )
