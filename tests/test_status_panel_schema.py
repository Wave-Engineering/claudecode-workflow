"""Regression tests for scripts/generate-status-panel schema tolerance [#665].

The standalone status-panel script duplicates the wave_status dashboard
renderer and had drifted: it assumed phase ``name`` (the v3 schema uses
``title``) and iterated the per-wave flight value directly (crashing on the
legacy envelope shape, same family as #663). Both made the panel crash on any
real plan. These tests run the real script against a ``title``-schema plan with
an envelope-shaped flights wave and assert it renders.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "generate-status-panel"

# v3 plan: phases use `title`/`phase_id`, NOT `name`.
_PHASES = {
    "plan_id": 1,
    "project": "org/repo",
    "base_branch": "main",
    "phases": [
        {
            "phase_id": "P1",
            "title": "Phase 1: Tier 1 Runtime",
            "epic_ref": "#1",
            "waves": [
                {
                    "id": "wave-1",
                    "issues": [
                        {"number": 1, "ref": "org/repo#1", "title": "S1",
                         "branch": "feature/1-s1", "depends_on": []},
                        # Uses `depends_on` (v3), not `deps`; 99 appears nowhere
                        # else so the rendered "#99" can only come from the deps
                        # column — proving the depends_on fallback works (#665).
                        {"number": 2, "ref": "org/repo#2", "title": "S2",
                         "branch": "feature/2-s2", "depends_on": [99]},
                    ],
                },
            ],
        },
    ],
}
_STATE = {
    "current_wave": "wave-1",
    "waves": {"wave-1": {"status": "pending"}},
    "issues": {},
    "deferrals": [],
}
# wave-1 uses the legacy ENVELOPE shape (the #663 drift) — the script must
# tolerate it without crashing on `'str' object has no attribute 'get'`.
_FLIGHTS = {
    "flights": {
        "wave-1": {
            "flights": [{"issues": [1], "status": "running"}],
            "strategy": "safe",
            "conflict_count": 1,
        }
    }
}


def _write_status(tmp_path: Path) -> Path:
    status = tmp_path / ".claude" / "status"
    status.mkdir(parents=True)
    (status / "phases-waves.json").write_text(json.dumps(_PHASES), encoding="utf-8")
    (status / "state.json").write_text(json.dumps(_STATE), encoding="utf-8")
    (status / "flights.json").write_text(json.dumps(_FLIGHTS), encoding="utf-8")
    return status


def test_panel_renders_on_title_schema_and_envelope_flights(tmp_path: Path) -> None:
    status = _write_status(tmp_path)
    out = tmp_path / "panel.html"

    result = subprocess.run(
        [sys.executable, str(_SCRIPT),
         "--status-dir", str(status), "--output", str(out)],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, (
        f"panel generation failed: rc={result.returncode}\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "KeyError" not in result.stderr
    assert "has no attribute" not in result.stderr  # envelope crash guard
    html = out.read_text(encoding="utf-8")
    assert html, "panel HTML is empty"
    # Phase heading renders from `title` (not `name`).
    assert "Phase 1: Tier 1 Runtime" in html
    # The envelope-shaped wave's flight actually rendered (not silently
    # dropped) — the flights block + a flight badge are present.
    assert '<div class="flights">' in html
    assert "Flight 1" in html
    # Deps column reads `depends_on` (v3), not `deps` — "#99" can only be the
    # rendered dependency of issue #2.
    assert "#99" in html


# ENG-7/#849: v3 state.json keys .issues (and a wave's mr_urls) by the qualified ref
# owner/repo#N. The panel's per-issue lookups used a bare str(num) → every issue rendered
# "pending" even when closed+promoted. These fixtures key by qualified ref AND include the
# #119-vs-#19 false-match pair so the anchored-suffix resolver is exercised end-to-end.
_QUALIFIED_PHASES = {
    "plan_id": 2,
    "project": "org/repo",
    "base_branch": "main",
    "phases": [
        {
            "phase_id": "P1",
            "title": "Phase 1",
            "waves": [
                {
                    "id": "wave-1",
                    "issues": [
                        {"number": 19, "ref": "org/repo#19", "title": "Nineteen", "depends_on": []},
                        {"number": 119, "ref": "org/repo#119", "title": "OneNineteen", "depends_on": []},
                    ],
                },
            ],
        },
    ],
}
_QUALIFIED_STATE = {
    "current_wave": "wave-1",
    # v3 qualified keys. #119 is closed; #19 has NO entry → must stay pending (proving
    # the resolver does NOT match org/repo#119 when looking up bare #19).
    "waves": {"wave-1": {"status": "completed", "mr_urls": {"org/repo#119": "https://example.test/mr/119"}}},
    "issues": {"org/repo#119": {"status": "closed"}},
    "deferrals": [],
}
_QUALIFIED_FLIGHTS = {"flights": {"wave-1": {"flights": [{"issues": [119], "status": "completed"}]}}}


def test_panel_resolves_qualified_issue_keys(tmp_path: Path) -> None:
    status = tmp_path / ".claude" / "status"
    status.mkdir(parents=True)
    (status / "phases-waves.json").write_text(json.dumps(_QUALIFIED_PHASES), encoding="utf-8")
    (status / "state.json").write_text(json.dumps(_QUALIFIED_STATE), encoding="utf-8")
    (status / "flights.json").write_text(json.dumps(_QUALIFIED_FLIGHTS), encoding="utf-8")
    out = tmp_path / "panel.html"

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--status-dir", str(status), "--output", str(out)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"rc={result.returncode}\nstderr={result.stderr!r}"
    html = out.read_text(encoding="utf-8")

    # Anchor on the issue-number cell `#<num></td>` (unique per row; `#119</td>` never
    # contains `#19</td>`, so the anchors don't collide).
    row119 = html.split("#119</td>", 1)[1].split("</tr>", 1)[0]
    assert "closed" in row119, "qualified-keyed #119 must render closed"
    assert "https://example.test/mr/119" in row119, "qualified-keyed mr_urls must render for #119"

    # #19 has NO state entry and must NOT be dragged closed by org/repo#119 (anchored-suffix guard).
    row19 = html.split("#19</td>", 1)[1].split("</tr>", 1)[0]
    assert "closed" not in row19, "#19 must stay pending — #119 must not false-match #19"
    assert "pending" in row19, "#19 (no state entry) renders pending"
