"""Dashboard generator: assembles all components into a complete HTML document.

Imports all dashboard components and composes them into a self-contained
HTML page with inline CSS and JS.  Also renders the header, action banner,
and footer directly (small enough not to need their own modules).

No imports outside Python 3.10+ stdlib (except wave_status internals) [CT-01].
"""

from __future__ import annotations

import html as _html
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from wave_status.dashboard.deferral_sections import (
    render_accepted_deferrals,
    render_pending_deferrals,
)
from wave_status.dashboard.execution_grid import render_execution_grid
from wave_status.dashboard.gauge_cards import render_gauge_cards
from wave_status.dashboard.kahuna_section import render_kahuna_section
from wave_status.dashboard.polling import render_polling_script
from wave_status.dashboard.progress_rail import render_progress_rail
from wave_status.dashboard.theme import ACTION_BANNER_STATES, render_base_css
from wave_status.state import html_path, status_dir


def _render_header(phases_data: dict, state_data: dict) -> str:
    """Render the dashboard header with project name and current wave.

    Only renders fields that exist in the current data schema.
    ``base_branch`` and ``master_issue`` are deferred to Wave 4.
    """
    project = _html.escape(str(phases_data.get("project", "Unknown Project")))
    current_wave = _html.escape(str(state_data.get("current_wave", "")))

    meta_parts: list[str] = []
    if current_wave:
        meta_parts.append(f"Wave: {current_wave}")

    meta_html = " | ".join(meta_parts) if meta_parts else ""

    return (
        '<div class="header">\n'
        f"  <h1>{project}</h1>\n"
        f'  <div class="meta">{meta_html}</div>\n'
        "</div>"
    )


def _render_action_banner(state_data: dict) -> str:
    """Render the action banner based on ``current_action`` state.

    ``current_action`` is a dict with keys ``action``, ``label``, ``detail``.
    Returns an empty string if ``current_action`` is ``None`` or missing.
    """
    current_action = state_data.get("current_action")
    if current_action is None:
        return ""

    action_key = current_action.get("action", "")
    if not action_key:
        return ""

    banner_state = ACTION_BANNER_STATES.get(action_key)
    if banner_state is None:
        return ""

    # icon and css_class come from the internal ACTION_BANNER_STATES constant
    # in theme.py — they are trusted HTML entities and CSS class names
    # respectively, intentionally NOT escaped.
    icon = banner_state["icon"]
    css_class = banner_state["css_class"]

    label = _html.escape(str(current_action.get("label", "")))
    detail = _html.escape(str(current_action.get("detail", "")))

    detail_html = ""
    if detail:
        detail_html = f'<span class="message">{detail}</span>'

    return (
        f'<div class="action-banner {css_class}" data-action-banner>\n'
        f'  <span class="icon">{icon}</span>\n'
        f'  <span class="label">{label}</span>\n'
        f"  {detail_html}\n"
        "</div>"
    )


def _render_footer(state_data: dict) -> str:
    """Render the footer with generation timestamp and last-update timestamp."""
    gen_time = _html.escape(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    last_updated = _html.escape(str(state_data.get("last_updated", "")))

    return (
        '<div class="footer">\n'
        f'  <div>Generated: {gen_time}</div>\n'
        f'  <div data-timestamp>Last state update: {last_updated}</div>\n'
        '  <div class="fallback-notice" data-fallback-notice></div>\n'
        "</div>"
    )


def generate_dashboard(
    root: Path,
    phases_data: dict,
    state_data: dict,
    flights_data: dict,
) -> Path:
    """Assemble and write the complete HTML dashboard.

    Parameters
    ----------
    root:
        Project root directory.  The HTML file is written to
        ``html_path(root)``.
    phases_data:
        The parsed phases-waves.json dict (project plan structure).
    state_data:
        The parsed state.json dict (runtime state).
    flights_data:
        The parsed flights.json dict (flight plan).

    Returns
    -------
    Path
        The path the HTML was written to.
    """
    css = render_base_css()
    header = _render_header(phases_data, state_data)
    banner = _render_action_banner(state_data)
    kahuna = render_kahuna_section(state_data, flights_data)
    rail = render_progress_rail(phases_data, state_data)
    gauges = render_gauge_cards(phases_data, state_data, flights_data)
    pending_deferrals = render_pending_deferrals(state_data)
    grid = render_execution_grid(phases_data, state_data, flights_data)
    accepted_deferrals = render_accepted_deferrals(state_data)
    footer = _render_footer(state_data)
    # Polling URL is the path FROM the HTML's directory TO state.json. Both
    # paths use the same status_dir resolution, so this is just the relative
    # path between them. POSIX separators because the URL lives in a browser
    # `fetch()`, not in fs APIs.
    state_rel = os.path.relpath(
        status_dir(root) / "state.json",
        start=html_path(root).parent,
    ).replace(os.sep, "/")
    script = render_polling_script(state_rel)

    # Kahuna section sits between the action banner and the progress rail
    # when present.  Legacy state files (no kahuna_branch / kahuna_branches)
    # produce an empty string — we drop an empty line to keep output tidy.
    kahuna_block = f"{kahuna}\n" if kahuna else ""

    html_content = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "  <title>Wave Status Dashboard</title>\n"
        "  <style>\n"
        f"{css}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="container">\n'
        f"{header}\n"
        f"{banner}\n"
        f"{kahuna_block}"
        f"{rail}\n"
        f"{gauges}\n"
        f"{pending_deferrals}\n"
        f"{grid}\n"
        f"{accepted_deferrals}\n"
        f"{footer}\n"
        "</div>\n"
        f"{script}\n"
        "</body>\n"
        "</html>\n"
    )

    # Atomic write: tempfile + os.replace [R-33]
    out_path = html_path(root)
    parent = out_path.parent
    parent.mkdir(parents=True, exist_ok=True)

    fd = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(parent),
        suffix=".tmp",
        delete=False,
    )
    try:
        fd.write(html_content)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(fd.name, str(out_path))
    except BaseException:
        fd.close()
        try:
            os.unlink(fd.name)
        except OSError:
            pass
        raise

    return out_path
