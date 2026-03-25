"""Tests for wave_status.dashboard.polling module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #17 related to polling.
"""

from __future__ import annotations

import os
import sys

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.polling import render_polling_script


# ---------------------------------------------------------------------------
# render_polling_script() tests
# ---------------------------------------------------------------------------


class TestRenderPollingScript:
    """The script block must satisfy R-27, R-28, R-29."""

    def setup_method(self) -> None:
        self.script = render_polling_script()

    def test_returns_string(self) -> None:
        assert isinstance(self.script, str)

    def test_nonempty(self) -> None:
        assert len(self.script) > 0

    # --- Structure ---

    def test_starts_with_script_tag(self) -> None:
        assert self.script.startswith("<script>")

    def test_ends_with_script_tag(self) -> None:
        assert self.script.strip().endswith("</script>")

    def test_script_is_self_contained(self) -> None:
        """No external src= references — must be inline [CT-04]."""
        assert 'src="' not in self.script
        assert "src='" not in self.script

    # --- R-27: Fetches state.json every 3s ---

    def test_fetches_state_json(self) -> None:
        assert "state.json" in self.script

    def test_uses_fetch_api(self) -> None:
        assert "fetch(" in self.script

    def test_poll_interval_3000ms(self) -> None:
        assert "3000" in self.script

    def test_uses_setinterval(self) -> None:
        assert "setInterval" in self.script

    # --- R-28: Disables on fetch failure with fallback notice ---

    def test_clears_interval_on_error(self) -> None:
        assert "clearInterval" in self.script

    def test_fallback_notice_text(self) -> None:
        # The exact text from the PRD
        assert "Live updates unavailable" in self.script

    def test_fallback_refresh_guidance(self) -> None:
        assert "refresh to update" in self.script

    def test_targets_fallback_notice_element(self) -> None:
        assert "data-fallback-notice" in self.script

    def test_fallback_notice_shown_on_error(self) -> None:
        """The script must make the fallback notice visible."""
        assert 'display' in self.script
        assert 'block' in self.script

    # --- R-29: Uses data-* selectors for DOM updates ---

    def test_uses_data_field_selector(self) -> None:
        assert "data-field" in self.script

    def test_uses_queryselectorall_for_data_attributes(self) -> None:
        assert "querySelectorAll" in self.script

    def test_uses_data_action_banner(self) -> None:
        assert "data-action-banner" in self.script

    def test_uses_data_status(self) -> None:
        assert "data-status" in self.script

    def test_uses_data_timestamp(self) -> None:
        assert "data-timestamp" in self.script

    # --- Action banner class updates ---

    def test_contains_all_action_css_classes(self) -> None:
        """The polling script must know all action CSS class names."""
        expected_classes = [
            "action-preflight",
            "action-planning",
            "action-inflight",
            "action-merging",
            "action-review",
            "action-meatbag",
            "action-idle",
        ]
        for cls in expected_classes:
            assert cls in self.script, f"Missing action class {cls!r} in script"

    def test_contains_all_action_names(self) -> None:
        """The script maps action names to CSS classes."""
        expected_actions = [
            "pre-flight",
            "planning",
            "in-flight",
            "merging",
            "post-wave-review",
            "waiting-on-meatbag",
            "idle",
        ]
        for action in expected_actions:
            assert action in self.script, f"Missing action name {action!r} in script"

    # --- Nested state value resolution ---

    def test_supports_dotted_paths(self) -> None:
        """The script must support dotted paths like 'current_wave.name'."""
        assert "split" in self.script  # path.split(".")

    # --- Immediate poll on load ---

    def test_immediate_poll_on_load(self) -> None:
        """Should call pollState immediately, not just on interval."""
        # The script calls pollState() after setInterval
        lines = self.script.splitlines()
        # Find setInterval line and then look for a standalone pollState() call after
        found_set_interval = False
        found_immediate_call = False
        for line in lines:
            stripped = line.strip()
            if "setInterval" in stripped:
                found_set_interval = True
            if found_set_interval and stripped == "pollState();":
                found_immediate_call = True
        assert found_set_interval, "Missing setInterval call"
        assert found_immediate_call, "Missing immediate pollState() call after setInterval"


# ---------------------------------------------------------------------------
# No external dependencies  [CT-01]
# ---------------------------------------------------------------------------


class TestNoDependencies:
    """Module must only use Python 3.10+ stdlib."""

    def test_polling_imports_only_stdlib(self) -> None:
        """Read polling.py source and verify no non-stdlib imports."""
        polling_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "src",
            "wave_status",
            "dashboard",
            "polling.py",
        )
        with open(polling_path) as f:
            source = f.read()

        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]

        for line in import_lines:
            assert line.startswith("from __future__"), (
                f"Non-stdlib import found: {line}"
            )


# ---------------------------------------------------------------------------
# Return value consistency
# ---------------------------------------------------------------------------


class TestConsistency:
    """Calling render_polling_script multiple times returns the same result."""

    def test_idempotent(self) -> None:
        a = render_polling_script()
        b = render_polling_script()
        assert a == b
