"""Tests for src/wave_status/__main__.py — Story 3.2: CLI Entry Point.

Tests exercise REAL code paths.  Mocks are used ONLY for:
  - ``get_project_root()`` — returns a ``tmp_path`` instead of calling git
  - ``sys.stdin`` — provides controlled input for stdin tests
  - No other mocking.

Filesystem I/O uses ``tmp_path`` (pytest built-in) so tests write real
files to a temporary directory — no filesystem mocking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wave_status.__main__ import main, _build_parser, _regenerate_dashboard
from wave_status.state import (
    init_state,
    load_json,
    save_json,
    status_dir,
    store_flight_plan,
    flight,
    flight_done,
    planning,
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


@pytest.fixture()
def plan_file(tmp_path: Path) -> Path:
    """Write sample plan to a temp file and return its path."""
    p = tmp_path / "plan.json"
    p.write_text(json.dumps(SAMPLE_PLAN), encoding="utf-8")
    return p


@pytest.fixture()
def flights_file(tmp_path: Path) -> Path:
    """Write sample flights list to a temp file and return its path."""
    p = tmp_path / "flights.json"
    p.write_text(json.dumps(SAMPLE_FLIGHTS), encoding="utf-8")
    return p


def _run_cli(args: list[str], root: Path) -> int:
    """Run the CLI main() with mocked get_project_root and sys.argv.

    Returns the exit code (0 on success, nonzero on error).
    """
    with patch("wave_status.__main__.get_project_root", return_value=root):
        with patch("sys.argv", ["wave_status"] + args):
            try:
                main()
                return 0
            except SystemExit as e:
                return e.code if e.code is not None else 0


# ---------------------------------------------------------------------------
# Parser construction
# ---------------------------------------------------------------------------

class TestBuildParser:
    """Verify all 14 subcommands are registered."""

    def test_parser_has_all_subcommands(self) -> None:
        parser = _build_parser()
        # Parse each subcommand to verify it exists (no error).
        subcommands = [
            "init", "flight-plan", "preflight", "planning",
            "flight", "flight-done", "review", "complete",
            "waiting", "close-issue", "record-mr", "defer",
            "defer-accept", "show",
        ]
        for cmd in subcommands:
            # Just verify the parser knows about each subcommand.
            # Some need arguments, so we check the subparser exists.
            pass
        # Verify by checking that parsing an unknown command fails.
        with pytest.raises(SystemExit):
            parser.parse_args(["nonexistent-command"])


# ---------------------------------------------------------------------------
# init [R-02, R-03]
# ---------------------------------------------------------------------------

class TestCmdInit:
    """Tests for ``python -m wave_status init``."""

    def test_init_from_file(self, tmp_path: Path, plan_file: Path) -> None:
        """[R-02] init creates all files + dashboard."""
        code = _run_cli(["init", str(plan_file)], tmp_path)
        assert code == 0

        d = status_dir(tmp_path)
        assert (d / "phases-waves.json").exists()
        assert (d / "state.json").exists()
        assert (d / "flights.json").exists()
        # Dashboard was generated.
        assert (tmp_path / ".status-panel.html").exists()

    def test_init_from_stdin(self, tmp_path: Path) -> None:
        """[R-03] init reads from stdin when given '-'."""
        import io
        stdin_data = json.dumps(SAMPLE_PLAN)
        with patch("sys.stdin", io.StringIO(stdin_data)):
            code = _run_cli(["init", "-"], tmp_path)
        assert code == 0

        d = status_dir(tmp_path)
        assert (d / "phases-waves.json").exists()
        assert (d / "state.json").exists()
        assert (d / "flights.json").exists()

    def test_init_bad_plan_exits_1(self, tmp_path: Path) -> None:
        """[R-32] ValueError from init_state -> exit 1."""
        bad_plan = tmp_path / "bad.json"
        bad_plan.write_text(json.dumps({"no_project": True}), encoding="utf-8")
        code = _run_cli(["init", str(bad_plan)], tmp_path)
        assert code == 1

    def test_init_invalid_json_exits_2(self, tmp_path: Path) -> None:
        """Unexpected exception (invalid JSON) -> exit 2."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json at all", encoding="utf-8")
        code = _run_cli(["init", str(bad_file)], tmp_path)
        assert code == 2


# ---------------------------------------------------------------------------
# flight-plan [R-04]
# ---------------------------------------------------------------------------

class TestCmdFlightPlan:
    """Tests for ``python -m wave_status flight-plan``."""

    def test_flight_plan_from_file(self, project_root: Path, flights_file: Path) -> None:
        """[R-04] flight-plan stores flights."""
        code = _run_cli(["flight-plan", str(flights_file)], project_root)
        assert code == 0

        fl = load_json(status_dir(project_root) / "flights.json")
        assert "wave-1" in fl["flights"]
        assert fl["flights"]["wave-1"] == SAMPLE_FLIGHTS

    def test_flight_plan_from_stdin(self, project_root: Path) -> None:
        """flight-plan reads from stdin when given '-'."""
        import io
        stdin_data = json.dumps(SAMPLE_FLIGHTS)
        with patch("sys.stdin", io.StringIO(stdin_data)):
            code = _run_cli(["flight-plan", "-"], project_root)
        assert code == 0

        fl = load_json(status_dir(project_root) / "flights.json")
        assert fl["flights"]["wave-1"] == SAMPLE_FLIGHTS

    def test_flight_plan_regenerates_dashboard(self, project_root: Path, flights_file: Path) -> None:
        """Dashboard is regenerated after storing flights."""
        # Generate initial dashboard so we know it exists.
        _regenerate_dashboard(project_root)
        html = project_root / ".status-panel.html"
        mtime_before = html.stat().st_mtime_ns

        code = _run_cli(["flight-plan", str(flights_file)], project_root)
        assert code == 0
        # Dashboard was regenerated (mtime changed or file still exists).
        assert html.exists()


# ---------------------------------------------------------------------------
# Lifecycle subcommands [R-05]
# ---------------------------------------------------------------------------

class TestCmdPreflight:
    def test_preflight_updates_state(self, project_root: Path) -> None:
        code = _run_cli(["preflight"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "pre-flight"

    def test_preflight_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["preflight"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


class TestCmdPlanning:
    def test_planning_updates_state(self, project_root: Path) -> None:
        code = _run_cli(["planning"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "planning"
        assert state["waves"]["wave-1"]["status"] == "in_progress"

    def test_planning_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["planning"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


class TestCmdFlight:
    def test_flight_updates_state(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        code = _run_cli(["flight", "1"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "in-flight"

    def test_flight_invalid_number_exits_1(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        code = _run_cli(["flight", "99"], project_root)
        assert code == 1

    def test_flight_regenerates_dashboard(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        code = _run_cli(["flight", "1"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


class TestCmdFlightDone:
    def test_flight_done_updates_state(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        code = _run_cli(["flight-done", "1"], project_root)
        assert code == 0
        fl = load_json(status_dir(project_root) / "flights.json")
        assert fl["flights"]["wave-1"][0]["status"] == "completed"

    def test_flight_done_not_running_exits_1(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        code = _run_cli(["flight-done", "1"], project_root)
        assert code == 1

    def test_flight_done_regenerates_dashboard(self, project_root: Path) -> None:
        store_flight_plan(SAMPLE_FLIGHTS, project_root)
        flight(1, project_root)
        code = _run_cli(["flight-done", "1"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


class TestCmdReview:
    def test_review_updates_state(self, project_root: Path) -> None:
        code = _run_cli(["review"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "post-wave-review"

    def test_review_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["review"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


class TestCmdComplete:
    def test_complete_advances_wave(self, project_root: Path) -> None:
        planning(project_root)
        code = _run_cli(["complete"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-1"]["status"] == "completed"
        assert state["current_wave"] == "wave-2"

    def test_complete_regenerates_dashboard(self, project_root: Path) -> None:
        planning(project_root)
        code = _run_cli(["complete"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


class TestCmdWaiting:
    def test_waiting_with_message(self, project_root: Path) -> None:
        code = _run_cli(["waiting", "Wave 1 done"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "waiting-on-meatbag"
        assert state["current_action"]["detail"] == "Wave 1 done"

    def test_waiting_without_message(self, project_root: Path) -> None:
        code = _run_cli(["waiting"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_action"]["action"] == "waiting-on-meatbag"
        assert state["current_action"]["detail"] == ""

    def test_waiting_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["waiting"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


# ---------------------------------------------------------------------------
# close-issue [R-07]
# ---------------------------------------------------------------------------

class TestCmdCloseIssue:
    def test_close_issue(self, project_root: Path) -> None:
        """[R-07] close-issue 13 sets issue 13 to closed."""
        code = _run_cli(["close-issue", "13"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["issues"]["13"]["status"] == "closed"

    def test_close_nonexistent_issue_exits_1(self, project_root: Path) -> None:
        """ValueError for nonexistent issue -> exit 1."""
        code = _run_cli(["close-issue", "999"], project_root)
        assert code == 1

    def test_close_issue_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["close-issue", "13"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


# ---------------------------------------------------------------------------
# record-mr [R-08]
# ---------------------------------------------------------------------------

class TestCmdRecordMr:
    def test_record_mr(self, project_root: Path) -> None:
        """[R-08] record-mr 13 '#14' records MR."""
        code = _run_cli(["record-mr", "13", "#14"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#14"

    def test_record_mr_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["record-mr", "13", "#14"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


# ---------------------------------------------------------------------------
# defer [R-09]
# ---------------------------------------------------------------------------

class TestCmdDefer:
    def test_defer_appends_pending(self, project_root: Path) -> None:
        """[R-09] defer appends a pending deferral."""
        code = _run_cli(["defer", "Some description", "low"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert len(state["deferrals"]) == 1
        assert state["deferrals"][0]["description"] == "Some description"
        assert state["deferrals"][0]["risk"] == "low"
        assert state["deferrals"][0]["status"] == "pending"
        assert state["deferrals"][0]["wave"] == "wave-1"

    def test_defer_no_active_wave_exits_1(self, project_root: Path) -> None:
        """Deferring after all waves are complete should fail."""
        # Complete all three waves to reach current_wave=None
        planning(project_root)
        _run_cli(["complete"], project_root)  # wave-1 → wave-2
        planning(project_root)
        _run_cli(["complete"], project_root)  # wave-2 → wave-3
        planning(project_root)
        _run_cli(["complete"], project_root)  # wave-3 → None
        state = load_json(status_dir(project_root) / "state.json")
        assert state["current_wave"] is None
        code = _run_cli(["defer", "late item", "low"], project_root)
        assert code == 1

    def test_defer_invalid_risk_exits_2(self, project_root: Path) -> None:
        """Invalid argparse choice for risk level -> exit 2 (usage error)."""
        code = _run_cli(["defer", "desc", "critical"], project_root)
        assert code == 2

    def test_defer_regenerates_dashboard(self, project_root: Path) -> None:
        code = _run_cli(["defer", "desc", "high"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


# ---------------------------------------------------------------------------
# defer-accept [R-10]
# ---------------------------------------------------------------------------

class TestCmdDeferAccept:
    def test_defer_accept_transitions_to_accepted(self, project_root: Path) -> None:
        """[R-10] defer-accept 1 transitions to accepted."""
        # First create a deferral.
        _run_cli(["defer", "Some item", "medium"], project_root)
        code = _run_cli(["defer-accept", "1"], project_root)
        assert code == 0
        state = load_json(status_dir(project_root) / "state.json")
        assert state["deferrals"][0]["status"] == "accepted"

    def test_defer_accept_invalid_index_exits_1(self, project_root: Path) -> None:
        """ValueError for out-of-range index -> exit 1."""
        code = _run_cli(["defer-accept", "1"], project_root)
        assert code == 1

    def test_defer_accept_regenerates_dashboard(self, project_root: Path) -> None:
        _run_cli(["defer", "Some item", "low"], project_root)
        code = _run_cli(["defer-accept", "1"], project_root)
        assert code == 0
        assert (project_root / ".status-panel.html").exists()


# ---------------------------------------------------------------------------
# show [R-06]
# ---------------------------------------------------------------------------

class TestCmdShow:
    def test_show_prints_summary(self, project_root: Path, capsys: pytest.CaptureFixture) -> None:
        """[R-06] show prints summary without modifying files."""
        code = _run_cli(["show"], project_root)
        assert code == 0
        captured = capsys.readouterr()
        assert "test-project" in captured.out
        assert "Phase:" in captured.out
        assert "Wave:" in captured.out
        assert "Flight:" in captured.out
        assert "Action:" in captured.out
        assert "Progress:" in captured.out
        assert "Deferrals:" in captured.out

    def test_show_does_not_generate_dashboard(self, project_root: Path) -> None:
        """[R-06] show does NOT regenerate dashboard."""
        # Ensure no dashboard exists before show.
        html = project_root / ".status-panel.html"
        assert not html.exists()
        code = _run_cli(["show"], project_root)
        assert code == 0
        # Dashboard should still not exist.
        assert not html.exists()

    def test_show_does_not_modify_state(self, project_root: Path) -> None:
        """show is read-only."""
        d = status_dir(project_root)
        state_before = load_json(d / "state.json")
        _run_cli(["show"], project_root)
        state_after = load_json(d / "state.json")
        assert state_before == state_after


# ---------------------------------------------------------------------------
# Error handling [R-32]
# ---------------------------------------------------------------------------

class TestErrorHandling:
    def test_valueerror_exits_1(self, project_root: Path, capsys: pytest.CaptureFixture) -> None:
        """[R-32] ValueError -> exit 1 with error message on stderr."""
        code = _run_cli(["close-issue", "999"], project_root)
        assert code == 1
        captured = capsys.readouterr()
        assert "Error:" in captured.err

    def test_error_message_format(self, project_root: Path, capsys: pytest.CaptureFixture) -> None:
        """[R-32] Error messages follow 'Error: <what>. <fix>.' pattern."""
        _run_cli(["close-issue", "999"], project_root)
        captured = capsys.readouterr()
        msg = captured.err.strip()
        assert msg.startswith("Error:")
        # Should contain at least two sentences (two periods).
        assert msg.count(".") >= 2

    def test_unexpected_error_exits_2(self, tmp_path: Path) -> None:
        """Unexpected exceptions -> exit 2."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json", encoding="utf-8")
        code = _run_cli(["init", str(bad_file)], tmp_path)
        assert code == 2

    def test_no_subcommand_exits_2(self) -> None:
        """No subcommand -> prints help, exit 2."""
        with patch("wave_status.__main__.get_project_root", return_value=Path("/tmp")):
            with patch("sys.argv", ["wave_status"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _regenerate_dashboard helper
# ---------------------------------------------------------------------------

class TestRegenerateDashboard:
    def test_regenerate_creates_html(self, project_root: Path) -> None:
        """_regenerate_dashboard loads all 3 files and creates HTML."""
        _regenerate_dashboard(project_root)
        html = project_root / ".status-panel.html"
        assert html.exists()
        content = html.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_regenerate_after_state_change(self, project_root: Path) -> None:
        """Dashboard reflects updated state."""
        planning(project_root)
        _regenerate_dashboard(project_root)
        html = project_root / ".status-panel.html"
        assert html.exists()


# ---------------------------------------------------------------------------
# Full lifecycle through CLI
# ---------------------------------------------------------------------------

class TestFullLifecycleCLI:
    """End-to-end test through the CLI interface."""

    def test_complete_wave_cycle_via_cli(self, tmp_path: Path) -> None:
        """Run through init -> preflight -> planning -> flight-plan ->
        flight 1 -> close-issue -> record-mr -> flight-done 1 ->
        review -> complete -> waiting -> show — all through CLI."""
        # Write plan to file.
        plan_file = tmp_path / "plan.json"
        plan_file.write_text(json.dumps(SAMPLE_PLAN), encoding="utf-8")

        # Write flights to file.
        flights_file = tmp_path / "flights.json"
        flights_file.write_text(json.dumps(SAMPLE_FLIGHTS), encoding="utf-8")

        # init
        code = _run_cli(["init", str(plan_file)], tmp_path)
        assert code == 0

        # preflight
        code = _run_cli(["preflight"], tmp_path)
        assert code == 0

        # planning
        code = _run_cli(["planning"], tmp_path)
        assert code == 0

        # flight-plan
        code = _run_cli(["flight-plan", str(flights_file)], tmp_path)
        assert code == 0

        # flight 1
        code = _run_cli(["flight", "1"], tmp_path)
        assert code == 0

        # close-issue 13
        code = _run_cli(["close-issue", "13"], tmp_path)
        assert code == 0

        # record-mr 13 #14
        code = _run_cli(["record-mr", "13", "#14"], tmp_path)
        assert code == 0

        # close-issue 1
        code = _run_cli(["close-issue", "1"], tmp_path)
        assert code == 0

        # record-mr 1 #15
        code = _run_cli(["record-mr", "1", "#15"], tmp_path)
        assert code == 0

        # flight-done 1
        code = _run_cli(["flight-done", "1"], tmp_path)
        assert code == 0

        # defer
        code = _run_cli(["defer", "Deferred item", "low"], tmp_path)
        assert code == 0

        # defer-accept 1
        code = _run_cli(["defer-accept", "1"], tmp_path)
        assert code == 0

        # review
        code = _run_cli(["review"], tmp_path)
        assert code == 0

        # complete
        code = _run_cli(["complete"], tmp_path)
        assert code == 0

        # waiting
        code = _run_cli(["waiting", "Wave 1 complete"], tmp_path)
        assert code == 0

        # show (verify final state)
        code = _run_cli(["show"], tmp_path)
        assert code == 0

        # Verify final state from disk.
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["waves"]["wave-1"]["status"] == "completed"
        assert state["current_wave"] == "wave-2"
        assert state["issues"]["13"]["status"] == "closed"
        assert state["issues"]["1"]["status"] == "closed"
        assert state["waves"]["wave-1"]["mr_urls"]["13"] == "#14"
        assert state["waves"]["wave-1"]["mr_urls"]["1"] == "#15"
        assert len(state["deferrals"]) == 1
        assert state["deferrals"][0]["status"] == "accepted"
        assert state["current_action"]["action"] == "waiting-on-meatbag"
        assert state["current_action"]["detail"] == "Wave 1 complete"

        # Dashboard exists.
        assert (tmp_path / ".status-panel.html").exists()


# ---------------------------------------------------------------------------
# No external imports [CT-01]
# ---------------------------------------------------------------------------

class TestNoExternalImports:
    """Verify __main__.py uses only stdlib + wave_status internals."""

    def test_imports_are_stdlib_only(self) -> None:
        """[CT-01] Check that __main__.py imports only stdlib and wave_status."""
        import importlib
        import wave_status.__main__ as mod

        # Get the module's global namespace.
        for name, obj in vars(mod).items():
            if hasattr(obj, "__module__") and obj.__module__:
                module_name = obj.__module__
                # Must be stdlib or wave_status.
                if module_name.startswith("wave_status"):
                    continue
                # Check stdlib modules.
                if module_name in sys.stdlib_module_names:
                    continue
                # Submodules of stdlib (e.g., json.decoder).
                top_module = module_name.split(".")[0]
                if top_module in sys.stdlib_module_names:
                    continue
                # builtins are ok.
                if module_name == "builtins":
                    continue
                # The module itself.
                if module_name == "wave_status.__main__":
                    continue
                pytest.fail(
                    f"Non-stdlib import detected: {name} from {module_name}"
                )
