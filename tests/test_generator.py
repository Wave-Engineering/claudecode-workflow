"""Tests for wave_status.dashboard.generator module.

Exercises REAL code paths -- no mocking of the module under test.
Validates all acceptance criteria from Issue #22.

Filesystem I/O is tested against real tmp directories using pytest's
tmp_path fixture.  No mocking of os.replace or tempfile.
"""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from pathlib import Path

from wave_status.dashboard.generator import (
    _render_action_banner,
    _render_footer,
    _render_header,
    generate_dashboard,
)
from wave_status.dashboard.theme import ACTION_BANNER_STATES


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

def _minimal_phases() -> dict:
    """Return a minimal phases_data dict for testing."""
    return {
        "project": "Test Project",
        "phases": [
            {
                "name": "Phase 1",
                "waves": [
                    {
                        "id": "wave-1",
                        "issues": [
                            {"number": 1, "title": "First issue"},
                            {"number": 2, "title": "Second issue"},
                        ],
                    }
                ],
            }
        ],
    }


def _minimal_state() -> dict:
    """Return a minimal state_data dict for testing."""
    return {
        "current_wave": "wave-1",
        "current_action": {
            "action": "in-flight",
            "label": "flight 1",
            "detail": "wave-1 -- issues: #1, #2",
        },
        "waves": {
            "wave-1": {"status": "in_progress", "mr_urls": {}},
        },
        "issues": {
            "1": {"status": "open"},
            "2": {"status": "closed"},
        },
        "deferrals": [],
        "last_updated": "2025-01-15T10:30:00Z",
    }


def _minimal_flights() -> dict:
    """Return a minimal flights_data dict for testing."""
    return {
        "flights": {
            "wave-1": [
                {"issues": [1, 2], "status": "running"},
            ],
        },
    }


# ---------------------------------------------------------------------------
# _render_header tests
# ---------------------------------------------------------------------------


class TestRenderHeader:
    """Header must render project name and current wave."""

    def test_renders_project_name(self) -> None:
        phases = _minimal_phases()
        state = _minimal_state()
        header = _render_header(phases, state)
        assert "Test Project" in header

    def test_renders_current_wave(self) -> None:
        phases = _minimal_phases()
        state = _minimal_state()
        header = _render_header(phases, state)
        assert "wave-1" in header

    def test_has_header_class(self) -> None:
        phases = _minimal_phases()
        state = _minimal_state()
        header = _render_header(phases, state)
        assert 'class="header"' in header

    def test_project_in_h1(self) -> None:
        phases = _minimal_phases()
        state = _minimal_state()
        header = _render_header(phases, state)
        assert "<h1>" in header
        assert "Test Project" in header

    def test_html_escapes_project_name(self) -> None:
        phases = {"project": '<script>alert("xss")</script>', "phases": []}
        state = {"current_wave": "wave-1"}
        header = _render_header(phases, state)
        assert "<script>" not in header
        assert "&lt;script&gt;" in header

    def test_html_escapes_wave_id(self) -> None:
        phases = _minimal_phases()
        state = {"current_wave": '<img src="x">'}
        header = _render_header(phases, state)
        assert '<img src="x">' not in header

    def test_missing_project_uses_default(self) -> None:
        phases = {"phases": []}
        state = {"current_wave": "wave-1"}
        header = _render_header(phases, state)
        assert "Unknown Project" in header

    def test_missing_wave_shows_empty_meta(self) -> None:
        phases = _minimal_phases()
        state = {"current_wave": None}
        header = _render_header(phases, state)
        # meta div should exist but without wave content
        assert 'class="meta"' in header

    def test_does_not_render_base_branch(self) -> None:
        """base_branch is deferred to Wave 4."""
        phases = _minimal_phases()
        state = _minimal_state()
        header = _render_header(phases, state)
        assert "base_branch" not in header

    def test_does_not_render_master_issue(self) -> None:
        """master_issue is deferred to Wave 4."""
        phases = _minimal_phases()
        state = _minimal_state()
        header = _render_header(phases, state)
        assert "master_issue" not in header


# ---------------------------------------------------------------------------
# _render_action_banner tests
# ---------------------------------------------------------------------------


class TestRenderActionBanner:
    """Action banner must use ACTION_BANNER_STATES for styling."""

    def test_in_flight_renders_correct_class(self) -> None:
        state = _minimal_state()
        banner = _render_action_banner(state)
        assert "action-inflight" in banner

    def test_in_flight_renders_icon(self) -> None:
        state = _minimal_state()
        banner = _render_action_banner(state)
        icon = ACTION_BANNER_STATES["in-flight"]["icon"]
        assert icon in banner

    def test_renders_label(self) -> None:
        state = _minimal_state()
        banner = _render_action_banner(state)
        assert "flight 1" in banner

    def test_renders_detail(self) -> None:
        state = _minimal_state()
        banner = _render_action_banner(state)
        assert "wave-1 -- issues: #1, #2" in banner

    def test_all_action_states_produce_valid_banner(self) -> None:
        """Every ACTION_BANNER_STATES key must produce a valid banner."""
        for action_key, expected in ACTION_BANNER_STATES.items():
            state = {
                "current_action": {
                    "action": action_key,
                    "label": action_key,
                    "detail": "",
                },
            }
            banner = _render_action_banner(state)
            assert expected["css_class"] in banner, (
                f"Action {action_key!r} did not produce class {expected['css_class']!r}"
            )
            assert expected["icon"] in banner, (
                f"Action {action_key!r} did not produce icon"
            )

    def test_none_current_action_returns_empty(self) -> None:
        state = {"current_action": None}
        banner = _render_action_banner(state)
        assert banner == ""

    def test_missing_current_action_returns_empty(self) -> None:
        state = {}
        banner = _render_action_banner(state)
        assert banner == ""

    def test_unknown_action_returns_empty(self) -> None:
        state = {
            "current_action": {
                "action": "nonexistent-action",
                "label": "test",
                "detail": "",
            },
        }
        banner = _render_action_banner(state)
        assert banner == ""

    def test_has_data_action_banner_attribute(self) -> None:
        state = _minimal_state()
        banner = _render_action_banner(state)
        assert "data-action-banner" in banner

    def test_html_escapes_label(self) -> None:
        state = {
            "current_action": {
                "action": "idle",
                "label": '<script>alert("xss")</script>',
                "detail": "",
            },
        }
        banner = _render_action_banner(state)
        assert "<script>" not in banner

    def test_html_escapes_detail(self) -> None:
        state = {
            "current_action": {
                "action": "idle",
                "label": "test",
                "detail": '<img src="x" onerror="alert(1)">',
            },
        }
        banner = _render_action_banner(state)
        assert '<img src=' not in banner

    def test_no_detail_omits_message_span(self) -> None:
        state = {
            "current_action": {
                "action": "idle",
                "label": "idle",
                "detail": "",
            },
        }
        banner = _render_action_banner(state)
        assert 'class="message"' not in banner

    def test_detail_present_renders_message_span(self) -> None:
        state = _minimal_state()
        banner = _render_action_banner(state)
        assert 'class="message"' in banner


# ---------------------------------------------------------------------------
# _render_footer tests
# ---------------------------------------------------------------------------


class TestRenderFooter:
    """Footer must include generation timestamp and last-update timestamp."""

    def test_has_footer_class(self) -> None:
        state = _minimal_state()
        footer = _render_footer(state)
        assert 'class="footer"' in footer

    def test_contains_generation_timestamp(self) -> None:
        state = _minimal_state()
        footer = _render_footer(state)
        assert "Generated:" in footer

    def test_contains_last_updated_timestamp(self) -> None:
        state = _minimal_state()
        footer = _render_footer(state)
        assert "2025-01-15T10:30:00Z" in footer

    def test_has_data_timestamp_attribute(self) -> None:
        state = _minimal_state()
        footer = _render_footer(state)
        assert "data-timestamp" in footer

    def test_has_fallback_notice_element(self) -> None:
        state = _minimal_state()
        footer = _render_footer(state)
        assert "data-fallback-notice" in footer

    def test_fallback_notice_class(self) -> None:
        state = _minimal_state()
        footer = _render_footer(state)
        assert "fallback-notice" in footer

    def test_html_escapes_last_updated(self) -> None:
        state = {"last_updated": '<script>alert("xss")</script>'}
        footer = _render_footer(state)
        assert "<script>" not in footer


# ---------------------------------------------------------------------------
# generate_dashboard — full integration tests
# ---------------------------------------------------------------------------


class TestGenerateDashboard:
    """Full integration: generate_dashboard writes a valid HTML file."""

    def test_writes_html_file(self, tmp_path: Path) -> None:
        html_file = generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        assert html_file.exists()

    def test_returns_correct_path(self, tmp_path: Path) -> None:
        html_file = generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        assert html_file == tmp_path / ".status-panel.html"

    def test_html_starts_with_doctype(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert content.startswith("<!DOCTYPE html>")

    def test_html_is_self_contained_no_external_css(self, tmp_path: Path) -> None:
        """No external stylesheet links [R-17, CT-04]."""
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert '<link rel="stylesheet"' not in content

    def test_html_is_self_contained_no_external_js(self, tmp_path: Path) -> None:
        """No external script src= references [R-17, CT-04]."""
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert '<script src=' not in content

    def test_has_inline_css(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "<style>" in content
        assert "</style>" in content

    def test_has_inline_js(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "<script>" in content
        assert "</script>" in content

    # --- Layout order [R-18] ---

    def test_layout_order(self, tmp_path: Path) -> None:
        """Components must appear in specified order [R-18]."""
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")

        # Find positions of key markers
        header_pos = content.find('class="header"')
        banner_pos = content.find("data-action-banner")
        rail_pos = content.find('class="progress-rail"')
        gauge_pos = content.find('class="gauge-grid"')
        pending_pos = content.find('class="deferrals-section pending"')
        grid_pos = content.find('class="execution-grid"')
        accepted_pos = content.find('class="deferrals-section accepted"')
        footer_pos = content.find('class="footer"')
        script_pos = content.find("<script>")

        assert header_pos != -1, "Header not found"
        assert banner_pos != -1, "Action banner not found"
        assert rail_pos != -1, "Progress rail not found"
        assert gauge_pos != -1, "Gauge grid not found"
        assert pending_pos != -1, "Pending deferrals not found"
        assert grid_pos != -1, "Execution grid not found"
        assert accepted_pos != -1, "Accepted deferrals not found"
        assert footer_pos != -1, "Footer not found"
        assert script_pos != -1, "Script not found"

        if banner_pos != -1:
            assert header_pos < banner_pos, "Header must come before banner"
            assert banner_pos < rail_pos, "Banner must come before rail"
        else:
            assert header_pos < rail_pos, "Header must come before rail (no banner)"
        assert rail_pos < gauge_pos, "Rail must come before gauges"
        assert gauge_pos < pending_pos, "Gauges must come before pending deferrals"
        assert pending_pos < grid_pos, "Pending deferrals must come before grid"
        assert grid_pos < accepted_pos, "Grid must come before accepted deferrals"
        assert accepted_pos < footer_pos, "Accepted deferrals must come before footer"
        assert footer_pos < script_pos, "Footer must come before script"

    # --- Action banner integration ---

    def test_action_banner_present_when_action_set(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "action-inflight" in content

    def test_no_action_banner_when_current_action_none(self, tmp_path: Path) -> None:
        state = _minimal_state()
        state["current_action"] = None
        generate_dashboard(tmp_path, _minimal_phases(), state, _minimal_flights())
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        # The polling script references data-action-banner as a selector string,
        # but the actual banner div should not be rendered.
        assert 'class="action-banner' not in content

    def test_no_action_banner_when_current_action_missing(self, tmp_path: Path) -> None:
        state = _minimal_state()
        del state["current_action"]
        generate_dashboard(tmp_path, _minimal_phases(), state, _minimal_flights())
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        # The polling script references data-action-banner as a selector string,
        # but the actual banner div should not be rendered.
        assert 'class="action-banner' not in content

    # --- Header integration ---

    def test_header_shows_project_name(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "Test Project" in content

    def test_header_shows_wave(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "wave-1" in content

    # --- Atomic write [R-33] ---

    def test_atomic_write_no_leftover_tmp(self, tmp_path: Path) -> None:
        """After successful write, no .tmp files should remain."""
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert tmp_files == [], f"Leftover tmp files: {tmp_files}"

    def test_atomic_write_file_readable(self, tmp_path: Path) -> None:
        """Written file must be a valid, readable text file."""
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert len(content) > 100

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Calling generate_dashboard twice should overwrite the file."""
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        first_content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")

        # Change state and regenerate
        state = _minimal_state()
        state["current_action"] = {
            "action": "idle",
            "label": "idle",
            "detail": "",
        }
        generate_dashboard(tmp_path, _minimal_phases(), state, _minimal_flights())
        second_content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")

        assert "action-idle" in second_content
        assert first_content != second_content

    # --- Component presence ---

    def test_contains_progress_rail(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "progress-rail" in content

    def test_contains_gauge_cards(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "gauge-grid" in content

    def test_contains_execution_grid(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "execution-grid" in content

    def test_contains_pending_deferrals(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "Pending Deferrals" in content

    def test_contains_accepted_deferrals(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "Accepted Deferrals" in content

    def test_contains_polling_script(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "setInterval" in content

    def test_legacy_layout_uses_relative_state_path(self, tmp_path: Path) -> None:
        """No .sdlc/ → HTML at root, state at .claude/status/ → STATE_URL must
        be the relative path from project root to state.json (cc-workflow#444).
        """
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert 'var STATE_URL = ".claude/status/state.json";' in content
        # And the bare-literal regression must not slip back in
        assert 'fetch("state.json")' not in content

    def test_sdlc_layout_uses_sibling_state_path(self, tmp_path: Path) -> None:
        """With .sdlc/ present → HTML and state are siblings → STATE_URL = 'state.json'."""
        (tmp_path / ".sdlc").mkdir()
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".sdlc" / "waves" / "dashboard.html").read_text(encoding="utf-8")
        assert 'var STATE_URL = "state.json";' in content

    def test_contains_footer(self, tmp_path: Path) -> None:
        generate_dashboard(
            tmp_path, _minimal_phases(), _minimal_state(), _minimal_flights()
        )
        content = (tmp_path / ".status-panel.html").read_text(encoding="utf-8")
        assert "Generated:" in content

    # --- Complex scenario ---

    def test_multi_phase_multi_wave(self, tmp_path: Path) -> None:
        """Test with a richer data set: multiple phases, waves, deferrals."""
        phases = {
            "project": "Multi-Phase Project",
            "phases": [
                {
                    "name": "Foundation",
                    "waves": [
                        {
                            "id": "wave-1",
                            "issues": [
                                {"number": 1, "title": "Setup"},
                                {"number": 2, "title": "Config"},
                            ],
                        },
                        {
                            "id": "wave-2",
                            "issues": [
                                {"number": 3, "title": "Core logic"},
                            ],
                        },
                    ],
                },
                {
                    "name": "Features",
                    "waves": [
                        {
                            "id": "wave-3",
                            "issues": [
                                {"number": 4, "title": "Feature A"},
                                {"number": 5, "title": "Feature B"},
                            ],
                        },
                    ],
                },
            ],
        }
        state = {
            "current_wave": "wave-2",
            "current_action": {
                "action": "planning",
                "label": "planning",
                "detail": "wave-2",
            },
            "waves": {
                "wave-1": {"status": "completed", "mr_urls": {}},
                "wave-2": {"status": "in_progress", "mr_urls": {}},
                "wave-3": {"status": "pending", "mr_urls": {}},
            },
            "issues": {
                "1": {"status": "closed"},
                "2": {"status": "closed"},
                "3": {"status": "open"},
                "4": {"status": "open"},
                "5": {"status": "open"},
            },
            "deferrals": [
                {
                    "wave": "wave-1",
                    "description": "Deferred item A",
                    "risk": "low",
                    "status": "pending",
                },
                {
                    "wave": "wave-1",
                    "description": "Deferred item B",
                    "risk": "high",
                    "status": "accepted",
                },
            ],
            "last_updated": "2025-01-15T12:00:00Z",
        }
        flights = {
            "flights": {
                "wave-1": [
                    {"issues": [1, 2], "status": "completed"},
                ],
                "wave-2": [
                    {"issues": [3], "status": "pending"},
                ],
            },
        }

        html_file = generate_dashboard(tmp_path, phases, state, flights)
        content = html_file.read_text(encoding="utf-8")

        assert "Multi-Phase Project" in content
        assert "wave-2" in content
        assert "action-planning" in content
        assert "Foundation" in content
        assert "Features" in content
        assert "Deferred item A" in content
        assert "Deferred item B" in content


# ---------------------------------------------------------------------------
# No external dependencies [CT-01]
# ---------------------------------------------------------------------------


class TestNoDependencies:
    """Module must only use Python 3.10+ stdlib + wave_status internals."""

    def test_generator_imports_only_stdlib_and_internals(self) -> None:
        """Read generator.py source and verify no non-stdlib/non-internal imports."""
        generator_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "wave_status",
            "dashboard",
            "generator.py",
        )
        with open(generator_path) as f:
            source = f.read()

        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]

        allowed_prefixes = (
            "from __future__",
            "import html",
            "import os",
            "import tempfile",
            "from datetime",
            "from pathlib",
            "from wave_status",
        )

        for line in import_lines:
            assert any(line.startswith(prefix) for prefix in allowed_prefixes), (
                f"Disallowed import found: {line}"
            )
