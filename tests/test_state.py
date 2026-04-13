"""Tests for src/wave_status/state.py — Story 1.1: State Machine.

Tests exercise REAL code paths.  Mocks are used ONLY for:
  - ``subprocess.run`` (external git process — true external boundary)
  - No other mocking.

Filesystem I/O uses ``tmp_path`` (pytest built-in) so tests write real
files to a temporary directory — no filesystem mocking.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wave_status.state import (
    close_issue,
    complete,
    ensure_status_dir,
    flight,
    flight_done,
    get_project_root,
    html_path,
    init_state,
    load_json,
    planning,
    preflight,
    record_mr,
    review,
    save_json,
    show,
    status_dir,
    store_flight_plan,
    waiting,
    waiting_ci,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PLAN = {
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

SAMPLE_FLIGHTS = [
    {"issues": [13, 1], "status": "pending"},
]

SAMPLE_FLIGHTS_MULTI = [
    {"issues": [2], "status": "pending"},
    {"issues": [3], "status": "pending"},
]


@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Set up a fake project root with init already called."""
    init_state(SAMPLE_PLAN, tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

class TestGetProjectRoot:
    """Tests for get_project_root() [R-31, R-34]."""

    def test_returns_path_inside_git_repo(self, tmp_path: Path) -> None:
        """Happy path: git rev-parse succeeds."""
        fake_root = str(tmp_path / "my-repo")
        with patch("wave_status.state.subprocess.run") as mock_run:
            mock_run.return_value.stdout = fake_root + "\n"
            mock_run.return_value.returncode = 0
            result = get_project_root()
            assert result == Path(fake_root)
            mock_run.assert_called_once()

    def test_raises_outside_git_repo(self) -> None:
        """Error case: not inside a git repo [R-31]."""
        import subprocess as real_subprocess

        with patch(
            "wave_status.state.subprocess.run",
            side_effect=real_subprocess.CalledProcessError(128, "git"),
        ):
            with pytest.raises(ValueError, match="Error:.*not inside a git repository"):
                get_project_root()

    def test_error_message_format(self) -> None:
        """Error messages follow 'Error: <what>. <fix>.' [R-32]."""
        import subprocess as real_subprocess

        with patch(
            "wave_status.state.subprocess.run",
            side_effect=real_subprocess.CalledProcessError(128, "git"),
        ):
            with pytest.raises(ValueError, match=r"Error:.*\..+\."):
                get_project_root()


class TestPathHelpers:
    """Tests for status_dir, html_path, ensure_status_dir."""

    def test_status_dir(self, tmp_path: Path) -> None:
        assert status_dir(tmp_path) == tmp_path / ".claude" / "status"

    def test_html_path(self, tmp_path: Path) -> None:
        assert html_path(tmp_path) == tmp_path / ".status-panel.html"

    def test_ensure_status_dir_creates_directory(self, tmp_path: Path) -> None:
        """[R-35] Creates .claude/status/ if absent."""
        d = ensure_status_dir(tmp_path)
        assert d.is_dir()
        assert d == tmp_path / ".claude" / "status"

    def test_ensure_status_dir_idempotent(self, tmp_path: Path) -> None:
        """Calling twice does not error."""
        ensure_status_dir(tmp_path)
        d = ensure_status_dir(tmp_path)
        assert d.is_dir()


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------

class TestAtomicJsonIO:
    """Tests for load_json and save_json [R-33]."""

    def test_save_and_load_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "test.json"
        data = {"key": "value", "nested": {"a": 1}}
        save_json(path, data)
        loaded = load_json(path)
        assert loaded == data

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "a" / "b" / "test.json"
        save_json(path, {"x": 1})
        assert path.exists()
        assert load_json(path) == {"x": 1}

    def test_atomic_write_no_temp_files_left(self, tmp_path: Path) -> None:
        """After a successful write, no .tmp files remain."""
        path = tmp_path / "data.json"
        save_json(path, {"a": 1})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_save_overwrites_existing(self, tmp_path: Path) -> None:
        path = tmp_path / "data.json"
        save_json(path, {"v": 1})
        save_json(path, {"v": 2})
        assert load_json(path) == {"v": 2}

    def test_save_json_produces_valid_json(self, tmp_path: Path) -> None:
        """File content is valid JSON parseable by the stdlib."""
        path = tmp_path / "data.json"
        save_json(path, {"hello": "world"})
        with open(path) as f:
            data = json.load(f)
        assert data == {"hello": "world"}


# ---------------------------------------------------------------------------
# init_state [R-02]
# ---------------------------------------------------------------------------

class TestInitState:
    """Tests for init_state() — writes phases-waves.json, state.json,
    flights.json [R-02]."""

    def test_creates_all_three_files(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        d = status_dir(tmp_path)
        assert (d / "phases-waves.json").exists()
        assert (d / "state.json").exists()
        assert (d / "flights.json").exists()

    def test_phases_waves_matches_plan(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        pw = load_json(status_dir(tmp_path) / "phases-waves.json")
        assert pw["project"] == "test-project"
        assert len(pw["phases"]) == 2
        assert pw["phases"][0]["waves"][0]["id"] == "wave-1"

    def test_state_json_all_waves_pending(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        for wid in ("wave-1", "wave-2", "wave-3"):
            assert state["waves"][wid]["status"] == "pending"

    def test_state_json_all_issues_open(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        for num in (13, 1, 2, 3, 5):
            assert state["issues"][str(num)]["status"] == "open"

    def test_state_json_current_wave_is_first(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["current_wave"] == "wave-1"

    def test_state_json_current_action_idle(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["current_action"]["action"] == "idle"

    def test_state_json_empty_deferrals(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["deferrals"] == []

    def test_state_json_has_last_updated(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert "last_updated" in state
        assert state["last_updated"].endswith("Z")

    def test_flights_json_empty(self, tmp_path: Path) -> None:
        init_state(SAMPLE_PLAN, tmp_path)
        fl = load_json(status_dir(tmp_path) / "flights.json")
        assert fl == {"flights": {}}

    def test_waves_have_mr_urls(self, tmp_path: Path) -> None:
        """Each wave state should have an mr_urls dict (backward compat)."""
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        for wid in ("wave-1", "wave-2", "wave-3"):
            assert "mr_urls" in state["waves"][wid]
            assert state["waves"][wid]["mr_urls"] == {}

    def test_creates_status_dir(self, tmp_path: Path) -> None:
        """[R-35] init creates .claude/status/ if absent."""
        init_state(SAMPLE_PLAN, tmp_path)
        assert (tmp_path / ".claude" / "status").is_dir()

    def test_rejects_missing_project(self, tmp_path: Path) -> None:
        """[R-32] Error on missing 'project'."""
        bad_plan = {"phases": []}
        with pytest.raises(ValueError, match="Error:.*project"):
            init_state(bad_plan, tmp_path)

    def test_rejects_missing_phases(self, tmp_path: Path) -> None:
        """[R-32] Error on missing 'phases'."""
        bad_plan = {"project": "x"}
        with pytest.raises(ValueError, match="Error:.*phases"):
            init_state(bad_plan, tmp_path)

    def test_rejects_non_list_phases(self, tmp_path: Path) -> None:
        bad_plan = {"project": "x", "phases": "not-a-list"}
        with pytest.raises(ValueError, match="Error:.*phases"):
            init_state(bad_plan, tmp_path)


# ---------------------------------------------------------------------------
# store_flight_plan [R-04]
# ---------------------------------------------------------------------------

class TestStoreFlightPlan:
    """Tests for store_flight_plan() [R-04]."""

    def test_stores_flights_for_current_wave(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        fl = load_json(status_dir(project_root) / "flights.json")
        assert "wave-1" in fl["flights"]
        assert fl["flights"]["wave-1"] == SAMPLE_FLIGHTS

    def test_raises_when_no_current_wave(self, tmp_path: Path) -> None:
        """Error when current_wave is null."""
        d = ensure_status_dir(tmp_path)
        save_json(d / "state.json", {"current_wave": None})
        save_json(d / "flights.json", {"flights": {}})
        with pytest.raises(ValueError, match="Error:.*no current wave"):
            store_flight_plan(SAMPLE_FLIGHTS, tmp_path)


# ---------------------------------------------------------------------------
# Lifecycle transitions [R-05]
# ---------------------------------------------------------------------------

class TestPreflight:
    def test_sets_action_to_preflight(self, project_root: Path) -> None:
        result = preflight(project_root)
        assert result["current_action"]["action"] == "pre-flight"

    def test_persists_to_disk(self, project_root: Path) -> None:
        preflight(project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "pre-flight"


class TestPlanning:
    def test_sets_action_to_planning(self, project_root: Path) -> None:
        result = planning(project_root)
        assert result["current_action"]["action"] == "planning"

    def test_sets_current_wave_to_in_progress(self, project_root: Path) -> None:
        result = planning(project_root)
        assert result["waves"]["wave-1"]["status"] == "in_progress"

    def test_persists_wave_status(self, project_root: Path) -> None:
        planning(project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-1"]["status"] == "in_progress"


class TestReview:
    def test_sets_action_to_review(self, project_root: Path) -> None:
        result = review(project_root)
        assert result["current_action"]["action"] == "post-wave-review"


class TestWaiting:
    def test_sets_action_to_waiting(self, project_root: Path) -> None:
        result = waiting(project_root)
        assert result["current_action"]["action"] == "waiting-on-meatbag"

    def test_includes_message(self, project_root: Path) -> None:
        result = waiting(project_root, msg="Wave 1 complete.")
        assert result["current_action"]["detail"] == "Wave 1 complete."


class TestWaitingCi:
    """Tests for ``waiting_ci()`` — heartbeat during CI polling (#172)."""

    def test_sets_action_to_waiting_ci(self, project_root: Path) -> None:
        result = waiting_ci(project_root)
        assert result["current_action"]["action"] == "waiting-ci"
        assert result["current_action"]["label"] == "waiting-ci"

    def test_includes_detail(self, project_root: Path) -> None:
        result = waiting_ci(project_root, detail="PR #42 attempt 3: 2/5 passed")
        assert result["current_action"]["detail"] == "PR #42 attempt 3: 2/5 passed"

    def test_updates_last_updated(self, project_root: Path) -> None:
        state_before = load_json(status_dir(project_root) / "state.json")
        ts_before = state_before.get("last_updated", "")
        waiting_ci(project_root, detail="poll")
        state_after = load_json(status_dir(project_root) / "state.json")
        ts_after = state_after.get("last_updated", "")
        # Timestamp should be refreshed (or at minimum present)
        assert ts_after >= ts_before
        assert len(ts_after) > 0


# ---------------------------------------------------------------------------
# flight [R-11]
# ---------------------------------------------------------------------------

class TestFlight:
    def test_sets_flight_to_running(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        fl = load_json(status_dir(project_root) / "flights.json")
        assert fl["flights"]["wave-1"][0]["status"] == "running"

    def test_sets_action_to_inflight(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        result = flight(1, project_root)
        assert result["current_action"]["action"] == "in-flight"

    def test_flight_2_raises_if_flight_1_not_completed(self, project_root: Path) -> None:
        """[R-11] Strict: flight 2 requires flight 1 completed."""
        store_flight_plan(SAMPLE_FLIGHTS_MULTI, project_root)
        # Start flight 1 but don't complete it.
        flight(1, project_root)
        with pytest.raises(ValueError, match="Error:.*flight 1.*not 'completed'"):
            flight(2, project_root)

    def test_flight_2_succeeds_after_flight_1_completed(self, project_root: Path) -> None:
        """Flight 2 works when flight 1 is completed."""
        store_flight_plan(SAMPLE_FLIGHTS_MULTI, project_root)
        flight(1, project_root)
        flight_done(1, project_root)
        result = flight(2, project_root)
        assert result["current_action"]["action"] == "in-flight"
        fl = load_json(status_dir(project_root) / "flights.json")
        assert fl["flights"]["wave-1"][1]["status"] == "running"

    def test_flight_invalid_number_raises(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        with pytest.raises(ValueError, match="Error:.*flight 99.*does not exist"):
            flight(99, project_root)

    def test_flight_zero_raises(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        with pytest.raises(ValueError, match="Error:.*flight 0.*does not exist"):
            flight(0, project_root)

    def test_flight_no_current_wave_raises(self, tmp_path: Path) -> None:
        d = ensure_status_dir(tmp_path)
        save_json(d / "state.json", {"current_wave": None})
        save_json(d / "flights.json", {"flights": {}})
        with pytest.raises(ValueError, match="Error:.*no current wave"):
            flight(1, tmp_path)


# ---------------------------------------------------------------------------
# flight_done [R-12]
# ---------------------------------------------------------------------------

class TestFlightDone:
    def test_sets_flight_to_completed(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        flight_done(1, project_root)
        fl = load_json(status_dir(project_root) / "flights.json")
        assert fl["flights"]["wave-1"][0]["status"] == "completed"

    def test_sets_action_to_merging(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        result = flight_done(1, project_root)
        assert result["current_action"]["action"] == "merging"

    def test_raises_if_flight_not_running(self, project_root: Path) -> None:
        """[R-12] Strict: flight_done requires the flight to be running."""
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        with pytest.raises(ValueError, match="Error:.*flight 1.*not 'running'"):
            flight_done(1, project_root)

    def test_raises_for_invalid_flight(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        with pytest.raises(ValueError, match="Error:.*flight 99.*does not exist"):
            flight_done(99, project_root)

    def test_raises_for_already_completed_flight(self, project_root: Path) -> None:
        """[R-12] Cannot complete a flight that is already completed."""
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        flight_done(1, project_root)
        with pytest.raises(ValueError, match="Error:.*flight 1.*'completed'.*not 'running'"):
            flight_done(1, project_root)


# ---------------------------------------------------------------------------
# complete [R-13]
# ---------------------------------------------------------------------------

class TestComplete:
    def test_sets_wave_to_completed(self, project_root: Path) -> None:
        planning(project_root)
        result = complete(project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-1"]["status"] == "completed"

    def test_advances_to_next_pending_wave(self, project_root: Path) -> None:
        """[R-13] current_wave advances to the next pending wave."""
        planning(project_root)
        result = complete(project_root)
        assert result["current_wave"] == "wave-2"

    def test_advances_across_phases(self, project_root: Path) -> None:
        """Completing wave-2 advances to wave-3 in the next phase."""
        planning(project_root)
        complete(project_root)
        # Now on wave-2.
        planning(project_root)
        result = complete(project_root)
        assert result["current_wave"] == "wave-3"

    def test_null_when_all_done(self, project_root: Path) -> None:
        """current_wave becomes null when all waves are completed."""
        # Complete all three waves.
        for _ in range(3):
            planning(project_root)
            complete(project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_wave"] is None

    def test_sets_action_to_idle(self, project_root: Path) -> None:
        planning(project_root)
        result = complete(project_root)
        assert result["current_action"]["action"] == "idle"

    def test_raises_when_no_current_wave(self, tmp_path: Path) -> None:
        d = ensure_status_dir(tmp_path)
        save_json(d / "state.json", {"current_wave": None, "waves": {}})
        save_json(d / "phases-waves.json", {"project": "x", "phases": []})
        with pytest.raises(ValueError, match="Error:.*no current wave"):
            complete(tmp_path)


# ---------------------------------------------------------------------------
# close_issue [R-07, R-14]
# ---------------------------------------------------------------------------

class TestCloseIssue:
    def test_sets_issue_to_closed(self, project_root: Path) -> None:
        result = close_issue(13, project_root)
        assert result["issues"]["13"]["status"] == "closed"

    def test_persists_to_disk(self, project_root: Path) -> None:
        close_issue(13, project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["issues"]["13"]["status"] == "closed"

    def test_raises_for_nonexistent_issue(self, project_root: Path) -> None:
        """[R-14] close_issue(999) raises error for nonexistent issue."""
        with pytest.raises(ValueError, match="Error:.*issue #999.*does not exist"):
            close_issue(999, project_root)

    def test_error_message_format(self, project_root: Path) -> None:
        """[R-32] Error messages follow pattern."""
        with pytest.raises(ValueError, match=r"Error:.*\..+\."):
            close_issue(999, project_root)


# ---------------------------------------------------------------------------
# record_mr [R-08]
# ---------------------------------------------------------------------------

class TestRecordMr:
    def test_records_mr_for_issue(self, project_root: Path) -> None:
        result = record_mr(13, "#14", project_root)
        assert result["waves"]["wave-1"]["mr_urls"]["13"] == "#14"

    def test_persists_to_disk(self, project_root: Path) -> None:
        record_mr(13, "#14", project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#14"

    def test_raises_when_no_current_wave(self, tmp_path: Path) -> None:
        d = ensure_status_dir(tmp_path)
        save_json(d / "state.json", {"current_wave": None, "waves": {}})
        with pytest.raises(ValueError, match="Error:.*no current wave"):
            record_mr(1, "#2", tmp_path)


# ---------------------------------------------------------------------------
# show [R-06]
# ---------------------------------------------------------------------------

class TestShow:
    def test_returns_summary_dict(self, project_root: Path) -> None:
        result = show(project_root)
        assert result["project"] == "test-project"
        assert "phase" in result
        assert "wave" in result
        assert "flight" in result
        assert "action" in result
        assert "progress" in result
        assert "deferrals" in result

    def test_does_not_modify_files(self, project_root: Path) -> None:
        """[R-06] show is read-only."""
        d = status_dir(project_root)
        state_before = load_json(d / "state.json")
        flights_before = load_json(d / "flights.json")
        plan_before = load_json(d / "phases-waves.json")

        show(project_root)

        state_after = load_json(d / "state.json")
        flights_after = load_json(d / "flights.json")
        plan_after = load_json(d / "phases-waves.json")

        assert state_before == state_after
        assert flights_before == flights_after
        assert plan_before == plan_after

    def test_initial_state_summary(self, project_root: Path) -> None:
        result = show(project_root)
        assert result["phase"] == "1/2"
        assert result["phase_name"] == "Foundation"
        assert "0/5" in result["progress"]
        assert "0%" in result["progress"]
        assert result["deferrals"] == "0 pending, 0 accepted"

    def test_after_closing_issues(self, project_root: Path) -> None:
        close_issue(13, project_root)
        close_issue(1, project_root)
        result = show(project_root)
        assert "2/5" in result["progress"]

    def test_flight_display_no_flights(self, project_root: Path) -> None:
        """Before flight-plan, flight shows em dash."""
        result = show(project_root)
        assert result["flight"] == "\u2014"  # em dash

    def test_flight_display_with_flights(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS_MULTI, project_root)
        flight(1, project_root)
        result = show(project_root)
        assert result["flight"] == "1/2"


# ---------------------------------------------------------------------------
# Backward compatibility with generate-status-panel [CT-03]
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    """Verify JSON schema is compatible with the existing
    generate-status-panel script."""

    def test_phases_waves_has_project(self, project_root: Path) -> None:
        pw = load_json(status_dir(project_root) / "phases-waves.json")
        assert "project" in pw

    def test_phases_waves_has_phases_with_waves(self, project_root: Path) -> None:
        pw = load_json(status_dir(project_root) / "phases-waves.json")
        assert "phases" in pw
        for phase in pw["phases"]:
            assert "name" in phase
            assert "waves" in phase
            for wave in phase["waves"]:
                assert "id" in wave
                assert "name" in wave
                assert "issues" in wave
                for issue in wave["issues"]:
                    assert "number" in issue
                    assert "title" in issue

    def test_state_json_has_waves_dict(self, project_root: Path) -> None:
        state = load_json(status_dir(project_root) / "state.json")
        assert isinstance(state["waves"], dict)
        for wid, ws in state["waves"].items():
            assert "status" in ws
            assert "mr_urls" in ws

    def test_state_json_has_issues_dict(self, project_root: Path) -> None:
        state = load_json(status_dir(project_root) / "state.json")
        assert isinstance(state["issues"], dict)
        for num, ist in state["issues"].items():
            assert "status" in ist

    def test_state_json_has_current_wave(self, project_root: Path) -> None:
        state = load_json(status_dir(project_root) / "state.json")
        assert "current_wave" in state

    def test_state_json_has_current_action(self, project_root: Path) -> None:
        state = load_json(status_dir(project_root) / "state.json")
        ca = state["current_action"]
        assert "action" in ca
        assert "label" in ca
        assert "detail" in ca

    def test_state_json_has_deferrals(self, project_root: Path) -> None:
        state = load_json(status_dir(project_root) / "state.json")
        assert "deferrals" in state
        assert isinstance(state["deferrals"], list)

    def test_state_json_has_last_updated(self, project_root: Path) -> None:
        state = load_json(status_dir(project_root) / "state.json")
        assert "last_updated" in state

    def test_flights_json_has_flights_dict(self, project_root: Path) -> None:
        fl = load_json(status_dir(project_root) / "flights.json")
        assert "flights" in fl
        assert isinstance(fl["flights"], dict)

    def test_flights_structure_after_store(self, project_root: Path) -> None:
        """Flights stored in the expected format for generate-status-panel."""
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        fl = load_json(status_dir(project_root) / "flights.json")
        wave_flights = fl["flights"]["wave-1"]
        assert isinstance(wave_flights, list)
        for f in wave_flights:
            assert "issues" in f
            assert "status" in f


# ---------------------------------------------------------------------------
# Full lifecycle integration test
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    """End-to-end lifecycle following the example session from PRD Appendix B."""

    def test_full_wave_cycle(self, project_root: Path) -> None:
        """Run through init -> preflight -> planning -> flight-plan ->
        flight 1 -> record-mr -> close-issue -> flight-done 1 ->
        review -> complete -> waiting.
        """
        # Preflight.
        result = preflight(project_root)
        assert result["current_action"]["action"] == "pre-flight"

        # Planning.
        result = planning(project_root)
        assert result["current_action"]["action"] == "planning"
        assert result["waves"]["wave-1"]["status"] == "in_progress"

        # Flight plan.
        store_flight_plan(SAMPLE_FLIGHTS, project_root)

        # Flight 1.
        result = flight(1, project_root)
        assert result["current_action"]["action"] == "in-flight"

        # Record MR and close issues.
        record_mr(13, "#14", project_root)
        close_issue(13, project_root)
        record_mr(1, "#15", project_root)
        close_issue(1, project_root)

        # Flight done.
        result = flight_done(1, project_root)
        assert result["current_action"]["action"] == "merging"

        # Review.
        result = review(project_root)
        assert result["current_action"]["action"] == "post-wave-review"

        # Complete.
        result = complete(project_root)
        assert result["waves"]["wave-1"]["status"] == "completed"
        assert result["current_wave"] == "wave-2"
        assert result["current_action"]["action"] == "idle"

        # Waiting.
        result = waiting(project_root, msg="Wave 1 complete. Ready for /nextwave.")
        assert result["current_action"]["action"] == "waiting-on-meatbag"
        assert result["current_action"]["detail"] == "Wave 1 complete. Ready for /nextwave."

        # Show.
        summary = show(project_root)
        assert summary["project"] == "test-project"
        assert "2/5" in summary["progress"]

    def test_multi_flight_wave(self, project_root: Path) -> None:
        """Wave 2 with two flights demonstrates strict flight ordering."""
        # Complete wave 1 first.
        planning(project_root)
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        flight_done(1, project_root)
        complete(project_root)

        # Now on wave 2.
        planning(project_root)
        store_flight_plan(SAMPLE_FLIGHTS_MULTI, project_root)

        # Flight 1.
        flight(1, project_root)
        record_mr(2, "#16", project_root)
        close_issue(2, project_root)
        flight_done(1, project_root)

        # Flight 2 (allowed because flight 1 is completed).
        flight(2, project_root)
        record_mr(3, "#17", project_root)
        close_issue(3, project_root)
        flight_done(2, project_root)

        complete(project_root)

        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-2"]["status"] == "completed"
        assert state["current_wave"] == "wave-3"


# ---------------------------------------------------------------------------
# Error message format [R-32]
# ---------------------------------------------------------------------------

class TestErrorMessageFormat:
    """All ValueError messages follow 'Error: <what>. <fix>.' [R-32]."""

    def _assert_error_format(self, exc_info: pytest.ExceptionInfo) -> None:
        msg = str(exc_info.value)
        assert msg.startswith("Error: "), f"Does not start with 'Error: ': {msg}"
        # Should contain at least two sentences (two periods).
        periods = msg.count(".")
        assert periods >= 2, f"Expected at least 2 periods in error: {msg}"

    def test_init_missing_project_format(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            init_state({"phases": []}, tmp_path)
        self._assert_error_format(exc_info)

    def test_close_nonexistent_format(self, project_root: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            close_issue(999, project_root)
        self._assert_error_format(exc_info)

    def test_flight_ordering_format(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS_MULTI, project_root)
        flight(1, project_root)
        with pytest.raises(ValueError) as exc_info:
            flight(2, project_root)
        self._assert_error_format(exc_info)

    def test_flight_done_not_running_format(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        with pytest.raises(ValueError) as exc_info:
            flight_done(1, project_root)
        self._assert_error_format(exc_info)


# ---------------------------------------------------------------------------
# Works from any directory [CT-05]
# ---------------------------------------------------------------------------

class TestAnyDirectory:
    """Verify functions work when root is passed explicitly (simulating
    invocation from any directory within a git repo) [CT-05]."""

    def test_operations_with_explicit_root(self, project_root: Path) -> None:
        """All operations receive root as a parameter, so they work
        regardless of the caller's cwd."""
        preflight(project_root)
        planning(project_root)
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        close_issue(13, project_root)
        record_mr(13, "#14", project_root)
        flight_done(1, project_root)
        review(project_root)
        complete(project_root)
        waiting(project_root, msg="Done")
        summary = show(project_root)
        assert summary["project"] == "test-project"
