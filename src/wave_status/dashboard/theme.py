"""Dashboard theme: CSS design tokens, action banner states, and base styles.

Pure data module — no business logic, no external dependencies.
Provides the cyberpunk dark theme specification from PRD Appendix A.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# CSS Custom Properties  [R-30]
# All tokens from PRD Appendix A
# ---------------------------------------------------------------------------

CSS_TOKENS: dict[str, str] = {
    "--bg": "#0a0a0f",
    "--surface": "#12121a",
    "--surface-2": "#1a1a26",
    "--border": "#2a2a3a",
    "--text": "#e0e0e8",
    "--text-dim": "#8888a0",
    "--fuchsia": "#ff00ff",
    "--fuchsia-dim": "#aa00aa",
    "--cyan": "#00ffff",
    "--green": "#00ff88",
    "--yellow": "#ffcc00",
    "--red": "#ff4444",
    "--orange": "#ff8800",
}

# ---------------------------------------------------------------------------
# Font stack  [R-30]
# ---------------------------------------------------------------------------

FONT_STACK = "'JetBrains Mono', 'Fira Code', 'Cascadia Code', monospace"

# ---------------------------------------------------------------------------
# Progress rail phase color cycle  [R-21, R-22]
# Phase mod 4: fuchsia -> cyan -> green -> yellow
# Each entry has full (1.0) and faded (0.2) rgba variants.
# ---------------------------------------------------------------------------

PHASE_COLORS: list[dict[str, str]] = [
    {
        "name": "fuchsia",
        "var": "--fuchsia",
        "completed": "rgba(255, 0, 255, 1.0)",
        "remaining": "rgba(255, 0, 255, 0.2)",
    },
    {
        "name": "cyan",
        "var": "--cyan",
        "completed": "rgba(0, 255, 255, 1.0)",
        "remaining": "rgba(0, 255, 255, 0.2)",
    },
    {
        "name": "green",
        "var": "--green",
        "completed": "rgba(0, 255, 136, 1.0)",
        "remaining": "rgba(0, 255, 136, 0.2)",
    },
    {
        "name": "yellow",
        "var": "--yellow",
        "completed": "rgba(255, 204, 0, 1.0)",
        "remaining": "rgba(255, 204, 0, 0.2)",
    },
]

# ---------------------------------------------------------------------------
# Action banner states  [R-30]
# All 7 states from PRD Appendix A with icon, CSS class, border color, and
# animation.
# ---------------------------------------------------------------------------

ACTION_BANNER_STATES: dict[str, dict[str, str]] = {
    "pre-flight": {
        "icon": "&#x1F50D;",
        "css_class": "action-preflight",
        "border_color": "var(--cyan)",
        "animation": "none",
    },
    "planning": {
        "icon": "&#x1F9E0;",
        "css_class": "action-planning",
        "border_color": "var(--yellow)",
        "animation": "none",
    },
    "in-flight": {
        "icon": "&#x1F680;",
        "css_class": "action-inflight",
        "border_color": "var(--fuchsia)",
        "animation": "glow 2s ease-in-out infinite",
    },
    "merging": {
        "icon": "&#x1F500;",
        "css_class": "action-merging",
        "border_color": "var(--green)",
        "animation": "none",
    },
    "post-wave-review": {
        "icon": "&#x1F50E;",
        "css_class": "action-review",
        "border_color": "var(--orange)",
        "animation": "none",
    },
    "waiting-on-meatbag": {
        "icon": "&#x1F9B4;",
        "css_class": "action-meatbag",
        "border_color": "var(--fuchsia)",
        "animation": "throb 2.5s ease-in-out infinite",
    },
    "idle": {
        "icon": "&#x1F4A4;",
        "css_class": "action-idle",
        "border_color": "var(--border)",
        "animation": "none",
    },
    # Kahuna trust-score gate evaluating — pulsing yellow to signal active
    # concurrent scoring (devspec §5.1.4, §5.2.5; R-23, MV-03).
    "gate_evaluating": {
        "icon": "&#x1F6A6;",  # vertical traffic light
        "css_class": "action-gate-evaluating",
        "border_color": "var(--yellow)",
        "animation": "pulse 1.5s ease-in-out infinite",
    },
    # Kahuna trust-score gate blocked — red emphasis, one or more signals
    # failed (devspec §5.1.4, §5.2.5; R-23, MV-03). Also gets an outer throb
    # so the blocked state reads clearly against the other red failure cues.
    "gate_blocked": {
        "icon": "&#x1F6D1;",  # stop sign
        "css_class": "action-gate-blocked",
        "border_color": "var(--red)",
        "animation": "throb 2.5s ease-in-out infinite",
    },
}


def render_base_css() -> str:
    """Return complete ``<style>`` content for the dashboard.

    Includes:
    - CSS custom properties (all tokens from Appendix A)
    - Font stack
    - Base layout (body, container)
    - Card styles (gauge cards, execution grid)
    - Badge styles (status badges)
    - Action banner classes with animations (throb, glow)
    """
    # Build custom properties block
    props = "\n".join(f"    {token}: {value};" for token, value in CSS_TOKENS.items())

    # Build action banner CSS classes
    banner_classes: list[str] = []
    for action, state in ACTION_BANNER_STATES.items():
        cls = state["css_class"]
        border = state["border_color"]
        anim = state["animation"]
        anim_line = (
            f"    animation: {anim};" if anim != "none" else "    animation: none;"
        )
        banner_classes.append(
            f".{cls} {{\n"
            f"    border-left: 4px solid {border};\n"
            f"{anim_line}\n"
            f"}}"
        )

    banner_css = "\n\n".join(banner_classes)

    return f"""\
:root {{
{props}
    --font-stack: {FONT_STACK};
}}

/* === Reset & Base === */

*, *::before, *::after {{
    box-sizing: border-box;
    margin: 0;
    padding: 0;
}}

body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-stack);
    font-size: 14px;
    line-height: 1.5;
    min-height: 100vh;
}}

/* === Layout === */

.container {{
    max-width: 1200px;
    margin: 0 auto;
    padding: 24px 16px;
}}

/* === Header === */

.header {{
    text-align: center;
    margin-bottom: 24px;
}}

.header h1 {{
    font-size: 1.8rem;
    color: var(--fuchsia);
    text-shadow: 0 0 20px var(--fuchsia-dim);
    letter-spacing: 2px;
    text-transform: uppercase;
}}

.header .meta {{
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 4px;
}}

/* === Action Banner === */

.action-banner {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px 20px;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 1.1rem;
}}

.action-banner .icon {{
    font-size: 1.5rem;
}}

.action-banner .label {{
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
}}

.action-banner .message {{
    color: var(--text-dim);
    margin-left: auto;
}}

{banner_css}

/* === Animations === */

@keyframes throb {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
}}

@keyframes glow {{
    0%, 100% {{ box-shadow: 0 0 5px var(--fuchsia-dim); }}
    50% {{ box-shadow: 0 0 20px var(--fuchsia), 0 0 40px var(--fuchsia-dim); }}
}}

@keyframes pulse {{
    0%, 100% {{ box-shadow: 0 0 4px var(--yellow), inset 0 0 0 rgba(255, 204, 0, 0); }}
    50%      {{ box-shadow: 0 0 16px var(--yellow), inset 0 0 0 rgba(255, 204, 0, 0.15); }}
}}

/* === Kahuna gate emphasis (devspec §5.2.5) === */

.action-banner.action-gate-blocked {{
    background: rgba(255, 68, 68, 0.08);
}}

.action-banner.action-gate-blocked .label {{
    color: var(--red);
}}

.action-banner.action-gate-evaluating .label {{
    color: var(--yellow);
}}

/* === Progress Rail === */

.progress-rail {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 20px;
}}

.progress-rail .bar {{
    display: flex;
    height: 24px;
    border-radius: 4px;
    overflow: hidden;
}}

.progress-rail .segment {{
    height: 100%;
    transition: width 0.3s ease;
}}

.progress-rail .text {{
    text-align: center;
    margin-top: 8px;
    font-size: 0.85rem;
    color: var(--text-dim);
}}

/* === Gauge Cards === */

.gauge-grid {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 12px;
    margin-bottom: 20px;
}}

.gauge-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
}}

.gauge-card .gauge-label {{
    font-size: 0.75rem;
    color: var(--text-dim);
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 8px;
}}

.gauge-card .gauge-value {{
    font-size: 1.4rem;
    font-weight: 700;
    margin-bottom: 8px;
}}

.gauge-card .gauge-bar {{
    height: 6px;
    background: var(--surface-2);
    border-radius: 3px;
    overflow: hidden;
}}

.gauge-card .gauge-bar .gauge-fill {{
    height: 100%;
    background: var(--fuchsia);
    border-radius: 3px;
    transition: width 0.3s ease;
}}

/* === Execution Grid === */

.execution-grid {{
    margin-bottom: 20px;
}}

.phase-section {{
    margin-bottom: 16px;
}}

.phase-header {{
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: 8px 8px 0 0;
    padding: 12px 16px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1px;
    cursor: pointer;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.phase-body {{
    border: 1px solid var(--border);
    border-top: none;
    border-radius: 0 0 8px 8px;
    padding: 12px;
}}

.wave-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 6px;
    margin-bottom: 8px;
    overflow: hidden;
}}

.wave-card:last-child {{
    margin-bottom: 0;
}}

.wave-card .wave-header {{
    background: var(--surface-2);
    padding: 10px 14px;
    font-weight: 600;
    font-size: 0.9rem;
    display: flex;
    align-items: center;
    gap: 8px;
}}

.wave-card .issue-table {{
    width: 100%;
    border-collapse: collapse;
}}

.wave-card .issue-table th,
.wave-card .issue-table td {{
    padding: 8px 14px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
}}

.wave-card .issue-table th {{
    color: var(--text-dim);
    font-weight: 500;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 1px;
}}

.wave-card .issue-table tr:last-child td {{
    border-bottom: none;
}}

/* === Badges === */

.badge {{
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 0.7rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

.badge-pending {{
    background: rgba(136, 136, 160, 0.2);
    color: var(--text-dim);
}}

.badge-in-progress {{
    background: rgba(255, 0, 255, 0.2);
    color: var(--fuchsia);
}}

.badge-running {{
    background: rgba(255, 0, 255, 0.2);
    color: var(--fuchsia);
}}

.badge-completed {{
    background: rgba(0, 255, 136, 0.2);
    color: var(--green);
}}

.badge-closed {{
    background: rgba(0, 255, 136, 0.2);
    color: var(--green);
}}

.badge-failed {{
    background: rgba(255, 68, 68, 0.2);
    color: var(--red);
}}

.badge-blocked {{
    background: rgba(255, 136, 0, 0.2);
    color: var(--orange);
}}

/* === Deferrals === */

.deferrals-section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
    margin-bottom: 20px;
}}

.deferrals-section h2 {{
    font-size: 0.9rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 12px;
    color: var(--text-dim);
}}

.deferrals-section.pending {{
    border-left: 4px solid var(--orange);
}}

.deferrals-section.accepted {{
    border-left: 4px solid var(--green);
}}

.deferrals-table {{
    width: 100%;
    border-collapse: collapse;
}}

.deferrals-table th,
.deferrals-table td {{
    padding: 8px 12px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 0.85rem;
}}

.deferrals-table th {{
    color: var(--text-dim);
    font-weight: 500;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 1px;
}}

.deferrals-table tr:last-child td {{
    border-bottom: none;
}}

/* === Footer === */

.footer {{
    text-align: center;
    padding: 16px;
    color: var(--text-dim);
    font-size: 0.75rem;
    border-top: 1px solid var(--border);
    margin-top: 20px;
}}

.footer .fallback-notice {{
    color: var(--orange);
    margin-top: 8px;
    display: none;
}}

/* === Kahuna section (devspec §5.2.5) === */

.kahuna-section {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-left: 4px solid var(--cyan);
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 20px;
}}

.kahuna-section h2 {{
    font-size: 0.95rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--cyan);
    margin-bottom: 10px;
}}

.kahuna-section .kahuna-branch {{
    font-family: var(--font-stack);
    color: var(--text);
    font-size: 0.95rem;
    margin-bottom: 6px;
    word-break: break-all;
}}

.kahuna-section .kahuna-counts {{
    color: var(--text-dim);
    font-size: 0.85rem;
}}

.kahuna-trust-signals,
.kahuna-signal-failures {{
    margin-top: 12px;
    padding-top: 10px;
    border-top: 1px dashed var(--border);
}}

.kahuna-trust-signals h3,
.kahuna-signal-failures h3 {{
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--text-dim);
    margin-bottom: 6px;
}}

.kahuna-signal-failures {{
    color: var(--red);
}}

.kahuna-signal-list {{
    list-style: none;
    padding: 0;
    margin: 0;
}}

.kahuna-signal-list li {{
    padding: 3px 0;
    font-size: 0.85rem;
}}

.kahuna-history {{
    margin-top: 12px;
}}

.kahuna-history summary {{
    cursor: pointer;
    color: var(--text-dim);
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 1px;
    padding: 6px 0;
}}

.kahuna-history-table {{
    width: 100%;
    border-collapse: collapse;
    margin-top: 6px;
}}

.kahuna-history-table th,
.kahuna-history-table td {{
    padding: 6px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    font-size: 0.8rem;
}}

.kahuna-history-table th {{
    color: var(--text-dim);
    font-weight: 500;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 1px;
}}

.kahuna-history-table tr:last-child td {{
    border-bottom: none;
}}

.kahuna-history-table .disposition-merged {{
    color: var(--green);
}}

.kahuna-history-table .disposition-aborted {{
    color: var(--red);
}}

.kahuna-history-table .disposition-abandoned {{
    color: var(--orange);
}}

/* === Responsive === */

@media (max-width: 768px) {{
    .gauge-grid {{
        grid-template-columns: repeat(2, 1fr);
    }}
}}

@media (max-width: 480px) {{
    .gauge-grid {{
        grid-template-columns: 1fr;
    }}
}}"""
