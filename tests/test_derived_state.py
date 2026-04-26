"""Tests for wave_status.dashboard.derived_state.

Pure-function snapshot computation — no IO, no mocks needed beyond plain
fixture dicts.  Validates issue #447 acceptance criteria for the new
gauge/rail dotted-path resolution shape.
"""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.derived_state import compute_derived_state


# ---------------------------------------------------------------------------
# Realistic fixtures (mirror what state.json + phases-waves.json look like)
# ---------------------------------------------------------------------------

PHASES_2_PHASES = {
    "project": "test-proj",
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {"id": "wave-1", "issues": [{"number": 1}, {"number": 2}]},
                {"id": "wave-2", "issues": [{"number": 3}, {"number": 4}]},
            ],
        },
        {
            "name": "Core",
            "waves": [
                {"id": "wave-3", "issues": [{"number": 5}]},
            ],
        },
    ],
}

STATE_WAVE1_ONE_CLOSED = {
    "current_wave": "wave-1",
    "waves": {
        "wave-1": {"status": "in_progress"},
        "wave-2": {"status": "pending"},
        "wave-3": {"status": "pending"},
    },
    "issues": {
        "1": {"status": "closed"},
        "2": {"status": "open"},
        "3": {"status": "open"},
        "4": {"status": "open"},
        "5": {"status": "open"},
    },
    "deferrals": [
        {"description": "d1", "risk": "low", "status": "pending"},
    ],
}

FLIGHTS_RUNNING = {
    "flights": {
        "wave-1": [
            {"issues": [1], "status": "completed"},
            {"issues": [2], "status": "running"},
        ]
    }
}


# ---------------------------------------------------------------------------
# Top-level shape
# ---------------------------------------------------------------------------


class TestComputeDerivedStateShape:
    def setup_method(self) -> None:
        self.derived = compute_derived_state(
            PHASES_2_PHASES, STATE_WAVE1_ONE_CLOSED, FLIGHTS_RUNNING
        )

    def test_top_level_keys(self) -> None:
        assert set(self.derived.keys()) == {"gauges", "rail"}

    def test_gauges_has_four_named_entries(self) -> None:
        # Mirror the four gauge_name strings that gauge_cards.render_card
        # uses; the polling resolver walks state.gauges.<name>.value.
        assert set(self.derived["gauges"].keys()) == {
            "phase",
            "wave",
            "flight",
            "deferrals",
        }

    def test_each_gauge_carries_value_and_pct(self) -> None:
        for name, entry in self.derived["gauges"].items():
            assert "value" in entry, f"{name} missing 'value'"
            assert "pct" in entry, f"{name} missing 'pct'"
            assert isinstance(entry["value"], str)
            assert isinstance(entry["pct"], (int, float))

    def test_rail_keyed_by_phase_label(self) -> None:
        # phase_label form matches progress_rail.py: "phase-1", "phase-2", …
        assert set(self.derived["rail"].keys()) == {"phase-1", "phase-2"}

    def test_each_rail_entry_has_completed_and_remaining(self) -> None:
        for phase_label, entry in self.derived["rail"].items():
            assert "completed_pct" in entry
            assert "remaining_pct" in entry
            assert isinstance(entry["completed_pct"], (int, float))
            assert isinstance(entry["remaining_pct"], (int, float))


# ---------------------------------------------------------------------------
# Numeric correctness
# ---------------------------------------------------------------------------


class TestGaugeValues:
    """Computed gauge values must agree with what the renderers emit."""

    def setup_method(self) -> None:
        self.gauges = compute_derived_state(
            PHASES_2_PHASES, STATE_WAVE1_ONE_CLOSED, FLIGHTS_RUNNING
        )["gauges"]

    def test_phase_value_is_x_over_y(self) -> None:
        # Phase 1 of 2.
        assert self.gauges["phase"]["value"] == "1/2"
        # 1/2 = 50%, stored as 0..100.
        assert self.gauges["phase"]["pct"] == 50.0

    def test_wave_value_is_n_over_m(self) -> None:
        # wave-1 is wave 1 of 2 in Foundation.
        assert self.gauges["wave"]["value"] == "1/2"
        assert self.gauges["wave"]["pct"] == 50.0

    def test_flight_value_reflects_running_flight(self) -> None:
        # Flight 2 of 2 is running → "2/2" with 50% pct (1/2 done).
        assert self.gauges["flight"]["value"] == "2/2"
        assert self.gauges["flight"]["pct"] == 50.0

    def test_deferrals_value_shows_pending_count(self) -> None:
        assert self.gauges["deferrals"]["value"] == "1 pending"
        # 1 pending / (1 pending + 0 accepted) = 100%.
        assert self.gauges["deferrals"]["pct"] == 100.0


class TestRailValues:
    """Computed rail percentages must reflect issues closed per phase."""

    def setup_method(self) -> None:
        self.rail = compute_derived_state(
            PHASES_2_PHASES, STATE_WAVE1_ONE_CLOSED, FLIGHTS_RUNNING
        )["rail"]

    def test_phase_1_completed_pct(self) -> None:
        # Phase 1: 4 issues (1,2,3,4), 1 closed → 25%.
        assert self.rail["phase-1"]["completed_pct"] == 25.0
        assert self.rail["phase-1"]["remaining_pct"] == 75.0

    def test_phase_2_completed_pct(self) -> None:
        # Phase 2: 1 issue, 0 closed → 0%.
        assert self.rail["phase-2"]["completed_pct"] == 0.0
        assert self.rail["phase-2"]["remaining_pct"] == 100.0

    def test_phase_completed_plus_remaining_is_100(self) -> None:
        for entry in self.rail.values():
            total = entry["completed_pct"] + entry["remaining_pct"]
            # Allow 1e-6 wobble from rounding to 4 decimals.
            assert abs(total - 100.0) < 1e-6


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_phases_yields_empty_rail(self) -> None:
        derived = compute_derived_state(
            {"phases": []},
            {"current_wave": None, "waves": {}, "issues": {}, "deferrals": []},
            {"flights": {}},
        )
        assert derived["rail"] == {}

    def test_empty_phases_still_produces_four_gauges(self) -> None:
        # Even with no phases, the gauges block carries the four keys (the
        # polling resolver doesn't tolerate missing intermediate keys).
        derived = compute_derived_state(
            {"phases": []},
            {"current_wave": None, "waves": {}, "issues": {}, "deferrals": []},
            {"flights": {}},
        )
        assert set(derived["gauges"].keys()) == {
            "phase",
            "wave",
            "flight",
            "deferrals",
        }

    def test_phase_with_no_issues_skipped_in_rail(self) -> None:
        # progress_rail.py uses `continue` when phase_total == 0 — the
        # derived snapshot agrees, so the polling JS doesn't try to update
        # widths for non-existent segments.
        derived = compute_derived_state(
            {
                "phases": [
                    {"name": "Empty", "waves": []},
                    {
                        "name": "Real",
                        "waves": [{"id": "w", "issues": [{"number": 1}]}],
                    },
                ]
            },
            {"current_wave": None, "waves": {}, "issues": {}, "deferrals": []},
            {"flights": {}},
        )
        assert "phase-1" not in derived["rail"]
        assert "phase-2" in derived["rail"]

    def test_pct_clamped_to_0_100(self) -> None:
        # No way to provoke >1 from real inputs in the current renderers,
        # but the helper should still clamp defensively. Use a state where
        # current_phase_info reports phase_idx > total_phases (impossible
        # in normal flow but cheap to test).
        derived = compute_derived_state(
            PHASES_2_PHASES, STATE_WAVE1_ONE_CLOSED, FLIGHTS_RUNNING
        )
        for entry in derived["gauges"].values():
            assert 0.0 <= entry["pct"] <= 100.0

    def test_pure_function_does_not_mutate_inputs(self) -> None:
        # The helper must not alter the dicts it consumes; callers reuse
        # them directly afterward (state_data is later passed to
        # generate_dashboard).
        import copy

        phases = copy.deepcopy(PHASES_2_PHASES)
        state = copy.deepcopy(STATE_WAVE1_ONE_CLOSED)
        flights = copy.deepcopy(FLIGHTS_RUNNING)
        compute_derived_state(phases, state, flights)
        assert phases == PHASES_2_PHASES
        assert state == STATE_WAVE1_ONE_CLOSED
        assert flights == FLIGHTS_RUNNING
