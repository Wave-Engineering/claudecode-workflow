"""Dashboard execution grid component.

Renders the main body of the dashboard: phase sections containing wave cards
with issue tables and flight badges.

Pure presentation — receives data dicts, returns HTML string.

No imports outside Python 3.10+ stdlib [CT-01].
"""

from __future__ import annotations

import html as _html

from wave_status.dashboard.theme import PHASE_COLORS


def _status_badge(status: str, data_wave: str = "", data_issue: str = "") -> str:
    """Return an HTML badge span for *status*.

    Parameters
    ----------
    status:
        Raw status string, e.g. ``"pending"``, ``"in_progress"``, ``"completed"``.
    data_wave:
        Optional value for a ``data-wave`` attribute.
    data_issue:
        Optional value for a ``data-issue`` attribute.
    """
    css_class = "badge-" + status.replace("_", "-")
    label = status.replace("_", " ")

    attrs = f'class="badge {_html.escape(css_class)}"'
    if data_wave:
        attrs += f' data-wave="{_html.escape(data_wave)}"'
    if data_issue:
        attrs += f' data-issue="{_html.escape(data_issue)}"'

    return f'<span {attrs}>{_html.escape(label)}</span>'


def _render_flight_badges(wave_id: str, flights_data: dict) -> str:
    """Return HTML flight badge spans for the given wave.

    Returns an empty string if no flight plan exists for *wave_id*.
    """
    wave_flights = flights_data.get("flights", {}).get(wave_id, [])
    if not wave_flights:
        return ""

    badges: list[str] = []
    wid = _html.escape(wave_id)
    for i, flight in enumerate(wave_flights, start=1):
        status = flight.get("status", "pending")
        css_class = "badge-" + status.replace("_", "-")
        label = f"flight {i}: {status.replace('_', ' ')}"
        badges.append(
            f'<span class="badge {_html.escape(css_class)}"'
            f' data-wave="{wid}"'
            f' data-field="flights.{wid}.{i - 1}.status">{_html.escape(label)}</span>'
        )

    return " ".join(badges)


def _render_issue_row(
    issue_number: int,
    issue_plan: dict,
    state_data: dict,
    wave_id: str,
) -> str:
    """Return an HTML ``<tr>`` for a single issue.

    Parameters
    ----------
    issue_number:
        The issue number (int).
    issue_plan:
        The issue dict from the plan (with ``number``, ``title``).
    state_data:
        The parsed state.json dict.
    wave_id:
        The parent wave ID, used for ``data-wave`` on dynamic elements.
    """
    title = _html.escape(issue_plan.get("title", f"Issue #{issue_number}"))
    issue_key = str(issue_number)
    issue_state = state_data.get("issues", {}).get(issue_key, {})
    status = issue_state.get("status", "open")
    wid = _html.escape(wave_id)

    # Normalize status for CSS: "open" maps to badge-pending display.
    if status == "open":
        badge_css = "badge-pending"
        badge_label = "open"
    elif status == "closed":
        badge_css = "badge-closed"
        badge_label = "closed"
    else:
        badge_css = "badge-" + status.replace("_", "-")
        badge_label = status.replace("_", " ")

    status_badge = (
        f'<span class="badge {_html.escape(badge_css)}"'
        f' data-wave="{wid}"'
        f' data-issue="{issue_number}"'
        f' data-field="issues.{issue_key}.status">{_html.escape(badge_label)}</span>'
    )

    # MR link — from current wave's mr_urls.
    mr_urls = state_data.get("waves", {}).get(wave_id, {}).get("mr_urls", {})
    mr_url = mr_urls.get(issue_key, "")
    if mr_url:
        mr_cell = (
            f'<a href="{_html.escape(mr_url, quote=True)}"'
            f' data-wave="{wid}"'
            f' data-issue="{issue_number}"'
            f' data-field="waves.{wid}.mr_urls.{issue_key}">{_html.escape(mr_url)}</a>'
        )
    else:
        mr_cell = (
            f'<span class="mr-link" data-wave="{wid}"'
            f' data-issue="{issue_number}"'
            f' data-field="waves.{wid}.mr_urls.{issue_key}"></span>'
        )

    return (
        f"<tr>\n"
        f'  <td>#{issue_number}</td>\n'
        f"  <td>{title}</td>\n"
        f"  <td>{status_badge}</td>\n"
        f"  <td>{mr_cell}</td>\n"
        f"</tr>"
    )


def _render_wave_card(
    wave_plan: dict,
    state_data: dict,
    flights_data: dict,
) -> str:
    """Return HTML for a single wave card.

    Parameters
    ----------
    wave_plan:
        Wave dict from the plan with ``id``, ``issues``.
    state_data:
        The parsed state.json dict.
    flights_data:
        The parsed flights.json dict.
    """
    wave_id = wave_plan.get("id", "")
    issues = wave_plan.get("issues", [])
    wid = _html.escape(wave_id)

    wave_state = state_data.get("waves", {}).get(wave_id, {})
    wave_status = wave_state.get("status", "pending")
    wave_css = "badge-" + wave_status.replace("_", "-")
    wave_label = wave_status.replace("_", " ")

    status_badge = (
        f'<span class="badge {_html.escape(wave_css)}"'
        f' data-wave="{wid}"'
        f' data-field="waves.{wid}.status">{_html.escape(wave_label)}</span>'
    )

    # Issue table rows.
    rows: list[str] = []
    for issue_plan in issues:
        issue_number = issue_plan.get("number")
        if issue_number is not None:
            rows.append(_render_issue_row(issue_number, issue_plan, state_data, wave_id))

    issue_table = (
        '<table class="issue-table">\n'
        "<thead><tr>"
        '<th>#</th><th>Title</th><th>Status</th><th>MR / PR</th>'
        "</tr></thead>\n"
        "<tbody>\n"
        + "\n".join(rows)
        + "\n</tbody>\n"
        "</table>"
    )

    # Flight badges (if flight plan exists for this wave).
    flight_badges_html = _render_flight_badges(wave_id, flights_data)
    flight_row = ""
    if flight_badges_html:
        flight_row = (
            f'\n<div class="flight-badges" data-wave="{wid}">'
            f"{flight_badges_html}</div>"
        )

    return (
        f'<div class="wave-card" data-wave="{wid}">\n'
        f'  <div class="wave-header">'
        f'<span class="wave-id">{wid}</span>{status_badge}'
        f"</div>\n"
        f"  {issue_table}"
        f"{flight_row}\n"
        f"</div>"
    )


def _render_phase_section(
    phase: dict,
    phase_index: int,
    state_data: dict,
    flights_data: dict,
) -> str:
    """Return HTML for a single phase section.

    Parameters
    ----------
    phase:
        Phase dict from the plan with ``name`` and ``waves``.
    phase_index:
        0-based index of this phase, used to pick phase color.
    state_data:
        The parsed state.json dict.
    flights_data:
        The parsed flights.json dict.
    """
    phase_name = _html.escape(phase.get("name", f"Phase {phase_index + 1}"))
    waves = phase.get("waves", [])
    color_entry = PHASE_COLORS[phase_index % len(PHASE_COLORS)]
    accent_color = f"var({color_entry['var']})"

    wave_cards = "\n".join(
        _render_wave_card(wave_plan, state_data, flights_data)
        for wave_plan in waves
    )

    return (
        f'<section class="phase-section" data-phase="{phase_index + 1}">\n'
        f'  <div class="phase-header" style="border-left: 4px solid {accent_color};">'
        f'<span class="phase-name">{phase_name}</span>'
        f"</div>\n"
        f'  <div class="phase-body">\n'
        f"    {wave_cards}\n"
        f"  </div>\n"
        f"</section>"
    )


def render_execution_grid(
    phases_data: dict,
    state_data: dict,
    flights_data: dict,
) -> str:
    """Render the execution grid as an HTML string.

    Parameters
    ----------
    phases_data:
        The parsed phases-waves.json dict. Must contain a ``phases`` list,
        each entry with ``name`` and ``waves`` (list of dicts with ``id`` and
        ``issues``).
    state_data:
        The parsed state.json dict. Must contain ``current_wave``, ``waves``,
        ``issues``.
    flights_data:
        The parsed flights.json dict. Must contain a ``flights`` dict keyed
        by wave ID.

    Returns
    -------
    str
        An HTML ``<div class="execution-grid">`` block containing one
        ``<section class="phase-section">`` per phase.
    """
    phases = phases_data.get("phases", [])
    sections = "\n".join(
        _render_phase_section(phase, pi, state_data, flights_data)
        for pi, phase in enumerate(phases)
    )
    return f'<div class="execution-grid">\n{sections}\n</div>'
