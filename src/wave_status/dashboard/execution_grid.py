"""Dashboard execution grid component.

Renders the main body of the dashboard: phase sections containing wave cards
with issue tables and flight badges.

Pure presentation — receives data dicts, returns HTML string.

No imports outside Python 3.10+ stdlib [CT-01].
"""

from __future__ import annotations

import html as _html

from wave_status.dashboard.theme import PHASE_COLORS
from wave_status.state import future_issue_key, resolve_issue_key, wave_flight_list


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
    wave_flights = wave_flight_list(flights_data, wave_id)
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


def _row_key(bag: dict, num: int, plan_data: dict | None, issue_plan: dict) -> str:
    """Resolve *num*'s key in *bag* for THIS ROW, preferring its own
    repo-qualified key over resolve_issue_key's context-free scan.

    cc-workflow#1173 code review: resolve_issue_key has no notion of which
    repo the CURRENT row belongs to — it returns the FIRST ``#N`` match in
    insertion order. A cross-repo plan can legitimately repeat an issue
    number across repos (state.py's ``_wave_work_item_counts`` docstring), so
    a blind scan can resolve a row to a DIFFERENT repo's same-numbered issue
    — silently binding this row's cell, and now its data-field, to someone
    else's data. Bare-exact-match still wins first, matching
    resolve_issue_key's own precedence (back-compat with pre-v3 state); only
    the ambiguous-scan case is disambiguated, using information only the
    caller has: which issue_plan this row is actually rendering.
    """
    bare = str(num)
    if bare in bag:
        return bare
    fk = future_issue_key(plan_data, issue_plan, num)
    if fk in bag:
        return fk
    return resolve_issue_key(bag, num) or fk


def _render_issue_row(
    issue_number: int,
    issue_plan: dict,
    state_data: dict,
    wave_id: str,
    plan_data: dict | None = None,
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
    plan_data:
        The full parsed phases-waves.json dict, used only to compose the
        repo-qualified key a not-yet-written entry WOULD get
        (:func:`future_issue_key`). Optional — falls back to a bare-number
        guess when omitted (matches pre-#1173 behavior).
    """
    title = _html.escape(issue_plan.get("title", f"Issue #{issue_number}"))
    # #1160: dual-read via _row_key (resolve_issue_key + future_issue_key),
    # not a bare-key lookup — a repo-qualified plan (#198/#1157/#1158)
    # composes state keys as "owner/repo#N", and a bare lookup here silently
    # falls through to the default (issue_state={}, status="open") for every
    # issue in such a plan, exactly like the mr_urls gap below (same
    # function, same root cause).
    #
    # #1173: data-field bakes the ACTUAL RESOLVED key (_row_key), not the
    # bare issue_number — the dashboard's client-side poller (polling.py)
    # does a literal dotted-path lookup against state.json with no bare/
    # qualified fallback of its own, so a data-field naming the bare number
    # for a qualified-key plan would render correctly ONCE at page load, then
    # never live-update again (the poll's lookup would always miss). Baking
    # the resolved key here means the server always emits the exact path the
    # client needs, with no client-side change required. _row_key falls back
    # to future_issue_key (code review) when nothing resolves yet, NOT a bare
    # guess — a bare guess disagrees with what record_mr/close_issue will
    # actually compose the moment a repo-qualified write lands, which is the
    # exact "renders once, never live-updates again" bug #1173 exists to fix,
    # just moved one step later (see future_issue_key's docstring). _row_key
    # also disambiguates a cross-repo same-number collision by preferring
    # THIS row's own future key — see _row_key's own docstring.
    #
    # Known gap, filed as #1180: baking the resolved key in verbatim means a
    # repo name containing a literal "." (legal on GitHub, unused by this
    # fleet today) breaks polling.py's naive path.split(".") client-side —
    # the same never-live-updates symptom, on a shape #1173 doesn't cover.
    issues_bag = state_data.get("issues", {})
    issue_key = _row_key(issues_bag, issue_number, plan_data, issue_plan)
    issue_state = issues_bag.get(issue_key, {})
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

    issue_key_attr = _html.escape(issue_key, quote=True)
    status_badge = (
        f'<span class="badge {_html.escape(badge_css)}"'
        f' data-wave="{wid}"'
        f' data-issue="{issue_number}"'
        f' data-field="issues.{issue_key_attr}.status">{_html.escape(badge_label)}</span>'
    )

    # MR link — from the rendered wave's mr_urls. #1160: dual-read, same reason as
    # issue_state above — record_mr composes a qualified key for repo-tagged
    # plans, and a bare lookup here would leave the MR-link column dark.
    #
    # #1173: resolved SEPARATELY from issue_key above — mr_urls and issues are
    # different dicts, and while they're composed under the same repo in
    # practice, nothing guarantees they resolve to an identical key, so each
    # data-field must name the key it actually reads from, not borrow the
    # other cell's. Same future_issue_key fallback as issue_key, for the same
    # reason — mr_urls starts EMPTY from init_state (unlike issues, which
    # init_state pre-populates with qualified keys), so this fallback is the
    # NORMAL case here, not an edge case: the dashboard renders before any MR
    # exists, then record_mr writes a qualified key later.
    mr_urls = state_data.get("waves", {}).get(wave_id, {}).get("mr_urls", {})
    mr_key = _row_key(mr_urls, issue_number, plan_data, issue_plan)
    mr_key_attr = _html.escape(mr_key, quote=True)
    mr_url = mr_urls.get(mr_key, "")
    if mr_url:
        mr_cell = (
            f'<a href="{_html.escape(mr_url, quote=True)}"'
            f' data-wave="{wid}"'
            f' data-issue="{issue_number}"'
            f' data-field="waves.{wid}.mr_urls.{mr_key_attr}">{_html.escape(mr_url)}</a>'
        )
    else:
        mr_cell = (
            f'<span class="mr-link" data-wave="{wid}"'
            f' data-issue="{issue_number}"'
            f' data-field="waves.{wid}.mr_urls.{mr_key_attr}"></span>'
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
    plan_data: dict | None = None,
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
    plan_data:
        The full parsed phases-waves.json dict — threaded down to
        ``_render_issue_row`` for ``future_issue_key``. See its docstring.
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
            rows.append(
                _render_issue_row(issue_number, issue_plan, state_data, wave_id, plan_data)
            )

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
    plan_data: dict | None = None,
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
    plan_data:
        The full parsed phases-waves.json dict — threaded down to
        ``_render_issue_row`` for ``future_issue_key``. See its docstring.
    """
    phase_name = _html.escape(phase.get("name", f"Phase {phase_index + 1}"))
    waves = phase.get("waves", [])
    color_entry = PHASE_COLORS[phase_index % len(PHASE_COLORS)]
    accent_color = f"var({color_entry['var']})"

    wave_cards = "\n".join(
        _render_wave_card(wave_plan, state_data, flights_data, plan_data)
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
        _render_phase_section(phase, pi, state_data, flights_data, phases_data)
        for pi, phase in enumerate(phases)
    )
    return f'<div class="execution-grid">\n{sections}\n</div>'
