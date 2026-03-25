"""Tests for wave_status.dashboard.execution_grid module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #21 (Story 2.3).
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.execution_grid import (
    _render_flight_badges,
    _render_issue_row,
    _render_phase_section,
    _render_wave_card,
    _status_badge,
    render_execution_grid,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PHASES_DATA = {
    "project": "test-proj",
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {
                    "id": "wave-1",
                    "issues": [
                        {"number": 1, "title": "Bootstrap repo"},
                        {"number": 2, "title": "Add CI"},
                    ],
                },
                {
                    "id": "wave-2",
                    "issues": [
                        {"number": 3, "title": "Auth module"},
                    ],
                },
            ],
        },
        {
            "name": "Core",
            "waves": [
                {
                    "id": "wave-3",
                    "issues": [
                        {"number": 4, "title": "Dashboard"},
                    ],
                },
            ],
        },
    ],
}

STATE_DATA_BASE = {
    "current_wave": "wave-1",
    "waves": {
        "wave-1": {"status": "in_progress", "mr_urls": {}},
        "wave-2": {"status": "pending", "mr_urls": {}},
        "wave-3": {"status": "pending", "mr_urls": {}},
    },
    "issues": {
        "1": {"status": "open"},
        "2": {"status": "open"},
        "3": {"status": "open"},
        "4": {"status": "open"},
    },
    "deferrals": [],
}

FLIGHTS_DATA_EMPTY = {"flights": {}}

FLIGHTS_DATA_WAVE1 = {
    "flights": {
        "wave-1": [
            {"issues": [1, 2], "status": "running"},
            {"issues": [3], "status": "pending"},
        ]
    }
}


# ---------------------------------------------------------------------------
# _status_badge() tests
# ---------------------------------------------------------------------------


class TestStatusBadge:
    """Badge HTML generation."""

    def test_returns_string(self) -> None:
        html = _status_badge("pending")
        assert isinstance(html, str)

    def test_badge_class_present(self) -> None:
        html = _status_badge("pending")
        assert 'class="badge badge-pending"' in html

    def test_in_progress_maps_to_hyphenated_class(self) -> None:
        html = _status_badge("in_progress")
        assert "badge-in-progress" in html

    def test_label_uses_spaces(self) -> None:
        html = _status_badge("in_progress")
        assert "in progress" in html

    def test_data_wave_attribute_when_provided(self) -> None:
        html = _status_badge("completed", data_wave="wave-1")
        assert 'data-wave="wave-1"' in html

    def test_data_issue_attribute_when_provided(self) -> None:
        html = _status_badge("open", data_issue="7")
        assert 'data-issue="7"' in html

    def test_no_data_attrs_when_not_provided(self) -> None:
        html = _status_badge("pending")
        assert "data-wave" not in html
        assert "data-issue" not in html


# ---------------------------------------------------------------------------
# _render_flight_badges() tests
# ---------------------------------------------------------------------------


class TestRenderFlightBadges:
    """Flight badge HTML for a wave."""

    def test_empty_when_no_flight_plan(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_EMPTY)
        assert result == ""

    def test_empty_when_wave_not_in_flights(self) -> None:
        result = _render_flight_badges("wave-99", FLIGHTS_DATA_WAVE1)
        assert result == ""

    def test_returns_badge_per_flight(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_WAVE1)
        assert result.count("flight 1") == 1
        assert result.count("flight 2") == 1

    def test_running_flight_gets_running_class(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_WAVE1)
        assert "badge-running" in result

    def test_pending_flight_gets_pending_class(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_WAVE1)
        assert "badge-pending" in result

    def test_data_wave_attribute_present(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_WAVE1)
        assert 'data-wave="wave-1"' in result

    def test_data_field_attribute_present(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_WAVE1)
        assert "data-field=" in result

    def test_data_field_references_flights_path(self) -> None:
        result = _render_flight_badges("wave-1", FLIGHTS_DATA_WAVE1)
        assert "flights.wave-1." in result

    def test_completed_flight_badge(self) -> None:
        flights = {
            "flights": {
                "wave-1": [
                    {"issues": [1], "status": "completed"},
                ]
            }
        }
        result = _render_flight_badges("wave-1", flights)
        assert "badge-completed" in result
        assert "completed" in result


# ---------------------------------------------------------------------------
# _render_issue_row() tests
# ---------------------------------------------------------------------------


class TestRenderIssueRow:
    """Issue table row HTML."""

    def setup_method(self) -> None:
        self.html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, STATE_DATA_BASE, "wave-1")

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_is_tr_element(self) -> None:
        assert self.html.startswith("<tr>")
        assert "</tr>" in self.html

    def test_contains_issue_number(self) -> None:
        assert "#1" in self.html

    def test_contains_title(self) -> None:
        assert "Bootstrap repo" in self.html

    def test_status_badge_present(self) -> None:
        assert 'class="badge' in self.html

    def test_open_status_renders_as_open(self) -> None:
        assert "open" in self.html

    def test_data_wave_on_status_badge(self) -> None:
        assert 'data-wave="wave-1"' in self.html

    def test_data_issue_on_status_badge(self) -> None:
        assert 'data-issue="1"' in self.html

    def test_data_field_on_status_badge(self) -> None:
        assert 'data-field="issues.1.status"' in self.html

    def test_mr_cell_empty_when_no_mr(self) -> None:
        # No MR URL -> empty span with data attributes
        assert 'data-field="waves.wave-1.mr_urls.1"' in self.html
        assert "<a href=" not in self.html

    def test_closed_issue_shows_closed_badge(self) -> None:
        state = {
            **STATE_DATA_BASE,
            "issues": {"1": {"status": "closed"}},
        }
        html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1")
        assert "badge-closed" in html
        assert "closed" in html

    def test_mr_link_renders_when_recorded(self) -> None:
        state = {
            **STATE_DATA_BASE,
            "waves": {
                "wave-1": {"status": "in_progress", "mr_urls": {"1": "https://github.com/org/repo/pull/42"}},
                "wave-2": {"status": "pending", "mr_urls": {}},
                "wave-3": {"status": "pending", "mr_urls": {}},
            },
        }
        html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1")
        assert '<a href="https://github.com/org/repo/pull/42"' in html
        assert 'data-field="waves.wave-1.mr_urls.1"' in html

    def test_issue_without_title_uses_fallback(self) -> None:
        html = _render_issue_row(99, {"number": 99}, STATE_DATA_BASE, "wave-1")
        assert "Issue #99" in html

    def test_unknown_issue_in_state_defaults_to_open(self) -> None:
        # Issue 999 not in state dict -> defaults to "open"
        html = _render_issue_row(999, {"number": 999, "title": "Mystery"}, STATE_DATA_BASE, "wave-1")
        assert "open" in html


# ---------------------------------------------------------------------------
# _render_wave_card() tests
# ---------------------------------------------------------------------------


class TestRenderWaveCard:
    """Wave card HTML structure."""

    def setup_method(self) -> None:
        wave_plan = PHASES_DATA["phases"][0]["waves"][0]
        self.html = _render_wave_card(wave_plan, STATE_DATA_BASE, FLIGHTS_DATA_EMPTY)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_wave_card_class(self) -> None:
        assert 'class="wave-card"' in self.html

    def test_data_wave_attribute(self) -> None:
        assert 'data-wave="wave-1"' in self.html

    def test_has_wave_header(self) -> None:
        assert 'class="wave-header"' in self.html

    def test_wave_id_in_header(self) -> None:
        assert "wave-1" in self.html

    def test_status_badge_in_header(self) -> None:
        assert 'class="badge' in self.html

    def test_wave_status_badge_has_data_field(self) -> None:
        assert 'data-field="waves.wave-1.status"' in self.html

    def test_has_issue_table(self) -> None:
        assert 'class="issue-table"' in self.html

    def test_all_issues_rendered(self) -> None:
        assert "#1" in self.html
        assert "#2" in self.html
        assert "Bootstrap repo" in self.html
        assert "Add CI" in self.html

    def test_no_flight_badges_when_no_flights(self) -> None:
        assert "flight-badges" not in self.html

    def test_flight_badges_when_flights_exist(self) -> None:
        wave_plan = PHASES_DATA["phases"][0]["waves"][0]
        html = _render_wave_card(wave_plan, STATE_DATA_BASE, FLIGHTS_DATA_WAVE1)
        assert "flight-badges" in html
        assert "flight 1" in html
        assert "flight 2" in html

    def test_completed_wave_status_badge(self) -> None:
        state = {
            **STATE_DATA_BASE,
            "waves": {
                "wave-1": {"status": "completed", "mr_urls": {}},
                "wave-2": {"status": "pending", "mr_urls": {}},
                "wave-3": {"status": "pending", "mr_urls": {}},
            },
        }
        wave_plan = PHASES_DATA["phases"][0]["waves"][0]
        html = _render_wave_card(wave_plan, state, FLIGHTS_DATA_EMPTY)
        assert "badge-completed" in html


# ---------------------------------------------------------------------------
# _render_phase_section() tests
# ---------------------------------------------------------------------------


class TestRenderPhaseSection:
    """Phase section HTML structure."""

    def setup_method(self) -> None:
        phase = PHASES_DATA["phases"][0]
        self.html = _render_phase_section(phase, 0, STATE_DATA_BASE, FLIGHTS_DATA_EMPTY)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_phase_section_class(self) -> None:
        assert 'class="phase-section"' in self.html

    def test_data_phase_attribute(self) -> None:
        assert 'data-phase="1"' in self.html

    def test_phase_name_in_header(self) -> None:
        assert "Foundation" in self.html

    def test_phase_color_applied_as_border(self) -> None:
        # Phase 0 -> fuchsia, var(--fuchsia)
        assert "var(--fuchsia)" in self.html

    def test_second_phase_uses_cyan(self) -> None:
        phase = PHASES_DATA["phases"][1]
        html = _render_phase_section(phase, 1, STATE_DATA_BASE, FLIGHTS_DATA_EMPTY)
        assert "var(--cyan)" in html

    def test_phase_index_wraps_mod_4(self) -> None:
        # Phase index 4 wraps to fuchsia again
        phase = PHASES_DATA["phases"][0]
        html = _render_phase_section(phase, 4, STATE_DATA_BASE, FLIGHTS_DATA_EMPTY)
        assert "var(--fuchsia)" in html

    def test_contains_wave_cards_for_all_waves_in_phase(self) -> None:
        assert 'data-wave="wave-1"' in self.html
        assert 'data-wave="wave-2"' in self.html

    def test_does_not_contain_wave_from_other_phase(self) -> None:
        assert 'data-wave="wave-3"' not in self.html

    def test_has_phase_body(self) -> None:
        assert 'class="phase-body"' in self.html


# ---------------------------------------------------------------------------
# render_execution_grid() tests  [R-29, R-04, R-07, R-08]
# ---------------------------------------------------------------------------


class TestRenderExecutionGrid:
    """Full integration tests for render_execution_grid()."""

    def setup_method(self) -> None:
        self.html = render_execution_grid(
            PHASES_DATA, STATE_DATA_BASE, FLIGHTS_DATA_EMPTY
        )

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_nonempty(self) -> None:
        assert len(self.html) > 0

    def test_has_execution_grid_wrapper(self) -> None:
        assert 'class="execution-grid"' in self.html

    # --- All phases rendered ---

    def test_renders_all_phases(self) -> None:
        assert "Foundation" in self.html
        assert "Core" in self.html

    def test_renders_both_phase_sections(self) -> None:
        assert self.html.count('class="phase-section"') == 2

    # --- All waves rendered [AC: Execution grid renders all phases, waves, issues, flights] ---

    def test_renders_all_waves(self) -> None:
        assert 'data-wave="wave-1"' in self.html
        assert 'data-wave="wave-2"' in self.html
        assert 'data-wave="wave-3"' in self.html

    # --- All issues rendered ---

    def test_renders_all_issues(self) -> None:
        assert "#1" in self.html
        assert "#2" in self.html
        assert "#3" in self.html
        assert "#4" in self.html
        assert "Bootstrap repo" in self.html
        assert "Add CI" in self.html
        assert "Auth module" in self.html
        assert "Dashboard" in self.html

    # --- Issue row: number, title, status badge, MR link [R-07, R-08] ---

    def test_issue_rows_have_status_badges(self) -> None:
        assert 'class="badge' in self.html

    def test_issue_rows_have_mr_cells(self) -> None:
        # MR cells present (data-field for mr_urls)
        assert "mr_urls" in self.html

    def test_issue_rows_show_number_and_title(self) -> None:
        assert "#1" in self.html
        assert "Bootstrap repo" in self.html

    # --- R-29: data-wave, data-issue, data-field attributes ---

    def test_data_wave_attributes_present(self) -> None:
        assert self.html.count("data-wave=") >= 3  # at least one per wave

    def test_data_issue_attributes_present(self) -> None:
        assert self.html.count("data-issue=") >= 4  # at least one per issue

    def test_data_field_attributes_present(self) -> None:
        assert self.html.count("data-field=") >= 4  # at least one per issue status

    def test_data_field_references_issues_status(self) -> None:
        assert 'data-field="issues.1.status"' in self.html

    def test_data_field_references_wave_status(self) -> None:
        assert 'data-field="waves.wave-1.status"' in self.html

    def test_data_field_references_mr_urls(self) -> None:
        assert "waves.wave-1.mr_urls" in self.html

    # --- Phase color cycle ---

    def test_phase_1_uses_fuchsia(self) -> None:
        assert "var(--fuchsia)" in self.html

    def test_phase_2_uses_cyan(self) -> None:
        assert "var(--cyan)" in self.html

    # --- Empty phases_data ---

    def test_empty_phases_returns_grid_wrapper(self) -> None:
        html = render_execution_grid(
            {"phases": []}, STATE_DATA_BASE, FLIGHTS_DATA_EMPTY
        )
        assert 'class="execution-grid"' in html
        assert "phase-section" not in html


class TestRenderExecutionGridWithFlights:
    """Execution grid with flight plan — verifies flight badges [R-04]."""

    def setup_method(self) -> None:
        self.html = render_execution_grid(
            PHASES_DATA, STATE_DATA_BASE, FLIGHTS_DATA_WAVE1
        )

    def test_flight_badges_present(self) -> None:
        assert "flight 1" in self.html
        assert "flight 2" in self.html

    def test_flight_badge_class_running(self) -> None:
        assert "badge-running" in self.html

    def test_flight_badge_class_pending(self) -> None:
        assert "badge-pending" in self.html

    def test_flight_data_wave_attribute(self) -> None:
        assert 'data-wave="wave-1"' in self.html

    def test_flight_data_field_attribute(self) -> None:
        assert "flights.wave-1." in self.html


class TestRenderExecutionGridWithMRLinks:
    """Execution grid with MR URLs recorded — verifies MR link rendering [R-08]."""

    def setup_method(self) -> None:
        state = {
            **STATE_DATA_BASE,
            "waves": {
                "wave-1": {
                    "status": "in_progress",
                    "mr_urls": {"1": "https://github.com/org/repo/pull/10"},
                },
                "wave-2": {"status": "pending", "mr_urls": {}},
                "wave-3": {"status": "pending", "mr_urls": {}},
            },
        }
        self.html = render_execution_grid(PHASES_DATA, state, FLIGHTS_DATA_EMPTY)

    def test_mr_link_href_present(self) -> None:
        assert 'href="https://github.com/org/repo/pull/10"' in self.html

    def test_mr_link_data_field_attribute(self) -> None:
        assert 'data-field="waves.wave-1.mr_urls.1"' in self.html


class TestRenderExecutionGridWithClosedIssues:
    """Execution grid with closed issues — verifies closed status badge [R-07]."""

    def setup_method(self) -> None:
        state = {
            **STATE_DATA_BASE,
            "issues": {
                "1": {"status": "closed"},
                "2": {"status": "open"},
                "3": {"status": "open"},
                "4": {"status": "open"},
            },
        }
        self.html = render_execution_grid(PHASES_DATA, state, FLIGHTS_DATA_EMPTY)

    def test_closed_issue_shows_closed_badge(self) -> None:
        assert "badge-closed" in self.html

    def test_open_issue_shows_open_badge(self) -> None:
        assert "badge-pending" in self.html or "open" in self.html


# ---------------------------------------------------------------------------
# CT-01: No non-stdlib imports
# ---------------------------------------------------------------------------


class TestNoNonStdlibImports:
    """CT-01: module uses only Python 3.10+ stdlib (plus wave_status internals)."""

    def test_module_importable_without_third_party(self) -> None:
        import wave_status.dashboard.execution_grid as eg  # noqa: F401

        assert hasattr(eg, "render_execution_grid")

    def test_module_has_no_non_stdlib_imports(self) -> None:
        src = (
            pathlib.Path(__file__).parent.parent
            / "src"
            / "wave_status"
            / "dashboard"
            / "execution_grid.py"
        )
        tree = ast.parse(src.read_text())
        stdlib_prefixes = {
            "__future__", "ast", "os", "sys", "pathlib", "json", "re",
            "html", "datetime", "collections", "itertools", "functools",
            "typing", "types", "abc", "io", "math", "copy", "string",
            "textwrap", "enum", "dataclasses", "contextlib",
        }
        external = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib_prefixes:
                        external.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in stdlib_prefixes and top != "wave_status":
                        external.append(node.module)
        assert external == [], f"Non-stdlib imports found: {external}"
