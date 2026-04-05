"""Tests for the SDLC dashboard viewer and dashboard-url subcommand.

Tests cover:
- ``sdlc-dashboard/index.html`` — existence, self-contained, key content
- ``_detect_org_repo()`` — SSH and HTTPS git remote parsing
- ``_detect_branch()`` — current branch detection
- ``dashboard-url`` subcommand via subprocess (integration tests)

Mocks are ONLY used for ``subprocess.run`` (external git process).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from campaign_status.__main__ import _detect_branch, _detect_org_repo

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = str(_PROJECT_ROOT / "src")
_DASHBOARD_HTML = _PROJECT_ROOT / "sdlc-dashboard" / "index.html"


# ---------------------------------------------------------------------------
# Helper: run campaign-status CLI
# ---------------------------------------------------------------------------

def _run_campaign_cli(
    args: list[str],
    cwd: str | Path,
) -> tuple[int, str, str]:
    """Run ``python3 -m campaign_status <args>`` as a subprocess."""
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _SRC_DIR + (os.pathsep + existing if existing else "")

    result = subprocess.run(
        [sys.executable, "-m", "campaign_status"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )
    return (result.returncode, result.stdout, result.stderr)


# ---------------------------------------------------------------------------
# Tests: sdlc-dashboard/index.html
# ---------------------------------------------------------------------------

class TestDashboardHtmlFile:
    """Verify the dashboard HTML file exists and is self-contained."""

    def test_index_html_exists(self) -> None:
        """sdlc-dashboard/index.html must exist in the project."""
        assert _DASHBOARD_HTML.exists(), (
            f"Expected {_DASHBOARD_HTML} to exist"
        )

    def test_is_valid_html(self) -> None:
        """Must start with DOCTYPE and contain html/head/body."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")
        assert "<html" in content
        assert "<head>" in content
        assert "<body>" in content
        assert "</html>" in content

    def test_no_external_dependencies(self) -> None:
        """Must not reference external CSS/JS files (self-contained)."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        # No external stylesheet links
        assert 'rel="stylesheet"' not in content or "href=" not in content.split('rel="stylesheet"')[0]
        # No script src (all JS is inline)
        assert '<script src=' not in content

    def test_has_inline_css(self) -> None:
        """Must have inline <style> block."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "<style>" in content
        assert "</style>" in content

    def test_has_inline_js(self) -> None:
        """Must have inline <script> block."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "<script>" in content
        assert "</script>" in content

    def test_contains_campaign_stages(self) -> None:
        """JS must reference the 5 SDLC stages."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        for stage in ("concept", "prd", "backlog", "implementation", "dod"):
            assert stage in content, f"Stage '{stage}' not found in index.html"

    def test_contains_poll_logic(self) -> None:
        """Must contain polling logic (setInterval or similar)."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "setInterval" in content or "setTimeout" in content

    def test_contains_raw_githubusercontent_url(self) -> None:
        """Must fetch from raw.githubusercontent.com."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "raw.githubusercontent.com" in content

    def test_contains_stale_indicator(self) -> None:
        """Must show stale indicator when fetch fails."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        # Check for stale-related CSS class or text
        assert "stale" in content.lower()

    def test_contains_auth_support(self) -> None:
        """Must support PAT in localStorage."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "localStorage" in content

    def test_contains_repo_url_param(self) -> None:
        """Must read repo from URL parameters."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "URLSearchParams" in content or "getParams" in content

    def test_responsive_meta_tag(self) -> None:
        """Must have viewport meta tag for mobile."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert 'name="viewport"' in content

    def test_responsive_css(self) -> None:
        """Must have media query for responsive layout."""
        content = _DASHBOARD_HTML.read_text(encoding="utf-8")
        assert "@media" in content


# ---------------------------------------------------------------------------
# Tests: _detect_org_repo
# ---------------------------------------------------------------------------

class TestDetectOrgRepo:
    """Tests for _detect_org_repo() — git remote URL parsing."""

    def test_ssh_url(self, tmp_path: Path) -> None:
        """Parse org/repo from SSH remote URL."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="git@github.com:Wave-Engineering/my-repo.git\n",
                returncode=0,
            )
            result = _detect_org_repo(tmp_path)
            assert result == "Wave-Engineering/my-repo"

    def test_https_url(self, tmp_path: Path) -> None:
        """Parse org/repo from HTTPS remote URL."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="https://github.com/Wave-Engineering/my-repo.git\n",
                returncode=0,
            )
            result = _detect_org_repo(tmp_path)
            assert result == "Wave-Engineering/my-repo"

    def test_https_no_git_suffix(self, tmp_path: Path) -> None:
        """Parse org/repo from HTTPS URL without .git suffix."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="https://github.com/MyOrg/MyRepo\n",
                returncode=0,
            )
            result = _detect_org_repo(tmp_path)
            assert result == "MyOrg/MyRepo"

    def test_ssh_no_git_suffix(self, tmp_path: Path) -> None:
        """Parse org/repo from SSH URL without .git suffix."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="git@github.com:MyOrg/MyRepo\n",
                returncode=0,
            )
            result = _detect_org_repo(tmp_path)
            assert result == "MyOrg/MyRepo"

    def test_no_remote_returns_none(self, tmp_path: Path) -> None:
        """Return None when no remote is configured."""
        with patch(
            "campaign_status.__main__.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            result = _detect_org_repo(tmp_path)
            assert result is None

    def test_passes_root_as_cwd(self, tmp_path: Path) -> None:
        """Verify subprocess is called with root as cwd."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="git@github.com:Org/Repo.git\n",
                returncode=0,
            )
            _detect_org_repo(tmp_path)
            call_kwargs = mock_run.call_args
            assert call_kwargs.kwargs.get("cwd") == str(tmp_path) or \
                (len(call_kwargs.args) > 0 and str(tmp_path) in str(call_kwargs))


# ---------------------------------------------------------------------------
# Tests: _detect_branch
# ---------------------------------------------------------------------------

class TestDetectBranch:
    """Tests for _detect_branch() — current branch detection."""

    def test_returns_current_branch(self, tmp_path: Path) -> None:
        """Return the branch name from git."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="feature/42-my-work\n",
                returncode=0,
            )
            result = _detect_branch(tmp_path)
            assert result == "feature/42-my-work"

    def test_defaults_to_main_on_failure(self, tmp_path: Path) -> None:
        """Default to 'main' when git fails."""
        with patch(
            "campaign_status.__main__.subprocess.run",
            side_effect=subprocess.CalledProcessError(128, "git"),
        ):
            result = _detect_branch(tmp_path)
            assert result == "main"

    def test_defaults_to_main_on_empty(self, tmp_path: Path) -> None:
        """Default to 'main' when git returns empty string."""
        with patch("campaign_status.__main__.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(
                stdout="\n",
                returncode=0,
            )
            result = _detect_branch(tmp_path)
            assert result == "main"


# ---------------------------------------------------------------------------
# Tests: dashboard-url subcommand (subprocess integration)
# ---------------------------------------------------------------------------

class TestDashboardUrlSubcommand:
    """Integration tests for ``campaign-status dashboard-url`` via subprocess."""

    def test_dashboard_url_outputs_url(self, temp_git_repo: Path) -> None:
        """dashboard-url should output a valid SDLC dashboard URL."""
        # Set up a remote so _detect_org_repo works
        subprocess.run(
            ["git", "remote", "add", "origin",
             "git@github.com:TestOrg/test-repo.git"],
            cwd=str(temp_git_repo),
            capture_output=True,
            check=True,
        )

        rc, out, err = _run_campaign_cli(["dashboard-url"], temp_git_repo)
        assert rc == 0, f"dashboard-url failed: {err}"
        url = out.strip()
        assert url.startswith("https://TestOrg.github.io/sdlc-dashboard/")
        assert "repo=TestOrg/test-repo" in url
        # Should include current branch
        assert "branch=" in url

    def test_dashboard_url_with_explicit_branch(
        self, temp_git_repo: Path
    ) -> None:
        """dashboard-url --branch <name> should use the specified branch."""
        subprocess.run(
            ["git", "remote", "add", "origin",
             "https://github.com/MyOrg/MyRepo.git"],
            cwd=str(temp_git_repo),
            capture_output=True,
            check=True,
        )

        rc, out, err = _run_campaign_cli(
            ["dashboard-url", "--branch", "feature/42-work"],
            temp_git_repo,
        )
        assert rc == 0, f"dashboard-url failed: {err}"
        url = out.strip()
        assert "branch=feature/42-work" in url
        assert "repo=MyOrg/MyRepo" in url

    def test_dashboard_url_no_remote_fails(
        self, temp_git_repo: Path
    ) -> None:
        """dashboard-url with no remote should fail gracefully."""
        rc, out, err = _run_campaign_cli(
            ["dashboard-url"], temp_git_repo
        )
        assert rc != 0
        assert "Error:" in err or "error" in err.lower()

    def test_dashboard_url_is_read_only(
        self, temp_git_repo: Path
    ) -> None:
        """dashboard-url should not create git commits or modify files."""
        subprocess.run(
            ["git", "remote", "add", "origin",
             "git@github.com:Org/Repo.git"],
            cwd=str(temp_git_repo),
            capture_output=True,
            check=True,
        )

        # Count commits before
        result_before = subprocess.run(
            ["git", "rev-list", "--all", "--count"],
            cwd=str(temp_git_repo),
            capture_output=True,
            text=True,
        )
        count_before = result_before.stdout.strip()

        _run_campaign_cli(["dashboard-url"], temp_git_repo)

        # Count commits after
        result_after = subprocess.run(
            ["git", "rev-list", "--all", "--count"],
            cwd=str(temp_git_repo),
            capture_output=True,
            text=True,
        )
        count_after = result_after.stdout.strip()

        assert count_after == count_before, "dashboard-url created a git commit"

    def test_dashboard_url_does_not_require_sdlc_dir(
        self, temp_git_repo: Path
    ) -> None:
        """dashboard-url should work without .sdlc/ directory
        (it only needs git remote, not campaign state).
        """
        subprocess.run(
            ["git", "remote", "add", "origin",
             "git@github.com:Org/Repo.git"],
            cwd=str(temp_git_repo),
            capture_output=True,
            check=True,
        )

        # Ensure no .sdlc exists
        sdlc_dir = temp_git_repo / ".sdlc"
        assert not sdlc_dir.exists()

        rc, out, err = _run_campaign_cli(["dashboard-url"], temp_git_repo)
        assert rc == 0, f"dashboard-url failed without .sdlc: {err}"
        assert "github.io/sdlc-dashboard/" in out
