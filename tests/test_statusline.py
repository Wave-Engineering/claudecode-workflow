"""Tests for config/statusline-command.sh — two-line layout, per-session
indicators, Unicode avatar, and color changes.

Strategy: run the real shell script via subprocess with crafted JSON stdin
and mock identity/session files in a temp directory.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# Path to the statusline script under test
STATUSLINE_SCRIPT = (
    Path(__file__).resolve().parent.parent / "config" / "statusline-command.sh"
)


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from text."""
    return re.sub(r"\033\[[0-9;]*m", "", text)


def _run_statusline(
    input_json: dict,
    *,
    cwd: str | Path | None = None,
    env_override: dict[str, str] | None = None,
) -> str:
    """Run the statusline script with JSON piped to stdin.

    Returns raw stdout (with ANSI codes intact).
    """
    env = os.environ.copy()
    if env_override:
        env.update(env_override)

    result = subprocess.run(
        ["bash", str(STATUSLINE_SCRIPT)],
        input=json.dumps(input_json),
        capture_output=True,
        text=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )
    # The script should always succeed
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    return result.stdout


class TestStatuslineTwoLines:
    """Verify the script outputs exactly two lines."""

    def test_statusline_two_lines_minimal(self, tmp_path: Path):
        """With minimal input (just cwd), output has exactly 2 lines."""
        output = _run_statusline(
            {"cwd": str(tmp_path)},
            cwd=tmp_path,
        )
        lines = output.split("\n")
        # Two content lines plus a trailing empty string from the final \n
        non_empty = [l for l in lines if l]
        # Should have at least 1 line (line 1 with pwd); line 2 may be empty
        # if no git info, no context, no model — but the script always prints
        # the second \n, so we get 2 lines (second may be blank)
        assert output.count("\n") == 2, (
            f"Expected exactly 2 newlines (two-line layout), got {output.count(chr(10))}: {output!r}"
        )

    def test_statusline_two_lines_with_all_fields(self, tmp_path: Path):
        """With git, model, and context data, output has exactly 2 lines."""
        # Init a git repo so the script finds git info
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        # Create an initial commit so branch shows up
        (tmp_path / "README.md").write_text("hello")
        subprocess.run(
            ["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        output = _run_statusline(
            {
                "cwd": str(tmp_path),
                "model": {"display_name": "Claude Sonnet"},
                "context_window": {"remaining_percentage": 72.5},
            },
            cwd=tmp_path,
        )
        assert output.count("\n") == 2, (
            f"Expected 2 lines, got: {output!r}"
        )

        clean = _strip_ansi(output)
        lines = clean.split("\n")

        # Line 1 should contain the path
        assert str(tmp_path) in lines[0] or "~" in lines[0]

        # Line 2 should contain git info, context remaining, and model
        assert "ctx remaining:" in lines[1]
        assert "Claude Sonnet" in lines[1]

    def test_line1_has_path_line2_has_git(self, tmp_path: Path):
        """Path is on line 1, git info is on line 2."""
        subprocess.run(
            ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )
        (tmp_path / "README.md").write_text("hello")
        subprocess.run(
            ["git", "add", "."], cwd=str(tmp_path), capture_output=True, check=True
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(tmp_path),
            capture_output=True,
            check=True,
        )

        output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
        clean = _strip_ansi(output)
        lines = clean.split("\n")

        repo_name = tmp_path.name
        # Line 1: path present
        assert str(tmp_path) in lines[0] or tmp_path.name in lines[0]
        # Line 2: git repo @ branch
        assert f"{repo_name} @" in lines[1] or "@ " in lines[1]
        # Line 1 should NOT have git repo info
        assert f"{repo_name} @" not in lines[0]


class TestStatuslineSessionIndicator:
    """Verify per-session indicator file is read and rendered first on line 1."""

    def test_statusline_session_indicator(self, tmp_path: Path):
        """Per-session file indicators appear as the first element on line 1."""
        # Create a mock agent identity file
        project_root = str(tmp_path)
        import hashlib

        dir_hash = hashlib.md5(project_root.encode()).hexdigest()
        agent_file = Path(f"/tmp/claude-agent-{dir_hash}.json")
        agent_file.write_text(
            json.dumps(
                {
                    "dev_team": "test-team",
                    "dev_name": "test-agent",
                    "dev_avatar": "🧠",
                }
            )
        )

        # Create per-session indicator file
        session_file = Path("/tmp/claude-statusline-test-agent.json")
        session_file.write_text(json.dumps({"indicators": ["● REC", "W2 3/5"]}))

        try:
            # Init git so the script can resolve project root
            subprocess.run(
                ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
            )

            output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
            clean = _strip_ansi(output)
            lines = clean.split("\n")

            # Indicators should be the first thing on line 1
            assert lines[0].startswith("● REC W2 3/5"), (
                f"Expected indicators first on line 1, got: {lines[0]!r}"
            )
        finally:
            agent_file.unlink(missing_ok=True)
            session_file.unlink(missing_ok=True)

    def test_no_session_file_no_indicators(self, tmp_path: Path):
        """When no session file exists, line 1 starts with the path."""
        output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
        clean = _strip_ansi(output)
        lines = clean.split("\n")

        # Should start with the path (or ~-substituted path), not indicators
        assert "● REC" not in lines[0]
        # The path should be the first visible content
        assert str(tmp_path) in lines[0] or "~" in lines[0] or tmp_path.name in lines[0]


class TestStatuslineUnicodeAvatar:
    """Verify Unicode emoji renders in output (not colon notation)."""

    def test_statusline_unicode_avatar(self, tmp_path: Path):
        """Unicode emoji from identity file renders on line 1."""
        import hashlib

        project_root = str(tmp_path)
        dir_hash = hashlib.md5(project_root.encode()).hexdigest()
        agent_file = Path(f"/tmp/claude-agent-{dir_hash}.json")
        agent_file.write_text(
            json.dumps(
                {
                    "dev_team": "test-team",
                    "dev_name": "beacon",
                    "dev_avatar": "📡",
                }
            )
        )

        try:
            subprocess.run(
                ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
            )

            output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
            clean = _strip_ansi(output)
            lines = clean.split("\n")

            # Unicode emoji should be present on line 1
            assert "📡" in lines[0], (
                f"Expected Unicode emoji 📡 on line 1, got: {lines[0]!r}"
            )
            # Dev name should also be on line 1
            assert "beacon" in lines[0]
            # No colon notation should appear
            assert ":satellite:" not in output
        finally:
            agent_file.unlink(missing_ok=True)


class TestStatuslineColors:
    """Verify color codes for dev-name and context remaining."""

    def test_dev_name_fuchsia(self, tmp_path: Path):
        """Dev-name renders with fuchsia color (38;5;13)."""
        import hashlib

        project_root = str(tmp_path)
        dir_hash = hashlib.md5(project_root.encode()).hexdigest()
        agent_file = Path(f"/tmp/claude-agent-{dir_hash}.json")
        agent_file.write_text(
            json.dumps(
                {
                    "dev_team": "test-team",
                    "dev_name": "beacon",
                    "dev_avatar": "📡",
                }
            )
        )

        try:
            subprocess.run(
                ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
            )

            output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
            # Fuchsia = \033[38;5;13m
            assert "\033[38;5;13m" in output, (
                f"Expected fuchsia ANSI code for dev-name, got: {output!r}"
            )
        finally:
            agent_file.unlink(missing_ok=True)

    def test_ctx_remaining_green_when_safe(self, tmp_path: Path):
        """Context remaining >25% renders green (01;32)."""
        output = _run_statusline(
            {
                "cwd": str(tmp_path),
                "context_window": {"remaining_percentage": 50.0},
            },
            cwd=tmp_path,
        )
        # Green = \033[01;32m
        assert "\033[01;32m" in output, (
            f"Expected green ANSI code for safe ctx remaining, got: {output!r}"
        )
        # Should NOT contain cyan for ctx remaining
        clean = _strip_ansi(output)
        assert "ctx remaining: 50%" in clean

    def test_ctx_remaining_yellow_when_low(self, tmp_path: Path):
        """Context remaining <=25% renders yellow (33)."""
        output = _run_statusline(
            {
                "cwd": str(tmp_path),
                "context_window": {"remaining_percentage": 20.0},
            },
            cwd=tmp_path,
        )
        assert "\033[33m" in output, (
            f"Expected yellow ANSI code for low ctx remaining, got: {output!r}"
        )

    def test_ctx_remaining_red_when_critical(self, tmp_path: Path):
        """Context remaining <=13% renders red (31)."""
        output = _run_statusline(
            {
                "cwd": str(tmp_path),
                "context_window": {"remaining_percentage": 10.0},
            },
            cwd=tmp_path,
        )
        assert "\033[31m" in output, (
            f"Expected red ANSI code for critical ctx remaining, got: {output!r}"
        )
