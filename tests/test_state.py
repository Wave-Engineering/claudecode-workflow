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
    CURRENT_SCHEMA_VERSION,
    close_issue,
    complete,
    ensure_status_dir,
    extend_state,
    flight,
    flight_done,
    get_project_root,
    hold_wave,
    html_path,
    init_state,
    load_json,
    load_state,
    migrate_state,
    planning,
    preflight,
    record_mr,
    resolve_campaign_head_detail,
    resolve_issue_value,
    review,
    save_json,
    show,
    status_dir,
    store_flight_plan,
    waiting,
    waiting_ci,
    wavemachine_start,
    wavemachine_stop,
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
# migrate_state / load_state — schema versioning (#174)
# ---------------------------------------------------------------------------

class TestMigrateState:
    """Tests for ``migrate_state()`` and ``load_state()`` — schema versioning."""

    def test_v0_to_v2_structural(self) -> None:
        """v0 (Phase 1 list-based) → v2: lists converted to dicts."""
        v0 = {
            "completed_waves": ["w1", "w2"],
            "completed_issues": [1, 2, 3],
            "merge_requests": {
                "1": "https://github.com/org/repo/pull/10",
                "2": "https://github.com/org/repo/pull/11",
            },
            "current_wave": "w3",
            "current_action": {"action": "idle", "label": "idle", "detail": ""},
            "wavemachine_active": True,
        }
        result = migrate_state(v0)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        # Lists converted to dicts.
        assert "completed_waves" not in result
        assert "completed_issues" not in result
        assert "merge_requests" not in result
        assert result["waves"]["w1"]["status"] == "completed"
        assert result["waves"]["w2"]["status"] == "completed"
        # mr_urls attached to last completed wave.
        assert result["waves"]["w2"]["mr_urls"]["1"] == "https://github.com/org/repo/pull/10"
        assert result["issues"]["1"]["status"] == "closed"
        assert result["issues"]["3"]["status"] == "closed"
        # Unknown key preserved.
        assert result["wavemachine_active"] is True

    def test_v1_to_v2_stamp(self) -> None:
        """v1 (has ``waves`` but no schema_version) → v2: stamp only."""
        v1 = {
            "current_wave": "w1",
            "waves": {"w1": {"status": "in_progress", "mr_urls": {}}},
            "issues": {"10": {"status": "open"}},
            "current_action": {"action": "idle", "label": "idle", "detail": ""},
        }
        result = migrate_state(v1)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION
        # Structure unchanged.
        assert result["waves"]["w1"]["status"] == "in_progress"
        assert result["issues"]["10"]["status"] == "open"

    def test_v2_to_v3_stamp_only(self) -> None:
        """v2 → v3: version bumped, structure otherwise unchanged (lazy migration)."""
        v2 = {
            "schema_version": 2,
            "current_wave": "w1",
            "waves": {"w1": {"status": "pending", "mr_urls": {}}},
            "issues": {"13": {"status": "open"}},
            "current_action": {"action": "idle", "label": "idle", "detail": ""},
        }
        result = migrate_state(v2)
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION == 3
        # Structure unchanged — lazy migration on writes only.
        assert result["waves"] == {"w1": {"status": "pending", "mr_urls": {}}}
        assert result["issues"] == {"13": {"status": "open"}}

    def test_v3_to_v3_noop(self) -> None:
        """v3 → v3: no changes."""
        v3 = {
            "schema_version": 3,
            "current_wave": "w1",
            "waves": {"w1": {"status": "pending", "mr_urls": {}}},
            "issues": {},
            "current_action": {"action": "idle", "label": "idle", "detail": ""},
        }
        import copy
        original = copy.deepcopy(v3)
        result = migrate_state(v3)
        assert result == original

    def test_write_back(self, project_root: Path) -> None:
        """load_state with write_back=True persists the migration."""
        d = status_dir(project_root)
        # Manually write a v1 state (no schema_version).
        state_path = d / "state.json"
        v1 = load_json(state_path)
        v1.pop("schema_version", None)
        save_json(state_path, v1)
        # Confirm no schema_version on disk.
        assert "schema_version" not in load_json(state_path)
        # load_state should migrate and write back.
        data = load_state(state_path, write_back=True)
        assert data["schema_version"] == CURRENT_SCHEMA_VERSION
        # Verify it was persisted.
        on_disk = load_json(state_path)
        assert on_disk["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_unknown_keys_preserved(self) -> None:
        """Migration preserves keys it does not recognize."""
        v1 = {
            "current_wave": "w1",
            "waves": {"w1": {"status": "pending", "mr_urls": {}}},
            "issues": {},
            "current_action": {"action": "idle", "label": "idle", "detail": ""},
            "wavemachine_active": True,
            "custom_field": [1, 2, 3],
        }
        result = migrate_state(v1)
        assert result["wavemachine_active"] is True
        assert result["custom_field"] == [1, 2, 3]
        assert result["schema_version"] == CURRENT_SCHEMA_VERSION

    def test_idempotent(self) -> None:
        """Calling migrate_state twice produces the same result."""
        v1 = {
            "current_wave": "w1",
            "waves": {"w1": {"status": "pending", "mr_urls": {}}},
            "issues": {},
            "current_action": {"action": "idle", "label": "idle", "detail": ""},
        }
        first = migrate_state(v1)
        import copy
        second = migrate_state(copy.deepcopy(first))
        assert first == second


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

    # --- Cross-repo qualified-key tests (#198, v3 schema) -----------------

    def test_issues_keyed_with_qualified_ref_when_repo_supplied(
        self, tmp_path: Path
    ) -> None:
        """When plan has ``repo``, state issues are keyed ``{repo}#{N}``."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert "Wave-Engineering/sdlc#13" in state["issues"]
        assert "13" not in state["issues"]
        assert state["issues"]["Wave-Engineering/sdlc#13"]["status"] == "open"

    def test_issues_keyed_bare_when_no_repo(self, tmp_path: Path) -> None:
        """Without ``repo``, state issues keep the bare numeric key (back-compat)."""
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        for num in (13, 1, 2, 3, 5):
            assert str(num) in state["issues"]

    def test_per_issue_repo_overrides_plan_default(self, tmp_path: Path) -> None:
        """Per-issue ``repo`` wins over plan-level ``repo``."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [
                                {"number": 13, "title": "t", "deps": []},
                                {
                                    "number": 14,
                                    "title": "t2",
                                    "deps": [],
                                    "repo": "other-org/other-repo",
                                },
                            ],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert "Wave-Engineering/sdlc#13" in state["issues"]
        assert "other-org/other-repo#14" in state["issues"]

    def test_init_stamps_schema_v3(self, tmp_path: Path) -> None:
        """Fresh init writes ``schema_version: 3`` to state.json."""
        init_state(SAMPLE_PLAN, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["schema_version"] == CURRENT_SCHEMA_VERSION == 3


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


class TestWavemachineStop:
    """``wavemachine_stop()`` is the campaign-exit finally (#636)."""

    def test_clears_wavemachine_ownership(self, project_root: Path) -> None:
        wavemachine_start(project_root, launcher="main")
        result = wavemachine_stop(project_root)
        assert "wavemachine_active" not in result
        assert "wavemachine_started_at" not in result
        assert "wavemachine_launcher" not in result

    def test_resets_stale_waiting_ci_to_idle(self, project_root: Path) -> None:
        """#636: a waiting-ci heartbeat left by post-merge CI polling must NOT
        survive campaign exit and trip the next campaign's pre-flight."""
        wavemachine_start(project_root, launcher="main")
        waiting_ci(project_root, detail="PR #621 attempt 58: 0/0 passed")
        # Sanity: the stale action is present before stop.
        mid = load_json(status_dir(project_root) / "state.json")
        assert mid["current_action"]["action"] == "waiting-ci"
        # Exit resets it.
        result = wavemachine_stop(project_root)
        assert result["current_action"]["action"] == "idle"
        persisted = load_json(status_dir(project_root) / "state.json")
        assert persisted["current_action"]["action"] == "idle"

    def test_idempotent_on_reentry(self, project_root: Path) -> None:
        """Worker abort paths re-enter; idle->idle is a safe no-op."""
        wavemachine_stop(project_root)
        result = wavemachine_stop(project_root)
        assert result["current_action"]["action"] == "idle"
        assert "wavemachine_active" not in result


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

    def test_complete_targets_explicit_wave(self, project_root: Path) -> None:
        """[ENG-1/#846] complete(root, '<id>') marks the explicit wave completed
        (keyed off the run's waveId, not a drifted current_wave) and advances."""
        planning(project_root)
        # Drift current_wave to a DIFFERENT wave than the one the run processed.
        d = status_dir(project_root)
        st = load_json(d / "state.json")
        st["current_wave"] = "wave-2"  # simulate pointer drift
        save_json(d / "state.json", st)
        # The run actually processed wave-1 → complete THAT wave explicitly.
        result = complete(project_root, wave_id="wave-1")
        state = load_json(d / "state.json")
        assert state["waves"]["wave-1"]["status"] == "completed"
        # wave-2 (the drifted pointer) must NOT have been marked completed.
        assert state["waves"]["wave-2"]["status"] != "completed"
        # Advance is anchored on the completed wave → next pending is wave-2.
        assert result["current_wave"] == "wave-2"


class TestResolveIssueValue:
    """ENG-7/#849: resolve bare + v3 qualified issue keys for the dashboard read path."""

    def test_bare_key_exact_match(self) -> None:
        assert resolve_issue_value({"13": {"status": "closed"}}, 13, {}) == {"status": "closed"}

    def test_qualified_key_suffix_match(self) -> None:
        m = {"owner/repo#13": {"status": "closed"}}
        assert resolve_issue_value(m, 13, {}).get("status") == "closed"
        # int or str num both resolve
        assert resolve_issue_value(m, "13", {}).get("status") == "closed"

    def test_suffix_false_match_guard(self) -> None:
        # #119 must NOT satisfy a lookup for #19 (the '#' is anchored).
        m = {"owner/repo#119": {"status": "closed"}}
        assert resolve_issue_value(m, 19, {}) == {}  # #19 absent → default, NOT the #119 entry
        assert resolve_issue_value(m, 119, {}).get("status") == "closed"

    def test_bare_preferred_over_scan(self) -> None:
        m = {"13": {"status": "open"}, "owner/repo#13": {"status": "closed"}}
        assert resolve_issue_value(m, 13, {}).get("status") == "open"  # exact bare wins

    def test_default_returned_when_absent(self) -> None:
        assert resolve_issue_value({}, 7, "") == ""  # mr_urls-style string default
        assert resolve_issue_value({"owner/repo#8": "url"}, 8, "") == "url"  # value type is generic


class TestHoldWave:
    """ENG-1/#846: hold_wave() marks a non-promoted wave 'held' without advancing."""

    def test_hold_wave_no_advance(self, project_root: Path) -> None:
        planning(project_root)
        before = load_json(status_dir(project_root) / "state.json")["current_wave"]
        result = hold_wave("wave-1", project_root, detail="gate HOLD: ci")
        assert result["waves"]["wave-1"]["status"] == "held"
        assert result["waves"]["wave-1"]["hold_detail"] == "gate HOLD: ci"
        # current_wave must be UNCHANGED (a held wave is re-attempted, not advanced past).
        assert result["current_wave"] == before

    def test_skipped_never_completed(self, project_root: Path) -> None:
        """A SKIPPED/held disposition never yields a 'completed' wave status."""
        planning(project_root)
        hold_wave("wave-1", project_root, detail="gate SKIPPED: no changed files")
        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-1"]["status"] == "held"
        assert state["waves"]["wave-1"]["status"] != "completed"

    def test_hold_wave_idempotent(self, project_root: Path) -> None:
        planning(project_root)
        hold_wave("wave-1", project_root, detail="first")
        result = hold_wave("wave-1", project_root, detail="second")
        assert result["waves"]["wave-1"]["status"] == "held"
        assert result["waves"]["wave-1"]["hold_detail"] == "second"

    def test_hold_wave_unknown_raises(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error: wave 'nope' not found"):
            hold_wave("nope", project_root)


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

    # --- FlightDeck wave tag: the issue's OWN wave, not current_wave -----
    # (cc-workflow#1157 code review) -- close_issue's emitted step must be
    # tagged with the CLOSED ISSUE'S wave, not wherever current_wave's
    # pointer happens to sit -- those two legitimately drift (a straggler
    # close after the campaign has advanced, human recovery via
    # set_current_wave, extend_state's auto-advance). A wrong tag here
    # would silently mis-attribute FlightDeck's wave-scope work-item
    # numerator to the wrong wave.

    def test_emitted_wave_tag_is_the_issue_own_wave_not_current_wave(
        self, tmp_path: Path
    ) -> None:
        from wave_status.events.emit import buffer_path

        plan = {
            "project": "wave-tag-test",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {
                    "name": "Only",
                    "waves": [
                        {"id": "wave-1", "name": "Wave 1", "issues": [{"number": 13, "title": "t", "deps": []}]},
                        {"id": "wave-2", "name": "Wave 2", "issues": [{"number": 20, "title": "t", "deps": []}]},
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        # Advance the pointer to wave-2, then close a WAVE-1 issue — the
        # straggler shape: current_wave has already moved on.
        state = load_json(status_dir(tmp_path) / "state.json")
        state["current_wave"] = "wave-2"
        save_json(status_dir(tmp_path) / "state.json", state)

        close_issue(13, tmp_path)

        buf = buffer_path()
        events = [json.loads(line) for line in buf.read_text(encoding="utf-8").splitlines()]
        close_events = [e for e in events if e.get("action") == "close-issue"]
        assert len(close_events) == 1
        # Must be "wave-1" (issue #13's real wave) — NOT "wave-2" (the
        # pointer at close time). This is the exact bug the fix closes.
        assert close_events[0]["wave"] == "wave-1"

    def test_emitted_wave_tag_falls_back_to_current_wave_if_lookup_fails(
        self, project_root: Path
    ) -> None:
        # Defensive fallback only — the issue's existence in the plan is
        # already validated before this point, so _issue_wave_id should
        # always find it in practice. Pins the fallback exists regardless.
        # current_wave is forced to a DIFFERENT wave than issue #13's real
        # one (wave-1, per SAMPLE_PLAN) so the fallback value is
        # distinguishable from what a working lookup would have produced —
        # otherwise this test would pass whether or not the fallback fired.
        from wave_status.events.emit import buffer_path

        state = load_json(status_dir(project_root) / "state.json")
        state["current_wave"] = "wave-2"
        save_json(status_dir(project_root) / "state.json", state)

        with patch("wave_status.state._issue_wave_id", return_value=None):
            close_issue(13, project_root)

        buf = buffer_path()
        events = [json.loads(line) for line in buf.read_text(encoding="utf-8").splitlines()]
        close_events = [e for e in events if e.get("action") == "close-issue"]
        assert close_events[-1]["wave"] == "wave-2"  # the forced fallback value

    def test_emitted_wave_tag_matches_the_actually_resolved_issue_not_the_raw_input(
        self, tmp_path: Path
    ) -> None:
        # #1157 review round 2: a BARE close can dual-read-resolve into a
        # DIFFERENT repo's issue than the raw (ref_num, ref_repo) input
        # names — _resolve_issue_key prefers a qualified hit over a bare
        # one when exactly one of each exists (not ambiguous; that guard
        # only fires on 2+ qualified hits). Both #5 exist here: wave-1's is
        # bare (no repo), wave-2's is qualified (org/b). A bare
        # close_issue(5) resolves to wave-2's "org/b#5" — the wave tag must
        # follow the issue that was ACTUALLY closed, not wave-1 (what a
        # lookup keyed on the raw un-resolved input would have found).
        from wave_status.events.emit import buffer_path

        plan = {
            "project": "dual-read-ambiguity",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {
                    "name": "Only",
                    "waves": [
                        {"id": "wave-1", "name": "Wave 1", "issues": [{"number": 5, "title": "bare", "deps": []}]},
                        {"id": "wave-2", "name": "Wave 2", "issues": [{"number": 5, "title": "qualified", "deps": [], "repo": "org/b"}]},
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        state_before = load_json(status_dir(tmp_path) / "state.json")
        assert "5" in state_before["issues"] and "org/b#5" in state_before["issues"]

        close_issue(5, tmp_path)  # bare — no repo qualifier

        state_after = load_json(status_dir(tmp_path) / "state.json")
        assert state_after["issues"]["org/b#5"]["status"] == "closed"
        assert state_after["issues"]["5"]["status"] != "closed"  # wave-1's #5 untouched

        buf = buffer_path()
        events = [json.loads(line) for line in buf.read_text(encoding="utf-8").splitlines()]
        close_events = [e for e in events if e.get("action") == "close-issue"]
        assert len(close_events) == 1
        assert close_events[0]["label"] == "org/b#5"
        assert close_events[0]["wave"] == "wave-2"  # NOT wave-1

    def test_emitted_wave_tag_survives_an_empty_string_wave_id(self, tmp_path: Path) -> None:
        # #1157 review round 2: `or` would treat a falsy-but-real wave id
        # ("") as a lookup miss and silently fall through to current_wave.
        # Nothing in this module rejects an empty wave id, so this is a
        # legitimate (if odd) plan shape, not a validation gap to close
        # here — the fix is `is None`, not `or`.
        plan = {
            "project": "empty-wave-id",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {"name": "Only", "waves": [{"id": "", "name": "Nameless", "issues": [{"number": 5, "title": "t", "deps": []}]}]}
            ],
        }
        init_state(plan, tmp_path)
        from wave_status.events.emit import buffer_path

        close_issue(5, tmp_path)

        buf = buffer_path()
        events = [json.loads(line) for line in buf.read_text(encoding="utf-8").splitlines()]
        close_events = [e for e in events if e.get("action") == "close-issue"]
        assert close_events[0]["wave"] == ""

    # --- Cross-repo qualified-key tests (#198) ----------------------------

    def test_bare_close_resolves_qualified_key(self, tmp_path: Path) -> None:
        """close_issue(13) finds and closes ``Wave-Engineering/sdlc#13``."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        # State has only the qualified key.
        state_before = load_json(status_dir(tmp_path) / "state.json")
        assert "Wave-Engineering/sdlc#13" in state_before["issues"]
        assert "13" not in state_before["issues"]

        close_issue(13, tmp_path)  # bare integer

        state_after = load_json(status_dir(tmp_path) / "state.json")
        assert state_after["issues"]["Wave-Engineering/sdlc#13"]["status"] == "closed"
        # No stray bare-key entry was created.
        assert "13" not in state_after["issues"]

    def test_qualified_close_ref(self, tmp_path: Path) -> None:
        """close_issue('Wave-Engineering/sdlc#13') direct-key lookup."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        close_issue("Wave-Engineering/sdlc#13", tmp_path)

        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["issues"]["Wave-Engineering/sdlc#13"]["status"] == "closed"

    def test_bare_close_still_works_on_bare_state(self, project_root: Path) -> None:
        """Back-compat: no repo, bare state, bare close arg — still works."""
        close_issue(13, project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["issues"]["13"]["status"] == "closed"

    def test_bare_close_string_digit_works(self, project_root: Path) -> None:
        """close_issue('13') also works — CLI always hands us a string."""
        close_issue("13", project_root)
        state = load_json(status_dir(project_root) / "state.json")
        assert state["issues"]["13"]["status"] == "closed"


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
        # No plan file at all -> plan_data stays None -> #1161's guard uses
        # the "Run 'init'" remedy, the genuinely-correct one for this cause.
        d = ensure_status_dir(tmp_path)
        save_json(d / "state.json", {"current_wave": None, "waves": {}})
        with pytest.raises(ValueError, match=r"Error:.*no current wave.*Run 'init'"):
            record_mr(1, "#2", tmp_path)

    # --- Cross-repo qualified-key tests (#198) ----------------------------

    def test_bare_mr_resolves_qualified_key(self, tmp_path: Path) -> None:
        """record_mr(13, ...) updates ``Wave-Engineering/sdlc#13`` in mr_urls."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        # Seed an existing qualified mr_urls entry to exercise dual-read.
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["waves"]["wave-1"]["mr_urls"]["Wave-Engineering/sdlc#13"] = "#old"
        save_json(d / "state.json", state)

        record_mr(13, "#new", tmp_path)  # bare integer

        state = load_json(d / "state.json")
        assert state["waves"]["wave-1"]["mr_urls"]["Wave-Engineering/sdlc#13"] == "#new"
        # No duplicate bare entry.
        assert "13" not in state["waves"]["wave-1"]["mr_urls"]

    def test_qualified_mr_ref(self, tmp_path: Path) -> None:
        """record_mr accepts qualified ref directly."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        record_mr("Wave-Engineering/sdlc#13", "#14", tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["waves"]["wave-1"]["mr_urls"]["Wave-Engineering/sdlc#13"] == "#14"

    def test_mr_new_key_uses_plan_repo(self, tmp_path: Path) -> None:
        """When mr_urls has no matching entry, new key uses plan's repo."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        record_mr(13, "#14", tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert "Wave-Engineering/sdlc#13" in state["waves"]["wave-1"]["mr_urls"]

    # --- Persisted write targets the issue's OWN wave, not current_wave ---
    # (cc-workflow#1158, the persisted-state sibling of #1157's close_issue
    # fix). Unlike #1157, only the WRITE target moves — the emitted event's
    # `wave` tag deliberately stays `current_wave` (audited: flightdeck's
    # fold.ts treats record-mr's tag as a genuine position update, not an
    # issue-static one, and retagging it would reintroduce #1157's
    # currentWave-snaps-backward bug in a different file).

    def _straggler_plan(self) -> dict:
        return {
            "project": "mr-wave-tag-test",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {
                    "name": "Only",
                    "waves": [
                        {"id": "wave-1", "name": "Wave 1", "issues": [{"number": 13, "title": "t", "deps": []}]},
                        {"id": "wave-2", "name": "Wave 2", "issues": [{"number": 20, "title": "t", "deps": []}]},
                    ],
                }
            ],
        }

    def test_persisted_write_targets_the_issue_own_wave_not_current_wave(
        self, tmp_path: Path
    ) -> None:
        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        # Advance the pointer to wave-2, then record an MR for a WAVE-1
        # issue — the straggler shape: current_wave has already moved on.
        state = load_json(d / "state.json")
        state["current_wave"] = "wave-2"
        save_json(d / "state.json", state)

        record_mr(13, "#99", tmp_path)

        state = load_json(d / "state.json")
        # Must land under wave-1 (issue #13's real wave) — NOT wave-2 (the
        # pointer at record time). This is the exact bug the fix closes.
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#99"
        assert "13" not in state["waves"]["wave-2"].get("mr_urls", {})

    def test_emitted_event_wave_tag_stays_current_wave_on_a_straggler(
        self, tmp_path: Path
    ) -> None:
        """Regression guard for the deliberate non-fix: unlike close_issue,
        record-mr's EMITTED wave tag must keep tracking current_wave even
        when the persisted write targets a different (the issue's real)
        wave — flightdeck's fold.ts relies on this tag as a position
        update. See the audit note on cc-workflow#1158."""
        from wave_status.events.emit import buffer_path

        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["current_wave"] = "wave-2"
        save_json(d / "state.json", state)

        record_mr(13, "#99", tmp_path)

        buf = buffer_path()
        events = [json.loads(line) for line in buf.read_text(encoding="utf-8").splitlines()]
        mr_events = [e for e in events if e.get("action") == "record-mr"]
        assert len(mr_events) == 1
        assert mr_events[0]["wave"] == "wave-2"  # current_wave, NOT wave-1

    def test_write_falls_back_to_current_wave_when_issue_not_in_plan(
        self, tmp_path: Path
    ) -> None:
        """record_mr, unlike close_issue, never required plan membership —
        an issue absent from the plan must still record successfully,
        falling back to current_wave exactly as it did before this fix."""
        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["current_wave"] = "wave-2"
        save_json(d / "state.json", state)

        record_mr(999, "#1", tmp_path)  # #999 is in no wave of this plan

        state = load_json(d / "state.json")
        assert state["waves"]["wave-2"]["mr_urls"]["999"] == "#1"

    def test_write_falls_back_to_current_wave_when_resolved_wave_not_in_state(
        self, tmp_path: Path
    ) -> None:
        """Defensive fallback, mirroring close_issue's analogous test: a
        wave id _issue_wave_id resolves but that ISN'T a real key in
        state["waves"] (unreachable in practice for a plan-valid wave, but
        the guard exists — pin it explicitly rather than leaving it as the
        one untested half of the `is not None and ... in waves` check)."""
        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["current_wave"] = "wave-2"
        save_json(d / "state.json", state)

        with patch("wave_status.state._issue_wave_id", return_value="ghost-wave"):
            record_mr(13, "#99", tmp_path)

        state = load_json(d / "state.json")
        assert state["waves"]["wave-2"]["mr_urls"]["13"] == "#99"  # fell back
        assert "ghost-wave" not in state["waves"]

    # --- cc-workflow#1161: current_wave=None straggler, resolvable via plan --

    def test_terminal_wave_straggler_resolves_via_plan_not_a_hard_fail(
        self, tmp_path: Path
    ) -> None:
        """current_wave went None (terminal wave completed,
        _find_next_pending_wave) — the MOST COMMON straggler shape, not an
        edge case. The issue is still plan-resolvable via _issue_wave_id, so
        this must succeed and land under that wave, not raise."""
        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["current_wave"] = None
        save_json(d / "state.json", state)

        record_mr(13, "#99", tmp_path)  # #13 lives in wave-1 per _straggler_plan

        state = load_json(d / "state.json")
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#99"

    def test_terminal_wave_straggler_emits_no_wave_tag(self, tmp_path: Path) -> None:
        """#1161 AC2: the emitted event's wave tag in this case is a
        DELIBERATE honest absence (wave=None -> emit() drops the key
        entirely), not target_wave — there is no live campaign position to
        tag a finished campaign's straggler MR with. Regression guard
        against silently switching this to target_wave later, which would
        misrepresent a finished campaign as having moved (see #1158's
        audit note for why the emitted tag and the persisted-write target
        are deliberately different fields)."""
        from wave_status.events.emit import buffer_path

        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["current_wave"] = None
        save_json(d / "state.json", state)

        record_mr(13, "#99", tmp_path)

        buf = buffer_path()
        events = [json.loads(line) for line in buf.read_text(encoding="utf-8").splitlines()]
        mr_events = [e for e in events if e.get("action") == "record-mr"]
        assert len(mr_events) == 1
        assert "wave" not in mr_events[0]

    def test_terminal_wave_straggler_still_raises_when_issue_not_in_plan(
        self, tmp_path: Path
    ) -> None:
        """#1161 AC3: current_wave=None AND the issue isn't plan-resolvable
        either — both signals genuinely absent, a clear error must still
        raise (no wave to fall back to). Code review: a plan DOES exist
        here (init_state ran) — the remedy must be "init --extend", NOT the
        generic "Run 'init'" (which plain-refuses on an existing plan and
        would misdirect toward a destructive `init --force`)."""
        init_state(self._straggler_plan(), tmp_path)
        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        state["current_wave"] = None
        save_json(d / "state.json", state)

        with pytest.raises(ValueError, match=r"Error:.*no current wave.*init --extend"):
            record_mr(999, "#1", tmp_path)  # #999 is in no wave of this plan

    def test_records_with_no_plan_file(self, tmp_path: Path) -> None:
        """record_mr never required a plan file to exist (unlike
        close_issue) — the FileNotFoundError branch this fix introduces
        (plan_data loaded once, up front) must preserve that: falls back to
        current_wave for the write target and a bare numeric key, exactly
        as the pre-fix code did when its OWN plan load (previously buried
        inside the key-composition fallback) hit the same error."""
        d = ensure_status_dir(tmp_path)
        save_json(d / "state.json", {"current_wave": "w1", "waves": {"w1": {"mr_urls": {}}}})

        record_mr(7, "#1", tmp_path)

        state = load_json(d / "state.json")
        assert state["waves"]["w1"]["mr_urls"]["7"] == "#1"

    # --- Cross-repo bare-ref consistency (#1158 code review) --------------
    # The wave lookup (_issue_wave_id) and the key-composition fallback used
    # to run as two INDEPENDENT scans over the same bare number, which can
    # name DIFFERENT issues when that number appears in more than one wave
    # under different repos — target_wave picking wave-1 (first match) while
    # the composed key names wave-2's issue would write wave-2's MR under
    # wave-1's mr_urls bag. Same ambiguous-bare-ref plan shape #1157 already
    # uses for close_issue's equivalent test.

    def test_bare_ref_target_wave_and_composed_key_name_the_same_issue(
        self, tmp_path: Path
    ) -> None:
        plan = {
            "project": "mr-cross-repo-ambiguity",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {
                    "name": "Only",
                    "waves": [
                        {"id": "wave-1", "name": "Wave 1", "issues": [{"number": 5, "title": "bare", "deps": []}]},
                        {"id": "wave-2", "name": "Wave 2", "issues": [{"number": 5, "title": "qualified", "deps": [], "repo": "org/b"}]},
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)

        record_mr(5, "#x", tmp_path)  # bare — no repo qualifier

        state = load_json(status_dir(tmp_path) / "state.json")
        # The composed key names wave-2's issue (org/b#5, per the existing
        # last-match-wins repo-inference convention) — the write MUST land
        # under wave-2, the wave that key actually belongs to, not wave-1
        # (what an independent first-match wave lookup would have picked).
        assert state["waves"]["wave-2"]["mr_urls"]["org/b#5"] == "#x"
        assert "org/b#5" not in state["waves"]["wave-1"].get("mr_urls", {})
        assert "5" not in state["waves"]["wave-1"].get("mr_urls", {})


# ---------------------------------------------------------------------------
# extend_state — cross-repo key handling (#198)
# ---------------------------------------------------------------------------


class TestExtendState:
    """Tests for extend_state() cross-repo semantics."""

    def test_collision_check_handles_mixed_key_shapes(self, tmp_path: Path) -> None:
        """Existing state has qualified keys; incoming plan bare — collision detected."""
        # First plan: qualified state (plan has repo).
        plan1 = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan1, tmp_path)
        # Same repo, same issue number in extend → collision.
        plan2 = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P2",
                    "waves": [
                        {
                            "id": "wave-2",
                            "name": "W2",
                            "issues": [{"number": 13, "title": "dup", "deps": []}],
                        }
                    ],
                }
            ],
        }
        with pytest.raises(ValueError, match="Error:.*collision"):
            extend_state(plan2, tmp_path)

    def test_extend_same_number_different_repo_is_ok(self, tmp_path: Path) -> None:
        """Same bare number in different repos is NOT a collision."""
        plan1 = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [{"number": 13, "title": "t", "deps": []}],
                        }
                    ],
                }
            ],
        }
        init_state(plan1, tmp_path)
        plan2 = {
            "repo": "other-org/other-repo",
            "phases": [
                {
                    "name": "P2",
                    "waves": [
                        {
                            "id": "wave-2",
                            "name": "W2",
                            "issues": [{"number": 13, "title": "ok", "deps": []}],
                        }
                    ],
                }
            ],
        }
        extend_state(plan2, tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert "Wave-Engineering/sdlc#13" in state["issues"]
        assert "other-org/other-repo#13" in state["issues"]


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

    # --- Cross-repo qualified-key tests (#198) ----------------------------

    def test_show_counts_issues_with_qualified_keys(self, tmp_path: Path) -> None:
        """show() counts closed/open correctly when keys are qualified."""
        plan = {
            "project": "test",
            "repo": "Wave-Engineering/sdlc",
            "phases": [
                {
                    "name": "P1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "W1",
                            "issues": [
                                {"number": 13, "title": "t1", "deps": []},
                                {"number": 14, "title": "t2", "deps": []},
                            ],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        # Close one issue — via bare arg to exercise dual-read end-to-end.
        close_issue(13, tmp_path)

        result = show(tmp_path)
        assert "1/2" in result["progress"]
        assert "50%" in result["progress"]


class TestResolveCampaignHeadDetail:
    """flightdeck#1145 — planTotal derived from the plan, never hand-typed."""

    def test_plan_total_is_wave_count(self, project_root: Path) -> None:
        # SAMPLE_PLAN carries wave-1/wave-2/wave-3 — 3 waves total, across 2 phases.
        detail = resolve_campaign_head_detail(project_root)
        assert detail["planTotal"] == 3
        assert detail["project"] == "test-project"

    def test_work_items_total_is_issue_count(self, project_root: Path) -> None:
        # SAMPLE_PLAN carries issues 13, 1, 2, 3, 5 — 5 work items total,
        # spread unevenly across the 3 waves (2 + 2 + 1) — a wave-count
        # coincidence must not make this pass by accident.
        detail = resolve_campaign_head_detail(project_root)
        assert detail["workItemsTotal"] == 5

    def test_wave_work_items_maps_each_wave_to_its_issue_count(
        self, project_root: Path
    ) -> None:
        # SAMPLE_PLAN: wave-1 has issues 13/1 (2), wave-2 has 2/3 (2),
        # wave-3 has 5 (1). An even split (5/3) or the campaign total
        # repeated per wave would both look plausible and both be wrong —
        # this fixture's counts are DISTINCT per wave specifically so a
        # wrong-but-plausible fix can't pass by accident.
        detail = resolve_campaign_head_detail(project_root)
        assert detail["waveWorkItems"] == {"wave-1": 2, "wave-2": 2, "wave-3": 1}

    def test_wave_with_zero_issues_is_a_real_zero_not_absent(
        self, tmp_path: Path
    ) -> None:
        # AC: a wave with no issues is a valid map entry (0), not a hole —
        # the plan can legitimately carry an empty wave.
        plan = {
            "project": "empty-wave",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {
                    "name": "Only",
                    "waves": [
                        {"id": "wave-1", "name": "Wave 1", "issues": [{"number": 1, "title": "t", "deps": []}]},
                        {"id": "wave-2", "name": "Wave 2", "issues": []},
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        detail = resolve_campaign_head_detail(tmp_path)
        assert detail["waveWorkItems"] == {"wave-1": 1, "wave-2": 0}
        assert "wave-2" in detail["waveWorkItems"]  # present, not omitted

    def test_work_items_total_counts_refs_not_bare_numbers(self, tmp_path: Path) -> None:
        # Code review finding (#1154): the defining reason for using
        # `_all_issue_refs` over `_all_issue_numbers` — a cross-repo plan can
        # legitimately repeat an issue number across repos — was untested.
        # SAMPLE_PLAN is single-repo with unique numbers, so it can't tell
        # `_all_issue_refs` and `_all_issue_numbers` apart: both would return
        # 5. This plan repeats #5 across two repos; only the ref-counting
        # implementation gets this right (3, not 2).
        plan = {
            "project": "cross-repo",
            "base_branch": "main",
            "master_issue": 1,
            "repo": "org/a",
            "phases": [
                {
                    "name": "Only",
                    "waves": [
                        {
                            "id": "wave-1",
                            "name": "Wave 1",
                            "issues": [
                                {"number": 5, "title": "in org/a", "deps": []},
                                {"number": 7, "title": "also org/a", "deps": []},
                                {"number": 5, "title": "same number, org/b", "deps": [], "repo": "org/b"},
                            ],
                        }
                    ],
                }
            ],
        }
        init_state(plan, tmp_path)
        detail = resolve_campaign_head_detail(tmp_path)
        assert detail["workItemsTotal"] == 3
        # Same cross-repo dedup rationale applies per-wave: this wave has 3
        # distinct issues (5@org/a, 7@org/a, 5@org/b), not 2.
        assert detail["waveWorkItems"] == {"wave-1": 3}

    def test_no_plan_refuses_rather_than_guessing(self, tmp_path: Path) -> None:
        # tmp_path here is a bare project root — init_state was never called.
        with pytest.raises(ValueError, match="no plan found"):
            resolve_campaign_head_detail(tmp_path)

    def test_zero_waves_refuses_rather_than_guessing(self, tmp_path: Path) -> None:
        empty_plan = {"project": "empty", "base_branch": "main", "master_issue": 1, "phases": []}
        init_state(empty_plan, tmp_path)
        with pytest.raises(ValueError, match="zero waves"):
            resolve_campaign_head_detail(tmp_path)

    def test_zero_work_items_refuses_rather_than_guessing(self, tmp_path: Path) -> None:
        # A wave with no issues at all — plan_total is nonzero (1 wave) so
        # this exercises the SECOND refusal, not the first.
        plan = {
            "project": "no-issues",
            "base_branch": "main",
            "master_issue": 1,
            "phases": [
                {"name": "Only", "waves": [{"id": "wave-1", "name": "Wave 1", "issues": []}]}
            ],
        }
        init_state(plan, tmp_path)
        with pytest.raises(ValueError, match="zero work items"):
            resolve_campaign_head_detail(tmp_path)

    def test_malformed_plan_json_refuses_with_a_clear_message(self, tmp_path: Path) -> None:
        d = status_dir(tmp_path)
        d.mkdir(parents=True, exist_ok=True)
        (d / "phases-waves.json").write_text("{ not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not valid JSON"):
            resolve_campaign_head_detail(tmp_path)

    def test_error_message_format(self, tmp_path: Path) -> None:
        """[R-32] Error messages follow 'Error: <what>. <fix>.' like every
        other ValueError site in this module (#1145 code review finding 3 —
        these three were the only ones missing the prefix)."""
        with pytest.raises(ValueError, match=r"Error:.*\..+\."):
            resolve_campaign_head_detail(tmp_path)

    def test_reflects_extend_state_additions(self, tmp_path: Path) -> None:
        # A campaign that grows mid-flight (init --extend) must see the NEW
        # total, not the total at first init — this is the whole point of
        # deriving from the plan rather than a one-time hand-typed literal.
        init_state(SAMPLE_PLAN, tmp_path)
        extra = {
            "project": "test-project",
            "phases": [
                {
                    "name": "Extension",
                    "waves": [
                        {"id": "wave-4", "name": "Wave 4", "issues": [{"number": 20, "title": "t", "deps": []}]},
                    ],
                }
            ],
        }
        extend_state(extra, tmp_path)
        detail = resolve_campaign_head_detail(tmp_path)
        assert detail["planTotal"] == 4
        assert detail["workItemsTotal"] == 6
        assert detail["waveWorkItems"] == {
            "wave-1": 2, "wave-2": 2, "wave-3": 1, "wave-4": 1,
        }


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
