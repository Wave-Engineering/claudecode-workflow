"""Tests for wave_status.dashboard.gauge_cards module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #20 (Story 2.2).
"""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.gauge_cards import (
    _deferral_info,
    _flight_info,
    _render_card,
    render_gauge_cards,
)
from wave_status.state import current_phase_info


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PHASES_DATA_2_PHASES = {
    "project": "test-proj",
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {"id": "wave-1", "issues": [{"number": 1}]},
                {"id": "wave-2", "issues": [{"number": 2}]},
            ],
        },
        {
            "name": "Core",
            "waves": [
                {"id": "wave-3", "issues": [{"number": 3}]},
            ],
        },
    ],
}

STATE_DATA_WAVE1 = {
    "current_wave": "wave-1",
    "waves": {
        "wave-1": {"status": "in_progress"},
        "wave-2": {"status": "pending"},
        "wave-3": {"status": "pending"},
    },
    "issues": {"1": {"status": "open"}, "2": {"status": "open"}, "3": {"status": "open"}},
    "deferrals": [],
}

FLIGHTS_DATA_EMPTY = {"flights": {}}

FLIGHTS_DATA_WITH_FLIGHTS = {
    "flights": {
        "wave-1": [
            {"issues": [1], "status": "running"},
            {"issues": [2], "status": "pending"},
        ]
    }
}


# ---------------------------------------------------------------------------
# current_phase_info() tests
# ---------------------------------------------------------------------------


class TestCurrentPhaseInfo:
    """Computes phase index, name, and wave position."""

    def test_first_wave_first_phase(self) -> None:
        info = current_phase_info(PHASES_DATA_2_PHASES, STATE_DATA_WAVE1)
        assert info["phase_idx"] == 1
        assert info["total_phases"] == 2
        assert info["phase_name"] == "Foundation"
        assert info["wave_in_phase"] == 1
        assert info["waves_in_phase"] == 2

    def test_second_wave_first_phase(self) -> None:
        state = {**STATE_DATA_WAVE1, "current_wave": "wave-2"}
        info = current_phase_info(PHASES_DATA_2_PHASES, state)
        assert info["phase_idx"] == 1
        assert info["wave_in_phase"] == 2
        assert info["waves_in_phase"] == 2
        assert info["phase_name"] == "Foundation"

    def test_wave_in_second_phase(self) -> None:
        state = {**STATE_DATA_WAVE1, "current_wave": "wave-3"}
        info = current_phase_info(PHASES_DATA_2_PHASES, state)
        assert info["phase_idx"] == 2
        assert info["phase_name"] == "Core"
        assert info["wave_in_phase"] == 1
        assert info["waves_in_phase"] == 1

    def test_unknown_wave_infers_from_pending(self) -> None:
        state = {**STATE_DATA_WAVE1, "current_wave": "wave-999"}
        info = current_phase_info(PHASES_DATA_2_PHASES, state)
        # wave-999 not in plan, falls through to inference — wave-2 is pending
        assert info["phase_idx"] == 1
        assert info["wave_in_phase"] == 2
        assert info["phase_name"] == "Foundation"

    def test_no_current_wave_infers_first_pending(self) -> None:
        state = {**STATE_DATA_WAVE1, "current_wave": None}
        info = current_phase_info(PHASES_DATA_2_PHASES, state)
        # wave-2 is the first pending wave, in phase 1
        assert info["phase_idx"] == 1
        assert info["total_phases"] == 2
        assert info["wave_in_phase"] == 2

    def test_no_current_wave_all_complete(self) -> None:
        state = {
            "current_wave": None,
            "waves": {
                "wave-1": {"status": "completed"},
                "wave-2": {"status": "completed"},
                "wave-3": {"status": "completed"},
            },
            "issues": {},
            "deferrals": [],
        }
        info = current_phase_info(PHASES_DATA_2_PHASES, state)
        # All waves done — should report last phase
        assert info["phase_idx"] == 2
        assert info["total_phases"] == 2
        assert info["phase_name"] == "Core"

    def test_empty_phases(self) -> None:
        info = current_phase_info({"phases": []}, STATE_DATA_WAVE1)
        assert info["phase_idx"] == 0
        assert info["total_phases"] == 0


# ---------------------------------------------------------------------------
# _flight_info() tests
# ---------------------------------------------------------------------------


class TestFlightInfo:
    """Computes flight value string and progress ratio."""

    def test_no_flights_returns_em_dash(self) -> None:
        info = _flight_info(STATE_DATA_WAVE1, FLIGHTS_DATA_EMPTY)
        assert info["value"] == "\u2014"
        assert info["pct"] == 0.0
        assert info["has_flights"] is False

    def test_no_flight_plan_for_wave(self) -> None:
        """No entry in flights dict for this wave."""
        flights = {"flights": {"wave-99": [{"status": "running"}]}}
        info = _flight_info(STATE_DATA_WAVE1, flights)
        assert info["value"] == "\u2014"
        assert info["has_flights"] is False

    def test_running_flight_shows_i_j(self) -> None:
        info = _flight_info(STATE_DATA_WAVE1, FLIGHTS_DATA_WITH_FLIGHTS)
        assert info["value"] == "1/2"
        assert info["has_flights"] is True

    def test_running_flight_pct_is_ratio(self) -> None:
        """Running flight 1 of 2 = 0/2 = 0.0 (not yet started progress)."""
        info = _flight_info(STATE_DATA_WAVE1, FLIGHTS_DATA_WITH_FLIGHTS)
        # flight 1 running: (1-1)/2 = 0.0
        assert info["pct"] == 0.0

    def test_second_flight_running(self) -> None:
        flights = {
            "flights": {
                "wave-1": [
                    {"issues": [1], "status": "completed"},
                    {"issues": [2], "status": "running"},
                ]
            }
        }
        info = _flight_info(STATE_DATA_WAVE1, flights)
        assert info["value"] == "2/2"
        # (2-1)/2 = 0.5
        assert info["pct"] == 0.5

    def test_all_flights_completed(self) -> None:
        flights = {
            "flights": {
                "wave-1": [
                    {"issues": [1], "status": "completed"},
                    {"issues": [2], "status": "completed"},
                ]
            }
        }
        info = _flight_info(STATE_DATA_WAVE1, flights)
        assert info["value"] == "2/2"
        assert info["pct"] == 1.0

    def test_flights_all_pending_shows_em_dash_count(self) -> None:
        flights = {
            "flights": {
                "wave-1": [
                    {"issues": [1], "status": "pending"},
                    {"issues": [2], "status": "pending"},
                ]
            }
        }
        info = _flight_info(STATE_DATA_WAVE1, flights)
        assert info["value"] == "\u2014/2"
        assert info["pct"] == 0.0
        assert info["has_flights"] is True


# ---------------------------------------------------------------------------
# _deferral_info() tests
# ---------------------------------------------------------------------------


class TestDeferralInfo:
    """Computes pending/accepted counts and drain ratio."""

    def test_no_deferrals_all_zero(self) -> None:
        info = _deferral_info(STATE_DATA_WAVE1)
        assert info["pending"] == 0
        assert info["accepted"] == 0
        assert info["pct"] == 0.0

    def test_only_pending(self) -> None:
        state = {
            **STATE_DATA_WAVE1,
            "deferrals": [
                {"description": "d1", "risk": "low", "status": "pending"},
                {"description": "d2", "risk": "high", "status": "pending"},
            ],
        }
        info = _deferral_info(state)
        assert info["pending"] == 2
        assert info["accepted"] == 0
        assert info["pct"] == 1.0  # 2/(2+0) = 1.0

    def test_mixed_pending_and_accepted(self) -> None:
        state = {
            **STATE_DATA_WAVE1,
            "deferrals": [
                {"description": "d1", "risk": "low", "status": "accepted"},
                {"description": "d2", "risk": "medium", "status": "pending"},
                {"description": "d3", "risk": "high", "status": "pending"},
            ],
        }
        info = _deferral_info(state)
        assert info["pending"] == 2
        assert info["accepted"] == 1
        # pct = 2/(2+1) = 0.666...
        assert abs(info["pct"] - (2 / 3)) < 1e-9

    def test_all_accepted_pct_zero(self) -> None:
        state = {
            **STATE_DATA_WAVE1,
            "deferrals": [
                {"description": "d1", "risk": "low", "status": "accepted"},
            ],
        }
        info = _deferral_info(state)
        assert info["pending"] == 0
        assert info["accepted"] == 1
        assert info["pct"] == 0.0  # 0/(0+1) = 0.0


# ---------------------------------------------------------------------------
# _render_card() tests
# ---------------------------------------------------------------------------


class TestRenderCard:
    """Single card HTML structure."""

    def setup_method(self) -> None:
        self.html = _render_card("phase", "Phase", "1/4", "Foundation", 0.25)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_gauge_card_class(self) -> None:
        assert 'class="gauge-card"' in self.html

    def test_data_gauge_attribute(self) -> None:
        assert 'data-gauge="phase"' in self.html

    def test_data_field_value_on_value_element(self) -> None:
        # Issue #447: bare data-field="value" never resolved in the polling
        # cycle (state.value is undefined). Bindings now use the dotted path
        # gauges.<gauge_name>.value so applyState's resolve() can walk it.
        assert 'data-field="gauges.phase.value"' in self.html

    def test_label_present(self) -> None:
        assert ">Phase<" in self.html

    def test_value_present(self) -> None:
        assert ">1/4<" in self.html

    def test_sub_line_present(self) -> None:
        assert ">Foundation<" in self.html

    def test_progress_bar_structure(self) -> None:
        assert 'class="gauge-bar"' in self.html
        assert 'class="gauge-fill"' in self.html

    def test_fill_width_reflects_pct(self) -> None:
        assert "width: 25.0%" in self.html

    def test_100_percent(self) -> None:
        html = _render_card("phase", "Phase", "4/4", "Done", 1.0)
        assert "width: 100.0%" in html

    def test_zero_percent(self) -> None:
        html = _render_card("flight", "Flight", "—", "—", 0.0)
        assert "width: 0.0%" in html

    def test_pct_clamped_above_one(self) -> None:
        html = _render_card("phase", "Phase", "x", "y", 1.5)
        assert "width: 100.0%" in html

    def test_pct_clamped_below_zero(self) -> None:
        html = _render_card("phase", "Phase", "x", "y", -0.5)
        assert "width: 0.0%" in html

    def test_different_gauge_name(self) -> None:
        html = _render_card("deferrals", "Deferrals", "3 pending", "1 accepted", 0.75)
        assert 'data-gauge="deferrals"' in html
        assert ">Deferrals<" in html
        assert ">3 pending<" in html
        assert ">1 accepted<" in html


# ---------------------------------------------------------------------------
# render_gauge_cards() integration tests  [R-24, R-29]
# ---------------------------------------------------------------------------


class TestRenderGaugeCards:
    """Full integration: four card grid from real data dicts."""

    def setup_method(self) -> None:
        self.html = render_gauge_cards(
            PHASES_DATA_2_PHASES, STATE_DATA_WAVE1, FLIGHTS_DATA_EMPTY
        )

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_nonempty(self) -> None:
        assert len(self.html) > 0

    # --- R-24: Four gauge cards ---

    def test_has_gauge_grid_wrapper(self) -> None:
        assert 'class="gauge-grid"' in self.html

    def test_has_phase_card(self) -> None:
        assert 'data-gauge="phase"' in self.html

    def test_has_wave_card(self) -> None:
        assert 'data-gauge="wave"' in self.html

    def test_has_flight_card(self) -> None:
        assert 'data-gauge="flight"' in self.html

    def test_has_deferrals_card(self) -> None:
        assert 'data-gauge="deferrals"' in self.html

    def test_exactly_four_gauge_cards(self) -> None:
        assert self.html.count('class="gauge-card"') == 4

    # --- R-29: data-gauge and data-field attributes ---

    def test_four_data_gauge_attributes(self) -> None:
        assert self.html.count("data-gauge=") == 4

    def test_four_data_field_value_attributes(self) -> None:
        # Issue #447: bare data-field="value" never resolved in the polling
        # cycle. Each card now binds via the dotted path
        # gauges.<gauge_name>.value — one per card, four cards, four
        # bindings (containment count via str.count would otherwise miss
        # because each gauge_name differs).
        for gauge_name in ("phase", "wave", "flight", "deferrals"):
            assert (
                f'data-field="gauges.{gauge_name}.value"' in self.html
            ), f"missing dotted-path binding for {gauge_name!r}"
        # Four cards × one value-binding each = four total occurrences of
        # the prefix.
        assert self.html.count('data-field="gauges.') == 4

    # --- Phase card content ---

    def test_phase_value_x_over_y(self) -> None:
        """Phase card shows 1/2 for wave-1 which is phase 1 of 2."""
        assert ">1/2<" in self.html

    def test_phase_sub_line_is_phase_name(self) -> None:
        assert ">Foundation<" in self.html

    # --- Wave card content ---

    def test_wave_value_n_over_m(self) -> None:
        """wave-1 is wave 1 of 2 in the Foundation phase."""
        assert ">1/2<" in self.html

    def test_wave_sub_line_scoped_to_phase(self) -> None:
        assert "in phase 1" in self.html

    # --- Flight card — no flights yet ---

    def test_flight_shows_em_dash_before_flight_plan(self) -> None:
        assert "\u2014" in self.html

    # --- Deferrals card — zero counts ---

    def test_deferrals_value_zero_pending(self) -> None:
        assert ">0 pending<" in self.html

    def test_deferrals_sub_zero_accepted(self) -> None:
        assert ">0 accepted<" in self.html


class TestRenderGaugeCardsWithFlights:
    """Gauge cards when flight plan exists."""

    def setup_method(self) -> None:
        self.html = render_gauge_cards(
            PHASES_DATA_2_PHASES, STATE_DATA_WAVE1, FLIGHTS_DATA_WITH_FLIGHTS
        )

    def test_flight_value_shows_i_j(self) -> None:
        assert ">1/2<" in self.html

    def test_flight_sub_line_shows_wave_id(self) -> None:
        assert "wave-1" in self.html


class TestRenderGaugeCardsWithDeferrals:
    """Gauge cards when deferrals exist."""

    def setup_method(self) -> None:
        state = {
            **STATE_DATA_WAVE1,
            "deferrals": [
                {"description": "d1", "risk": "low", "status": "pending"},
                {"description": "d2", "risk": "medium", "status": "pending"},
                {"description": "d3", "risk": "high", "status": "accepted"},
            ],
        }
        self.html = render_gauge_cards(
            PHASES_DATA_2_PHASES, state, FLIGHTS_DATA_EMPTY
        )

    def test_deferrals_value_shows_pending_count(self) -> None:
        assert ">2 pending<" in self.html

    def test_deferrals_sub_shows_accepted_count(self) -> None:
        assert ">1 accepted<" in self.html

    def test_deferrals_bar_reflects_drain_ratio(self) -> None:
        # pct = 2/3 = 66.7%
        assert "width: 66.7%" in self.html


class TestRenderGaugeCardsSecondPhase:
    """Phase and Wave cards when current wave is in the second phase."""

    def setup_method(self) -> None:
        state = {**STATE_DATA_WAVE1, "current_wave": "wave-3"}
        self.html = render_gauge_cards(
            PHASES_DATA_2_PHASES, state, FLIGHTS_DATA_EMPTY
        )

    def test_phase_value_is_2_of_2(self) -> None:
        assert ">2/2<" in self.html

    def test_phase_sub_line_is_core(self) -> None:
        assert ">Core<" in self.html

    def test_wave_in_phase_1_of_1(self) -> None:
        assert ">1/1<" in self.html

    def test_wave_sub_line_scoped_to_phase_2(self) -> None:
        assert "in phase 2" in self.html


class TestRenderGaugeCardsNoneCurrentWave:
    """Handles gracefully when current_wave is None — infers from wave status."""

    def setup_method(self) -> None:
        # wave-1 in_progress, wave-2 and wave-3 pending → should infer phase 1
        state = {**STATE_DATA_WAVE1, "current_wave": None}
        self.html = render_gauge_cards(
            PHASES_DATA_2_PHASES, state, FLIGHTS_DATA_EMPTY
        )

    def test_returns_four_cards(self) -> None:
        assert self.html.count('class="gauge-card"') == 4

    def test_phase_infers_from_pending_waves(self) -> None:
        # First pending wave is wave-2 in phase 1 → shows 1/2
        assert ">1/2<" in self.html

    def test_flight_shows_em_dash(self) -> None:
        assert "\u2014" in self.html


class TestRenderGaugeCardsAllComplete:
    """When all waves are completed and current_wave is None."""

    def setup_method(self) -> None:
        state = {
            "current_wave": None,
            "waves": {
                "wave-1": {"status": "completed"},
                "wave-2": {"status": "completed"},
                "wave-3": {"status": "completed"},
            },
            "issues": {"1": {"status": "closed"}, "2": {"status": "closed"}, "3": {"status": "closed"}},
            "deferrals": [],
        }
        self.html = render_gauge_cards(
            PHASES_DATA_2_PHASES, state, FLIGHTS_DATA_EMPTY
        )

    def test_returns_four_cards(self) -> None:
        assert self.html.count('class="gauge-card"') == 4

    def test_phase_shows_last_phase(self) -> None:
        assert ">2/2<" in self.html

    def test_phase_name_is_last_phase(self) -> None:
        assert ">Core<" in self.html


class TestRenderGaugeCardsNoImportsOutsideStdlib:
    """CT-01: module uses only Python 3.10+ stdlib."""

    def test_module_importable_without_third_party(self) -> None:
        """If the import succeeded at top of file, stdlib-only constraint holds."""
        import wave_status.dashboard.gauge_cards as gc  # noqa: F401

        assert hasattr(gc, "render_gauge_cards")

    def test_module_has_no_non_stdlib_imports(self) -> None:
        """Check source file does not import third-party packages."""
        import ast
        import pathlib

        src = pathlib.Path(__file__).parent.parent / "src" / "wave_status" / "dashboard" / "gauge_cards.py"
        tree = ast.parse(src.read_text())
        # Collect top-level import names
        external = []
        stdlib_prefixes = {
            "__future__", "ast", "os", "sys", "pathlib", "json", "re",
            "html", "datetime", "collections", "itertools", "functools",
            "typing", "types", "abc", "io", "math", "copy", "string",
            "textwrap", "enum", "dataclasses", "contextlib",
        }
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
