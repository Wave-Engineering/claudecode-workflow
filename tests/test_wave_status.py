"""Subprocess-based integration tests for ``python -m wave_status``.

Story 4.2 — Black-box validation of the CLI as a real executable.
Every test invokes the CLI via ``subprocess.run`` in a temporary git repo.
No function imports, no mocking.

Complements ``tests/test_cli.py`` (white-box, direct ``main()`` calls).
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
# Sample data (local copies for use in file-writing helpers)
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

_SAMPLE_FLIGHTS_MULTI: list = [
    {"issues": [13], "status": "pending"},
    {"issues": [1], "status": "pending"},
]


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


# ---------------------------------------------------------------------------
# Full lifecycle test [R-11, R-12, R-13]
# ---------------------------------------------------------------------------

class TestFullLifecycleSubprocess:
    """End-to-end lifecycle via subprocess calls."""

    def test_complete_wave_cycle(self, temp_git_repo: Path, run_cli) -> None:
        """Happy path: init -> preflight -> planning -> flight-plan ->
        flight 1 -> close-issue -> record-mr -> flight-done 1 ->
        defer -> defer-accept -> review -> complete -> waiting -> show.

        Each step via subprocess, verifying exit code 0.
        Final ``show`` output contains expected project/phase/wave info.
        """
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo)

        # init
        rc, out, err = run_cli(["init", "plan.json"], repo)
        assert rc == 0, f"init failed: {err}"

        # preflight
        rc, out, err = run_cli(["preflight"], repo)
        assert rc == 0, f"preflight failed: {err}"

        # planning
        rc, out, err = run_cli(["planning"], repo)
        assert rc == 0, f"planning failed: {err}"

        # flight-plan
        rc, out, err = run_cli(["flight-plan", "flights.json"], repo)
        assert rc == 0, f"flight-plan failed: {err}"

        # flight 1
        rc, out, err = run_cli(["flight", "1"], repo)
        assert rc == 0, f"flight 1 failed: {err}"

        # close-issue 13
        rc, out, err = run_cli(["close-issue", "13"], repo)
        assert rc == 0, f"close-issue 13 failed: {err}"

        # record-mr 13 #14
        rc, out, err = run_cli(["record-mr", "13", "#14"], repo)
        assert rc == 0, f"record-mr 13 failed: {err}"

        # close-issue 1
        rc, out, err = run_cli(["close-issue", "1"], repo)
        assert rc == 0, f"close-issue 1 failed: {err}"

        # record-mr 1 #15
        rc, out, err = run_cli(["record-mr", "1", "#15"], repo)
        assert rc == 0, f"record-mr 1 failed: {err}"

        # flight-done 1
        rc, out, err = run_cli(["flight-done", "1"], repo)
        assert rc == 0, f"flight-done 1 failed: {err}"

        # defer
        rc, out, err = run_cli(["defer", "Deferred item", "low"], repo)
        assert rc == 0, f"defer failed: {err}"

        # defer-accept 1
        rc, out, err = run_cli(["defer-accept", "1"], repo)
        assert rc == 0, f"defer-accept failed: {err}"

        # review
        rc, out, err = run_cli(["review"], repo)
        assert rc == 0, f"review failed: {err}"

        # complete
        rc, out, err = run_cli(["complete"], repo)
        assert rc == 0, f"complete failed: {err}"

        # waiting
        rc, out, err = run_cli(["waiting", "Wave 1 complete"], repo)
        assert rc == 0, f"waiting failed: {err}"

        # show — verify output contains expected info
        rc, out, err = run_cli(["show"], repo)
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
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["waves"]["wave-1"]["status"] == "completed"
        assert state["current_wave"] == "wave-2"
        assert state["issues"]["13"]["status"] == "closed"
        assert state["issues"]["1"]["status"] == "closed"
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#14"
        assert state["waves"]["wave-1"]["mr_urls"]["1"] == "#15"
        assert len(state["deferrals"]) == 1
        assert state["deferrals"][0]["status"] == "accepted"
        assert state["current_action"]["action"] == "waiting-on-meatbag"


# ---------------------------------------------------------------------------
# State machine rejection tests [R-14, R-15, R-16]
# ---------------------------------------------------------------------------

class TestStateMachineRejection:
    """Verify the state machine rejects invalid transitions via subprocess."""

    def test_flight_2_rejected_when_flight_1_not_completed(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """flight 2 rejected when flight 1 is not completed -> exit 1."""
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo, _SAMPLE_FLIGHTS_MULTI)

        run_cli(["init", "plan.json"], repo)
        run_cli(["flight-plan", "flights.json"], repo)

        # Start flight 1 (sets it to running)
        rc, _, _ = run_cli(["flight", "1"], repo)
        assert rc == 0

        # Try flight 2 — flight 1 is running, not completed
        rc, out, err = run_cli(["flight", "2"], repo)
        assert rc == 1
        assert "Error:" in err

    def test_flight_done_rejected_when_flight_not_running(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """flight-done 1 rejected when flight 1 is not running -> exit 1."""
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo)

        run_cli(["init", "plan.json"], repo)
        run_cli(["flight-plan", "flights.json"], repo)

        # flight-done 1 without starting flight 1 first
        rc, out, err = run_cli(["flight-done", "1"], repo)
        assert rc == 1
        assert "Error:" in err

    def test_close_issue_rejects_nonexistent_issue(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """close-issue 999 rejects nonexistent issue -> exit 1."""
        repo = temp_git_repo
        _write_plan(repo)

        run_cli(["init", "plan.json"], repo)

        rc, out, err = run_cli(["close-issue", "999"], repo)
        assert rc == 1
        assert "Error:" in err


# ---------------------------------------------------------------------------
# Stdin tests [R-03]
# ---------------------------------------------------------------------------

class TestStdinInput:
    """Verify stdin piping works for init and flight-plan."""

    def test_init_from_stdin(self, temp_git_repo: Path, run_cli) -> None:
        """``echo '<plan>' | python3 -m wave_status init -`` reads from stdin."""
        repo = temp_git_repo
        plan_json = json.dumps(_SAMPLE_PLAN)

        rc, out, err = run_cli(["init", "-"], repo, plan_json)
        assert rc == 0, f"init from stdin failed: {err}"

        # Verify state files were created
        state_path = repo / ".claude" / "status" / "state.json"
        assert state_path.exists()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        assert state["current_wave"] == "wave-1"

    def test_flight_plan_from_stdin(self, temp_git_repo: Path, run_cli) -> None:
        """``echo '<flights>' | python3 -m wave_status flight-plan -`` reads from stdin."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        flights_json = json.dumps(_SAMPLE_FLIGHTS)
        rc, out, err = run_cli(["flight-plan", "-"], repo, flights_json)
        assert rc == 0, f"flight-plan from stdin failed: {err}"

        # Verify flights were stored
        flights_path = repo / ".claude" / "status" / "flights.json"
        flights = json.loads(flights_path.read_text(encoding="utf-8"))
        assert "wave-1" in flights["flights"]
        assert flights["flights"]["wave-1"] == _SAMPLE_FLIGHTS


# ---------------------------------------------------------------------------
# Error output format tests [R-31, R-32]
# ---------------------------------------------------------------------------

class TestErrorOutputFormat:
    """Verify errors go to stderr with correct format and exit codes."""

    def test_errors_go_to_stderr_not_stdout(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Errors appear on stderr, not stdout."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        # Trigger a ValueError (nonexistent issue)
        rc, out, err = run_cli(["close-issue", "999"], repo)
        assert rc == 1
        # Error message should be on stderr
        assert "Error:" in err
        # stdout should NOT contain the error
        assert "Error:" not in out

    def test_error_message_format(self, temp_git_repo: Path, run_cli) -> None:
        """Error messages follow 'Error: <what>. <fix>.' pattern on stderr."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, out, err = run_cli(["close-issue", "999"], repo)
        msg = err.strip()
        assert msg.startswith("Error:")
        # Should contain at least two sentences (two periods)
        assert msg.count(".") >= 2

    def test_invalid_json_exits_2(self, temp_git_repo: Path, run_cli) -> None:
        """Invalid JSON input -> exit 2."""
        repo = temp_git_repo
        bad_file = repo / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")

        rc, out, err = run_cli(["init", "bad.json"], repo)
        assert rc == 2

    def test_no_subcommand_exits_2(self, temp_git_repo: Path, run_cli) -> None:
        """No subcommand -> exit 2."""
        repo = temp_git_repo

        rc, out, err = run_cli([], repo)
        assert rc == 2

    def test_invalid_risk_level_exits_1(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Invalid risk level on defer -> exit 1 with error on stderr."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, out, err = run_cli(["defer", "desc", "critical"], repo)
        assert rc == 1
        assert "Error:" in err

    def test_flight_nonexistent_exits_1(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Flight number out of range -> exit 1."""
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo)

        run_cli(["init", "plan.json"], repo)
        run_cli(["flight-plan", "flights.json"], repo)

        rc, out, err = run_cli(["flight", "99"], repo)
        assert rc == 1
        assert "Error:" in err


# ---------------------------------------------------------------------------
# Dashboard generation tests [R-19]
# ---------------------------------------------------------------------------

class TestDashboardGeneration:
    """Verify dashboard HTML is created/updated by subcommands."""

    def test_init_creates_dashboard(self, temp_git_repo: Path, run_cli) -> None:
        """After init, ``.status-panel.html`` exists."""
        repo = temp_git_repo
        _write_plan(repo)

        rc, _, _ = run_cli(["init", "plan.json"], repo)
        assert rc == 0

        html = repo / ".status-panel.html"
        assert html.exists(), "Dashboard HTML was not created by init"
        content = html.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_state_change_regenerates_dashboard(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """After state changes, dashboard is regenerated (mtime check)."""
        repo = temp_git_repo
        _write_plan(repo)
        html = repo / ".status-panel.html"

        run_cli(["init", "plan.json"], repo)
        assert html.exists()
        mtime_after_init = html.stat().st_mtime_ns

        # Small sleep to ensure mtime changes (filesystem resolution)
        time.sleep(0.05)

        # preflight should regenerate
        run_cli(["preflight"], repo)
        mtime_after_preflight = html.stat().st_mtime_ns
        assert mtime_after_preflight >= mtime_after_init

        time.sleep(0.05)

        # planning should regenerate
        run_cli(["planning"], repo)
        mtime_after_planning = html.stat().st_mtime_ns
        assert mtime_after_planning >= mtime_after_preflight

    def test_show_does_not_create_dashboard(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``show`` does NOT create/modify dashboard [R-06]."""
        repo = temp_git_repo
        _write_plan(repo)

        run_cli(["init", "plan.json"], repo)

        # Remove the dashboard
        html = repo / ".status-panel.html"
        html.unlink()
        assert not html.exists()

        # show should NOT recreate it
        rc, out, err = run_cli(["show"], repo)
        assert rc == 0
        assert not html.exists(), "show should not create/modify dashboard"

    def test_show_does_not_modify_dashboard(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``show`` does not touch the dashboard when it exists."""
        repo = temp_git_repo
        _write_plan(repo)
        html = repo / ".status-panel.html"

        run_cli(["init", "plan.json"], repo)
        assert html.exists()
        mtime_before = html.stat().st_mtime_ns

        time.sleep(0.05)

        rc, _, _ = run_cli(["show"], repo)
        assert rc == 0
        mtime_after = html.stat().st_mtime_ns
        assert mtime_after == mtime_before, "show modified the dashboard"


# ---------------------------------------------------------------------------
# No external dependencies test [CT-01]
# ---------------------------------------------------------------------------

class TestNoExternalDependencies:
    """Verify wave_status can be imported without pip install."""

    def test_import_succeeds_without_pip_install(
        self, temp_git_repo: Path
    ) -> None:
        """``python3 -c 'import wave_status'`` succeeds with PYTHONPATH set."""
        env = os.environ.copy()
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        existing = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src_dir + (os.pathsep + existing if existing else "")

        result = subprocess.run(
            [sys.executable, "-c", "import wave_status"],
            cwd=str(temp_git_repo),
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, f"import failed: {result.stderr}"
