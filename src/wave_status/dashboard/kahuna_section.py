"""Dashboard Kahuna section component.

Renders the "Kahuna" block for the wave-status dashboard:
- active ``kahuna_branch`` display with merged/pending flight counts
- trust-signal summary block when ``action == gate_evaluating``
- signal-failure detail block when ``action == gate_blocked``
- ``kahuna_branches`` history table (collapsible, last 10 entries)

Devspec references: §5.1.4 (schema), §5.2.5 (CLI/dashboard render), R-17/R-18,
MV-02/MV-03.

Pure presentation — takes parsed state/flights dicts and returns an HTML
string. Returns an empty string when no Kahuna context is present so the
legacy (non-KAHUNA) dashboard stays visually identical.

No imports outside Python 3.10+ stdlib and wave_status internals [CT-01].
"""

from __future__ import annotations

import html as _html


# Maximum number of history rows rendered before the table collapses.  The
# spec calls for "last 10 entries" (devspec §5.2.5).
_HISTORY_LIMIT = 10


def _flight_counts(flights_data: dict, current_wave: str | None) -> tuple[int, int]:
    """Return ``(merged, pending)`` flight counts for *current_wave*.

    "merged" here means a flight whose status is ``completed`` — the CLI's
    existing vocabulary for a flight whose PRs have been merged (see
    ``state.flight_done``).  Anything else that isn't ``completed`` counts as
    "pending" (pending, running, or any future intermediate status).
    """
    if current_wave is None:
        return (0, 0)
    wave_flights = flights_data.get("flights", {}).get(current_wave, [])
    merged = 0
    pending = 0
    for fl in wave_flights:
        if fl.get("status") == "completed":
            merged += 1
        else:
            pending += 1
    return (merged, pending)


def _render_trust_signals(state_data: dict) -> str:
    """Render the trust-signal summary block for ``action == gate_evaluating``.

    The summary lists which signals are currently being evaluated.  The list
    comes from ``current_action.detail.signals`` when present (a list of
    strings); otherwise falls back to the four canonical signals from
    devspec §5.2.2 step 4.
    """
    current_action = state_data.get("current_action") or {}
    detail = current_action.get("detail")

    signals: list[str] = []
    if isinstance(detail, dict):
        raw = detail.get("signals")
        if isinstance(raw, list):
            signals = [str(s) for s in raw]
    if not signals:
        # Canonical four signals per devspec §5.2.2 step 4 / §4.4.4 detection.
        signals = [
            "commutativity_verify",
            "ci_wait_run",
            "code-reviewer",
            "trivy vuln scan",
        ]

    items = "\n".join(
        f"    <li>{_html.escape(s)}</li>" for s in signals
    )
    return (
        '  <div class="kahuna-trust-signals">\n'
        '    <h3>Trust signals evaluating</h3>\n'
        '    <ul class="kahuna-signal-list">\n'
        f"{items}\n"
        "    </ul>\n"
        "  </div>"
    )


def _render_signal_failures(state_data: dict) -> str:
    """Render the signal-failure detail block for ``action == gate_blocked``.

    Reads ``current_action.detail.failures`` — a list of either plain strings
    or dicts shaped ``{"signal": "...", "reason": "..."}``.  Falls back to
    rendering the raw detail string when that structure isn't present, so
    older callers that stuff a free-form message into ``detail`` still get
    something visible.
    """
    current_action = state_data.get("current_action") or {}
    detail = current_action.get("detail")

    failure_items: list[str] = []
    if isinstance(detail, dict):
        raw = detail.get("failures")
        if isinstance(raw, list):
            for entry in raw:
                if isinstance(entry, dict):
                    signal = _html.escape(str(entry.get("signal", "")))
                    reason = _html.escape(str(entry.get("reason", "")))
                    text = f"<strong>{signal}</strong>"
                    if reason:
                        text = f"{text}: {reason}"
                    failure_items.append(text)
                else:
                    failure_items.append(_html.escape(str(entry)))
    elif isinstance(detail, str) and detail:
        failure_items.append(_html.escape(detail))

    if not failure_items:
        failure_items.append("Gate blocked — see wave state for details.")

    items_html = "\n".join(
        f"    <li>{item}</li>" for item in failure_items
    )
    return (
        '  <div class="kahuna-signal-failures">\n'
        '    <h3>Gate blocked — failing signals</h3>\n'
        '    <ul class="kahuna-signal-list">\n'
        f"{items_html}\n"
        "    </ul>\n"
        "  </div>"
    )


def _render_history_table(state_data: dict) -> str:
    """Render the ``kahuna_branches`` history table (collapsible, last 10).

    Missing optional fields (``main_merge_sha``, ``abort_reason``) are
    tolerated — their columns render as an em-dash placeholder.
    """
    history = state_data.get("kahuna_branches")
    if not isinstance(history, list) or not history:
        return ""

    # Take the most recent N entries; order preserved as written (the
    # orchestrator appends chronologically per devspec §5.1.4 schema).
    rows_src = history[-_HISTORY_LIMIT:]

    rows: list[str] = []
    for entry in rows_src:
        if not isinstance(entry, dict):
            continue
        branch = _html.escape(str(entry.get("branch", "")))
        epic_id = _html.escape(str(entry.get("epic_id", "")))
        created_at = _html.escape(str(entry.get("created_at", "")))
        resolved_at = _html.escape(str(entry.get("resolved_at", "")))
        disposition = str(entry.get("disposition", ""))
        disposition_html = _html.escape(disposition) if disposition else "—"
        disposition_class = (
            f"disposition-{_html.escape(disposition)}" if disposition else ""
        )
        # Optional fields — render an em-dash when missing.
        merge_sha = entry.get("main_merge_sha")
        merge_sha_html = _html.escape(str(merge_sha)) if merge_sha else "—"
        abort_reason = entry.get("abort_reason")
        abort_reason_html = (
            _html.escape(str(abort_reason)) if abort_reason else "—"
        )
        rows.append(
            "      <tr>\n"
            f"        <td>{branch}</td>\n"
            f"        <td>{epic_id}</td>\n"
            f"        <td>{created_at}</td>\n"
            f"        <td>{resolved_at}</td>\n"
            f'        <td class="{disposition_class}">{disposition_html}</td>\n'
            f"        <td>{merge_sha_html}</td>\n"
            f"        <td>{abort_reason_html}</td>\n"
            "      </tr>"
        )

    if not rows:
        return ""

    header = (
        "<thead><tr>"
        "<th>Branch</th>"
        "<th>Epic</th>"
        "<th>Created</th>"
        "<th>Resolved</th>"
        "<th>Disposition</th>"
        "<th>Merge SHA</th>"
        "<th>Abort reason</th>"
        "</tr></thead>"
    )
    return (
        '  <details class="kahuna-history">\n'
        f"    <summary>Kahuna history ({len(rows)} / {len(history)} entries)</summary>\n"
        '    <table class="kahuna-history-table">\n'
        f"      {header}\n"
        "      <tbody>\n"
        + "\n".join(rows)
        + "\n      </tbody>\n"
        "    </table>\n"
        "  </details>"
    )


def render_kahuna_section(state_data: dict, flights_data: dict) -> str:
    """Render the full Kahuna section.

    Returns an empty string when the state has no Kahuna context at all
    (no active ``kahuna_branch`` AND no ``kahuna_branches`` history).
    Legacy non-KAHUNA state files produce no output so the existing
    dashboard layout is unaffected.
    """
    kahuna_branch = state_data.get("kahuna_branch")
    history = state_data.get("kahuna_branches")
    has_history = isinstance(history, list) and len(history) > 0

    if not kahuna_branch and not has_history:
        return ""

    action_obj = state_data.get("current_action") or {}
    action_key = action_obj.get("action", "")

    parts: list[str] = ['<div class="kahuna-section">']
    parts.append("  <h2>Kahuna</h2>")

    if kahuna_branch:
        branch_html = _html.escape(str(kahuna_branch))
        parts.append(
            f'  <div class="kahuna-branch">Active branch: '
            f"<code>{branch_html}</code></div>"
        )
        current_wave = state_data.get("current_wave")
        merged, pending = _flight_counts(flights_data, current_wave)
        parts.append(
            f'  <div class="kahuna-counts">'
            f"Flights: {merged} merged, {pending} pending"
            "</div>"
        )
    else:
        # Only history is present (epic completed, cleaned up) — still show
        # the header so the history table has context.
        parts.append(
            '  <div class="kahuna-counts">No active Kahuna branch.</div>'
        )

    # Action-conditional blocks (MV-03).
    if action_key == "gate_evaluating":
        parts.append(_render_trust_signals(state_data))
    elif action_key == "gate_blocked":
        parts.append(_render_signal_failures(state_data))

    if has_history:
        history_html = _render_history_table(state_data)
        if history_html:
            parts.append(history_html)

    parts.append("</div>")
    return "\n".join(parts)
