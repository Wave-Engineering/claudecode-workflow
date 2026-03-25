"""Tests for wave_status.dashboard.theme module.

Exercises REAL code paths — no mocking of the module under test.
Validates all acceptance criteria from Issue #17 and PRD Appendix A.
"""

from __future__ import annotations

import sys
import os

# Ensure src/ is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from wave_status.dashboard.theme import (
    ACTION_BANNER_STATES,
    CSS_TOKENS,
    FONT_STACK,
    PHASE_COLORS,
    render_base_css,
)


# ---------------------------------------------------------------------------
# CSS_TOKENS tests  [R-30]
# ---------------------------------------------------------------------------


class TestCSSTokens:
    """Every custom property from PRD Appendix A must be present."""

    EXPECTED_TOKENS: dict[str, str] = {
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

    def test_token_count(self) -> None:
        """All 13 tokens from Appendix A are defined."""
        assert len(CSS_TOKENS) == 13

    def test_each_token_present_with_correct_value(self) -> None:
        """Every token key and value matches the PRD specification."""
        for token, value in self.EXPECTED_TOKENS.items():
            assert token in CSS_TOKENS, f"Missing CSS token: {token}"
            assert CSS_TOKENS[token] == value, (
                f"Token {token}: expected {value!r}, got {CSS_TOKENS[token]!r}"
            )

    def test_no_extra_tokens(self) -> None:
        """No unexpected tokens are defined."""
        extra = set(CSS_TOKENS.keys()) - set(self.EXPECTED_TOKENS.keys())
        assert extra == set(), f"Unexpected tokens: {extra}"


# ---------------------------------------------------------------------------
# FONT_STACK test  [R-30]
# ---------------------------------------------------------------------------


class TestFontStack:
    def test_font_stack_contains_jetbrains_mono(self) -> None:
        assert "JetBrains Mono" in FONT_STACK

    def test_font_stack_contains_fira_code(self) -> None:
        assert "Fira Code" in FONT_STACK

    def test_font_stack_contains_cascadia_code(self) -> None:
        assert "Cascadia Code" in FONT_STACK

    def test_font_stack_ends_with_monospace(self) -> None:
        assert FONT_STACK.strip().endswith("monospace")


# ---------------------------------------------------------------------------
# PHASE_COLORS tests  [R-21, R-22]
# ---------------------------------------------------------------------------


class TestPhaseColors:
    """Color cycle: fuchsia -> cyan -> green -> yellow with full/faded rgba."""

    def test_four_colors(self) -> None:
        assert len(PHASE_COLORS) == 4

    def test_cycle_order(self) -> None:
        names = [c["name"] for c in PHASE_COLORS]
        assert names == ["fuchsia", "cyan", "green", "yellow"]

    def test_each_color_has_required_keys(self) -> None:
        for color in PHASE_COLORS:
            assert "name" in color
            assert "var" in color
            assert "completed" in color
            assert "remaining" in color

    def test_completed_is_full_opacity(self) -> None:
        for color in PHASE_COLORS:
            assert "1.0)" in color["completed"], (
                f"{color['name']} completed should have alpha 1.0"
            )

    def test_remaining_is_faded_opacity(self) -> None:
        for color in PHASE_COLORS:
            assert "0.2)" in color["remaining"], (
                f"{color['name']} remaining should have alpha 0.2"
            )

    def test_fuchsia_rgba_values(self) -> None:
        fc = PHASE_COLORS[0]
        assert fc["completed"] == "rgba(255, 0, 255, 1.0)"
        assert fc["remaining"] == "rgba(255, 0, 255, 0.2)"

    def test_cyan_rgba_values(self) -> None:
        cy = PHASE_COLORS[1]
        assert cy["completed"] == "rgba(0, 255, 255, 1.0)"
        assert cy["remaining"] == "rgba(0, 255, 255, 0.2)"

    def test_green_rgba_values(self) -> None:
        gr = PHASE_COLORS[2]
        assert gr["completed"] == "rgba(0, 255, 136, 1.0)"
        assert gr["remaining"] == "rgba(0, 255, 136, 0.2)"

    def test_yellow_rgba_values(self) -> None:
        yl = PHASE_COLORS[3]
        assert yl["completed"] == "rgba(255, 204, 0, 1.0)"
        assert yl["remaining"] == "rgba(255, 204, 0, 0.2)"

    def test_var_references_match(self) -> None:
        expected_vars = ["--fuchsia", "--cyan", "--green", "--yellow"]
        for color, expected_var in zip(PHASE_COLORS, expected_vars):
            assert color["var"] == expected_var


# ---------------------------------------------------------------------------
# ACTION_BANNER_STATES tests  [R-30]
# ---------------------------------------------------------------------------


class TestActionBannerStates:
    """All 7 action banner states from PRD Appendix A."""

    EXPECTED_ACTIONS = [
        "pre-flight",
        "planning",
        "in-flight",
        "merging",
        "post-wave-review",
        "waiting-on-meatbag",
        "idle",
    ]

    def test_seven_states(self) -> None:
        assert len(ACTION_BANNER_STATES) == 7

    def test_all_actions_present(self) -> None:
        for action in self.EXPECTED_ACTIONS:
            assert action in ACTION_BANNER_STATES, f"Missing action: {action}"

    def test_no_extra_actions(self) -> None:
        extra = set(ACTION_BANNER_STATES.keys()) - set(self.EXPECTED_ACTIONS)
        assert extra == set(), f"Unexpected actions: {extra}"

    def test_each_state_has_required_keys(self) -> None:
        for action, state in ACTION_BANNER_STATES.items():
            for key in ("icon", "css_class", "border_color", "animation"):
                assert key in state, f"Action {action!r} missing key {key!r}"

    def test_preflight_properties(self) -> None:
        s = ACTION_BANNER_STATES["pre-flight"]
        assert s["icon"] == "&#x1F50D;"  # magnifying glass
        assert s["css_class"] == "action-preflight"
        assert s["border_color"] == "var(--cyan)"
        assert s["animation"] == "none"

    def test_planning_properties(self) -> None:
        s = ACTION_BANNER_STATES["planning"]
        assert s["icon"] == "&#x1F9E0;"  # brain
        assert s["css_class"] == "action-planning"
        assert s["border_color"] == "var(--yellow)"
        assert s["animation"] == "none"

    def test_inflight_properties(self) -> None:
        s = ACTION_BANNER_STATES["in-flight"]
        assert s["icon"] == "&#x1F680;"  # rocket
        assert s["css_class"] == "action-inflight"
        assert s["border_color"] == "var(--fuchsia)"
        assert s["animation"] == "glow 2s ease-in-out infinite"

    def test_merging_properties(self) -> None:
        s = ACTION_BANNER_STATES["merging"]
        assert s["icon"] == "&#x1F500;"  # shuffle
        assert s["css_class"] == "action-merging"
        assert s["border_color"] == "var(--green)"
        assert s["animation"] == "none"

    def test_review_properties(self) -> None:
        s = ACTION_BANNER_STATES["post-wave-review"]
        assert s["icon"] == "&#x1F50E;"  # right magnifier
        assert s["css_class"] == "action-review"
        assert s["border_color"] == "var(--orange)"
        assert s["animation"] == "none"

    def test_meatbag_properties(self) -> None:
        s = ACTION_BANNER_STATES["waiting-on-meatbag"]
        assert s["icon"] == "&#x1F9B4;"  # bone
        assert s["css_class"] == "action-meatbag"
        assert s["border_color"] == "var(--fuchsia)"
        assert s["animation"] == "throb 2.5s ease-in-out infinite"

    def test_idle_properties(self) -> None:
        s = ACTION_BANNER_STATES["idle"]
        assert s["icon"] == "&#x1F4A4;"  # zzz
        assert s["css_class"] == "action-idle"
        assert s["border_color"] == "var(--border)"
        assert s["animation"] == "none"


# ---------------------------------------------------------------------------
# render_base_css() tests  [R-30]
# ---------------------------------------------------------------------------


class TestRenderBaseCSS:
    """The CSS output must include all required components."""

    def setup_method(self) -> None:
        self.css = render_base_css()

    def test_returns_string(self) -> None:
        assert isinstance(self.css, str)

    def test_nonempty(self) -> None:
        assert len(self.css) > 0

    # --- Custom properties ---

    def test_contains_root_block(self) -> None:
        assert ":root" in self.css

    def test_all_custom_properties_present(self) -> None:
        for token in CSS_TOKENS:
            assert token in self.css, f"Missing custom property {token} in CSS"

    def test_all_custom_property_values_present(self) -> None:
        for token, value in CSS_TOKENS.items():
            assert value in self.css, f"Missing value {value} for {token} in CSS"

    # --- Font stack ---

    def test_font_stack_in_css(self) -> None:
        assert "JetBrains Mono" in self.css

    # --- Base layout ---

    def test_body_styles(self) -> None:
        assert "body" in self.css
        assert "var(--bg)" in self.css

    def test_container_styles(self) -> None:
        assert ".container" in self.css

    # --- Action banner classes ---

    def test_all_action_classes_present(self) -> None:
        for action, state in ACTION_BANNER_STATES.items():
            cls = state["css_class"]
            assert f".{cls}" in self.css, f"Missing CSS class .{cls}"

    def test_action_banner_border_colors(self) -> None:
        for action, state in ACTION_BANNER_STATES.items():
            border = state["border_color"]
            assert border in self.css, (
                f"Missing border color {border} for {action}"
            )

    # --- Animations ---

    def test_throb_keyframes(self) -> None:
        assert "@keyframes throb" in self.css

    def test_glow_keyframes(self) -> None:
        assert "@keyframes glow" in self.css

    def test_throb_animation_reference(self) -> None:
        assert "throb 2.5s ease-in-out infinite" in self.css

    def test_glow_animation_reference(self) -> None:
        assert "glow 2s ease-in-out infinite" in self.css

    # --- Component styles ---

    def test_gauge_card_styles(self) -> None:
        assert ".gauge-card" in self.css

    def test_badge_styles(self) -> None:
        assert ".badge" in self.css
        assert ".badge-pending" in self.css
        assert ".badge-completed" in self.css

    def test_progress_rail_styles(self) -> None:
        assert ".progress-rail" in self.css

    def test_execution_grid_styles(self) -> None:
        assert ".execution-grid" in self.css

    def test_deferrals_styles(self) -> None:
        assert ".deferrals-section" in self.css

    def test_footer_styles(self) -> None:
        assert ".footer" in self.css

    def test_fallback_notice_hidden_by_default(self) -> None:
        assert ".fallback-notice" in self.css
        assert "display: none" in self.css


# ---------------------------------------------------------------------------
# No external dependencies  [CT-01]
# ---------------------------------------------------------------------------


class TestNoDependencies:
    """Module must only use Python 3.10+ stdlib."""

    def test_theme_imports_only_stdlib(self) -> None:
        """Read theme.py source and verify no non-stdlib imports."""
        theme_path = os.path.join(
            os.path.dirname(__file__), "..", "src", "wave_status", "dashboard", "theme.py"
        )
        with open(theme_path) as f:
            source = f.read()

        # Extract all import statements
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]

        # Only __future__ is allowed (it's a stdlib module)
        for line in import_lines:
            assert line.startswith("from __future__"), (
                f"Non-stdlib import found: {line}"
            )
