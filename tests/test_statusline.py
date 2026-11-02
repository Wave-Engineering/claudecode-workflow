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
    # No git cache unless a test asks for one: a test that changes a repo between two renders
    # must see the change (#1427).
    env["CLAUDE_STATUSLINE_GIT_TTL"] = "0"
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
                "context_window": {"remaining_percentage": 72.5, "total_input_tokens": 37542},
            },
            cwd=tmp_path,
        )
        assert output.count("\n") == 2, (
            f"Expected 2 lines, got: {output!r}"
        )

        clean = _strip_ansi(output)
        lines = clean.split("\n")

        # Row 1 carries the model and the absolute context size (#1427)
        assert lines[0] == "Claude Sonnet │ 38K", lines[0]

        # Row 2 carries the project-branch and the path
        assert lines[1].startswith(f"{tmp_path.name}-"), lines[1]
        assert str(tmp_path) in lines[1] or "~" in lines[1]

    def test_line2_has_path_and_git(self, tmp_path: Path):
        """The project-branch and the path are both on row 2 (#1427); row 1 has neither."""
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
        # Row 2: project-branch, then the path, divided
        assert lines[1].startswith(f"{repo_name}-"), lines[1]
        assert " │ " in lines[1]
        assert lines[1].endswith(str(tmp_path)), lines[1]
        # Row 1 has nothing here: no model, no context, no panel icons
        assert lines[0] == ""


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
        """When no session file exists, row 1 has no panel icons and the path is on row 2."""
        output = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)
        clean = _strip_ansi(output)
        lines = clean.split("\n")

        assert "● REC" not in lines[0]
        assert lines[0] == ""
        # The path is row 2's content
        assert str(tmp_path) in lines[1] or "~" in lines[1] or tmp_path.name in lines[1]


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

            # Unicode emoji should be present on row 2 (#1427), after the dev-name
            assert "📡" in lines[1], (
                f"Expected Unicode emoji 📡 on row 2, got: {lines[1]!r}"
            )
            assert lines[1].startswith("beacon 📡"), lines[1]
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
                "context_window": {"remaining_percentage": 50.0, "total_input_tokens": 312000},
            },
            cwd=tmp_path,
        )
        # Green = \033[01;32m
        assert "\033[01;32m312K" in output, (
            f"Expected green ANSI code for safe context, got: {output!r}"
        )
        # The context panel is the absolute size: no bar, no percent (#1427)
        clean = _strip_ansi(output)
        assert clean.split("\n")[0] == "312K"
        assert "%" not in clean.split("\n")[0]

    def test_ctx_remaining_yellow_when_low(self, tmp_path: Path):
        """Context remaining <=25% renders yellow (33)."""
        output = _run_statusline(
            {
                "cwd": str(tmp_path),
                "context_window": {"remaining_percentage": 20.0, "total_input_tokens": 800000},
            },
            cwd=tmp_path,
        )
        assert "\033[33m800K" in output, (
            f"Expected yellow ANSI code for low ctx remaining, got: {output!r}"
        )

    def test_ctx_remaining_red_when_critical(self, tmp_path: Path):
        """Context remaining <=13% renders red (31)."""
        output = _run_statusline(
            {
                "cwd": str(tmp_path),
                "context_window": {"remaining_percentage": 10.0, "total_input_tokens": 900000},
            },
            cwd=tmp_path,
        )
        assert "\033[31m900K" in output, (
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
                        "total_input_tokens": used_tokens or 1000,
                        "total_output_tokens": 0,
                    },
                },
                cwd=tmp_path,
            )
        finally:
            cfg.unlink(missing_ok=True)
        # The context panel is the absolute size ("1K", "140K"); its color code is the
        # one immediately before it.
        size = f"{round((used_tokens or 1000) / 1000)}K"
        return output.split(size)[0][-16:]

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

    def test_raw_token_fields_persisted(self, tmp_path: Path):
        """#1297: the gate recomputes against the autocompact window, so the
        reading carries the raw numbers Claude Code's percentage was made from."""
        state = tmp_path / "state"
        payload = self._payload(tmp_path, "tok-1", 80)
        payload["model"] = {"id": "claude-opus-5-5", "display_name": "Opus 5.5"}
        payload["context_window"].update(
            {"total_input_tokens": 202373, "total_output_tokens": 379, "context_window_size": 1000000})
        _run_statusline(payload, cwd=tmp_path, env_override={"CLAUDE_CONTEXT_STATE_DIR": str(state)})
        data = json.loads((state / "tok-1.json").read_text())
        assert data["used_tokens"] == 202373
        assert data["window_tokens"] == 1000000
        assert data["model_id"] == "claude-opus-5-5"

    def test_missing_raw_fields_are_omitted_not_null(self, tmp_path: Path):
        state = tmp_path / "state"
        _run_statusline(self._payload(tmp_path, "tok-2", 50), cwd=tmp_path,
                        env_override={"CLAUDE_CONTEXT_STATE_DIR": str(state)})
        data = json.loads((state / "tok-2.json").read_text())
        assert set(data) == {"session_id", "remaining_percentage", "ts"}

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
        payload = self._payload(tmp_path, "../../escape", 50)
        payload["context_window"]["total_input_tokens"] = 5000
        output = _run_statusline(payload, cwd=tmp_path,
                                 env_override={"CLAUDE_CONTEXT_STATE_DIR": str(state)})
        assert not state.exists() or not any(state.iterdir())
        assert not (tmp_path / "escape.json").exists()
        assert _strip_ansi(output).split("\n")[0] == "5K"

    def test_unwritable_state_dir_does_not_break_the_render(self, tmp_path: Path):
        blocker = tmp_path / "file-not-dir"
        blocker.write_text("x")
        payload = self._payload(tmp_path, "s2", 33)
        payload["context_window"]["total_input_tokens"] = 7000
        output = _run_statusline(payload, cwd=tmp_path,
                                 env_override={"CLAUDE_CONTEXT_STATE_DIR": str(blocker / "sub")})
        assert _strip_ansi(output).split("\n")[0] == "7K"
        assert output.count("\n") == 2


class TestStatuslineAskIndicators:
    """#1430: the asks panel renders from /tmp/claude-statusline-<dev>.asks.json, first on
    line 1, grouped by kind and blocking, blockers first."""

    def _setup(self, tmp_path: Path) -> tuple[str, Path]:
        dev = f"asks-{uuid.uuid4().hex[:8]}"
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_name": dev, "dev_avatar": "🧠"}))
        subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
        return dev, Path(f"/tmp/claude-statusline-{dev}.asks.json")

    def _line1(self, tmp_path: Path) -> str:
        return _strip_ansi(_run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path)).split("\n")[0]

    @staticmethod
    def _ask(kind: str, blocking: bool = False, seq: int = 1) -> dict:
        return {"list": "bj:needs", "seq": seq, "kind": kind, "blocking": blocking}

    def test_grouping_blockers_first_counts_above_one(self, tmp_path: Path):
        dev, asks = self._setup(tmp_path)
        try:
            asks.write_text(json.dumps({"asks": [
                self._ask("question", seq=1), self._ask("blocker", True, 2),
                self._ask("question", seq=3), self._ask("approval", True, 4),
                self._ask("blocker", True, 5), self._ask("question", seq=6),
            ], "synced_at": 1}))
            line = self._line1(tmp_path)
            assert line == "⛔2 ✅❗ ❓3", line
        finally:
            asks.unlink(missing_ok=True)

    def test_each_kind_and_the_order_inside_a_tier(self, tmp_path: Path):
        dev, asks = self._setup(tmp_path)
        try:
            asks.write_text(json.dumps({"asks": [
                self._ask("unspecified", seq=1), self._ask("question", seq=2),
                self._ask("action", seq=3), self._ask("approval", seq=4),
                self._ask("unspecified", True, 5), self._ask("action", True, 6),
            ]}))
            # Blocking asks, then non-blocking; approval, action, question, unspecified.
            assert self._line1(tmp_path) == "🔧❗ 🔔❗ ✅ 🔧 ❓ 🔔", self._line1(tmp_path)
        finally:
            asks.unlink(missing_ok=True)

    def test_a_blocker_never_shows_the_blocking_mark(self, tmp_path: Path):
        dev, asks = self._setup(tmp_path)
        try:
            asks.write_text(json.dumps({"asks": [self._ask("blocker", True)]}))
            assert self._line1(tmp_path) == "⛔", self._line1(tmp_path)
            assert "⛔❗" not in self._line1(tmp_path)
        finally:
            asks.unlink(missing_ok=True)

    def test_asks_come_before_the_existing_indicators(self, tmp_path: Path):
        dev, asks = self._setup(tmp_path)
        session = Path(f"/tmp/claude-statusline-{dev}.json")
        try:
            asks.write_text(json.dumps({"asks": [self._ask("approval", True)]}))
            session.write_text(json.dumps({"indicators": ["● REC", "W2 3/5"]}))
            assert self._line1(tmp_path) == "✅❗ ● REC W2 3/5", self._line1(tmp_path)
        finally:
            asks.unlink(missing_ok=True)
            session.unlink(missing_ok=True)

    def test_missing_empty_or_malformed_renders_nothing(self, tmp_path: Path):
        dev, asks = self._setup(tmp_path)
        try:
            baseline = self._line1(tmp_path)
            for content in ["", "not json", "[]", '{"asks": "x"}', '{"asks": []}',
                            '{"asks": [1, null, {"kind": "bogus"}, {"kind": 5}]}', '{"synced_at": 1}']:
                asks.write_text(content)
                assert self._line1(tmp_path) == baseline, content
        finally:
            asks.unlink(missing_ok=True)

    def test_no_identity_no_panel(self, tmp_path: Path):
        """Without a dev_name the file cannot be found, so nothing renders and nothing breaks."""
        out = _strip_ansi(_run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path))
        assert out.count("\n") == 2


# --- #1427: the two-row layout ---------------------------------------------------------------

DIM_BAR = "\033[2m│\033[00m"


def _git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t"})
    return r.stdout.strip()


def _repo(path: Path, *, branch: str = "main") -> Path:
    """A git repo with one commit, on `branch`."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", branch)
    (path / "README.md").write_text("x")
    _git(path, "add", ".")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _rows(output: str) -> list[str]:
    return _strip_ansi(output).split("\n")


class TestStatuslineLayout:
    """#1427: row 1 is `icons │ Model-Effort │ nerf │ runway │ context │ floor │ Session │ Weekly │
    spend`, row 2 is `dev-name avatar │ project-branch (worktree) │ cwd`. A panel with nothing to
    show leaves no divider."""

    FULL = {
        "model": {"display_name": "Sonnet 5.5", "id": "claude-sonnet-5-5"},
        "effort": {"level": "medium"},
        "context_window": {"total_input_tokens": 37542, "remaining_percentage": 61},
        "rate_limits": {"five_hour": {"used_percentage": 12}, "seven_day": {"used_percentage": 92}},
    }

    def _setup(self, tmp_path: Path, *, indicators: list[str] | None = None) -> tuple[str, list[Path]]:
        dev = f"layout-{uuid.uuid4().hex[:8]}"
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / "agent-identity.json").write_text(
            json.dumps({"dev_name": dev, "dev_avatar": "🧠"}))
        files: list[Path] = []
        if indicators is not None:
            f = Path(f"/tmp/claude-statusline-{dev}.json")
            f.write_text(json.dumps({"indicators": indicators}))
            files.append(f)
        return dev, files

    def _payload(self, tmp_path: Path, **drop) -> dict:
        p = json.loads(json.dumps(self.FULL))
        p["cwd"] = str(tmp_path)
        for path in drop.get("remove", []):
            node = p
            *parents, last = path.split(".")
            for k in parents:
                node = node[k]
            del node[last]
        return p

    def test_all_panels_two_rows_with_a_dim_divider(self, tmp_path: Path):
        proj = _repo(tmp_path / "myproj")
        dev, files = self._setup(proj, indicators=["● REC"])
        try:
            out = _run_statusline(self._payload(proj), cwd=proj)
        finally:
            for f in files:
                f.unlink(missing_ok=True)
        assert out.count("\n") == 2
        assert DIM_BAR in out  # a dim │, not a plain one
        rows = _rows(out)
        assert rows[0] == "● REC │ Sonnet 5.5-medium │ 38K │ Session:12% │ Weekly:92%"
        parts = rows[1].split(" │ ")
        assert len(parts) == 3, rows[1]
        assert parts[0] == f"{dev} 🧠"
        assert parts[1].startswith("myproj-main"), parts[1]
        assert parts[2] == str(proj)

    @pytest.mark.parametrize("remove, row1", [
        ([], "● REC │ Sonnet 5.5-medium │ 38K │ Session:12% │ Weekly:92%"),
        (["model"], "● REC │ 38K │ Session:12% │ Weekly:92%"),
        (["effort"], "● REC │ Sonnet 5.5 │ 38K │ Session:12% │ Weekly:92%"),
        (["context_window"], "● REC │ Sonnet 5.5-medium │ Session:12% │ Weekly:92%"),
        (["rate_limits.five_hour"], "● REC │ Sonnet 5.5-medium │ 38K │ Weekly:92%"),
        (["rate_limits.seven_day"], "● REC │ Sonnet 5.5-medium │ 38K │ Session:12%"),
        (["rate_limits"], "● REC │ Sonnet 5.5-medium │ 38K"),
        (["model", "effort", "context_window", "rate_limits"], "● REC"),
    ])
    def test_each_panel_empty_in_turn_leaves_no_stray_divider(self, tmp_path: Path, remove, row1):
        dev, files = self._setup(tmp_path, indicators=["● REC"])
        try:
            rows = _rows(_run_statusline(self._payload(tmp_path, remove=remove), cwd=tmp_path))
        finally:
            for f in files:
                f.unlink(missing_ok=True)
        assert rows[0] == row1
        assert "│ │" not in rows[0] and not rows[0].startswith("│") and not rows[0].endswith("│")

    def test_no_panel_icons_means_no_leading_divider(self, tmp_path: Path):
        self._setup(tmp_path)
        assert _rows(_run_statusline(self._payload(tmp_path), cwd=tmp_path))[0] == \
            "Sonnet 5.5-medium │ 38K │ Session:12% │ Weekly:92%"

    def test_nothing_to_show_gives_two_empty_rows_not_dividers(self, tmp_path: Path):
        out = _run_statusline({"cwd": ""}, cwd=tmp_path)
        assert _strip_ansi(out) == "\n\n"

    def test_row_two_without_an_identity_still_renders_the_rest(self, tmp_path: Path):
        proj = _repo(tmp_path / "noid")
        rows = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj))
        parts = rows[1].split(" │ ")
        assert len(parts) == 2 and parts[0].startswith("noid-main") and parts[1] == str(proj)

    # --- payload variants ---
    def test_effort_is_dropped_when_the_payload_has_none(self, tmp_path: Path):
        rows = _rows(_run_statusline({"cwd": str(tmp_path), "model": {"display_name": "Opus 5.5"}}, cwd=tmp_path))
        assert rows[0] == "Opus 5.5"

    def test_seven_day_only_and_both_and_neither(self, tmp_path: Path):
        def row1(limits):
            p = {"cwd": str(tmp_path)}
            if limits is not None:
                p["rate_limits"] = limits
            return _rows(_run_statusline(p, cwd=tmp_path))[0]
        assert row1({"seven_day": {"used_percentage": 40}}) == "Weekly:40%"
        assert row1({"five_hour": {"used_percentage": 3}, "seven_day": {"used_percentage": 40}}) == "Session:3% │ Weekly:40%"
        assert row1(None) == ""
        assert row1({}) == ""

    # --- context formatting ---
    @pytest.mark.parametrize("tokens, text", [
        (0, "0"), (999, "999"), (1000, "1K"), (37542, "38K"), (312000, "312K"),
        (999499, "999K"), (999999, "1M"), (1000000, "1M"), (1200000, "1.2M"), (1949999, "1.9M"),
    ])
    def test_context_is_absolute_tokens_with_no_percent(self, tmp_path: Path, tokens, text):
        rows = _rows(_run_statusline(
            {"cwd": str(tmp_path), "context_window": {"total_input_tokens": tokens}}, cwd=tmp_path))
        assert rows[0] == text
        assert "%" not in rows[0]

    # --- Session / Weekly colours ---
    @pytest.mark.parametrize("pct, color", [
        (0, "\033[01;32m"), (49, "\033[01;32m"), (50, "\033[33m"), (79, "\033[33m"),
        (80, "\033[31m"), (100, "\033[31m"), (49.9, "\033[01;32m"), (79.9, "\033[33m"),
    ])
    def test_usage_colours_green_yellow_red(self, tmp_path: Path, pct, color):
        shown = int(pct)
        for key, label in (("five_hour", "Session"), ("seven_day", "Weekly")):
            out = _run_statusline({"cwd": str(tmp_path), "rate_limits": {key: {"used_percentage": pct}}}, cwd=tmp_path)
            assert f"{color}{label}:{shown}%" in out, out

    # --- git ---
    def test_main_checkout_shows_project_and_branch_only(self, tmp_path: Path):
        proj = _repo(tmp_path / "alpha", branch="feature/x")
        parts = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj))[1].split(" │ ")
        assert parts[0].startswith("alpha-feature/x") and "(" not in parts[0]

    def test_linked_worktree_shows_its_project_and_the_worktree_dir(self, tmp_path: Path):
        proj = _repo(tmp_path / "alpha")
        wt = tmp_path / "alpha-wt-7"
        _git(proj, "worktree", "add", "-q", "-b", "fix/7-thing", str(wt))
        parts = _rows(_run_statusline({"cwd": str(wt)}, cwd=wt))[1].split(" │ ")
        assert parts[0].startswith("alpha-fix/7-thing (alpha-wt-7)"), parts[0]
        # ...and the main checkout, same repo, has no (worktree) part
        parts = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj))[1].split(" │ ")
        assert "(" not in parts[0]

    def test_detached_head_shows_the_short_commit(self, tmp_path: Path):
        proj = _repo(tmp_path / "alpha")
        short = _git(proj, "rev-parse", "--short", "HEAD")
        _git(proj, "checkout", "-q", "--detach")
        parts = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj))[1].split(" │ ")
        assert parts[0].startswith(f"alpha-{short}"), parts[0]

    def test_no_repo_means_no_project_panel(self, tmp_path: Path):
        d = tmp_path / "plain"
        d.mkdir()
        assert _rows(_run_statusline({"cwd": str(d)}, cwd=d))[1] == str(d)

    def test_git_lookups_are_cached_for_a_few_seconds(self, tmp_path: Path):
        proj = _repo(tmp_path / "alpha")
        cache = {"CLAUDE_STATUSLINE_GIT_TTL": "60", "CLAUDE_STATUSLINE_CACHE_DIR": str(tmp_path / "cache")}
        (tmp_path / "cache").mkdir()
        first = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj, env_override=cache))[1]
        _git(proj, "checkout", "-q", "-b", "other")
        again = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj, env_override=cache))[1]
        assert again == first and "alpha-main" in again  # still the cached branch
        fresh = _rows(_run_statusline({"cwd": str(proj)}, cwd=proj))[1]  # default test env: no cache
        assert "alpha-other" in fresh

    def test_a_planted_git_cache_cannot_run_commands_or_inject_escapes(self, tmp_path: Path):
        """The cache sits in a directory other users may write to, and what it holds is used in
        arithmetic and printed: a hostile value must be read as text or as 0, never evaluated."""
        import hashlib

        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        marker = tmp_path / "pwned"
        digest = hashlib.md5(str(tmp_path).encode()).hexdigest()
        planted = cache_dir / f"claude-statusline-git-{os.getuid()}-{digest}"
        planted.write_text(f"proj\x1b[31mX\nmain\n\na[$(touch {marker})]\n$(touch {marker})\n7\nb[`touch {marker}`]\n")
        out = _run_statusline({"cwd": str(tmp_path)}, cwd=tmp_path, env_override={
            "CLAUDE_STATUSLINE_GIT_TTL": "60", "CLAUDE_STATUSLINE_CACHE_DIR": str(cache_dir)})
        assert not marker.exists()
        row2 = _rows(out)[1]
        assert "\x1b" not in row2 and "proj[31mX-main" in row2  # control characters stripped, text kept
        assert "↑7" in row2 and "↓" not in row2 and "+" not in row2  # non-numbers read as 0

    def test_the_git_cache_file_is_per_user(self, tmp_path: Path):
        proj = _repo(tmp_path / "alpha")
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()
        _run_statusline({"cwd": str(proj)}, cwd=proj, env_override={
            "CLAUDE_STATUSLINE_GIT_TTL": "60", "CLAUDE_STATUSLINE_CACHE_DIR": str(cache_dir)})
        names = [p.name for p in cache_dir.iterdir()]
        assert len(names) == 1 and names[0].startswith(f"claude-statusline-git-{os.getuid()}-"), names

    # --- the #1225 state file ---
    def test_context_state_file_has_exactly_the_same_content_as_before(self, tmp_path: Path):
        state = tmp_path / "state"
        payload = {
            "cwd": str(tmp_path), "session_id": "gold-1", "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
            "context_window": {"remaining_percentage": 80, "total_input_tokens": 202373,
                               "total_output_tokens": 379, "context_window_size": 1000000},
        }
        before = int(__import__("time").time())
        _run_statusline(payload, cwd=tmp_path, env_override={"CLAUDE_CONTEXT_STATE_DIR": str(state)})
        data = json.loads((state / "gold-1.json").read_text())
        ts = data.pop("ts")
        assert before <= ts <= before + 5
        assert data == {"session_id": "gold-1", "remaining_percentage": 80, "used_tokens": 202373,
                        "window_tokens": 1000000, "model_id": "claude-opus-5-5"}

    # --- one jq per payload ---
    def test_the_payload_is_read_with_one_jq_invocation(self, tmp_path: Path):
        import shutil

        real = shutil.which("jq")
        assert real
        log = tmp_path / "jq-calls.log"
        stub_dir = tmp_path / "stubbin"
        stub_dir.mkdir()
        stub = stub_dir / "jq"
        # An invocation whose last argument is not a readable file reads its input from stdin: the payload.
        stub.write_text(
            "#!/usr/bin/env bash\n"
            'last="${*: -1}"\n'
            f'if [ -f "$last" ]; then echo file >> "{log}"; else echo stdin >> "{log}"; fi\n'
            f'exec "{real}" "$@"\n')
        stub.chmod(0o755)
        proj = _repo(tmp_path / "alpha")
        dev, files = TestStatuslineLayout()._setup(proj, indicators=["● REC"])
        try:
            payload = TestStatuslineLayout()._payload(proj)
            payload["session_id"] = "one-jq"
            _run_statusline(payload, cwd=proj, env_override={
                "PATH": f"{stub_dir}:{os.environ['PATH']}",
                "CLAUDE_CONTEXT_STATE_DIR": str(tmp_path / "state")})
        finally:
            for f in files:
                f.unlink(missing_ok=True)
        calls = log.read_text().split()
        assert calls.count("stdin") == 1, calls
