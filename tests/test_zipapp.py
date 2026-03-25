"""Smoke tests for the zipapp artifact (``dist/wave-status``).

Builds the zipapp once per session via ``scripts/ci/build.sh`` and then
exercises the resulting ``dist/wave-status`` binary through subprocess
invocations.  Catches regressions in the staging directory pattern,
wrapper ``__main__.py`` generation, and zipapp packaging.

Every test invokes ``dist/wave-status``, NOT ``python3 -m wave_status``.
"""

from __future__ import annotations

import json
import stat
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent
_BUILD_SCRIPT = _REPO_DIR / "scripts" / "ci" / "build.sh"
_ZIPAPP_PATH = _REPO_DIR / "dist" / "wave-status"


# ---------------------------------------------------------------------------
# Sample data (local copies — mirrors conftest.py)
# ---------------------------------------------------------------------------

_SAMPLE_PLAN: dict = {
    "project": "test-project",
    "base_branch": "main",
    "master_issue": 100,
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {
                    "id": "wave-1",
                    "name": "Wave 1",
                    "issues": [
                        {"number": 13, "title": "Issue 13", "deps": []},
                        {"number": 1, "title": "Issue 1", "deps": []},
                    ],
                },
                {
                    "id": "wave-2",
                    "name": "Wave 2",
                    "issues": [
                        {"number": 2, "title": "Issue 2", "deps": [13]},
                        {"number": 3, "title": "Issue 3", "deps": [1]},
                    ],
                },
            ],
        },
        {
            "name": "Enhancement",
            "waves": [
                {
                    "id": "wave-3",
                    "name": "Wave 3",
                    "issues": [
                        {"number": 5, "title": "Issue 5", "deps": [2, 3]},
                    ],
                },
            ],
        },
    ],
}

_SAMPLE_FLIGHTS: list = [
    {"issues": [13, 1], "status": "pending"},
]


# ---------------------------------------------------------------------------
# Session-scoped fixture: build the zipapp once
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def zipapp_binary() -> Path:
    """Build the zipapp via ``scripts/ci/build.sh`` and return its path.

    Runs once per session.  All tests in this module are skipped if the
    build fails or ``python3 -m zipapp`` is unavailable.
    """
    # Check that python3 -m zipapp is available
    probe = subprocess.run(
        ["python3", "-m", "zipapp", "--help"],
        capture_output=True,
    )
    if probe.returncode != 0:
        pytest.skip("python3 -m zipapp is unavailable")

    result = subprocess.run(
        ["bash", str(_BUILD_SCRIPT)],
        capture_output=True,
        text=True,
        cwd=str(_REPO_DIR),
    )
    if result.returncode != 0:
        pytest.skip(f"build.sh failed: {result.stderr}")

    if not _ZIPAPP_PATH.exists():
        pytest.skip(f"Zipapp not found at {_ZIPAPP_PATH} after build")

    return _ZIPAPP_PATH


# ---------------------------------------------------------------------------
# Helper: run the zipapp binary in a temp git repo
# ---------------------------------------------------------------------------

def _run_zipapp(
    binary: Path,
    args: list[str],
    cwd: str | Path,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """Run ``dist/wave-status <args>`` as a subprocess.

    Parameters
    ----------
    binary:
        Path to the zipapp executable.
    args:
        CLI arguments (e.g. ``["init", "plan.json"]``).
    cwd:
        Working directory — must be a git repo for ``get_project_root()``.
    input_text:
        Optional text piped to stdin.

    Returns
    -------
    tuple[int, str, str]
        ``(returncode, stdout, stderr)``
    """
    result = subprocess.run(
        [str(binary)] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        input=input_text,
    )
    return (result.returncode, result.stdout, result.stderr)


# ---------------------------------------------------------------------------
# Helper: write plan/flights to files in the temp git repo
# ---------------------------------------------------------------------------

def _write_plan(repo: Path, plan: dict | None = None) -> Path:
    """Write sample plan JSON to ``plan.json`` in *repo* and return the path."""
    p = repo / "plan.json"
    p.write_text(json.dumps(plan or _SAMPLE_PLAN), encoding="utf-8")
    return p


def _write_flights(repo: Path, flights: list | None = None) -> Path:
    """Write sample flights JSON to ``flights.json`` in *repo* and return the path."""
    p = repo / "flights.json"
    p.write_text(json.dumps(flights or _SAMPLE_FLIGHTS), encoding="utf-8")
    return p


# ===========================================================================
# Tests
# ===========================================================================


class TestZipappIsExecutable:
    """Verify the artifact exists and has correct permissions."""

    def test_zipapp_is_file(self, zipapp_binary: Path) -> None:
        """``dist/wave-status`` exists and is a regular file."""
        assert zipapp_binary.is_file()

    def test_zipapp_has_execute_permission(self, zipapp_binary: Path) -> None:
        """``dist/wave-status`` has the executable bit set."""
        mode = zipapp_binary.stat().st_mode
        assert mode & stat.S_IXUSR, "Owner execute bit not set"
        assert mode & stat.S_IXGRP, "Group execute bit not set"


class TestZipappHelp:
    """Verify ``--help`` works and lists all subcommands."""

    # The 14 subcommands from __main__.py
    _SUBCOMMANDS = [
        "init",
        "flight-plan",
        "preflight",
        "planning",
        "flight",
        "flight-done",
        "review",
        "complete",
        "waiting",
        "close-issue",
        "record-mr",
        "defer",
        "defer-accept",
        "show",
    ]

    def test_help_exits_zero(self, zipapp_binary: Path, temp_git_repo: Path) -> None:
        """``dist/wave-status --help`` exits 0."""
        rc, out, err = _run_zipapp(zipapp_binary, ["--help"], temp_git_repo)
        assert rc == 0, f"--help exited {rc}: {err}"

    def test_help_lists_all_subcommands(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """``dist/wave-status --help`` output mentions all 14 subcommands."""
        rc, out, err = _run_zipapp(zipapp_binary, ["--help"], temp_git_repo)
        assert rc == 0
        for cmd in self._SUBCOMMANDS:
            assert cmd in out, f"Subcommand '{cmd}' not found in --help output"


class TestZipappInitAndShow:
    """Init a plan via the zipapp, then show returns expected output."""

    def test_init_and_show(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """init followed by show prints project name and status fields."""
        repo = temp_git_repo
        _write_plan(repo)

        # init
        rc, out, err = _run_zipapp(zipapp_binary, ["init", "plan.json"], repo)
        assert rc == 0, f"init failed: {err}"

        # show
        rc, out, err = _run_zipapp(zipapp_binary, ["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "test-project" in out
        assert "Phase:" in out
        assert "Wave:" in out


class TestZipappFullLifecycle:
    """Full lifecycle: init through complete, all via zipapp binary."""

    def test_full_lifecycle(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """init -> preflight -> planning -> flight-plan -> flight 1 ->
        flight-done 1 -> review -> complete -> show.

        All via zipapp binary.  Verify exit codes and final state on disk.
        """
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo)

        # init
        rc, out, err = _run_zipapp(zipapp_binary, ["init", "plan.json"], repo)
        assert rc == 0, f"init failed: {err}"

        # preflight
        rc, out, err = _run_zipapp(zipapp_binary, ["preflight"], repo)
        assert rc == 0, f"preflight failed: {err}"

        # planning
        rc, out, err = _run_zipapp(zipapp_binary, ["planning"], repo)
        assert rc == 0, f"planning failed: {err}"

        # flight-plan
        rc, out, err = _run_zipapp(
            zipapp_binary, ["flight-plan", "flights.json"], repo
        )
        assert rc == 0, f"flight-plan failed: {err}"

        # flight 1
        rc, out, err = _run_zipapp(zipapp_binary, ["flight", "1"], repo)
        assert rc == 0, f"flight 1 failed: {err}"

        # close-issue 13
        rc, out, err = _run_zipapp(zipapp_binary, ["close-issue", "13"], repo)
        assert rc == 0, f"close-issue 13 failed: {err}"

        # record-mr 13 #14
        rc, out, err = _run_zipapp(
            zipapp_binary, ["record-mr", "13", "#14"], repo
        )
        assert rc == 0, f"record-mr 13 failed: {err}"

        # close-issue 1
        rc, out, err = _run_zipapp(zipapp_binary, ["close-issue", "1"], repo)
        assert rc == 0, f"close-issue 1 failed: {err}"

        # record-mr 1 #15
        rc, out, err = _run_zipapp(
            zipapp_binary, ["record-mr", "1", "#15"], repo
        )
        assert rc == 0, f"record-mr 1 failed: {err}"

        # flight-done 1
        rc, out, err = _run_zipapp(zipapp_binary, ["flight-done", "1"], repo)
        assert rc == 0, f"flight-done 1 failed: {err}"

        # review
        rc, out, err = _run_zipapp(zipapp_binary, ["review"], repo)
        assert rc == 0, f"review failed: {err}"

        # complete
        rc, out, err = _run_zipapp(zipapp_binary, ["complete"], repo)
        assert rc == 0, f"complete failed: {err}"

        # show — verify output
        rc, out, err = _run_zipapp(zipapp_binary, ["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "test-project" in out
        assert "Phase:" in out
        assert "Wave:" in out
        assert "Flight:" in out
        assert "Action:" in out
        assert "Progress:" in out
        assert "Deferrals:" in out

        # Verify state on disk
        state_path = repo / ".claude" / "status" / "state.json"
        assert state_path.exists(), "state.json not found after lifecycle"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["waves"]["wave-1"]["status"] == "completed"
        assert state["current_wave"] == "wave-2"
        assert state["issues"]["13"]["status"] == "closed"
        assert state["issues"]["1"]["status"] == "closed"
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#14"
        assert state["waves"]["wave-1"]["mr_urls"]["1"] == "#15"


class TestZipappErrorHandling:
    """Verify error exit codes from the zipapp binary."""

    def test_invalid_json_exits_2(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """Invalid JSON file -> exit 2."""
        repo = temp_git_repo
        bad_file = repo / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")

        rc, out, err = _run_zipapp(zipapp_binary, ["init", "bad.json"], repo)
        assert rc == 2

    def test_nonexistent_issue_exits_1(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """close-issue with a nonexistent issue number -> exit 1."""
        repo = temp_git_repo
        _write_plan(repo)
        _run_zipapp(zipapp_binary, ["init", "plan.json"], repo)

        rc, out, err = _run_zipapp(
            zipapp_binary, ["close-issue", "999"], repo
        )
        assert rc == 1
        assert "Error:" in err

    def test_no_subcommand_exits_2(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """No subcommand -> exit 2."""
        rc, out, err = _run_zipapp(zipapp_binary, [], temp_git_repo)
        assert rc == 2


class TestZipappStdin:
    """Verify stdin piping works through the zipapp."""

    def test_init_from_stdin(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """``echo '<plan>' | dist/wave-status init -`` reads from stdin."""
        repo = temp_git_repo
        plan_json = json.dumps(_SAMPLE_PLAN)

        rc, out, err = _run_zipapp(
            zipapp_binary, ["init", "-"], repo, plan_json
        )
        assert rc == 0, f"init from stdin failed: {err}"

        # Verify state was created
        state_path = repo / ".claude" / "status" / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["current_wave"] == "wave-1"


class TestZipappDashboardCreated:
    """Verify dashboard HTML is created by the zipapp."""

    def test_init_creates_dashboard(
        self, zipapp_binary: Path, temp_git_repo: Path
    ) -> None:
        """After init via zipapp, ``.status-panel.html`` exists."""
        repo = temp_git_repo
        _write_plan(repo)

        rc, _, err = _run_zipapp(zipapp_binary, ["init", "plan.json"], repo)
        assert rc == 0, f"init failed: {err}"

        html = repo / ".status-panel.html"
        assert html.exists(), "Dashboard HTML was not created by zipapp init"
        content = html.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
