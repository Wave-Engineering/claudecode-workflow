"""Tests for wave_status.dashboard.kahuna_section and KAHUNA state rendering.

Exercises REAL code paths — no mocking of the module under test.
Covers AC-1 through AC-6 from issue #415 (KAHUNA devspec §5.1.4, §5.2.5).

AC-7 (zipapp build succeeds) is covered by tests/test_zipapp.py and the
``./scripts/ci/build.sh`` invocation in /precheck.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.generator import generate_dashboard
from wave_status.dashboard.kahuna_section import (
    render_kahuna_section,
    _flight_counts,
)
from wave_status.dashboard.theme import ACTION_BANNER_STATES, render_base_css


# ---------------------------------------------------------------------------
# Shared fixture data
# ---------------------------------------------------------------------------

def _legacy_state() -> dict:
    """State with NO kahuna_branch and NO kahuna_branches history.

    Backward-compat case — these fields were added additively by the
    KAHUNA devspec. Reader must parse without error (AC-1 / AC-2).
    """
    return {
        "current_wave": "wave-1",
        "current_action": {
            "action": "planning",
            "label": "planning",
            "detail": "wave-1",
        },
        "waves": {"wave-1": {"status": "in_progress", "mr_urls": {}}},
        "issues": {"1": {"status": "open"}, "2": {"status": "open"}},
        "deferrals": [],
        "last_updated": "2026-04-24T00:00:00Z",
    }


def _kahuna_state(action: str = "in-flight", detail=None) -> dict:
    """State with kahuna_branch + kahuna_branches populated.

    History includes entries with BOTH variants — one with optional fields
    present (``main_merge_sha``) and one missing them (``abort_reason``
    only) — to exercise AC-2's "tolerates missing optional fields" clause.
    """
    return {
        "current_wave": "wave-1",
        "current_action": {
            "action": action,
            "label": action,
            "detail": detail if detail is not None else "",
        },
        "waves": {"wave-1": {"status": "in_progress", "mr_urls": {}}},
        "issues": {"1": {"status": "open"}, "2": {"status": "open"}},
        "deferrals": [],
        "last_updated": "2026-04-24T00:00:00Z",
        "kahuna_branch": "kahuna/42-wave-status-cli",
        "kahuna_branches": [
            {
                "branch": "kahuna/41-prior-epic",
                "epic_id": 41,
                "created_at": "2026-04-23T10:00:00Z",
                "resolved_at": "2026-04-24T02:15:00Z",
                "disposition": "merged",
                "main_merge_sha": "abc123def456",
            },
            {
                # Missing main_merge_sha; present abort_reason.
                "branch": "kahuna/40-aborted-epic",
                "epic_id": 40,
                "created_at": "2026-04-22T08:00:00Z",
                "resolved_at": "2026-04-22T09:30:00Z",
                "disposition": "aborted",
                "abort_reason": "code_reviewer_critical_findings",
            },
            {
                # Missing BOTH optional fields.
                "branch": "kahuna/39-abandoned-epic",
                "epic_id": 39,
                "created_at": "2026-04-21T08:00:00Z",
                "resolved_at": "2026-04-21T09:30:00Z",
                "disposition": "abandoned",
            },
        ],
    }


def _kahuna_flights() -> dict:
    """Flights data with one completed flight and two non-completed."""
    return {
        "flights": {
            "wave-1": [
                {"issues": [1], "status": "completed"},
                {"issues": [2], "status": "running"},
                {"issues": [3], "status": "pending"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# AC-1 / AC-2: parser tolerates missing/optional fields
# ---------------------------------------------------------------------------


class TestLegacyStateTolerance:
    """Legacy state files without kahuna_* fields must render without error.

    Maps to AC-1 (``kahuna_branch`` absent ignored) and AC-2
    (``kahuna_branches`` array tolerated when absent).
    """

    def test_render_legacy_returns_empty(self) -> None:
        """No kahuna fields -> empty string (no output at all)."""
        html = render_kahuna_section(_legacy_state(), {"flights": {}})
        assert html == ""

    def test_legacy_state_full_dashboard_renders(self, tmp_path: Path) -> None:
        """Full generate_dashboard with legacy state must not raise."""
        phases = {
            "project": "Legacy Project",
            "phases": [
                {
                    "name": "Phase 1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "issues": [
                                {"number": 1, "title": "A"},
                                {"number": 2, "title": "B"},
                            ],
                        },
                    ],
                }
            ],
        }
        out = generate_dashboard(
            tmp_path, phases, _legacy_state(), {"flights": {}}
        )
        content = out.read_text(encoding="utf-8")
        # No kahuna section should leak into the DOM.
        assert 'class="kahuna-section"' not in content
        # But the rest of the dashboard is intact.
        assert "<!DOCTYPE html>" in content
        assert "Legacy Project" in content


class TestMissingOptionalFields:
    """``kahuna_branches`` entries may omit ``main_merge_sha`` or
    ``abort_reason`` — rendering must tolerate their absence (AC-2)."""

    def test_missing_main_merge_sha_renders(self) -> None:
        state = {
            "kahuna_branches": [
                {
                    "branch": "kahuna/1-x",
                    "epic_id": 1,
                    "created_at": "2026-04-22T08:00:00Z",
                    "resolved_at": "2026-04-22T09:30:00Z",
                    "disposition": "aborted",
                    "abort_reason": "manual_abandon",
                },
            ],
        }
        html = render_kahuna_section(state, {"flights": {}})
        assert "kahuna/1-x" in html
        assert "manual_abandon" in html
        # A missing main_merge_sha renders as an em-dash placeholder.
        assert "—" in html

    def test_missing_abort_reason_renders(self) -> None:
        state = {
            "kahuna_branches": [
                {
                    "branch": "kahuna/2-y",
                    "epic_id": 2,
                    "created_at": "2026-04-22T08:00:00Z",
                    "resolved_at": "2026-04-22T09:30:00Z",
                    "disposition": "merged",
                    "main_merge_sha": "deadbeef",
                },
            ],
        }
        html = render_kahuna_section(state, {"flights": {}})
        assert "kahuna/2-y" in html
        assert "deadbeef" in html

    def test_both_optional_fields_missing_renders(self) -> None:
        state = {
            "kahuna_branches": [
                {
                    "branch": "kahuna/3-z",
                    "epic_id": 3,
                    "created_at": "2026-04-22T08:00:00Z",
                    "resolved_at": "2026-04-22T09:30:00Z",
                    "disposition": "abandoned",
                },
            ],
        }
        html = render_kahuna_section(state, {"flights": {}})
        assert "kahuna/3-z" in html
        assert "abandoned" in html


# ---------------------------------------------------------------------------
# AC-3: new action values rendered with emoji/label
# ---------------------------------------------------------------------------


class TestGateActionStates:
    """``gate_evaluating`` and ``gate_blocked`` are registered in
    ACTION_BANNER_STATES with emoji + css_class + animation (AC-3)."""

    def test_gate_evaluating_registered(self) -> None:
        assert "gate_evaluating" in ACTION_BANNER_STATES
        state = ACTION_BANNER_STATES["gate_evaluating"]
        # An icon (hex HTML entity, same style as existing "🧠 PLANNING").
        assert state["icon"].startswith("&#x")
        assert state["css_class"] == "action-gate-evaluating"
        # Pulsing per devspec §5.2.5 ("pulsing?").
        assert "pulse" in state["animation"]

    def test_gate_blocked_registered(self) -> None:
        assert "gate_blocked" in ACTION_BANNER_STATES
        state = ACTION_BANNER_STATES["gate_blocked"]
        assert state["icon"].startswith("&#x")
        assert state["css_class"] == "action-gate-blocked"
        # Red-emphasis border color (devspec §5.2.5).
        assert state["border_color"] == "var(--red)"

    def test_gate_evaluating_css_class_in_base_css(self) -> None:
        css = render_base_css()
        assert ".action-gate-evaluating" in css
        assert "@keyframes pulse" in css

    def test_gate_blocked_css_class_has_red_emphasis(self) -> None:
        css = render_base_css()
        # Either a dedicated override block or border color references --red.
        assert ".action-gate-blocked" in css
        assert "var(--red)" in css


# ---------------------------------------------------------------------------
# AC-4: CLI/dashboard includes Kahuna section when kahuna_branch present
# ---------------------------------------------------------------------------


class TestKahunaSectionPresence:
    """AC-4: Kahuna section renders when kahuna_branch is set."""

    def test_renders_kahuna_header(self) -> None:
        html = render_kahuna_section(_kahuna_state(), _kahuna_flights())
        assert '<div class="kahuna-section">' in html
        assert "<h2>Kahuna</h2>" in html

    def test_renders_active_branch(self) -> None:
        html = render_kahuna_section(_kahuna_state(), _kahuna_flights())
        assert "kahuna/42-wave-status-cli" in html

    def test_renders_flight_counts(self) -> None:
        """One completed flight, two non-completed -> "1 merged, 2 pending"."""
        html = render_kahuna_section(_kahuna_state(), _kahuna_flights())
        assert "1 merged, 2 pending" in html

    def test_no_active_branch_but_history_still_shows_header(self) -> None:
        """Epic complete, branch cleaned — history-only case still shows
        the section so operators can see the audit trail."""
        state = _kahuna_state()
        state["kahuna_branch"] = None
        html = render_kahuna_section(state, _kahuna_flights())
        assert '<div class="kahuna-section">' in html
        assert "No active Kahuna branch" in html
        assert "kahuna/41-prior-epic" in html


class TestFlightCountHelper:
    """``_flight_counts`` partitions flight statuses by completion."""

    def test_none_wave_returns_zero_zero(self) -> None:
        assert _flight_counts({"flights": {}}, None) == (0, 0)

    def test_unknown_wave_returns_zero_zero(self) -> None:
        flights = {"flights": {"other": [{"status": "completed"}]}}
        assert _flight_counts(flights, "wave-1") == (0, 0)

    def test_mixed_statuses(self) -> None:
        flights = {
            "flights": {
                "wave-1": [
                    {"status": "completed"},
                    {"status": "completed"},
                    {"status": "running"},
                    {"status": "pending"},
                ],
            },
        }
        assert _flight_counts(flights, "wave-1") == (2, 2)


# ---------------------------------------------------------------------------
# AC-5: Dashboard HTML renders new fields per MV-02 / MV-03
# ---------------------------------------------------------------------------


class TestDashboardIntegration:
    """End-to-end: generate_dashboard includes the Kahuna section and the
    new action banner CSS classes when the state carries KAHUNA context."""

    def _phases(self) -> dict:
        return {
            "project": "Kahuna Project",
            "phases": [
                {
                    "name": "Phase 1",
                    "waves": [
                        {
                            "id": "wave-1",
                            "issues": [
                                {"number": 1, "title": "A"},
                                {"number": 2, "title": "B"},
                                {"number": 3, "title": "C"},
                            ],
                        },
                    ],
                }
            ],
        }

    def test_active_kahuna_appears_in_html(self, tmp_path: Path) -> None:
        """MV-02: dashboard shows active kahuna_branch + flight counts."""
        out = generate_dashboard(
            tmp_path, self._phases(), _kahuna_state(), _kahuna_flights()
        )
        content = out.read_text(encoding="utf-8")
        assert "kahuna/42-wave-status-cli" in content
        assert "1 merged, 2 pending" in content

    def test_gate_evaluating_shows_trust_signals(self, tmp_path: Path) -> None:
        """MV-03: ``gate_evaluating`` shows trust-signal summary block."""
        state = _kahuna_state(
            action="gate_evaluating",
            detail={
                "signals": [
                    "commutativity_verify",
                    "ci_wait_run",
                    "code-reviewer",
                    "trivy vuln scan",
                ],
            },
        )
        out = generate_dashboard(
            tmp_path, self._phases(), state, _kahuna_flights()
        )
        content = out.read_text(encoding="utf-8")
        assert "action-gate-evaluating" in content
        assert "kahuna-trust-signals" in content
        assert "commutativity_verify" in content
        assert "ci_wait_run" in content
        assert "code-reviewer" in content
        assert "trivy vuln scan" in content

    def test_gate_blocked_shows_failure_detail(self, tmp_path: Path) -> None:
        """MV-03: ``gate_blocked`` shows signal-failure detail block with
        red-emphasis styling."""
        state = _kahuna_state(
            action="gate_blocked",
            detail={
                "failures": [
                    {
                        "signal": "commutativity_verify",
                        "reason": "WEAK verdict on shared module",
                    },
                    {
                        "signal": "trivy vuln scan",
                        "reason": "CVE-2026-0001 HIGH severity",
                    },
                ],
            },
        )
        out = generate_dashboard(
            tmp_path, self._phases(), state, _kahuna_flights()
        )
        content = out.read_text(encoding="utf-8")
        assert "action-gate-blocked" in content
        assert "kahuna-signal-failures" in content
        assert "commutativity_verify" in content
        assert "WEAK verdict on shared module" in content
        assert "CVE-2026-0001 HIGH severity" in content

    def test_history_table_renders(self, tmp_path: Path) -> None:
        """MV-02: kahuna_branches history table (collapsible, last 10)."""
        out = generate_dashboard(
            tmp_path, self._phases(), _kahuna_state(), _kahuna_flights()
        )
        content = out.read_text(encoding="utf-8")
        # The table uses <details> for collapsibility (devspec §5.2.5).
        assert '<details class="kahuna-history">' in content
        assert "kahuna-history-table" in content
        assert "kahuna/41-prior-epic" in content
        assert "kahuna/40-aborted-epic" in content
        assert "abc123def456" in content
        assert "code_reviewer_critical_findings" in content

    def test_history_caps_at_last_ten(self, tmp_path: Path) -> None:
        """Last 10 of 12 entries rendered; first 2 dropped."""
        state = _kahuna_state()
        # Pad with 10 extra entries so we have 13 total; last 10 should win.
        extra = [
            {
                "branch": f"kahuna/{i:03d}-past",
                "epic_id": i,
                "created_at": f"2026-03-{i:02d}T08:00:00Z",
                "resolved_at": f"2026-03-{i:02d}T09:30:00Z",
                "disposition": "merged",
                "main_merge_sha": f"sha{i:03d}",
            }
            for i in range(10)
        ]
        state["kahuna_branches"] = extra + state["kahuna_branches"]
        out = generate_dashboard(
            tmp_path, self._phases(), state, _kahuna_flights()
        )
        content = out.read_text(encoding="utf-8")
        # Oldest two dropped.
        assert "kahuna/000-past" not in content
        assert "kahuna/001-past" not in content
        # Newest ones present.
        assert "kahuna/41-prior-epic" in content
        assert "kahuna/40-aborted-epic" in content


# ---------------------------------------------------------------------------
# HTML escaping — every string-in-state field is user-controlled
# ---------------------------------------------------------------------------


class TestHtmlEscaping:
    """kahuna_* state fields route through html.escape so injected markup
    doesn't break the DOM or enable XSS."""

    def test_branch_name_escaped(self) -> None:
        state = {
            "kahuna_branch": '<script>alert(1)</script>',
        }
        html = render_kahuna_section(state, {"flights": {}})
        assert "<script>" not in html
        assert "&lt;script&gt;" in html

    def test_failure_reason_escaped(self) -> None:
        state = {
            "kahuna_branch": "kahuna/1-x",
            "current_action": {
                "action": "gate_blocked",
                "label": "gate_blocked",
                "detail": {
                    "failures": [
                        {
                            "signal": "x",
                            "reason": '<img src=x onerror=alert(1)>',
                        },
                    ],
                },
            },
        }
        html = render_kahuna_section(state, {"flights": {}})
        assert "<img src=x" not in html

    def test_history_abort_reason_escaped(self) -> None:
        state = {
            "kahuna_branches": [
                {
                    "branch": "kahuna/1-x",
                    "epic_id": 1,
                    "created_at": "2026-04-22T08:00:00Z",
                    "resolved_at": "2026-04-22T09:30:00Z",
                    "disposition": "aborted",
                    "abort_reason": "<script>alert(1)</script>",
                },
            ],
        }
        html = render_kahuna_section(state, {"flights": {}})
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# No external dependencies [CT-01]
# ---------------------------------------------------------------------------


class TestNoDependencies:
    """kahuna_section module must only use Python 3.10+ stdlib + wave_status."""

    def test_imports_only_stdlib_and_internals(self) -> None:
        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "wave_status",
            "dashboard",
            "kahuna_section.py",
        )
        with open(path) as f:
            source = f.read()
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        allowed_prefixes = (
            "from __future__",
            "import html",
            "from wave_status",
        )
        for line in import_lines:
            assert any(line.startswith(p) for p in allowed_prefixes), (
                f"Disallowed import: {line}"
            )
