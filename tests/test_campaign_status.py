"""Subprocess-based integration tests for ``python -m campaign_status``.

Black-box validation of the CLI as a real executable.
Every test invokes the CLI via ``subprocess.run`` in a temporary git repo.
No function imports, no mocking.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helper: run campaign-status CLI
# ---------------------------------------------------------------------------

_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")


def _run_campaign_cli(
    args: list[str],
    cwd: str | Path,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """Run ``python3 -m campaign_status <args>`` as a subprocess.

    Returns (returncode, stdout, stderr).
    """
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _SRC_DIR + (os.pathsep + existing if existing else "")

    result = subprocess.run(
        [sys.executable, "-m", "campaign_status"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        input=input_text,
        env=env,
    )
    return (result.returncode, result.stdout, result.stderr)


# ---------------------------------------------------------------------------
# Full lifecycle test
# ---------------------------------------------------------------------------

class TestFullLifecycleSubprocess:
    """End-to-end lifecycle via subprocess calls."""

    def test_complete_campaign_cycle(self, temp_git_repo: Path) -> None:
        """Happy path: init -> stage-start -> stage-review -> stage-complete
        for all stages, plus defer and show.
        """
        repo = temp_git_repo

        # init
        rc, out, err = _run_campaign_cli(["init", "test-project"], repo)
        assert rc == 0, f"init failed: {err}"
        assert "initialized" in out.lower()

        # stage-start concept
        rc, out, err = _run_campaign_cli(["stage-start", "concept"], repo)
        assert rc == 0, f"stage-start concept failed: {err}"
        assert "active" in out.lower()

        # stage-review concept
        rc, out, err = _run_campaign_cli(["stage-review", "concept"], repo)
        assert rc == 0, f"stage-review concept failed: {err}"
        assert "review" in out.lower()

        # stage-complete concept
        rc, out, err = _run_campaign_cli(["stage-complete", "concept"], repo)
        assert rc == 0, f"stage-complete concept failed: {err}"
        assert "complete" in out.lower()

        # stage-start prd
        rc, out, err = _run_campaign_cli(["stage-start", "prd"], repo)
        assert rc == 0, f"stage-start prd failed: {err}"

        # defer during prd
        rc, out, err = _run_campaign_cli(
            ["defer", "Advanced analytics", "--reason", "Phase 2"], repo
        )
        assert rc == 0, f"defer failed: {err}"
        assert "deferred" in out.lower()

        # stage-review prd
        rc, out, err = _run_campaign_cli(["stage-review", "prd"], repo)
        assert rc == 0, f"stage-review prd failed: {err}"

        # stage-complete prd
        rc, out, err = _run_campaign_cli(["stage-complete", "prd"], repo)
        assert rc == 0, f"stage-complete prd failed: {err}"

        # backlog (no review gate)
        rc, out, err = _run_campaign_cli(["stage-start", "backlog"], repo)
        assert rc == 0, f"stage-start backlog failed: {err}"
        rc, out, err = _run_campaign_cli(["stage-complete", "backlog"], repo)
        assert rc == 0, f"stage-complete backlog failed: {err}"

        # implementation (no review gate)
        rc, out, err = _run_campaign_cli(["stage-start", "implementation"], repo)
        assert rc == 0, f"stage-start implementation failed: {err}"
        rc, out, err = _run_campaign_cli(["stage-complete", "implementation"], repo)
        assert rc == 0, f"stage-complete implementation failed: {err}"

        # dod (with review gate)
        rc, out, err = _run_campaign_cli(["stage-start", "dod"], repo)
        assert rc == 0, f"stage-start dod failed: {err}"
        rc, out, err = _run_campaign_cli(["stage-review", "dod"], repo)
        assert rc == 0, f"stage-review dod failed: {err}"
        rc, out, err = _run_campaign_cli(["stage-complete", "dod"], repo)
        assert rc == 0, f"stage-complete dod failed: {err}"

        # show
        rc, out, err = _run_campaign_cli(["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "test-project" in out
        assert "concept" in out.lower()

        # Verify state on disk
        state_path = repo / ".sdlc" / "campaign-state.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        for stage in ("concept", "prd", "backlog", "implementation", "dod"):
            assert state["stages"][stage] == "complete"

        # Verify deferral on disk
        items_path = repo / ".sdlc" / "campaign-items.json"
        items = json.loads(items_path.read_text(encoding="utf-8"))
        assert len(items["deferrals"]) == 1
        assert items["deferrals"][0]["item"] == "Advanced analytics"


# ---------------------------------------------------------------------------
# State machine rejection tests
# ---------------------------------------------------------------------------

class TestStateMachineRejection:
    """Verify the state machine rejects invalid transitions via subprocess."""

    def test_stage_start_prd_before_concept_complete(
        self, temp_git_repo: Path
    ) -> None:
        """Starting prd before concept is complete -> exit 1."""
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        rc, out, err = _run_campaign_cli(["stage-start", "prd"], repo)
        assert rc == 1
        assert "Error:" in err

    def test_stage_review_backlog_rejected(
        self, temp_git_repo: Path
    ) -> None:
        """Reviewing backlog (no review gate) -> exit 1."""
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        rc, out, err = _run_campaign_cli(["stage-review", "backlog"], repo)
        assert rc == 1
        assert "Error:" in err

    def test_stage_complete_concept_without_review(
        self, temp_git_repo: Path
    ) -> None:
        """Completing concept from active (needs review first) -> exit 1."""
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)
        _run_campaign_cli(["stage-start", "concept"], repo)

        rc, out, err = _run_campaign_cli(["stage-complete", "concept"], repo)
        assert rc == 1
        assert "Error:" in err

    def test_reinit_rejected(self, temp_git_repo: Path) -> None:
        """Re-initializing -> exit 1."""
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        rc, out, err = _run_campaign_cli(["init", "another-project"], repo)
        assert rc == 1
        assert "Error:" in err


# ---------------------------------------------------------------------------
# Error output format tests
# ---------------------------------------------------------------------------

class TestErrorOutputFormat:
    """Verify errors go to stderr with correct format and exit codes."""

    def test_errors_go_to_stderr(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        rc, out, err = _run_campaign_cli(["stage-start", "prd"], repo)
        assert rc == 1
        assert "Error:" in err
        assert "Error:" not in out

    def test_no_subcommand_exits_2(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo
        rc, out, err = _run_campaign_cli([], repo)
        assert rc == 2

    def test_invalid_stage_name_exits_2(self, temp_git_repo: Path) -> None:
        """Invalid argparse choice for stage -> exit 2 (usage error)."""
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        rc, out, err = _run_campaign_cli(["stage-start", "invalid"], repo)
        assert rc == 2
        assert "invalid choice" in err


# ---------------------------------------------------------------------------
# Dashboard generation tests
# ---------------------------------------------------------------------------

class TestDashboardGeneration:
    """Verify dashboard HTML is created/updated by subcommands."""

    def test_init_creates_dashboard(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo

        rc, _, _ = _run_campaign_cli(["init", "test-project"], repo)
        assert rc == 0

        html = repo / ".sdlc" / "dashboard.html"
        assert html.exists(), "Dashboard HTML was not created by init"
        content = html.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "test-project" in content

    def test_state_change_regenerates_dashboard(
        self, temp_git_repo: Path
    ) -> None:
        repo = temp_git_repo
        html = repo / ".sdlc" / "dashboard.html"

        _run_campaign_cli(["init", "test-project"], repo)
        assert html.exists()
        mtime_after_init = html.stat().st_mtime_ns

        time.sleep(0.05)

        _run_campaign_cli(["stage-start", "concept"], repo)
        mtime_after_start = html.stat().st_mtime_ns
        assert mtime_after_start >= mtime_after_init

    def test_show_does_not_create_dashboard(
        self, temp_git_repo: Path
    ) -> None:
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        html = repo / ".sdlc" / "dashboard.html"
        html.unlink()
        assert not html.exists()

        rc, out, err = _run_campaign_cli(["show"], repo)
        assert rc == 0
        assert not html.exists(), "show should not create/modify dashboard"

    def test_show_does_not_modify_dashboard(
        self, temp_git_repo: Path
    ) -> None:
        repo = temp_git_repo
        html = repo / ".sdlc" / "dashboard.html"

        _run_campaign_cli(["init", "test-project"], repo)
        assert html.exists()
        mtime_before = html.stat().st_mtime_ns

        time.sleep(0.05)

        rc, _, _ = _run_campaign_cli(["show"], repo)
        assert rc == 0
        mtime_after = html.stat().st_mtime_ns
        assert mtime_after == mtime_before, "show modified the dashboard"


# ---------------------------------------------------------------------------
# Git integration tests
# ---------------------------------------------------------------------------

class TestGitIntegration:
    """Verify that state mutations produce git commits."""

    def test_init_creates_git_commit(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo

        rc, _, _ = _run_campaign_cli(["init", "test-project"], repo)
        assert rc == 0

        # Check git log
        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert "sdlc:" in result.stdout

    def test_stage_start_creates_git_commit(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        _run_campaign_cli(["stage-start", "concept"], repo)

        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert "sdlc:" in result.stdout
        assert "concept" in result.stdout.lower()

    def test_defer_creates_git_commit(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)
        _run_campaign_cli(["stage-start", "concept"], repo)

        _run_campaign_cli(
            ["defer", "Feature X", "--reason", "Not MVP"], repo
        )

        result = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert "sdlc:" in result.stdout
        assert "defer" in result.stdout.lower()

    def test_show_does_not_create_git_commit(self, temp_git_repo: Path) -> None:
        repo = temp_git_repo
        _run_campaign_cli(["init", "test-project"], repo)

        # Count commits
        result_before = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        count_before = int(result_before.stdout.strip())

        _run_campaign_cli(["show"], repo)

        result_after = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        count_after = int(result_after.stdout.strip())

        assert count_after == count_before, "show created a git commit"


# ---------------------------------------------------------------------------
# No external dependencies test
# ---------------------------------------------------------------------------

class TestNoExternalDependencies:
    """Verify campaign_status can be imported without pip install."""

    def test_import_succeeds_without_pip_install(
        self, temp_git_repo: Path
    ) -> None:
        env = os.environ.copy()
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = _SRC_DIR + (os.pathsep + existing if existing else "")

        result = subprocess.run(
            [sys.executable, "-c", "import campaign_status"],
            cwd=str(temp_git_repo),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"import failed: {result.stderr}"
