"""Dashboard gauge cards component.

Renders the four metric gauge cards displayed below the progress rail.
Pure presentation — receives data dicts, returns HTML string.

No imports outside Python 3.10+ stdlib [CT-01].
"""

from __future__ import annotations

import html as _html

from wave_status.state import current_phase_info


def _flight_info(state_data: dict, flights_data: dict) -> dict:
    """Return a dict with current flight info for the active wave.

    Returns:
        {
            "value": str  — "i/j" or "—" when no flights
            "pct": float  — 0.0..1.0 ratio for progress bar
            "has_flights": bool
        }
    """
    current_wave = state_data.get("current_wave") or ""
    wave_flights = flights_data.get("flights", {}).get(current_wave, [])

    if not wave_flights:
        return {"value": "\u2014", "pct": 0.0, "has_flights": False}

    total = len(wave_flights)
    running_idx = None
    completed_count = 0

    for fi, fl in enumerate(wave_flights):
        status = fl.get("status", "pending")
        if status == "completed":
            completed_count += 1
        if status == "running" and running_idx is None:
            running_idx = fi + 1  # 1-based

    if running_idx is not None:
        value = f"{running_idx}/{total}"
        pct = (running_idx - 1) / total if total > 0 else 0.0
    else:
        # No running flight — show completed count or em-dash
        if completed_count > 0:
            value = f"{completed_count}/{total}"
            pct = completed_count / total
        else:
            value = f"\u2014/{total}"
            pct = 0.0

    return {"value": value, "pct": pct, "has_flights": True}


def _deferral_info(state_data: dict) -> dict:
    """Return pending/accepted counts and progress bar ratio.

    Returns:
        {
            "pending": int,
            "accepted": int,
            "pct": float  — u/(u+v), drains toward 0 as pending items accepted
        }
    """
    deferrals = state_data.get("deferrals", [])
    pending = sum(1 for d in deferrals if d.get("status") == "pending")
    accepted = sum(1 for d in deferrals if d.get("status") == "accepted")
    total = pending + accepted
    pct = pending / total if total > 0 else 0.0
    return {"pending": pending, "accepted": accepted, "pct": pct}


def _render_card(
    gauge_name: str,
    label: str,
    value: str,
    sub_line: str,
    pct: float,
) -> str:
    """Render a single gauge card as an HTML string.

    Parameters
    ----------
    gauge_name:
        Identifier for data-gauge attribute (e.g. "phase", "wave").
    label:
        Uppercase card label shown at top.
    value:
        Primary metric value (e.g. "1/4", "2 pending").
    sub_line:
        Secondary text below the value.
    pct:
        Progress bar fill ratio, 0.0..1.0.
    """
    pct_clamped = max(0.0, min(1.0, pct))
    fill_pct = round(pct_clamped * 100, 1)

    return (
        f'<div class="gauge-card" data-gauge="{_html.escape(gauge_name)}">\n'
        f'  <div class="gauge-label">{_html.escape(label)}</div>\n'
        f'  <div class="gauge-value" data-field="value">{_html.escape(value)}</div>\n'
        f'  <div class="gauge-sub">{_html.escape(sub_line)}</div>\n'
        f'  <div class="gauge-bar">'
        f'<div class="gauge-fill" style="width: {fill_pct}%"></div>'
        f"</div>\n"
        f"</div>"
    )


def render_gauge_cards(
    phases_data: dict,
    state_data: dict,
    flights_data: dict,
) -> str:
    """Render the four gauge cards section as an HTML string.

    Parameters
    ----------
    phases_data:
        The parsed phases-waves.json dict. Must contain a ``phases`` list,
        each entry with ``name`` and ``waves`` (list of dicts with ``id``).
    state_data:
        The parsed state.json dict. Must contain ``current_wave``,
        ``waves``, ``issues``, and ``deferrals``.
    flights_data:
        The parsed flights.json dict. Must contain a ``flights`` dict
        keyed by wave ID.

    Returns
    -------
    str
        An HTML ``<div class="gauge-grid">`` block containing four
        ``<div class="gauge-card">`` children.
    """
    phase_info = current_phase_info(phases_data, state_data)
    flight_info = _flight_info(state_data, flights_data)
    deferral_info = _deferral_info(state_data)

    # --- Phase card ---
    x = phase_info["phase_idx"]
    y = phase_info["total_phases"]
    phase_value = f"{x}/{y}"
    phase_sub = phase_info["phase_name"] or "\u2014"
    phase_pct = x / y if y > 0 else 0.0
    phase_card = _render_card("phase", "Phase", phase_value, phase_sub, phase_pct)

    # --- Wave card ---
    n = phase_info["wave_in_phase"]
    m = phase_info["waves_in_phase"]
    wave_value = f"{n}/{m}"
    wave_sub = f"in phase {x}" if x > 0 else "\u2014"
    wave_pct = n / m if m > 0 else 0.0
    wave_card = _render_card("wave", "Wave", wave_value, wave_sub, wave_pct)

    # --- Flight card ---
    flight_value = flight_info["value"]
    current_wave_id = state_data.get("current_wave") or "\u2014"
    flight_sub = current_wave_id if flight_info["has_flights"] else "\u2014"
    flight_pct = flight_info["pct"]
    flight_card = _render_card("flight", "Flight", flight_value, flight_sub, flight_pct)

    # --- Deferrals card ---
    u = deferral_info["pending"]
    v = deferral_info["accepted"]
    deferral_value = f"{u} pending"
    deferral_sub = f"{v} accepted"
    deferral_pct = deferral_info["pct"]
    deferral_card = _render_card(
        "deferrals", "Deferrals", deferral_value, deferral_sub, deferral_pct
    )

    cards = "\n".join([phase_card, wave_card, flight_card, deferral_card])
    return f'<div class="gauge-grid">\n{cards}\n</div>'
