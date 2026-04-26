"""Derived-state computation for the dashboard polling cycle.

The polling JS in ``polling.py`` resolves ``data-field`` bindings against
``state.json`` only.  Gauge values and progress-rail fill widths are
*computed* from ``phases-waves.json`` + ``state.json`` + ``flights.json``
at HTML-generation time, so they don't naturally live in ``state.json``.

This module exposes :func:`compute_derived_state`, a pure function that
returns the same computed snapshot the gauge/rail renderers consume —
shaped so the polling JS's existing dotted-path resolver can find each
value via a stable key (e.g. ``gauges.phase.value``,
``rail.phase-1.completed_pct``).

Writing the snapshot back into ``state.json`` happens in the dashboard
regen path (``wave_status.__main__._regenerate_dashboard``), which is the
one place that has all three input dicts in hand.

No imports outside Python 3.10+ stdlib (except wave_status internals)
[CT-01].
"""

from __future__ import annotations

from wave_status.dashboard.gauge_cards import _deferral_info, _flight_info
from wave_status.state import current_phase_info


def _compute_gauges(
    phases_data: dict, state_data: dict, flights_data: dict
) -> dict:
    """Return a dict keyed by gauge name with ``value`` / ``pct`` entries.

    Keys match the ``gauge_name`` argument passed to ``_render_card`` in
    ``gauge_cards.py`` so the rendered binding ``data-field=
    "gauges.<gauge_name>.value"`` resolves cleanly.
    """
    phase_info = current_phase_info(phases_data, state_data)
    flight_info = _flight_info(state_data, flights_data)
    deferral_info = _deferral_info(state_data)

    # Phase card
    x = phase_info["phase_idx"]
    y = phase_info["total_phases"]
    phase_value = f"{x}/{y}"
    phase_pct = (x / y) if y > 0 else 0.0

    # Wave card
    n = phase_info["wave_in_phase"]
    m = phase_info["waves_in_phase"]
    wave_value = f"{n}/{m}"
    wave_pct = (n / m) if m > 0 else 0.0

    # Flight card
    flight_value = flight_info["value"]
    flight_pct = flight_info["pct"]

    # Deferrals card
    u = deferral_info["pending"]
    deferral_value = f"{u} pending"
    deferral_pct = deferral_info["pct"]

    # `pct` is stored as a 0..100 percentage (NOT a 0..1 ratio) so the
    # polling JS can splice it directly into ``style.width`` without
    # arithmetic.  The renderer in gauge_cards.py also multiplies its
    # 0..1 input by 100 — same rounding (1 decimal) is applied here so
    # the on-load HTML and the live-polled width agree byte-for-byte.
    return {
        "phase": {"value": phase_value, "pct": _to_pct100(phase_pct)},
        "wave": {"value": wave_value, "pct": _to_pct100(wave_pct)},
        "flight": {"value": flight_value, "pct": _to_pct100(flight_pct)},
        "deferrals": {"value": deferral_value, "pct": _to_pct100(deferral_pct)},
    }


def _compute_rail(phases_data: dict, state_data: dict) -> dict:
    """Return per-phase completed/remaining percentages for the progress rail.

    Keys are ``phase-1``, ``phase-2``, … matching the ``data-rail-phase``
    label rendered by ``progress_rail.py``.  Each entry carries
    ``completed_pct`` and ``remaining_pct`` floats in the 0..100 range,
    representing the width *within* that phase's segment (not the global
    width).
    """
    phases: list[dict] = phases_data.get("phases", [])
    issues_state: dict[str, dict] = state_data.get("issues", {})

    rail: dict[str, dict] = {}
    for phase_index, phase in enumerate(phases):
        phase_issues: list[int] = []
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                phase_issues.append(issue["number"])

        phase_total = len(phase_issues)
        if phase_total == 0:
            continue

        phase_closed = sum(
            1
            for num in phase_issues
            if issues_state.get(str(num), {}).get("status") == "closed"
        )

        completed_pct = (phase_closed / phase_total * 100) if phase_total else 0.0
        remaining_pct = 100.0 - completed_pct

        rail[f"phase-{phase_index + 1}"] = {
            "completed_pct": round(completed_pct, 4),
            "remaining_pct": round(remaining_pct, 4),
        }
    return rail


def _to_pct100(value: float) -> float:
    """Clamp *value* to [0.0, 1.0] then convert to a 0..100 percentage.

    Matches the rounding ``_render_card`` applies to its inline
    ``style="width: X%"`` attribute (1 decimal place) so the initial HTML
    width and the live-polled width never disagree by float drift.
    """
    clamped = max(0.0, min(1.0, float(value)))
    return round(clamped * 100, 1)


def compute_derived_state(
    phases_data: dict, state_data: dict, flights_data: dict
) -> dict:
    """Return ``{"gauges": {...}, "rail": {...}}`` computed from inputs.

    Pure function — no IO, no mutation of arguments.  Caller is
    responsible for splicing the result into ``state.json`` (or wherever
    the polling cycle reads from).

    The returned dict's structure is the contract the polling JS relies
    on: bare-path bindings (``data-field="value"``) were always broken,
    so this fix migrates them to dotted paths (``gauges.<name>.value``,
    ``rail.<phase>.completed_pct``) that ``resolve(state, path)`` can
    walk.  See AC on issue #447.
    """
    return {
        "gauges": _compute_gauges(phases_data, state_data, flights_data),
        "rail": _compute_rail(phases_data, state_data),
    }
