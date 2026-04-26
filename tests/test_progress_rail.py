"""Tests for wave_status.dashboard.progress_rail module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #19 and PRD Section 7, Story 2.1.
"""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.progress_rail import render_progress_rail
from wave_status.dashboard.theme import PHASE_COLORS


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_phases_data(phase_specs: list[list[int]]) -> dict:
    """Build a minimal phases_data dict.

    ``phase_specs`` is a list of lists, each inner list being the issue
    numbers for that phase (all in a single wave for simplicity).
    """
    phases = []
    phase_num = 1
    for issue_numbers in phase_specs:
        phases.append(
            {
                "name": f"Phase {phase_num}",
                "waves": [
                    {
                        "id": f"wave-{phase_num}",
                        "issues": [{"number": n} for n in issue_numbers],
                    }
                ],
            }
        )
        phase_num += 1
    return {"project": "test", "phases": phases}


def _make_state_data(closed_numbers: list[int]) -> dict:
    """Build a minimal state_data dict with the given issues closed."""
    issues = {str(n): {"status": "closed"} for n in closed_numbers}
    return {"issues": issues}


# ---------------------------------------------------------------------------
# Basic return type and structure  [R-19]
# ---------------------------------------------------------------------------


class TestReturnType:
    def test_returns_string(self) -> None:
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert isinstance(result, str)

    def test_nonempty(self) -> None:
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert len(result) > 0

    def test_contains_progress_rail_class(self) -> None:
        """Outer div must use .progress-rail CSS class  [R-19]."""
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert 'class="progress-rail"' in result

    def test_contains_bar_div(self) -> None:
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert 'class="bar"' in result

    def test_contains_segment_divs(self) -> None:
        """Each phase must produce at least one segment div  [R-19]."""
        phases_data = _make_phases_data([[1, 2], [3, 4]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert 'class="segment"' in result


# ---------------------------------------------------------------------------
# Text overlay `w/z issues (p%)`  [R-23]
# ---------------------------------------------------------------------------


class TestTextOverlay:
    def test_text_zero_closed(self) -> None:
        """0/3 issues (0%) when nothing is closed."""
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert "0/3 issues (0%)" in result

    def test_text_all_closed(self) -> None:
        """3/3 issues (100%) when everything is closed."""
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([1, 2, 3])
        result = render_progress_rail(phases_data, state_data)
        assert "3/3 issues (100%)" in result

    def test_text_partial_closed(self) -> None:
        """2/4 issues (50%) when half are closed."""
        phases_data = _make_phases_data([[1, 2, 3, 4]])
        state_data = _make_state_data([1, 2])
        result = render_progress_rail(phases_data, state_data)
        assert "2/4 issues (50%)" in result

    def test_text_rounds_percentage(self) -> None:
        """1/3 = 33% (rounded)."""
        phases_data = _make_phases_data([[1, 2, 3]])
        state_data = _make_state_data([1])
        result = render_progress_rail(phases_data, state_data)
        assert "1/3 issues (33%)" in result

    def test_text_counts_across_phases(self) -> None:
        """Closed count aggregates across multiple phases."""
        phases_data = _make_phases_data([[1, 2], [3, 4]])
        state_data = _make_state_data([1, 3])
        result = render_progress_rail(phases_data, state_data)
        assert "2/4 issues (50%)" in result

    def test_text_element_has_class(self) -> None:
        """Text is wrapped in a .text element."""
        phases_data = _make_phases_data([[1]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert 'class="text"' in result


# ---------------------------------------------------------------------------
# Segment widths proportional to issue count  [R-20]
# ---------------------------------------------------------------------------


class TestSegmentWidths:
    def test_single_phase_full_width(self) -> None:
        """One phase with all issues → width near 100%."""
        phases_data = _make_phases_data([[1, 2, 3, 4]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        # The outer segment wrapper should be close to 100% wide
        assert "100.0000%" in result or "width:100" in result

    def test_two_equal_phases_each_fifty_percent(self) -> None:
        """Two phases with equal issue counts → each ~50%."""
        phases_data = _make_phases_data([[1, 2], [3, 4]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert "50.0000%" in result

    def test_three_phases_proportional_widths(self) -> None:
        """3 phases with 1, 2, 3 issues → 16.67%, 33.33%, 50.0% widths."""
        phases_data = _make_phases_data([[1], [2, 3], [4, 5, 6]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        # Phase 1: 1/6 = 16.6667%
        assert "16.6667%" in result
        # Phase 2: 2/6 = 33.3333%
        assert "33.3333%" in result
        # Phase 3: 3/6 = 50.0000%
        assert "50.0000%" in result

    def test_width_in_segment_style(self) -> None:
        """Width appears in an inline style attribute."""
        phases_data = _make_phases_data([[1, 2]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert "width:" in result


# ---------------------------------------------------------------------------
# Opacity: full (1.0) for completed, 0.2 for remaining  [R-21]
# ---------------------------------------------------------------------------


class TestOpacity:
    def test_completed_color_is_full_opacity(self) -> None:
        """Closed issues get rgba(..., 1.0) color."""
        phases_data = _make_phases_data([[1, 2]])
        state_data = _make_state_data([1])
        result = render_progress_rail(phases_data, state_data)
        assert "rgba(255, 0, 255, 1.0)" in result

    def test_remaining_color_is_faded(self) -> None:
        """Open issues get rgba(..., 0.2) color."""
        phases_data = _make_phases_data([[1, 2]])
        state_data = _make_state_data([1])
        result = render_progress_rail(phases_data, state_data)
        assert "rgba(255, 0, 255, 0.2)" in result

    def test_all_closed_only_full_opacity_fill(self) -> None:
        """When all issues are closed, completed portion is 100% within segment."""
        phases_data = _make_phases_data([[1, 2]])
        state_data = _make_state_data([1, 2])
        result = render_progress_rail(phases_data, state_data)
        # Completed fill div should be 100% wide
        assert "100.0000%" in result
        assert "rgba(255, 0, 255, 1.0)" in result

    def test_all_open_only_faded_fill(self) -> None:
        """When nothing is closed, remaining portion is 100% within segment."""
        phases_data = _make_phases_data([[1, 2]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert "100.0000%" in result
        assert "rgba(255, 0, 255, 0.2)" in result


# ---------------------------------------------------------------------------
# Color cycle fuchsia → cyan → green → yellow mod 4  [R-22]
# ---------------------------------------------------------------------------


class TestColorCycle:
    def test_phase_1_uses_fuchsia(self) -> None:
        """Phase index 0 → fuchsia (PHASE_COLORS[0])."""
        phases_data = _make_phases_data([[1]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        fuchsia_remaining = PHASE_COLORS[0]["remaining"]
        assert fuchsia_remaining in result

    def test_phase_2_uses_cyan(self) -> None:
        """Phase index 1 → cyan (PHASE_COLORS[1])."""
        phases_data = _make_phases_data([[1], [2]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        cyan_remaining = PHASE_COLORS[1]["remaining"]
        assert cyan_remaining in result

    def test_phase_3_uses_green(self) -> None:
        """Phase index 2 → green (PHASE_COLORS[2])."""
        phases_data = _make_phases_data([[1], [2], [3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        green_remaining = PHASE_COLORS[2]["remaining"]
        assert green_remaining in result

    def test_phase_4_uses_yellow(self) -> None:
        """Phase index 3 → yellow (PHASE_COLORS[3])."""
        phases_data = _make_phases_data([[1], [2], [3], [4]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        yellow_remaining = PHASE_COLORS[3]["remaining"]
        assert yellow_remaining in result

    def test_phase_5_cycles_back_to_fuchsia(self) -> None:
        """Phase index 4 → cycles back to fuchsia (4 % 4 = 0)."""
        # 5 phases; phase 5 (index 4) should use fuchsia colors
        phases_data = _make_phases_data([[1], [2], [3], [4], [5]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        # Both phase 1 and phase 5 use fuchsia — fuchsia colors appear at least twice
        fuchsia_remaining = PHASE_COLORS[0]["remaining"]
        assert result.count(fuchsia_remaining) >= 2

    def test_phase_colors_from_theme_constants(self) -> None:
        """Color values match theme.PHASE_COLORS — not hardcoded."""
        phases_data = _make_phases_data([[1], [2], [3], [4]])
        state_data = _make_state_data([1, 2, 3, 4])
        result = render_progress_rail(phases_data, state_data)
        for color in PHASE_COLORS:
            assert color["completed"] in result, (
                f"Expected completed color {color['completed']!r} not found"
            )


# ---------------------------------------------------------------------------
# data-rail-phase attributes  [R-29]
# ---------------------------------------------------------------------------


class TestDataAttributes:
    def test_data_rail_phase_on_segments(self) -> None:
        """Segments have data-rail-phase attribute  [R-29]."""
        phases_data = _make_phases_data([[1, 2], [3, 4]])
        state_data = _make_state_data([1])
        result = render_progress_rail(phases_data, state_data)
        assert 'data-rail-phase="phase-1"' in result
        assert 'data-rail-phase="phase-2"' in result

    def test_data_rail_phase_values_match_phase_number(self) -> None:
        """data-rail-phase values are phase-1, phase-2, etc."""
        phases_data = _make_phases_data([[1], [2], [3]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert 'data-rail-phase="phase-1"' in result
        assert 'data-rail-phase="phase-2"' in result
        assert 'data-rail-phase="phase-3"' in result

    def test_data_bind_width_on_fill_elements(self) -> None:
        """Fill divs carry a dotted-path data-bind-width binding  [R-29].

        Issue #447: the legacy ``data-field="fill"`` attribute was a bare
        path that ``resolve(state, "fill")`` could never find — silent
        no-op in the polling cycle.  The completed/remaining segments now
        bind via ``data-bind-width="rail.<phase_label>.{completed,remaining}_pct"``
        so the polling JS can update ``style.width`` from the live state.
        """
        phases_data = _make_phases_data([[1, 2]])
        state_data = _make_state_data([1])
        result = render_progress_rail(phases_data, state_data)
        assert 'data-bind-width="rail.phase-1.completed_pct"' in result
        assert 'data-bind-width="rail.phase-1.remaining_pct"' in result
        # Legacy bare path must not regress.
        assert 'data-field="fill"' not in result

    def test_data_rail_phase_on_all_phases(self) -> None:
        """Four phases → data-rail-phase attributes for all four."""
        phases_data = _make_phases_data([[1], [2], [3], [4]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        for i in range(1, 5):
            assert f'data-rail-phase="phase-{i}"' in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_phases(self) -> None:
        """No phases → returns HTML string (no crash)."""
        phases_data: dict = {"project": "test", "phases": []}
        state_data: dict = {"issues": {}}
        result = render_progress_rail(phases_data, state_data)
        assert isinstance(result, str)
        assert 'class="progress-rail"' in result

    def test_empty_phases_text_shows_zero(self) -> None:
        """No phases → text shows 0/0 issues (0%)."""
        phases_data: dict = {"project": "test", "phases": []}
        state_data: dict = {"issues": {}}
        result = render_progress_rail(phases_data, state_data)
        assert "0/0 issues (0%)" in result

    def test_phase_with_no_issues_is_skipped(self) -> None:
        """A phase with zero issues produces no segment."""
        phases_data = {
            "project": "test",
            "phases": [
                {"name": "Empty", "waves": [{"id": "w1", "issues": []}]},
                {"name": "Real", "waves": [{"id": "w2", "issues": [{"number": 1}]}]},
            ],
        }
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        # Only the non-empty phase should appear; phase-1 is empty so skipped
        assert 'data-rail-phase="phase-2"' in result
        assert 'data-rail-phase="phase-1"' not in result

    def test_unknown_issue_in_state_treated_as_open(self) -> None:
        """Issues absent from state_data are treated as open (not closed)."""
        phases_data = _make_phases_data([[1, 2, 3]])
        # Only issue 1 is in state_data, issues 2 and 3 are missing entirely
        state_data: dict = {"issues": {"1": {"status": "closed"}}}
        result = render_progress_rail(phases_data, state_data)
        assert "1/3 issues (33%)" in result

    def test_multiple_waves_per_phase(self) -> None:
        """Issues from multiple waves in a phase are all counted."""
        phases_data = {
            "project": "test",
            "phases": [
                {
                    "name": "Phase 1",
                    "waves": [
                        {"id": "w1", "issues": [{"number": 1}, {"number": 2}]},
                        {"id": "w2", "issues": [{"number": 3}, {"number": 4}]},
                    ],
                }
            ],
        }
        state_data = _make_state_data([1, 2])
        result = render_progress_rail(phases_data, state_data)
        # 2 closed out of 4 total
        assert "2/4 issues (50%)" in result


# ---------------------------------------------------------------------------
# No imports outside Python 3.10+ stdlib  [CT-01]
# ---------------------------------------------------------------------------


class TestNoExternalImports:
    def test_module_importable_without_third_party(self) -> None:
        """Module must import successfully with only stdlib available."""
        # The import at the top of this file proves this; but we also verify
        # that calling the function doesn't trigger any lazy imports.
        phases_data = _make_phases_data([[1]])
        state_data = _make_state_data([])
        result = render_progress_rail(phases_data, state_data)
        assert result  # non-empty string confirms successful execution

    def test_function_signature(self) -> None:
        """render_progress_rail accepts two positional dict args."""
        import inspect

        sig = inspect.signature(render_progress_rail)
        params = list(sig.parameters.keys())
        assert params == ["phases_data", "state_data"]
