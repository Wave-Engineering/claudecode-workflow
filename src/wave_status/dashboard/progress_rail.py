"""Progress rail renderer for the wave status dashboard.

Renders the full-width segmented bar showing global issue completion
with phase-colored segments.  Pure presentation — receives data dicts,
returns an HTML string.

No imports outside Python 3.10+ stdlib  [CT-01].
"""

from __future__ import annotations

from wave_status.dashboard.theme import PHASE_COLORS


def render_progress_rail(phases_data: dict, state_data: dict) -> str:
    """Render the full-width progress rail HTML.

    Parameters
    ----------
    phases_data:
        The plan structure — a dict with a ``phases`` list.  Each phase
        has a ``waves`` list; each wave has an ``issues`` list of dicts
        with at minimum a ``number`` key.

    state_data:
        The runtime state dict with an ``issues`` sub-dict mapping
        string issue numbers to ``{"status": "open" | "closed"}``.

    Returns
    -------
    str
        Self-contained HTML ``<div class="progress-rail">`` block.
    """
    phases: list[dict] = phases_data.get("phases", [])
    issues_state: dict[str, dict] = state_data.get("issues", {})

    # ------------------------------------------------------------------
    # Compute global totals across all phases
    # ------------------------------------------------------------------
    total_issues = 0
    total_closed = 0

    for phase in phases:
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                total_issues += 1
                if issues_state.get(str(issue["number"]), {}).get("status") == "closed":
                    total_closed += 1

    pct = round(100 * total_closed / total_issues) if total_issues else 0
    text = f"{total_closed}/{total_issues} issues ({pct}%)"

    # ------------------------------------------------------------------
    # Build phase segment HTML
    # ------------------------------------------------------------------
    segments_html: list[str] = []

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

        # Proportional width as percentage of total issues [R-20]
        width_pct = (phase_total / total_issues * 100) if total_issues else 0

        # Color cycle fuchsia → cyan → green → yellow mod 4  [R-22]
        color = PHASE_COLORS[phase_index % 4]
        completed_color = color["completed"]
        remaining_color = color["remaining"]

        # Completed fill width as a percentage *within* this segment
        completed_pct = (phase_closed / phase_total * 100) if phase_total else 0
        remaining_pct = 100.0 - completed_pct

        phase_label = f"phase-{phase_index + 1}"

        # Completed (solid) fill  [R-21]
        # data-bind-width gives the polling JS a dotted path into
        # state.rail.<phase>.completed_pct so the live cycle can update
        # the segment's width.  The legacy bare data-field="fill" was a
        # silent no-op (issue #447).
        completed_fill = (
            f'<div class="segment" '
            f'data-rail-phase="{phase_label}" '
            f'data-bind-width="rail.{phase_label}.completed_pct" '
            f'style="width:{completed_pct:.4f}%;'
            f'background:{completed_color};'
            f'flex-shrink:0;"></div>'
        )

        # Remaining (faded) fill  [R-21]
        remaining_fill = (
            f'<div class="segment" '
            f'data-rail-phase="{phase_label}" '
            f'data-bind-width="rail.{phase_label}.remaining_pct" '
            f'style="width:{remaining_pct:.4f}%;'
            f'background:{remaining_color};'
            f'flex-shrink:0;"></div>'
        )

        # Segment wrapper whose width is proportional to phase size  [R-20]
        segment_html = (
            f'<div class="segment" '
            f'data-rail-phase="{phase_label}" '
            f'style="width:{width_pct:.4f}%;display:flex;overflow:hidden;">'
            f"{completed_fill}"
            f"{remaining_fill}"
            f"</div>"
        )
        segments_html.append(segment_html)

    bar_html = "\n    ".join(segments_html)

    return (
        '<div class="progress-rail">\n'
        f'  <div class="text">{text}</div>\n'
        '  <div class="bar">\n'
        f"    {bar_html}\n"
        "  </div>\n"
        "</div>"
    )
