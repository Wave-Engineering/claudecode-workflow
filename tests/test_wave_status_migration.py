"""Tests for wave-status path migration between .claude/status/ and .sdlc/waves/.

Verifies that wave-status correctly falls back to .claude/status/ when
.sdlc/ does not exist, and uses .sdlc/waves/ when .sdlc/ does exist.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wave_status.state import (
    ensure_status_dir,
    html_path,
    status_dir,
)


# ---------------------------------------------------------------------------
# status_dir migration
# ---------------------------------------------------------------------------

class TestStatusDirMigration:
    """Tests for status_dir() fallback behavior."""

    def test_returns_claude_status_when_no_sdlc(self, tmp_path: Path) -> None:
        """Without .sdlc/, returns .claude/status/."""
        result = status_dir(tmp_path)
        assert result == tmp_path / ".claude" / "status"

    def test_returns_sdlc_waves_when_sdlc_exists(self, tmp_path: Path) -> None:
        """With .sdlc/waves/ present, returns .sdlc/waves/."""
        (tmp_path / ".sdlc" / "waves").mkdir(parents=True)
        result = status_dir(tmp_path)
        assert result == tmp_path / ".sdlc" / "waves"

    def test_returns_sdlc_waves_when_sdlc_exists_but_no_waves_subdir(
        self, tmp_path: Path
    ) -> None:
        """With .sdlc/ but no waves/ subdirectory, still returns .sdlc/waves/.

        The predicate is .sdlc/ existence, matching html_path() and
        ensure_status_dir().  The caller (ensure_status_dir or init_state)
        creates the waves/ subdirectory as needed.
        """
        (tmp_path / ".sdlc").mkdir()
        result = status_dir(tmp_path)
        assert result == tmp_path / ".sdlc" / "waves"


# ---------------------------------------------------------------------------
# html_path migration
# ---------------------------------------------------------------------------

class TestHtmlPathMigration:
    """Tests for html_path() fallback behavior."""

    def test_returns_status_panel_when_no_sdlc(self, tmp_path: Path) -> None:
        """Without .sdlc/, returns .status-panel.html."""
        result = html_path(tmp_path)
        assert result == tmp_path / ".status-panel.html"

    def test_returns_sdlc_dashboard_when_sdlc_exists(self, tmp_path: Path) -> None:
        """With .sdlc/ present, returns .sdlc/waves/dashboard.html."""
        (tmp_path / ".sdlc").mkdir()
        result = html_path(tmp_path)
        assert result == tmp_path / ".sdlc" / "waves" / "dashboard.html"


# ---------------------------------------------------------------------------
# ensure_status_dir migration
# ---------------------------------------------------------------------------

class TestEnsureStatusDirMigration:
    """Tests for ensure_status_dir() migration behavior."""

    def test_creates_claude_status_when_no_sdlc(self, tmp_path: Path) -> None:
        """Without .sdlc/, creates and returns .claude/status/."""
        d = ensure_status_dir(tmp_path)
        assert d == tmp_path / ".claude" / "status"
        assert d.is_dir()

    def test_creates_sdlc_waves_when_sdlc_exists(self, tmp_path: Path) -> None:
        """With .sdlc/ present, creates and returns .sdlc/waves/."""
        (tmp_path / ".sdlc").mkdir()
        d = ensure_status_dir(tmp_path)
        assert d == tmp_path / ".sdlc" / "waves"
        assert d.is_dir()

    def test_idempotent_with_sdlc(self, tmp_path: Path) -> None:
        """Calling twice with .sdlc/ does not error."""
        (tmp_path / ".sdlc").mkdir()
        ensure_status_dir(tmp_path)
        d = ensure_status_dir(tmp_path)
        assert d.is_dir()

    def test_idempotent_without_sdlc(self, tmp_path: Path) -> None:
        """Calling twice without .sdlc/ does not error."""
        ensure_status_dir(tmp_path)
        d = ensure_status_dir(tmp_path)
        assert d.is_dir()
