"""Tests for wave_status.dashboard.deferral_sections module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #21 (Story 2.3).
"""

from __future__ import annotations

import ast
import os
import pathlib
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.deferral_sections import (
    render_accepted_deferrals,
    render_pending_deferrals,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

STATE_NO_DEFERRALS = {
    "current_wave": "wave-1",
    "waves": {"wave-1": {"status": "in_progress", "mr_urls": {}}},
    "issues": {},
    "deferrals": [],
}

STATE_PENDING_ONLY = {
    **STATE_NO_DEFERRALS,
    "deferrals": [
        {"wave": "wave-1", "description": "Fix login timeout", "risk": "high", "status": "pending"},
        {"wave": "wave-1", "description": "Add retry logic", "risk": "medium", "status": "pending"},
    ],
}

STATE_ACCEPTED_ONLY = {
    **STATE_NO_DEFERRALS,
    "deferrals": [
        {"wave": "wave-1", "description": "Refactor config", "risk": "low", "status": "accepted"},
        {"wave": "wave-2", "description": "Update docs", "risk": "low", "status": "accepted"},
    ],
}

STATE_MIXED = {
    **STATE_NO_DEFERRALS,
    "deferrals": [
        {"wave": "wave-1", "description": "Fix login timeout", "risk": "high", "status": "pending"},
        {"wave": "wave-1", "description": "Refactor config", "risk": "low", "status": "accepted"},
        {"wave": "wave-2", "description": "Add retry logic", "risk": "medium", "status": "pending"},
        {"wave": "wave-2", "description": "Update docs", "risk": "low", "status": "accepted"},
    ],
}


# ---------------------------------------------------------------------------
# render_pending_deferrals() tests  [R-25]
# ---------------------------------------------------------------------------


class TestRenderPendingDeferralsEmpty:
    """Pending section collapses to zero height when empty [R-25]."""

    def setup_method(self) -> None:
        self.html = render_pending_deferrals(STATE_NO_DEFERRALS)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_deferrals_section_class(self) -> None:
        assert 'class="deferrals-section pending"' in self.html

    def test_collapses_to_zero_height_when_empty(self) -> None:
        # Container must have max-height: 0 style when no items [R-25]
        assert "max-height: 0" in self.html

    def test_overflow_hidden_when_empty(self) -> None:
        assert "overflow: hidden" in self.html

    def test_padding_zero_when_empty(self) -> None:
        assert "padding: 0" in self.html

    def test_no_table_when_empty(self) -> None:
        assert "<table" not in self.html

    def test_has_heading(self) -> None:
        assert "Pending Deferrals" in self.html


class TestRenderPendingDeferralsWithItems:
    """Pending section is visible and shows items when they exist [R-25]."""

    def setup_method(self) -> None:
        self.html = render_pending_deferrals(STATE_PENDING_ONLY)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_deferrals_section_class(self) -> None:
        assert 'class="deferrals-section pending"' in self.html

    def test_does_not_collapse_when_items_exist(self) -> None:
        # No collapse style when pending items present
        assert "max-height: 0" not in self.html

    def test_has_table(self) -> None:
        assert '<table class="deferrals-table"' in self.html

    def test_has_table_headers(self) -> None:
        assert "<th>#</th>" in self.html
        assert "<th>Wave</th>" in self.html
        assert "<th>Description</th>" in self.html
        assert "<th>Risk</th>" in self.html

    def test_1based_index_first_row(self) -> None:
        assert "<td>1</td>" in self.html

    def test_1based_index_second_row(self) -> None:
        assert "<td>2</td>" in self.html

    def test_wave_column_present(self) -> None:
        assert "<td>wave-1</td>" in self.html

    def test_description_column_present(self) -> None:
        assert "Fix login timeout" in self.html
        assert "Add retry logic" in self.html

    def test_risk_column_present(self) -> None:
        assert "<td>high</td>" in self.html
        assert "<td>medium</td>" in self.html

    def test_has_heading(self) -> None:
        assert "Pending Deferrals" in self.html

    def test_only_pending_items_shown(self) -> None:
        """Only items with status=pending should appear."""
        html = render_pending_deferrals(STATE_MIXED)
        # 2 pending items
        assert html.count("<tr>") == 3  # 1 header row + 2 data rows

    def test_does_not_include_accepted_items(self) -> None:
        html = render_pending_deferrals(STATE_MIXED)
        assert "Refactor config" not in html
        assert "Update docs" not in html


class TestRenderPendingDeferralsOrangeAccent:
    """Orange-accented styling markers."""

    def test_pending_class_allows_orange_css_accent(self) -> None:
        """The 'pending' class on deferrals-section enables orange border per theme CSS."""
        html = render_pending_deferrals(STATE_PENDING_ONLY)
        # The CSS from theme.py applies border-left: 4px solid var(--orange) to .deferrals-section.pending
        # We verify the class is present to hook the CSS.
        assert "deferrals-section pending" in html


# ---------------------------------------------------------------------------
# render_accepted_deferrals() tests  [R-26]
# ---------------------------------------------------------------------------


class TestRenderAcceptedDeferralsEmpty:
    """Accepted section renders even when empty [R-26]."""

    def setup_method(self) -> None:
        self.html = render_accepted_deferrals(STATE_NO_DEFERRALS)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_deferrals_section_accepted_class(self) -> None:
        assert 'class="deferrals-section accepted"' in self.html

    def test_has_heading(self) -> None:
        assert "Accepted Deferrals" in self.html

    def test_no_table_when_empty(self) -> None:
        assert "<table" not in self.html

    def test_no_collapse_style(self) -> None:
        # Accepted section never collapses — always visible
        assert "max-height: 0" not in self.html


class TestRenderAcceptedDeferralsWithItems:
    """Accepted section shows items with subdued styling [R-26]."""

    def setup_method(self) -> None:
        self.html = render_accepted_deferrals(STATE_ACCEPTED_ONLY)

    def test_returns_string(self) -> None:
        assert isinstance(self.html, str)

    def test_has_deferrals_section_accepted_class(self) -> None:
        assert 'class="deferrals-section accepted"' in self.html

    def test_has_table(self) -> None:
        assert '<table class="deferrals-table"' in self.html

    def test_has_table_headers(self) -> None:
        assert "<th>#</th>" in self.html
        assert "<th>Wave</th>" in self.html
        assert "<th>Description</th>" in self.html
        assert "<th>Risk</th>" in self.html

    def test_1based_index_first_row(self) -> None:
        assert "<td>1</td>" in self.html

    def test_1based_index_second_row(self) -> None:
        assert "<td>2</td>" in self.html

    def test_wave_column_present(self) -> None:
        assert "<td>wave-1</td>" in self.html
        assert "<td>wave-2</td>" in self.html

    def test_description_column_present(self) -> None:
        assert "Refactor config" in self.html
        assert "Update docs" in self.html

    def test_risk_column_present(self) -> None:
        assert "<td>low</td>" in self.html

    def test_has_heading(self) -> None:
        assert "Accepted Deferrals" in self.html

    def test_only_accepted_items_shown(self) -> None:
        """Only items with status=accepted should appear."""
        html = render_accepted_deferrals(STATE_MIXED)
        # 2 accepted items
        assert html.count("<tr>") == 3  # 1 header row + 2 data rows

    def test_does_not_include_pending_items(self) -> None:
        html = render_accepted_deferrals(STATE_MIXED)
        assert "Fix login timeout" not in html
        assert "Add retry logic" not in html


class TestRenderAcceptedDeferralsSubduedStyling:
    """Accepted section uses subdued (accepted) CSS class."""

    def test_accepted_class_not_pending(self) -> None:
        html = render_accepted_deferrals(STATE_ACCEPTED_ONLY)
        assert "deferrals-section accepted" in html
        # Must not have the orange-accent 'pending' class
        assert "deferrals-section pending" not in html


# ---------------------------------------------------------------------------
# Both sections together — ordering and independence
# ---------------------------------------------------------------------------


class TestBothSectionsTogether:
    """Pending appears above, accepted below [R-25, R-26]."""

    def test_pending_section_structure(self) -> None:
        p_html = render_pending_deferrals(STATE_MIXED)
        a_html = render_accepted_deferrals(STATE_MIXED)
        # Both are independent HTML strings — can be concatenated in correct order
        combined = p_html + a_html
        pending_pos = combined.index("Pending Deferrals")
        accepted_pos = combined.index("Accepted Deferrals")
        assert pending_pos < accepted_pos

    def test_pending_section_shows_pending_count(self) -> None:
        html = render_pending_deferrals(STATE_MIXED)
        assert "Fix login timeout" in html
        assert "Add retry logic" in html

    def test_accepted_section_shows_accepted_count(self) -> None:
        html = render_accepted_deferrals(STATE_MIXED)
        assert "Refactor config" in html
        assert "Update docs" in html


# ---------------------------------------------------------------------------
# CT-01: No non-stdlib imports
# ---------------------------------------------------------------------------


class TestNoNonStdlibImports:
    """CT-01: module uses only Python 3.10+ stdlib (plus wave_status internals)."""

    def test_module_importable_without_third_party(self) -> None:
        import wave_status.dashboard.deferral_sections as ds  # noqa: F401

        assert hasattr(ds, "render_pending_deferrals")
        assert hasattr(ds, "render_accepted_deferrals")

    def test_module_has_no_non_stdlib_imports(self) -> None:
        src = (
            pathlib.Path(__file__).parent.parent
            / "src"
            / "wave_status"
            / "dashboard"
            / "deferral_sections.py"
        )
        tree = ast.parse(src.read_text())
        stdlib_prefixes = {
            "__future__", "ast", "os", "sys", "pathlib", "json", "re",
            "html", "datetime", "collections", "itertools", "functools",
            "typing", "types", "abc", "io", "math", "copy", "string",
            "textwrap", "enum", "dataclasses", "contextlib",
        }
        external = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib_prefixes:
                        external.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    top = node.module.split(".")[0]
                    if top not in stdlib_prefixes and top != "wave_status":
                        external.append(node.module)
        assert external == [], f"Non-stdlib imports found: {external}"
