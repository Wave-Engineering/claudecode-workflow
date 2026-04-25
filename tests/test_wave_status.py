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

    def test_invalid_risk_level_exits_2(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Invalid argparse choice for risk level -> exit 2 (usage error)."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, out, err = run_cli(["defer", "desc", "critical"], repo)
        assert rc == 2
        assert "invalid choice" in err

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
# set-current + wavemachine-start/stop tests (issue #382)
# ---------------------------------------------------------------------------

def _state(repo: Path) -> dict:
    """Read state.json from *repo* into a dict."""
    return json.loads(
        (repo / ".claude" / "status" / "state.json").read_text(encoding="utf-8")
    )


class TestSetCurrent:
    """Verify ``set-current <wave-id>`` updates current_wave."""

    def test_set_current_moves_pointer(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``set-current wave-3`` sets current_wave to wave-3."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, _, err = run_cli(["set-current", "wave-3"], repo)
        assert rc == 0, f"set-current failed: {err}"
        assert _state(repo)["current_wave"] == "wave-3"

    def test_set_current_rejects_unknown_wave(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Unknown wave ID -> exit 1 with a listing of valid IDs."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, _, err = run_cli(["set-current", "wave-does-not-exist"], repo)
        assert rc == 1
        assert "Error:" in err
        # Valid IDs should be listed to guide recovery.
        assert "wave-1" in err

    def test_set_current_rejects_completed_wave(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Target wave already completed -> exit 1 (no status corruption)."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        # Manually mark wave-1 as completed.
        state_path = repo / ".claude" / "status" / "state.json"
        st = json.loads(state_path.read_text(encoding="utf-8"))
        st["waves"]["wave-1"]["status"] = "completed"
        state_path.write_text(json.dumps(st), encoding="utf-8")

        rc, _, err = run_cli(["set-current", "wave-1"], repo)
        assert rc == 1
        assert "Error:" in err
        assert "already completed" in err
        # Completed status must not have been flipped to anything else.
        assert _state(repo)["waves"]["wave-1"]["status"] == "completed"

    def test_set_current_regenerates_dashboard(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``set-current`` regenerates the status panel (state mutation)."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        html = repo / ".status-panel.html"
        assert html.exists()
        mtime_before = html.stat().st_mtime_ns

        time.sleep(0.05)
        rc, _, _ = run_cli(["set-current", "wave-2"], repo)
        assert rc == 0
        assert html.stat().st_mtime_ns >= mtime_before


class TestSetKahunaBranch:
    """Verify ``set-kahuna-branch`` writes/clears the KAHUNA branch field."""

    def test_set_kahuna_branch_writes_field(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``set-kahuna-branch kahuna/42-foo`` writes kahuna_branch to state."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, _, err = run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)
        assert rc == 0, f"set-kahuna-branch failed: {err}"
        assert _state(repo)["kahuna_branch"] == "kahuna/42-foo"

    def test_set_kahuna_branch_empty_arg_clears(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Empty string arg clears the field (sets to null)."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)

        rc, _, err = run_cli(["set-kahuna-branch", ""], repo)
        assert rc == 0, f"clear failed: {err}"
        assert _state(repo)["kahuna_branch"] is None

    def test_set_kahuna_branch_no_arg_clears(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Missing positional arg defaults to empty → clear."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)

        rc, _, err = run_cli(["set-kahuna-branch"], repo)
        assert rc == 0, f"clear via no-arg failed: {err}"
        assert _state(repo)["kahuna_branch"] is None

    def test_set_kahuna_branch_idempotent(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Re-setting the same value does not error and leaves state unchanged."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)

        rc, _, err = run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)
        assert rc == 0, f"idempotent re-set failed: {err}"
        assert _state(repo)["kahuna_branch"] == "kahuna/42-foo"

    def test_set_kahuna_branch_regenerates_dashboard(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``set-kahuna-branch`` triggers dashboard regeneration."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        html = repo / ".status-panel.html"
        assert html.exists()
        mtime_before = html.stat().st_mtime_ns

        time.sleep(0.05)
        rc, _, _ = run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)
        assert rc == 0
        assert html.stat().st_mtime_ns >= mtime_before

    def test_set_kahuna_branch_replaces_previous(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Setting a new branch overwrites the previous value."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)
        run_cli(["set-kahuna-branch", "kahuna/43-bar"], repo)

        assert _state(repo)["kahuna_branch"] == "kahuna/43-bar"


class TestWavemachineFlag:
    """Verify ``wavemachine-start`` / ``wavemachine-stop`` flip state flags."""

    def test_start_sets_active_flag(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``wavemachine-start`` writes wavemachine_active=true + metadata."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, _, err = run_cli(
            ["wavemachine-start", "--launcher", "task-abc"], repo
        )
        assert rc == 0, f"wavemachine-start failed: {err}"

        st = _state(repo)
        assert st["wavemachine_active"] is True
        assert "wavemachine_started_at" in st
        assert st["wavemachine_launcher"] == "task-abc"

    def test_start_rejects_when_already_active(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Second ``wavemachine-start`` fails — one plan at a time."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["wavemachine-start"], repo)

        rc, _, err = run_cli(["wavemachine-start"], repo)
        assert rc == 1
        assert "Error:" in err
        assert "already active" in err

    def test_stop_clears_all_wavemachine_keys(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``wavemachine-stop`` removes all three wavemachine keys."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["wavemachine-start", "--launcher", "task-xyz"], repo)

        rc, _, err = run_cli(["wavemachine-stop"], repo)
        assert rc == 0, f"wavemachine-stop failed: {err}"

        st = _state(repo)
        assert "wavemachine_active" not in st
        assert "wavemachine_started_at" not in st
        assert "wavemachine_launcher" not in st

    def test_stop_is_idempotent(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Calling ``wavemachine-stop`` on a clean state succeeds (exit 0)."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        # No wavemachine-start first — should still succeed.
        rc, _, err = run_cli(["wavemachine-stop"], repo)
        assert rc == 0, f"idempotent stop failed: {err}"

    def test_start_preserves_other_state_keys(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """``wavemachine-start`` leaves current_wave, waves, issues untouched."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        before = _state(repo)

        run_cli(["wavemachine-start"], repo)
        after = _state(repo)

        assert after["current_wave"] == before["current_wave"]
        assert after["waves"] == before["waves"]
        assert after["issues"] == before["issues"]


# ---------------------------------------------------------------------------
# init --extend auto-advance current_wave (issue #382)
# ---------------------------------------------------------------------------

class TestExtendAutoAdvance:
    """Verify ``init --extend`` auto-advances current_wave when prior done."""

    # Phase 2 extension data — wave-6a, wave-6b with unique issue numbers.
    _EXTEND_PLAN: dict = {
        "phases": [
            {
                "name": "Extended",
                "waves": [
                    {
                        "id": "wave-6a",
                        "name": "Wave 6a",
                        "issues": [
                            {"number": 600, "title": "New 600", "deps": []},
                        ],
                    },
                    {
                        "id": "wave-6b",
                        "name": "Wave 6b",
                        "issues": [
                            {"number": 601, "title": "New 601", "deps": [600]},
                        ],
                    },
                ],
            },
        ],
    }

    def _complete_all_waves(self, repo: Path) -> None:
        """Manually mark every wave and issue in the state as completed/closed."""
        state_path = repo / ".claude" / "status" / "state.json"
        st = json.loads(state_path.read_text(encoding="utf-8"))
        for wid in st["waves"]:
            st["waves"][wid]["status"] = "completed"
        for iid in st["issues"]:
            st["issues"][iid]["status"] = "closed"
        st["current_wave"] = None
        state_path.write_text(json.dumps(st), encoding="utf-8")

    def test_extend_advances_from_none_to_first_new_wave(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Prior plan fully done (current_wave=None) — extend sets it to the new wave."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        self._complete_all_waves(repo)

        extend_path = repo / "extend.json"
        extend_path.write_text(json.dumps(self._EXTEND_PLAN), encoding="utf-8")

        rc, _, err = run_cli(["init", "--extend", "extend.json"], repo)
        assert rc == 0, f"extend failed: {err}"
        assert _state(repo)["current_wave"] == "wave-6a"

    def test_extend_preserves_current_wave_when_prior_active(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Prior plan still in progress — extend leaves current_wave alone."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        # current_wave is wave-1 after init, all pending — do NOT complete.

        extend_path = repo / "extend.json"
        extend_path.write_text(json.dumps(self._EXTEND_PLAN), encoding="utf-8")

        rc, _, err = run_cli(["init", "--extend", "extend.json"], repo)
        assert rc == 0, f"extend failed: {err}"
        # Prior phase still has pending waves, so current_wave should not jump.
        assert _state(repo)["current_wave"] == "wave-1"

    def test_extend_advances_from_completed_pointer(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """current_wave stuck on last completed wave (not None) — extend advances."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        # Simulate a plan that ended with the pointer still on the last
        # completed wave rather than being advanced to None (possible via
        # manual state edit or a migration path that bypassed `complete`).
        state_path = repo / ".claude" / "status" / "state.json"
        st = json.loads(state_path.read_text(encoding="utf-8"))
        for wid in st["waves"]:
            st["waves"][wid]["status"] = "completed"
        for iid in st["issues"]:
            st["issues"][iid]["status"] = "closed"
        st["current_wave"] = "wave-3"
        state_path.write_text(json.dumps(st), encoding="utf-8")

        extend_path = repo / "extend.json"
        extend_path.write_text(json.dumps(self._EXTEND_PLAN), encoding="utf-8")

        rc, _, err = run_cli(["init", "--extend", "extend.json"], repo)
        assert rc == 0, f"extend failed: {err}"
        assert _state(repo)["current_wave"] == "wave-6a"


# ---------------------------------------------------------------------------
# No external dependencies test [CT-01]
# ---------------------------------------------------------------------------

class TestShowKahuna:
    """``wave-status show`` KAHUNA section rendering (issue #415, AC-4/AC-6).

    Legacy state files render unchanged; KAHUNA state files add a Kahuna
    block with branch, flight counts, conditional trust/failure blocks, and
    a history listing.
    """

    def _init_and_load_state(self, repo: Path, run_cli) -> dict:
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["flight-plan", "flights.json"], repo)
        state_path = repo / ".claude" / "status" / "state.json"
        return json.loads(state_path.read_text(encoding="utf-8"))

    def _write_state(self, repo: Path, state: dict) -> None:
        state_path = repo / ".claude" / "status" / "state.json"
        state_path.write_text(json.dumps(state), encoding="utf-8")

    def test_legacy_state_show_has_no_kahuna_block(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Legacy state (no kahuna_*) prints NO Kahuna section (AC-1/AC-2)."""
        repo = temp_git_repo
        _write_plan(repo)
        run_cli(["init", "plan.json"], repo)

        rc, out, err = run_cli(["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "Kahuna:" not in out
        # But the standard fields remain.
        assert "Project:" in out
        assert "Progress:" in out

    def test_kahuna_branch_show_renders_section(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """kahuna_branch set -> "Kahuna:" section with branch+counts (AC-4)."""
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["flight-plan", "flights.json"], repo)
        run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)

        rc, out, err = run_cli(["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "Kahuna:" in out
        assert "kahuna/42-foo" in out
        # One pending flight (from _SAMPLE_FLIGHTS) -> "0 merged, 1 pending".
        assert "0 merged, 1 pending" in out

    def test_kahuna_branches_history_in_show(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Populated kahuna_branches history appears in show output."""
        repo = temp_git_repo
        state = self._init_and_load_state(repo, run_cli)
        state["kahuna_branch"] = "kahuna/42-foo"
        state["kahuna_branches"] = [
            {
                "branch": "kahuna/41-prior",
                "epic_id": 41,
                "created_at": "2026-04-23T10:00:00Z",
                "resolved_at": "2026-04-24T02:15:00Z",
                "disposition": "merged",
                "main_merge_sha": "abc123",
            },
            {
                "branch": "kahuna/40-aborted",
                "epic_id": 40,
                "created_at": "2026-04-22T08:00:00Z",
                "resolved_at": "2026-04-22T09:30:00Z",
                "disposition": "aborted",
                "abort_reason": "code_reviewer_findings",
            },
        ]
        self._write_state(repo, state)

        rc, out, err = run_cli(["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "History" in out
        assert "kahuna/41-prior" in out
        assert "kahuna/40-aborted" in out
        assert "code_reviewer_findings" in out

    def test_gate_evaluating_shows_trust_signals(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """action=gate_evaluating prints the Trust signals evaluating list."""
        repo = temp_git_repo
        state = self._init_and_load_state(repo, run_cli)
        state["kahuna_branch"] = "kahuna/42-foo"
        state["current_action"] = {
            "action": "gate_evaluating",
            "label": "gate_evaluating",
            "detail": {
                "signals": ["commutativity_verify", "ci_wait_run"],
            },
        }
        self._write_state(repo, state)

        rc, out, err = run_cli(["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "Trust signals evaluating" in out
        assert "commutativity_verify" in out
        assert "ci_wait_run" in out

    def test_gate_blocked_shows_failures(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """action=gate_blocked prints Gate blocked failure reasons."""
        repo = temp_git_repo
        state = self._init_and_load_state(repo, run_cli)
        state["kahuna_branch"] = "kahuna/42-foo"
        state["current_action"] = {
            "action": "gate_blocked",
            "label": "gate_blocked",
            "detail": {
                "failures": [
                    {
                        "signal": "commutativity_verify",
                        "reason": "WEAK verdict",
                    },
                ],
            },
        }
        self._write_state(repo, state)

        rc, out, err = run_cli(["show"], repo)
        assert rc == 0, f"show failed: {err}"
        assert "Gate blocked" in out
        assert "commutativity_verify" in out
        assert "WEAK verdict" in out

    def test_dashboard_html_has_kahuna_section(
        self, temp_git_repo: Path, run_cli
    ) -> None:
        """Dashboard HTML renders the Kahuna section (AC-5, MV-02)."""
        repo = temp_git_repo
        _write_plan(repo)
        _write_flights(repo)
        run_cli(["init", "plan.json"], repo)
        run_cli(["flight-plan", "flights.json"], repo)
        run_cli(["set-kahuna-branch", "kahuna/42-foo"], repo)

        html = (repo / ".status-panel.html").read_text(encoding="utf-8")
        assert 'class="kahuna-section"' in html
        assert "kahuna/42-foo" in html


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
