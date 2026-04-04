"""Dashboard generator: assembles campaign status into an HTML document.

Produces a self-contained HTML page with inline CSS showing campaign
progress through SDLC stages, deferred items, and current state.

No imports outside Python 3.10+ stdlib (except campaign_status internals).
"""

from __future__ import annotations

import html as _html
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from campaign_status.state import STAGES, STAGES_WITH_REVIEW, campaign_dir


# ---------------------------------------------------------------------------
# Status styling
# ---------------------------------------------------------------------------

_STATUS_STYLES: dict[str, dict[str, str]] = {
    "not_started": {"bg": "#2d2d2d", "fg": "#888", "icon": "&#x25CB;", "label": "Not Started"},
    "active": {"bg": "#1a3a5c", "fg": "#4dabf7", "icon": "&#x25CF;", "label": "Active"},
    "review": {"bg": "#5c3a1a", "fg": "#ffa94d", "icon": "&#x25D4;", "label": "In Review"},
    "complete": {"bg": "#1a3a1a", "fg": "#51cf66", "icon": "&#x2714;", "label": "Complete"},
}


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def _render_css() -> str:
    """Return the inline CSS for the campaign dashboard."""
    return """\
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: #1a1a2e;
  color: #e0e0e0;
  padding: 2rem;
}
.container { max-width: 800px; margin: 0 auto; }
.header { margin-bottom: 2rem; }
.header h1 { font-size: 1.5rem; color: #fff; margin-bottom: 0.25rem; }
.header .meta { font-size: 0.85rem; color: #888; }
.stages { margin-bottom: 2rem; }
.stages h2 { font-size: 1.1rem; margin-bottom: 1rem; color: #ccc; }
.stage-card {
  display: flex;
  align-items: center;
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  border-radius: 6px;
  border-left: 4px solid;
}
.stage-icon { font-size: 1.1rem; margin-right: 0.75rem; }
.stage-name { flex: 1; font-weight: 500; }
.stage-status {
  font-size: 0.8rem;
  padding: 0.2rem 0.6rem;
  border-radius: 3px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.stage-review-badge {
  font-size: 0.7rem;
  color: #888;
  margin-left: 0.5rem;
}
.deferrals { margin-bottom: 2rem; }
.deferrals h2 { font-size: 1.1rem; margin-bottom: 1rem; color: #ccc; }
.deferral-card {
  padding: 0.75rem 1rem;
  margin-bottom: 0.5rem;
  background: #2d2d2d;
  border-radius: 6px;
  border-left: 4px solid #ffa94d;
}
.deferral-item { font-weight: 500; margin-bottom: 0.25rem; }
.deferral-reason { font-size: 0.85rem; color: #aaa; }
.deferral-meta { font-size: 0.75rem; color: #666; margin-top: 0.25rem; }
.footer {
  font-size: 0.75rem;
  color: #555;
  padding-top: 1rem;
  border-top: 1px solid #333;
}
.no-deferrals { color: #666; font-style: italic; }
"""


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def _render_stage_card(stage: str, status: str) -> str:
    """Render a single stage card."""
    style = _STATUS_STYLES.get(status, _STATUS_STYLES["not_started"])
    name = _html.escape(stage.replace("_", " ").title())
    if stage == "prd":
        name = "PRD"
    elif stage == "dod":
        name = "DoD"

    review_badge = ""
    if stage in STAGES_WITH_REVIEW and status != "complete":
        review_badge = '<span class="stage-review-badge">(has review gate)</span>'

    return (
        f'<div class="stage-card" style="background:{style["bg"]};border-color:{style["fg"]}">\n'
        f'  <span class="stage-icon">{style["icon"]}</span>\n'
        f'  <span class="stage-name">{name}{review_badge}</span>\n'
        f'  <span class="stage-status" style="color:{style["fg"]}">{style["label"]}</span>\n'
        f"</div>"
    )


def _render_deferral_card(deferral: dict) -> str:
    """Render a single deferral card."""
    item = _html.escape(str(deferral.get("item", "")))
    reason = _html.escape(str(deferral.get("reason", "")))
    stage = _html.escape(str(deferral.get("stage", "unknown")))
    timestamp = _html.escape(str(deferral.get("timestamp", "")))

    return (
        '<div class="deferral-card">\n'
        f'  <div class="deferral-item">{item}</div>\n'
        f'  <div class="deferral-reason">{reason}</div>\n'
        f'  <div class="deferral-meta">Stage: {stage} | {timestamp}</div>\n'
        "</div>"
    )


def generate_dashboard(
    root: Path,
    campaign_data: dict,
    state_data: dict,
    items_data: dict,
) -> Path:
    """Assemble and write the complete HTML dashboard.

    Parameters
    ----------
    root:
        Project root directory.  The HTML file is written to
        ``.sdlc/dashboard.html``.
    campaign_data:
        The parsed campaign.json dict.
    state_data:
        The parsed campaign-state.json dict.
    items_data:
        The parsed campaign-items.json dict.

    Returns
    -------
    Path
        The path the HTML was written to.
    """
    project = _html.escape(str(campaign_data.get("project", "Unknown")))
    active_stage = state_data.get("active_stage") or "none"
    stages = state_data.get("stages", {})
    last_updated = _html.escape(str(state_data.get("last_updated", "")))

    css = _render_css()

    # Stage cards
    stage_cards = "\n".join(
        _render_stage_card(s, stages.get(s, "not_started"))
        for s in STAGES
    )

    # Deferrals
    deferrals = items_data.get("deferrals", [])
    if deferrals:
        deferral_cards = "\n".join(_render_deferral_card(d) for d in deferrals)
    else:
        deferral_cards = '<div class="no-deferrals">No deferred items.</div>'

    gen_time = _html.escape(datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))

    html_content = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"  <title>Campaign Status — {project}</title>\n"
        "  <style>\n"
        f"{css}\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '<div class="container">\n'
        '  <div class="header">\n'
        f"    <h1>{project}</h1>\n"
        f'    <div class="meta">Active stage: {_html.escape(active_stage)}</div>\n'
        "  </div>\n"
        '  <div class="stages">\n'
        "    <h2>Stages</h2>\n"
        f"    {stage_cards}\n"
        "  </div>\n"
        '  <div class="deferrals">\n'
        f"    <h2>Deferred Items ({len(deferrals)})</h2>\n"
        f"    {deferral_cards}\n"
        "  </div>\n"
        '  <div class="footer">\n'
        f"    <div>Generated: {gen_time}</div>\n"
        f"    <div>Last state update: {last_updated}</div>\n"
        "  </div>\n"
        "</div>\n"
        "</body>\n"
        "</html>\n"
    )

    # Atomic write: tempfile + os.replace
    out_path = campaign_dir(root) / "dashboard.html"
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
