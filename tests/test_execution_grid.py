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

    def test_data_status_on_status_badge(self) -> None:
        # cc-workflow#1180: data-status (not data-field) drives the badge —
        # data-field only ever updated textContent, never the CSS class.
        assert 'data-status="issues.*.status"' in self.html
        assert 'data-field-key="1"' in self.html

    def test_mr_cell_empty_when_no_mr(self) -> None:
        # cc-workflow#1180 code review: no MR URL -> a hidden <a> (never a
        # <span>), so a later poll tick can populate href without needing to
        # change the element's tag.
        assert 'data-field="waves.wave-1.mr_urls.*"' in self.html
        assert 'data-bind-href="waves.wave-1.mr_urls.*"' in self.html
        assert 'data-field-key="1"' in self.html
        assert "<a href=" not in self.html
        assert '<a class="mr-link" style="display:none"' in self.html

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
        assert '<a class="mr-link" href="https://github.com/org/repo/pull/42"' in html
        assert 'data-field="waves.wave-1.mr_urls.*"' in html
        assert 'data-bind-href="waves.wave-1.mr_urls.*"' in html
        assert 'data-field-key="1"' in html
        assert "display:none" not in html

    def test_issue_without_title_uses_fallback(self) -> None:
        html = _render_issue_row(99, {"number": 99}, STATE_DATA_BASE, "wave-1")
        assert "Issue #99" in html

    def test_unknown_issue_in_state_defaults_to_open(self) -> None:
        # Issue 999 not in state dict -> defaults to "open"
        html = _render_issue_row(999, {"number": 999, "title": "Mystery"}, STATE_DATA_BASE, "wave-1")
        assert "open" in html

    def test_status_badge_resolves_qualified_key(self) -> None:
        # #1160: a repo-qualified plan's state.json stores issues under
        # "owner/repo#N" (state._compose_issue_key), not a bare number. A
        # bare-key-only lookup would silently fall through to the "open"
        # default even though the issue is actually closed.
        state = {
            **STATE_DATA_BASE,
            "issues": {"acme/widgets#1": {"status": "closed"}},
        }
        html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1")
        assert "badge-closed" in html
        assert ">closed<" in html
        assert ">open<" not in html
        # #1173 (fixed): the resolved key rides in data-field-key, not
        # interpolated into the path — this is what makes the dashboard's
        # live-poll able to find this cell again on a later poll tick, not
        # just at initial render. #1180: a template "*" segment, not the
        # literal key, since the key itself may contain a "." (see below).
        assert 'data-status="issues.*.status"' in html
        assert 'data-field-key="acme/widgets#1"' in html

    def test_mr_link_resolves_qualified_key(self) -> None:
        # #1160: record_mr composes a qualified "owner/repo#N" key for a
        # repo-tagged plan — the MR-link cell must find it via the same
        # dual-read resolve_issue_value convention as the issues dict.
        state = {
            **STATE_DATA_BASE,
            "waves": {
                "wave-1": {
                    "status": "in_progress",
                    "mr_urls": {"acme/widgets#1": "https://github.com/acme/widgets/pull/42"},
                },
                "wave-2": {"status": "pending", "mr_urls": {}},
                "wave-3": {"status": "pending", "mr_urls": {}},
            },
        }
        html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1")
        assert '<a class="mr-link" href="https://github.com/acme/widgets/pull/42"' in html
        # #1173 (fixed): the resolved key rides in data-field-key, same
        # reasoning as the status-badge test above — the live-poll needs it.
        assert 'data-field="waves.wave-1.mr_urls.*"' in html
        assert 'data-bind-href="waves.wave-1.mr_urls.*"' in html
        assert 'data-field-key="acme/widgets#1"' in html

    def test_mr_link_data_field_uses_future_key_before_mr_is_recorded(self) -> None:
        # cc-workflow#1173 code review: mr_urls starts EMPTY from init_state
        # (unlike issues, which init_state pre-populates) — the dashboard's
        # very FIRST render of a repo-qualified plan hits exactly this state,
        # not an edge case. Without future_issue_key, the pre-#1173-code-
        # review fallback baked the BARE issue number here, which record_mr
        # then never writes to (it composes "acme/widgets#1") — the live-poll
        # binding would target a path that never gets an entry, silently,
        # forever. This is issue #1173's own AC #2 and Test Procedure #1.
        state = {**STATE_DATA_BASE}  # wave-1's mr_urls is {} in the base fixture
        plan_data = {**PHASES_DATA, "repo": "acme/widgets"}
        html = _render_issue_row(
            1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1", plan_data
        )
        assert (
            'data-field="waves.wave-1.mr_urls.*" data-bind-href="waves.wave-1.mr_urls.*"'
            ' data-field-key="acme/widgets#1"'
        ) in html
        assert (
            'data-field="waves.wave-1.mr_urls.*" data-bind-href="waves.wave-1.mr_urls.*"'
            ' data-field-key="1"'
        ) not in html

    def test_status_badge_data_field_uses_future_key_when_issue_wholly_absent(self) -> None:
        # Same future_issue_key fallback, issues-side: an issue absent from
        # state.json entirely (e.g. added via `init --extend` before a
        # re-init) must still get a qualified binding for a repo-tagged plan,
        # not a bare guess the write path will never use.
        state = {**STATE_DATA_BASE, "issues": {}}
        plan_data = {**PHASES_DATA, "repo": "acme/widgets"}
        html = _render_issue_row(
            1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1", plan_data
        )
        assert 'data-status="issues.*.status"' in html
        assert 'data-field-key="acme/widgets#1"' in html

    def test_future_key_fallback_stays_bare_without_plan_data(self) -> None:
        # Regression guard: omitting plan_data (existing callers, non-#1173
        # code) must keep the pre-review bare-number behavior — no forced
        # migration, no crash on a missing argument.
        state = {**STATE_DATA_BASE, "issues": {}}
        html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1")
        assert 'data-status="issues.*.status"' in html
        assert 'data-field-key="1"' in html

    def test_resolved_key_is_html_escaped_in_data_field(self) -> None:
        # Code review: issue_key/mr_key are read from state.json (operator-
        # authored plan data), not guaranteed dot-free ints like the old bare
        # issue_number — every other interpolated string in this renderer
        # goes through _html.escape, these must too.
        state = {
            **STATE_DATA_BASE,
            "issues": {'ac"me/widgets#1': {"status": "closed"}},
        }
        html = _render_issue_row(1, {"number": 1, "title": "Bootstrap repo"}, state, "wave-1")
        assert 'data-field-key="ac&quot;me/widgets#1"' in html
        assert 'data-field-key="ac"me/widgets#1"' not in html

    def test_cross_repo_same_number_does_not_collide(self) -> None:
        # Code review: resolve_issue_key's scan has no notion of which repo
        # THIS row belongs to — it returns the FIRST "#N" match in insertion
        # order. A cross-repo plan can legitimately repeat an issue number
        # across repos (state.py's _wave_work_item_counts docstring), so a
        # blind scan can bind this row to a DIFFERENT repo's same-numbered
        # issue. _row_key must prefer THIS row's own future_issue_key when
        # it's actually present in the bag, not the first insertion match.
        state = {
            **STATE_DATA_BASE,
            "issues": {
                "acme/a#5": {"status": "open"},
                "acme/b#5": {"status": "closed"},
            },
        }
        plan_data = {**PHASES_DATA, "repo": "acme/a"}
        # This row's issue_plan carries its OWN repo override — "acme/b" —
        # distinct from the plan-level default ("acme/a").
        html = _render_issue_row(
            5, {"number": 5, "title": "Widget B", "repo": "acme/b"}, state, "wave-1", plan_data
        )
        assert "badge-closed" in html
        assert ">closed<" in html
        assert 'data-field-key="acme/b#5"' in html
        assert 'data-field-key="acme/a#5"' not in html


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
        # cc-workflow#1180: data-status (not data-field) — live-updates
        # both the class and label, not textContent alone.
        assert 'data-status="waves.wave-1.status"' in self.html

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
        # cc-workflow#1180: issue-status badges moved to data-status, so
        # this count now comes from the MR-link cells (one per issue), plus
        # any wave/flight data-field bindings — not the status badges.
        assert self.html.count("data-field=") >= 4

    def test_data_field_references_issues_status(self) -> None:
        assert 'data-status="issues.*.status"' in self.html
        assert 'data-field-key="1"' in self.html

    def test_data_field_references_wave_status(self) -> None:
        assert 'data-status="waves.wave-1.status"' in self.html

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
        assert 'data-field="waves.wave-1.mr_urls.*"' in self.html
        assert 'data-bind-href="waves.wave-1.mr_urls.*"' in self.html
        assert 'data-field-key="1"' in self.html


class TestRenderExecutionGridQualifiedPlanWiring:
    """cc-workflow#1173 code review: pins the FULL production call chain
    (render_execution_grid -> _render_phase_section -> _render_wave_card ->
    _render_issue_row), not just the private _render_issue_row entry point
    the other qualified-key tests call directly. Every prior qualified-key
    test in this file calls _render_issue_row(..., plan_data) itself, so
    deleting the plan_data argument from the real wiring at any of the three
    intermediate hops would fail NO test while silently reintroducing the
    bare-number regression #1173 exists to fix — this is issue #1173's own
    Test Procedure #1, exercised at the level the operator actually calls
    (generator.py -> render_execution_grid)."""

    def test_qualified_plan_data_fields_reach_the_real_call_chain(self) -> None:
        plan = {**PHASES_DATA, "repo": "acme/widgets"}
        state = {**STATE_DATA_BASE, "issues": {}}  # nothing recorded yet
        html = render_execution_grid(plan, state, FLIGHTS_DATA_EMPTY)
        assert 'data-status="issues.*.status"' in html
        assert 'data-field="waves.wave-1.mr_urls.*"' in html
        assert 'data-field-key="acme/widgets#1"' in html
        assert 'data-field-key="1"' not in html


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
