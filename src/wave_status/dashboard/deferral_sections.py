"""Dashboard deferral sections component.

Renders the pending and accepted deferral tables.

Pure presentation — receives state_data dict, returns HTML string.

No imports outside Python 3.10+ stdlib [CT-01].
"""

from __future__ import annotations

import html as _html

from wave_status.deferrals import accepted_list, pending_list


def render_pending_deferrals(state_data: dict) -> str:
    """Render the pending deferrals section as an HTML string.

    The container collapses to zero height (``overflow: hidden; max-height: 0``)
    when no pending items exist [R-25].  When items exist, the section uses
    orange-accented styling.

    Parameters
    ----------
    state_data:
        The parsed state.json dict. Must contain a ``deferrals`` list.

    Returns
    -------
    str
        An HTML ``<div class="deferrals-section pending">`` block.
    """
    items = pending_list(state_data)

    # Collapse to zero height when empty [R-25].
    if not items:
        collapse_style = ' style="overflow: hidden; max-height: 0; padding: 0; margin: 0;"'
        table_html = ""
    else:
        collapse_style = ""
        rows: list[str] = []
        for i, deferral in enumerate(items, start=1):
            wave = _html.escape(deferral.get("wave", ""))
            description = _html.escape(deferral.get("description", ""))
            risk = _html.escape(deferral.get("risk", ""))
            rows.append(
                f"<tr>\n"
                f"  <td>{i}</td>\n"
                f"  <td>{wave}</td>\n"
                f"  <td>{description}</td>\n"
                f"  <td>{risk}</td>\n"
                f"</tr>"
            )

        table_html = (
            '<table class="deferrals-table">\n'
            "<thead><tr>"
            "<th>#</th><th>Wave</th><th>Description</th><th>Risk</th>"
            "</tr></thead>\n"
            "<tbody>\n"
            + "\n".join(rows)
            + "\n</tbody>\n"
            "</table>"
        )

    return (
        f'<div class="deferrals-section pending"{collapse_style}>\n'
        f'  <h2>Pending Deferrals</h2>\n'
        f"  {table_html}\n"
        f"</div>"
    )


def render_accepted_deferrals(state_data: dict) -> str:
    """Render the accepted deferrals section as an HTML string.

    Uses subdued styling (resolved items have less visual urgency).
    Renders below the execution grid [R-26].

    Parameters
    ----------
    state_data:
        The parsed state.json dict. Must contain a ``deferrals`` list.

    Returns
    -------
    str
        An HTML ``<div class="deferrals-section accepted">`` block.
    """
    items = accepted_list(state_data)

    if not items:
        table_html = ""
    else:
        rows: list[str] = []
        for i, deferral in enumerate(items, start=1):
            wave = _html.escape(deferral.get("wave", ""))
            description = _html.escape(deferral.get("description", ""))
            risk = _html.escape(deferral.get("risk", ""))
            rows.append(
                f"<tr>\n"
                f"  <td>{i}</td>\n"
                f"  <td>{wave}</td>\n"
                f"  <td>{description}</td>\n"
                f"  <td>{risk}</td>\n"
                f"</tr>"
            )

        table_html = (
            '<table class="deferrals-table">\n'
            "<thead><tr>"
            "<th>#</th><th>Wave</th><th>Description</th><th>Risk</th>"
            "</tr></thead>\n"
            "<tbody>\n"
            + "\n".join(rows)
            + "\n</tbody>\n"
            "</table>"
        )

    return (
        f'<div class="deferrals-section accepted">\n'
        f'  <h2>Accepted Deferrals</h2>\n'
        f"  {table_html}\n"
        f"</div>"
    )
