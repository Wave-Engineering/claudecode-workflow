"""Regression tests for the legacy flight-envelope shape [#663].

``flights.json`` stores per-wave flight data as ``flights[<wave_id>]``. The
canonical shape is a flat list of flight dicts; a legacy flight-partition
writer persisted a nested envelope (``{"flights": [...], "strategy": ...}``)
for some waves. Renderers that iterate the per-wave value directly crashed on
the envelope shape with ``'str' object has no attribute 'get'`` (iterating a
dict yields its string keys).

``state.wave_flight_list`` normalizes both shapes; these tests pin that the
helper and all four consumers (three dashboard renderers + the CLI summary)
tolerate the envelope shape and agree with the flat-list shape.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard import execution_grid, gauge_cards, kahuna_section
from wave_status.state import (
    flight,
    load_json,
    save_json,
    status_dir,
    wave_flight_list,
)

_FLIGHT = {"issues": [20], "status": "completed"}

# Same wave expressed both ways.
_FLAT = {"flights": {"wave-x": [_FLIGHT]}}
_ENVELOPE = {
    "flights": {"wave-x": {"flights": [_FLIGHT], "strategy": "safe", "conflict_count": 1}}
}


class TestWaveFlightList:
    def test_flat_list_passthrough(self) -> None:
        assert wave_flight_list(_FLAT, "wave-x") == [_FLIGHT]

    def test_envelope_unwrapped(self) -> None:
        assert wave_flight_list(_ENVELOPE, "wave-x") == [_FLIGHT]

    def test_missing_wave_returns_empty(self) -> None:
        assert wave_flight_list(_FLAT, "nope") == []

    def test_non_dict_elements_dropped(self) -> None:
        data = {"flights": {"wave-x": ["junk", _FLIGHT, 7]}}
        assert wave_flight_list(data, "wave-x") == [_FLIGHT]

    def test_garbage_value_returns_empty(self) -> None:
        assert wave_flight_list({"flights": {"wave-x": "nonsense"}}, "wave-x") == []
        assert wave_flight_list({}, "wave-x") == []


class TestRenderersTolerateEnvelope:
    """Each consumer must produce the SAME result for the envelope shape as
    for the flat list — and must not raise ``'str' object has no attribute
    'get'`` on the envelope."""

    def test_execution_grid_badges(self) -> None:
        flat = execution_grid._render_flight_badges("wave-x", _FLAT)
        env = execution_grid._render_flight_badges("wave-x", _ENVELOPE)
        assert flat == env
        assert flat  # non-empty — the flight rendered

    def test_gauge_cards_flight_info(self) -> None:
        state = {"current_wave": "wave-x"}
        flat = gauge_cards._flight_info(state, _FLAT)
        env = gauge_cards._flight_info(state, _ENVELOPE)
        assert flat == env
        assert env["has_flights"] is True

    def test_kahuna_flight_counts(self) -> None:
        flat = kahuna_section._flight_counts(_FLAT, "wave-x")
        env = kahuna_section._flight_counts(_ENVELOPE, "wave-x")
        assert flat == env == (1, 0)


class TestWriteSideSelfHeals:
    """``flight`` / ``flight_done`` read the per-wave value to validate and
    mutate it. On the envelope shape they previously crashed; now they read
    via ``wave_flight_list`` and write the flat list back — self-healing the
    drift so the legacy envelope never persists past the next flight op."""

    def test_flight_tolerates_and_heals_envelope(self, temp_git_repo) -> None:
        repo = temp_git_repo
        d = status_dir(repo)
        d.mkdir(parents=True, exist_ok=True)
        save_json(d / "state.json", {"current_wave": "wave-x", "waves": {}})
        # Envelope-shaped wave (legacy drift) with one pending flight.
        save_json(
            d / "flights.json",
            {
                "flights": {
                    "wave-x": {
                        "flights": [{"issues": [20], "status": "pending"}],
                        "strategy": "safe",
                        "conflict_count": 1,
                    }
                }
            },
        )

        # Previously raised on the envelope shape; must now succeed.
        result = flight(1, repo)
        assert result["current_action"]["action"] == "in-flight"

        # Self-heal: the persisted shape is now the flat list, and the flight
        # is marked running.
        healed = load_json(d / "flights.json")
        assert healed["flights"]["wave-x"] == [
            {"issues": [20], "status": "running"}
        ]
