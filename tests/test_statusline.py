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
import tempfile
import uuid
from pathlib import Path

import pytest

# Path to the statusline script under test
STATUSLINE_SCRIPT = (
    Path(__file__).resolve().parent.parent / "config" / "statusline-command.sh"
)


# One throwaway context-state dir for the whole module, removed at exit (#1225):
# the script persists per-session readings, and a test must never write into
# the real ~/.claude/state/context.
_CTX_STATE = tempfile.TemporaryDirectory(prefix="statusline-ctx-")


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
    # The script persists remaining context per session (#1225). Without this,
    # every test that passes a session_id would write into the REAL
    # ~/.claude/state/context of whoever runs the suite.
    env["CLAUDE_CONTEXT_STATE_DIR"] = _CTX_STATE.name
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
        # Create a mock agent identity file at the project-local durable path
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        agent_file = claude_dir / "agent-identity.json"
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
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        agent_file = claude_dir / "agent-identity.json"
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
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        agent_file = claude_dir / "agent-identity.json"
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

    def test_statusline_falls_back_to_tmp_identity(self, tmp_path: Path):
        """When project-local identity file is absent, legacy /tmp path is used."""
        import hashlib

        project_root = str(tmp_path)
        dir_hash = hashlib.md5(project_root.encode()).hexdigest()
        legacy_file = Path(f"/tmp/claude-agent-{dir_hash}.json")
        legacy_file.write_text(
            json.dumps(
                {
                    "dev_team": "test-team",
                    "dev_name": "legacy-beacon",
                    "dev_avatar": "📡",
                }
            )
        )

        try:
            subprocess.run(
                ["git", "init"], cwd=str(tmp_path), capture_output=True, check=True
            )

            # No .claude/agent-identity.json written — only the legacy /tmp file exists
            output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
            clean = _strip_ansi(output)

            assert "legacy-beacon" in clean, (
                f"Expected dev-name from legacy /tmp fallback, got: {clean!r}"
            )
        finally:
            legacy_file.unlink(missing_ok=True)

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


class TestStatuslineNerfDarts:
    """mcp-server-nerf#32: nerf stores darts as percent of the window used under
    `darts_pct`. The ctx segment colors by them when present, still honours an
    older nerf's absolute-token `darts`, and falls back to 13%/25% otherwise."""

    GREEN, YELLOW, ORANGE, RED = "\033[01;32m", "\033[33m", "\033[38;5;208m", "\033[31m"

    def _render(self, tmp_path: Path, nerf: dict | None, remaining: float, used_tokens: int = 0) -> str:
        sid = f"nerf-darts-{uuid.uuid4().hex[:12]}"
        cfg = Path(f"/tmp/nerf-{sid}.json")
        if nerf is not None:
            cfg.write_text(json.dumps(nerf))
        try:
            output = _run_statusline(
                {
                    "cwd": str(tmp_path),
                    "session_id": sid,
                    "context_window": {
                        "remaining_percentage": remaining,
                        "total_input_tokens": used_tokens,
                        "total_output_tokens": 0,
                    },
                },
                cwd=tmp_path,
            )
        finally:
            cfg.unlink(missing_ok=True)
        # The ctx segment is the color code immediately before "ctx remaining".
        return output.split("ctx remaining")[0][-16:]

    PCT = {"darts_pct": {"soft": 51, "hard": 63, "ouch": 85}}

    def test_darts_pct_green_below_soft(self, tmp_path: Path):
        assert self.GREEN in self._render(tmp_path, self.PCT, remaining=60)  # 40% used

    def test_darts_pct_yellow_at_soft(self, tmp_path: Path):
        assert self.YELLOW in self._render(tmp_path, self.PCT, remaining=40)  # 60% used

    def test_darts_pct_orange_at_hard(self, tmp_path: Path):
        assert self.ORANGE in self._render(tmp_path, self.PCT, remaining=30)  # 70% used

    def test_darts_pct_red_at_ouch(self, tmp_path: Path):
        assert self.RED in self._render(tmp_path, self.PCT, remaining=10)  # 90% used

    def test_darts_pct_is_window_size_independent(self, tmp_path: Path):
        # 70% used is "hard" whether the window is 200k (140k tokens) or 1M (700k).
        for tokens in (140_000, 700_000):
            assert self.ORANGE in self._render(tmp_path, self.PCT, remaining=30, used_tokens=tokens)

    def test_legacy_token_darts_still_honoured(self, tmp_path: Path):
        legacy = {"darts": {"soft": 120_000, "hard": 150_000, "ouch": 200_000}}
        assert self.ORANGE in self._render(tmp_path, legacy, remaining=50, used_tokens=160_000)

    def test_no_nerf_config_uses_legacy_thresholds(self, tmp_path: Path):
        # 20% remaining is yellow under the 13%/25% fallback, though 80% used
        # would be orange against the default darts_pct.
        assert self.YELLOW in self._render(tmp_path, None, remaining=20)


class TestStatuslineRepaintsNerfUnknown:
    """After a compaction nerf shows `nerf:ctx ?` and nothing but nerf repaints
    it. When a render persists a fresh reading while that marker is up, the
    statusline asks nerf (in the background) to repaint (mcp-server-nerf#32)."""

    def _setup(self, tmp_path: Path, indicators: list[str]) -> tuple[Path, Path, Path]:
        dev = f"repaint-{uuid.uuid4().hex[:8]}"
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_team": "t", "dev_name": dev, "dev_avatar": "🧪"})
        )
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
        session_file = Path(f"/tmp/claude-statusline-{dev}.json")
        session_file.write_text(json.dumps({"indicators": indicators}))
        calls = tmp_path / "nerf-calls.log"
        stub = tmp_path / "nerf-server"
        stub.write_text(f'#!/usr/bin/env bash\nprintf "%s|%s\\n" "$PWD" "$*" >> "{calls}"\n')
        stub.chmod(0o755)
        return session_file, stub, calls

    def _render(self, tmp_path: Path, stub: Path, pct: float | None = 55.0) -> None:
        payload: dict = {"cwd": str(tmp_path), "session_id": "sess-repaint-1"}
        if pct is not None:
            payload["context_window"] = {"remaining_percentage": pct}
        _run_statusline(payload, cwd=tmp_path, env_override={"NERF_BIN": str(stub)})

    @staticmethod
    def _wait_for(path: Path, timeout: float = 3.0) -> str:
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            if path.exists() and path.read_text().strip():
                return path.read_text()
            time.sleep(0.05)
        return ""

    def test_ctx_unknown_with_fresh_reading_triggers_repaint(self, tmp_path: Path):
        session_file, stub, calls = self._setup(tmp_path, ["nerf:ctx ?"])
        try:
            self._render(tmp_path, stub)
            log = self._wait_for(calls)
            assert f"{tmp_path}|refresh-indicator --session-id sess-repaint-1" in log
        finally:
            session_file.unlink(missing_ok=True)

    def test_no_repaint_when_nerf_indicator_is_known(self, tmp_path: Path):
        session_file, stub, calls = self._setup(tmp_path, ["nerf:⚡ 55%"])
        try:
            self._render(tmp_path, stub)
            assert self._wait_for(calls, timeout=0.5) == ""
        finally:
            session_file.unlink(missing_ok=True)

    def test_no_repaint_without_a_fresh_reading(self, tmp_path: Path):
        session_file, stub, calls = self._setup(tmp_path, ["nerf:ctx ?"])
        try:
            self._render(tmp_path, stub, pct=None)
            assert self._wait_for(calls, timeout=0.5) == ""
        finally:
            session_file.unlink(missing_ok=True)


class TestStatuslinePersistsContext:
    """#1225: the statusline is the only thing Claude Code hands the window-aware
    remaining_percentage to, so it persists it per session for the reseed Stop
    gate and nerf to read."""

    def _payload(self, tmp_path: Path, session_id: str, pct: float) -> dict:
        return {
            "cwd": str(tmp_path),
            "session_id": session_id,
            "context_window": {"remaining_percentage": pct},
        }

    def test_context_json_written_per_session(self, tmp_path: Path):
        state = tmp_path / "state"
        _run_statusline(self._payload(tmp_path, "abc-123", 42.5), cwd=tmp_path,
                        env_override={"CLAUDE_CONTEXT_STATE_DIR": str(state)})
        data = json.loads((state / "abc-123.json").read_text())
        assert data["session_id"] == "abc-123"
        assert data["remaining_percentage"] == 42.5
        assert isinstance(data["ts"], int) and data["ts"] > 0
        # Atomic write: no temp file left beside it.
        assert sorted(p.name for p in state.iterdir()) == ["abc-123.json"]

    def test_second_render_overwrites_not_appends(self, tmp_path: Path):
        state = tmp_path / "state"
        env = {"CLAUDE_CONTEXT_STATE_DIR": str(state)}
        _run_statusline(self._payload(tmp_path, "s1", 80), cwd=tmp_path, env_override=env)
        _run_statusline(self._payload(tmp_path, "s1", 12), cwd=tmp_path, env_override=env)
        assert json.loads((state / "s1.json").read_text())["remaining_percentage"] == 12

    def test_unsafe_session_id_is_refused_not_sanitised(self, tmp_path: Path):
        """The session id becomes a filename — a traversal-shaped one must write
        nothing anywhere, and the statusline must still render."""
        state = tmp_path / "state"
        output = _run_statusline(self._payload(tmp_path, "../../escape", 50), cwd=tmp_path,
                                 env_override={"CLAUDE_CONTEXT_STATE_DIR": str(state)})
        assert not state.exists() or not any(state.iterdir())
        assert not (tmp_path / "escape.json").exists()
        assert "ctx remaining: 50%" in _strip_ansi(output)

    def test_unwritable_state_dir_does_not_break_the_render(self, tmp_path: Path):
        blocker = tmp_path / "file-not-dir"
        blocker.write_text("x")
        output = _run_statusline(self._payload(tmp_path, "s2", 33), cwd=tmp_path,
                                 env_override={"CLAUDE_CONTEXT_STATE_DIR": str(blocker / "sub")})
        assert "ctx remaining: 33%" in _strip_ansi(output)
        assert output.count("\n") == 2
