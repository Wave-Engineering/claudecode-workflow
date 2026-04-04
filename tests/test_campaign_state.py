"""Tests for src/campaign_status/state.py -- Campaign State Machine.

Tests exercise REAL code paths.  Mocks are used ONLY for:
  - ``subprocess.run`` (external git process -- true external boundary)
  - No other mocking.

Filesystem I/O uses ``tmp_path`` (pytest built-in) so tests write real
files to a temporary directory -- no filesystem mocking.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure src/ is importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from campaign_status.state import (
    STAGES,
    STAGES_WITH_REVIEW,
    campaign_dir,
    defer_item,
    ensure_campaign_dir,
    get_project_root,
    init_campaign,
    load_json,
    save_json,
    show_campaign,
    stage_complete,
    stage_review,
    stage_start,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def project_root(tmp_path: Path) -> Path:
    """Set up a fake project root with campaign already initialized."""
    init_campaign("test-project", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

class TestGetProjectRoot:
    """Tests for get_project_root()."""

    def test_returns_path_inside_git_repo(self, tmp_path: Path) -> None:
        fake_root = str(tmp_path / "my-repo")
        with patch("campaign_status.state.subprocess.run") as mock_run:
            mock_run.return_value.stdout = fake_root + "\n"
            mock_run.return_value.returncode = 0
            result = get_project_root()
            assert result == Path(fake_root)
            mock_run.assert_called_once()

    def test_raises_outside_git_repo(self) -> None:
        import subprocess as real_subprocess

        with patch(
            "campaign_status.state.subprocess.run",
            side_effect=real_subprocess.CalledProcessError(128, "git"),
        ):
            with pytest.raises(ValueError, match="Error:.*not inside a git repository"):
                get_project_root()


class TestPathHelpers:
    """Tests for campaign_dir, ensure_campaign_dir."""

    def test_campaign_dir(self, tmp_path: Path) -> None:
        assert campaign_dir(tmp_path) == tmp_path / ".sdlc"

    def test_ensure_campaign_dir_creates_directory(self, tmp_path: Path) -> None:
        d = ensure_campaign_dir(tmp_path)
        assert d.is_dir()
        assert d == tmp_path / ".sdlc"

    def test_ensure_campaign_dir_idempotent(self, tmp_path: Path) -> None:
        ensure_campaign_dir(tmp_path)
        d = ensure_campaign_dir(tmp_path)
        assert d.is_dir()


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------

class TestAtomicJsonIO:
    """Tests for load_json and save_json."""

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
        path = tmp_path / "data.json"
        save_json(path, {"a": 1})
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


# ---------------------------------------------------------------------------
# init_campaign
# ---------------------------------------------------------------------------

class TestInitCampaign:
    """Tests for init_campaign()."""

    def test_creates_all_three_files(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        d = campaign_dir(tmp_path)
        assert (d / "campaign.json").exists()
        assert (d / "campaign-state.json").exists()
        assert (d / "campaign-items.json").exists()

    def test_campaign_json_content(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        data = load_json(campaign_dir(tmp_path) / "campaign.json")
        assert data["project"] == "my-project"
        assert data["stages"] == list(STAGES)
        assert "created" in data

    def test_state_all_stages_not_started(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        state = load_json(campaign_dir(tmp_path) / "campaign-state.json")
        for stage in STAGES:
            assert state["stages"][stage] == "not_started"

    def test_state_active_stage_is_none(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        state = load_json(campaign_dir(tmp_path) / "campaign-state.json")
        assert state["active_stage"] is None

    def test_state_has_last_updated(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        state = load_json(campaign_dir(tmp_path) / "campaign-state.json")
        assert "last_updated" in state
        assert state["last_updated"].endswith("Z")

    def test_items_empty_deferrals(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        items = load_json(campaign_dir(tmp_path) / "campaign-items.json")
        assert items["deferrals"] == []

    def test_rejects_empty_project_name(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*project name.*empty"):
            init_campaign("", tmp_path)

    def test_rejects_whitespace_project_name(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*project name.*empty"):
            init_campaign("   ", tmp_path)

    def test_rejects_reinit(self, tmp_path: Path) -> None:
        init_campaign("my-project", tmp_path)
        with pytest.raises(ValueError, match="Error:.*already initialized"):
            init_campaign("another-project", tmp_path)

    def test_returns_state_dict(self, tmp_path: Path) -> None:
        result = init_campaign("my-project", tmp_path)
        assert "stages" in result
        assert "active_stage" in result
        assert "last_updated" in result


# ---------------------------------------------------------------------------
# stage_start
# ---------------------------------------------------------------------------

class TestStageStart:
    """Tests for stage_start()."""

    def test_starts_concept(self, project_root: Path) -> None:
        result = stage_start("concept", project_root)
        assert result["stages"]["concept"] == "active"
        assert result["active_stage"] == "concept"

    def test_persists_to_disk(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        state = load_json(campaign_dir(project_root) / "campaign-state.json")
        assert state["stages"]["concept"] == "active"

    def test_rejects_invalid_stage(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*'invalid'.*not a valid stage"):
            stage_start("invalid", project_root)

    def test_rejects_starting_already_active(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        with pytest.raises(ValueError, match="Error:.*'concept'.*'active'.*expected 'not_started'"):
            stage_start("concept", project_root)

    def test_rejects_prd_before_concept_complete(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*'concept'.*not 'complete'"):
            stage_start("prd", project_root)

    def test_prd_after_concept_complete(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        stage_complete("concept", project_root)
        result = stage_start("prd", project_root)
        assert result["stages"]["prd"] == "active"

    def test_sequential_order_enforced(self, project_root: Path) -> None:
        """Cannot start stage N+1 until stage N is complete."""
        with pytest.raises(ValueError, match="Error:.*previous stage"):
            stage_start("backlog", project_root)

    def test_updates_last_updated(self, project_root: Path) -> None:
        state_before = load_json(campaign_dir(project_root) / "campaign-state.json")
        stage_start("concept", project_root)
        state_after = load_json(campaign_dir(project_root) / "campaign-state.json")
        assert state_after["last_updated"] >= state_before["last_updated"]


# ---------------------------------------------------------------------------
# stage_review
# ---------------------------------------------------------------------------

class TestStageReview:
    """Tests for stage_review()."""

    def test_moves_concept_to_review(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        result = stage_review("concept", project_root)
        assert result["stages"]["concept"] == "review"

    def test_persists_to_disk(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        state = load_json(campaign_dir(project_root) / "campaign-state.json")
        assert state["stages"]["concept"] == "review"

    def test_rejects_backlog_review(self, project_root: Path) -> None:
        """backlog does not have a review gate."""
        with pytest.raises(ValueError, match="Error:.*'backlog'.*does not have a review gate"):
            stage_review("backlog", project_root)

    def test_rejects_implementation_review(self, project_root: Path) -> None:
        """implementation does not have a review gate."""
        with pytest.raises(ValueError, match="Error:.*'implementation'.*does not have a review gate"):
            stage_review("implementation", project_root)

    def test_rejects_not_active(self, project_root: Path) -> None:
        """Cannot review a stage that is not active."""
        with pytest.raises(ValueError, match="Error:.*'concept'.*'not_started'.*expected 'active'"):
            stage_review("concept", project_root)

    def test_all_reviewable_stages(self, project_root: Path) -> None:
        """concept, prd, dod all support review."""
        assert set(STAGES_WITH_REVIEW) == {"concept", "prd", "dod"}

    def test_clears_active_stage(self, project_root: Path) -> None:
        """active_stage must be cleared when a stage enters review."""
        stage_start("concept", project_root)
        result = stage_review("concept", project_root)
        assert result["active_stage"] is None

    def test_rejects_invalid_stage(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*'bogus'.*not a valid stage"):
            stage_review("bogus", project_root)


# ---------------------------------------------------------------------------
# stage_complete
# ---------------------------------------------------------------------------

class TestStageComplete:
    """Tests for stage_complete()."""

    def test_completes_concept_from_review(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        result = stage_complete("concept", project_root)
        assert result["stages"]["concept"] == "complete"

    def test_completes_backlog_from_active(self, project_root: Path) -> None:
        """backlog completes directly from active (no review gate)."""
        # Set up: concept -> prd -> backlog
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        stage_complete("concept", project_root)
        stage_start("prd", project_root)
        stage_review("prd", project_root)
        stage_complete("prd", project_root)
        stage_start("backlog", project_root)
        result = stage_complete("backlog", project_root)
        assert result["stages"]["backlog"] == "complete"

    def test_completes_implementation_from_active(self, project_root: Path) -> None:
        """implementation completes directly from active (no review gate)."""
        # Set up: concept -> prd -> backlog -> implementation
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        stage_complete("concept", project_root)
        stage_start("prd", project_root)
        stage_review("prd", project_root)
        stage_complete("prd", project_root)
        stage_start("backlog", project_root)
        stage_complete("backlog", project_root)
        stage_start("implementation", project_root)
        result = stage_complete("implementation", project_root)
        assert result["stages"]["implementation"] == "complete"

    def test_rejects_concept_complete_from_active(self, project_root: Path) -> None:
        """concept requires review before complete."""
        stage_start("concept", project_root)
        with pytest.raises(ValueError, match="Error:.*'concept'.*'active'.*expected 'review'"):
            stage_complete("concept", project_root)

    def test_rejects_backlog_complete_when_not_active(self, project_root: Path) -> None:
        """backlog must be active to complete (no review needed)."""
        with pytest.raises(ValueError, match="Error:.*'backlog'.*expected 'active'"):
            stage_complete("backlog", project_root)

    def test_clears_active_stage(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        result = stage_complete("concept", project_root)
        assert result["active_stage"] is None

    def test_persists_to_disk(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        stage_complete("concept", project_root)
        state = load_json(campaign_dir(project_root) / "campaign-state.json")
        assert state["stages"]["concept"] == "complete"

    def test_rejects_invalid_stage(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*'nope'.*not a valid stage"):
            stage_complete("nope", project_root)


# ---------------------------------------------------------------------------
# defer_item
# ---------------------------------------------------------------------------

class TestDeferItem:
    """Tests for defer_item()."""

    def test_appends_deferral(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        result = defer_item("User auth", "Not needed for MVP", project_root)
        assert len(result["deferrals"]) == 1
        assert result["deferrals"][0]["item"] == "User auth"
        assert result["deferrals"][0]["reason"] == "Not needed for MVP"

    def test_records_stage_and_timestamp(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        result = defer_item("Feature X", "Deprioritized", project_root)
        assert result["deferrals"][0]["stage"] == "concept"
        assert result["deferrals"][0]["timestamp"].endswith("Z")

    def test_multiple_deferrals(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        defer_item("Item 1", "Reason 1", project_root)
        result = defer_item("Item 2", "Reason 2", project_root)
        assert len(result["deferrals"]) == 2

    def test_persists_to_disk(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        defer_item("Feature X", "Later", project_root)
        items = load_json(campaign_dir(project_root) / "campaign-items.json")
        assert len(items["deferrals"]) == 1
        assert items["deferrals"][0]["item"] == "Feature X"

    def test_rejects_empty_item(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*item description.*empty"):
            defer_item("", "reason", project_root)

    def test_rejects_empty_reason(self, project_root: Path) -> None:
        with pytest.raises(ValueError, match="Error:.*reason.*empty"):
            defer_item("item", "", project_root)

    def test_defer_without_active_stage(self, project_root: Path) -> None:
        """Deferral works even with no active stage (stage is None)."""
        result = defer_item("Something", "Pre-concept thought", project_root)
        assert result["deferrals"][0]["stage"] is None


# ---------------------------------------------------------------------------
# show_campaign
# ---------------------------------------------------------------------------

class TestShowCampaign:
    """Tests for show_campaign()."""

    def test_returns_summary_dict(self, project_root: Path) -> None:
        result = show_campaign(project_root)
        assert result["project"] == "test-project"
        assert "active_stage" in result
        assert "stages" in result
        assert "stage_lines" in result
        assert "deferrals_count" in result
        assert "deferrals" in result

    def test_initial_state(self, project_root: Path) -> None:
        result = show_campaign(project_root)
        assert result["active_stage"] == "none"
        assert result["deferrals_count"] == 0
        for stage in STAGES:
            assert result["stages"][stage] == "not_started"

    def test_does_not_modify_files(self, project_root: Path) -> None:
        d = campaign_dir(project_root)
        state_before = load_json(d / "campaign-state.json")
        items_before = load_json(d / "campaign-items.json")
        campaign_before = load_json(d / "campaign.json")

        show_campaign(project_root)

        state_after = load_json(d / "campaign-state.json")
        items_after = load_json(d / "campaign-items.json")
        campaign_after = load_json(d / "campaign.json")

        assert state_before == state_after
        assert items_before == items_after
        assert campaign_before == campaign_after

    def test_after_stage_start(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        result = show_campaign(project_root)
        assert result["active_stage"] == "concept"
        assert result["stages"]["concept"] == "active"

    def test_with_deferrals(self, project_root: Path) -> None:
        stage_start("concept", project_root)
        defer_item("Item 1", "Reason 1", project_root)
        result = show_campaign(project_root)
        assert result["deferrals_count"] == 1

    def test_stage_lines_format(self, project_root: Path) -> None:
        result = show_campaign(project_root)
        assert len(result["stage_lines"]) == 5
        for line in result["stage_lines"]:
            assert line.startswith("  ")


# ---------------------------------------------------------------------------
# Full lifecycle integration
# ---------------------------------------------------------------------------

class TestFullLifecycle:
    """End-to-end lifecycle through all 5 stages."""

    def test_full_campaign_cycle(self, project_root: Path) -> None:
        """Walk through concept -> prd -> backlog -> implementation -> dod."""
        # Concept
        stage_start("concept", project_root)
        stage_review("concept", project_root)
        stage_complete("concept", project_root)

        # PRD
        stage_start("prd", project_root)
        defer_item("Advanced analytics", "Phase 2", project_root)
        stage_review("prd", project_root)
        stage_complete("prd", project_root)

        # Backlog (no review gate)
        stage_start("backlog", project_root)
        stage_complete("backlog", project_root)

        # Implementation (no review gate)
        stage_start("implementation", project_root)
        stage_complete("implementation", project_root)

        # DoD
        stage_start("dod", project_root)
        stage_review("dod", project_root)
        stage_complete("dod", project_root)

        # Verify final state
        state = load_json(campaign_dir(project_root) / "campaign-state.json")
        for stage in STAGES:
            assert state["stages"][stage] == "complete"

        items = load_json(campaign_dir(project_root) / "campaign-items.json")
        assert len(items["deferrals"]) == 1
        assert items["deferrals"][0]["item"] == "Advanced analytics"

    def test_cannot_skip_stages(self, project_root: Path) -> None:
        """Cannot start backlog without completing concept and prd first."""
        with pytest.raises(ValueError):
            stage_start("backlog", project_root)


# ---------------------------------------------------------------------------
# Error message format
# ---------------------------------------------------------------------------

class TestErrorMessageFormat:
    """All ValueError messages follow 'Error: <what>. <fix>.' pattern."""

    def _assert_error_format(self, exc_info: pytest.ExceptionInfo) -> None:
        msg = str(exc_info.value)
        assert msg.startswith("Error: "), f"Does not start with 'Error: ': {msg}"
        periods = msg.count(".")
        assert periods >= 2, f"Expected at least 2 periods in error: {msg}"

    def test_empty_project_name_format(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            init_campaign("", tmp_path)
        self._assert_error_format(exc_info)

    def test_invalid_stage_format(self, project_root: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            stage_start("invalid", project_root)
        self._assert_error_format(exc_info)

    def test_wrong_state_format(self, project_root: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            stage_start("prd", project_root)
        self._assert_error_format(exc_info)

    def test_no_review_gate_format(self, project_root: Path) -> None:
        with pytest.raises(ValueError) as exc_info:
            stage_review("backlog", project_root)
        self._assert_error_format(exc_info)
