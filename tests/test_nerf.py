"""Tests for the nerf config read/write library.

Tests exercise REAL code paths.  Mocks are used ONLY for:
  - File system isolation via tmp_path and monkeypatch
  - No other mocking.

Covers:
  - Session config file creation, read, update
  - Dart scaling when setting ouch
  - Doom mode to crystallizer mode mapping
  - Token value parsing (150k, 200000, 1m, etc.)
  - Threshold conversion to percentages
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure the nerf lib is importable
_SKILLS_DIR = str(Path(__file__).resolve().parent.parent / "skills" / "nerf" / "lib")
sys.path.insert(0, _SKILLS_DIR)

from nerf_config import (
    DEFAULT_DARTS,
    DEFAULT_MODE,
    HARD_RATIO,
    MODE_TO_CRYSTALLIZE,
    SOFT_RATIO,
    VALID_MODES,
    config_path,
    darts_to_percentages,
    default_config,
    get_crystallize_mode,
    parse_token_value,
    read_config,
    scale_darts,
    update_darts,
    update_mode,
    update_ouch_scaled,
    write_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def session_id():
    """Return a test session ID."""
    return "test-session-abc123"


@pytest.fixture()
def nerf_tmp(tmp_path, monkeypatch, session_id):
    """Redirect nerf config path to tmp_path for isolation.

    Monkeypatches config_path so all reads/writes go to tmp_path.
    """
    def _config_path(sid: str) -> Path:
        return tmp_path / f"nerf-{sid}.json"

    import nerf_config
    monkeypatch.setattr(nerf_config, "config_path", _config_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Token value parsing
# ---------------------------------------------------------------------------

class TestParseTokenValue:
    """Tests for parse_token_value()."""

    def test_plain_integer(self):
        assert parse_token_value(200000) == 200000

    def test_plain_float(self):
        assert parse_token_value(200000.0) == 200000

    def test_string_plain_number(self):
        assert parse_token_value("200000") == 200000

    def test_string_k_suffix(self):
        assert parse_token_value("200k") == 200000

    def test_string_k_suffix_uppercase(self):
        assert parse_token_value("200K") == 200000

    def test_string_k_suffix_decimal(self):
        assert parse_token_value("150.5k") == 150500

    def test_string_m_suffix(self):
        assert parse_token_value("1m") == 1000000

    def test_string_m_suffix_decimal(self):
        assert parse_token_value("0.5m") == 500000

    def test_string_with_whitespace(self):
        assert parse_token_value("  200k  ") == 200000

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty token value"):
            parse_token_value("")

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_token_value("abc")

    def test_negative_number(self):
        # Negative numbers don't match our pattern (no leading minus)
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_token_value("-100k")

    def test_non_string_non_numeric_raises(self):
        with pytest.raises(ValueError, match="Cannot parse"):
            parse_token_value([200])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Dart scaling
# ---------------------------------------------------------------------------

class TestDartScaling:
    """Tests for scale_darts() and the scaling ratios."""

    def test_default_ouch_200k(self):
        darts = scale_darts(200000)
        assert darts["soft"] == 150000
        assert darts["hard"] == 180000
        assert darts["ouch"] == 200000

    def test_ouch_500k(self):
        darts = scale_darts(500000)
        assert darts["soft"] == 375000  # 500k * 0.75
        assert darts["hard"] == 450000  # 500k * 0.90
        assert darts["ouch"] == 500000

    def test_ouch_1m(self):
        darts = scale_darts(1000000)
        assert darts["soft"] == 750000
        assert darts["hard"] == 900000
        assert darts["ouch"] == 1000000

    def test_ratios_are_correct(self):
        assert SOFT_RATIO == 0.75
        assert HARD_RATIO == 0.90

    def test_ordering_always_maintained(self):
        """For any positive ouch, soft < hard < ouch."""
        for ouch in [100, 1000, 100000, 500000, 1000000]:
            darts = scale_darts(ouch)
            assert darts["soft"] < darts["hard"] < darts["ouch"]


# ---------------------------------------------------------------------------
# Mode mapping
# ---------------------------------------------------------------------------

class TestModeMapping:
    """Tests for doom mode to crystallizer mode mapping."""

    def test_not_too_rough_maps_to_manual(self):
        assert MODE_TO_CRYSTALLIZE["not-too-rough"] == "manual"

    def test_hurt_me_plenty_maps_to_prompt(self):
        assert MODE_TO_CRYSTALLIZE["hurt-me-plenty"] == "prompt"

    def test_ultraviolence_maps_to_yolo(self):
        assert MODE_TO_CRYSTALLIZE["ultraviolence"] == "yolo"

    def test_all_valid_modes_have_mapping(self):
        for mode in VALID_MODES:
            assert mode in MODE_TO_CRYSTALLIZE

    def test_default_mode_is_hurt_me_plenty(self):
        assert DEFAULT_MODE == "hurt-me-plenty"

    def test_get_crystallize_mode_default(self):
        cfg = {"mode": "hurt-me-plenty"}
        assert get_crystallize_mode(cfg) == "prompt"

    def test_get_crystallize_mode_ultraviolence(self):
        cfg = {"mode": "ultraviolence"}
        assert get_crystallize_mode(cfg) == "yolo"

    def test_get_crystallize_mode_not_too_rough(self):
        cfg = {"mode": "not-too-rough"}
        assert get_crystallize_mode(cfg) == "manual"

    def test_get_crystallize_mode_missing_key(self):
        """Missing mode key falls back to default -> prompt."""
        cfg = {}
        assert get_crystallize_mode(cfg) == "prompt"


# ---------------------------------------------------------------------------
# Config read/write
# ---------------------------------------------------------------------------

class TestConfigReadWrite:
    """Tests for session config file creation, read, update."""

    def test_config_path_format(self, session_id):
        p = config_path(session_id)
        assert p == Path(f"/tmp/nerf-{session_id}.json")

    def test_default_config(self, session_id):
        cfg = default_config(session_id)
        assert cfg["mode"] == DEFAULT_MODE
        assert cfg["darts"] == DEFAULT_DARTS
        assert cfg["session_id"] == session_id

    def test_read_nonexistent_returns_defaults(self, nerf_tmp, session_id):
        cfg = read_config(session_id)
        assert cfg["mode"] == DEFAULT_MODE
        assert cfg["darts"]["soft"] == 150000
        assert cfg["darts"]["hard"] == 180000
        assert cfg["darts"]["ouch"] == 200000

    def test_write_then_read(self, nerf_tmp, session_id):
        original = {
            "mode": "ultraviolence",
            "darts": {"soft": 100000, "hard": 150000, "ouch": 200000},
            "session_id": session_id,
        }
        write_config(session_id, original)

        loaded = read_config(session_id)
        assert loaded["mode"] == "ultraviolence"
        assert loaded["darts"]["soft"] == 100000
        assert loaded["darts"]["hard"] == 150000
        assert loaded["darts"]["ouch"] == 200000

    def test_write_creates_valid_json(self, nerf_tmp, session_id):
        cfg = default_config(session_id)
        p = write_config(session_id, cfg)
        raw = p.read_text()
        parsed = json.loads(raw)
        assert parsed == cfg

    def test_read_corrupt_file_returns_defaults(self, nerf_tmp, session_id):
        """Corrupt JSON should fall back to defaults."""
        import nerf_config
        p = nerf_config.config_path(session_id)
        p.write_text("NOT VALID JSON {{{")
        cfg = read_config(session_id)
        assert cfg["mode"] == DEFAULT_MODE

    def test_read_missing_mode_returns_defaults(self, nerf_tmp, session_id):
        """Config missing 'mode' field falls back to defaults."""
        import nerf_config
        p = nerf_config.config_path(session_id)
        p.write_text(json.dumps({"darts": {"soft": 1, "hard": 2, "ouch": 3}}))
        cfg = read_config(session_id)
        assert cfg["mode"] == DEFAULT_MODE

    def test_read_missing_dart_field_returns_defaults(self, nerf_tmp, session_id):
        """Config with incomplete darts falls back to defaults."""
        import nerf_config
        p = nerf_config.config_path(session_id)
        p.write_text(json.dumps({
            "mode": "ultraviolence",
            "darts": {"soft": 100, "hard": 200},  # missing ouch
        }))
        cfg = read_config(session_id)
        assert cfg["darts"] == DEFAULT_DARTS


# ---------------------------------------------------------------------------
# Mode updates
# ---------------------------------------------------------------------------

class TestUpdateMode:
    """Tests for update_mode()."""

    def test_set_ultraviolence(self, nerf_tmp, session_id):
        cfg = update_mode(session_id, "ultraviolence")
        assert cfg["mode"] == "ultraviolence"
        # Verify persisted
        loaded = read_config(session_id)
        assert loaded["mode"] == "ultraviolence"

    def test_set_not_too_rough(self, nerf_tmp, session_id):
        cfg = update_mode(session_id, "not-too-rough")
        assert cfg["mode"] == "not-too-rough"

    def test_invalid_mode_raises(self, nerf_tmp, session_id):
        with pytest.raises(ValueError, match="Invalid mode"):
            update_mode(session_id, "nightmare")

    def test_mode_update_preserves_darts(self, nerf_tmp, session_id):
        """Changing mode should not alter dart thresholds."""
        update_darts(session_id, 100000, 150000, 200000)
        cfg = update_mode(session_id, "ultraviolence")
        assert cfg["darts"]["soft"] == 100000
        assert cfg["darts"]["hard"] == 150000
        assert cfg["darts"]["ouch"] == 200000


# ---------------------------------------------------------------------------
# Dart updates
# ---------------------------------------------------------------------------

class TestUpdateDarts:
    """Tests for update_darts() and update_ouch_scaled()."""

    def test_set_explicit_darts(self, nerf_tmp, session_id):
        cfg = update_darts(session_id, 100000, 150000, 200000)
        assert cfg["darts"]["soft"] == 100000
        assert cfg["darts"]["hard"] == 150000
        assert cfg["darts"]["ouch"] == 200000

    def test_darts_persisted(self, nerf_tmp, session_id):
        update_darts(session_id, 100000, 150000, 200000)
        loaded = read_config(session_id)
        assert loaded["darts"]["ouch"] == 200000

    def test_soft_ge_hard_raises(self, nerf_tmp, session_id):
        with pytest.raises(ValueError, match="soft.*must be less than hard"):
            update_darts(session_id, 200000, 200000, 300000)

    def test_hard_ge_ouch_raises(self, nerf_tmp, session_id):
        with pytest.raises(ValueError, match="hard.*must be less than ouch"):
            update_darts(session_id, 100000, 300000, 300000)

    def test_darts_update_preserves_mode(self, nerf_tmp, session_id):
        """Changing darts should not alter the mode."""
        update_mode(session_id, "ultraviolence")
        cfg = update_darts(session_id, 100000, 150000, 200000)
        assert cfg["mode"] == "ultraviolence"

    def test_ouch_scaled_200k(self, nerf_tmp, session_id):
        cfg = update_ouch_scaled(session_id, 200000)
        assert cfg["darts"]["soft"] == 150000
        assert cfg["darts"]["hard"] == 180000
        assert cfg["darts"]["ouch"] == 200000

    def test_ouch_scaled_500k(self, nerf_tmp, session_id):
        cfg = update_ouch_scaled(session_id, 500000)
        assert cfg["darts"]["soft"] == 375000
        assert cfg["darts"]["hard"] == 450000
        assert cfg["darts"]["ouch"] == 500000

    def test_ouch_scaled_preserves_mode(self, nerf_tmp, session_id):
        """Scaling ouch should not alter the mode."""
        update_mode(session_id, "not-too-rough")
        cfg = update_ouch_scaled(session_id, 300000)
        assert cfg["mode"] == "not-too-rough"


# ---------------------------------------------------------------------------
# Threshold conversion
# ---------------------------------------------------------------------------

class TestDartsToPercentages:
    """Tests for darts_to_percentages()."""

    def test_defaults_against_1m_window(self):
        """Default darts against 1M window should give small percentages."""
        pcts = darts_to_percentages(DEFAULT_DARTS, 1_000_000)
        assert pcts["warn"] == pytest.approx(15.0)
        assert pcts["danger"] == pytest.approx(18.0)
        assert pcts["critical"] == pytest.approx(20.0)

    def test_defaults_against_200k_window(self):
        """Default darts against old 200k window match original percentages."""
        pcts = darts_to_percentages(DEFAULT_DARTS, 200_000)
        assert pcts["warn"] == pytest.approx(75.0)
        assert pcts["danger"] == pytest.approx(90.0)
        assert pcts["critical"] == pytest.approx(100.0)

    def test_custom_darts(self):
        darts = {"soft": 375000, "hard": 450000, "ouch": 500000}
        pcts = darts_to_percentages(darts, 1_000_000)
        assert pcts["warn"] == pytest.approx(37.5)
        assert pcts["danger"] == pytest.approx(45.0)
        assert pcts["critical"] == pytest.approx(50.0)

    def test_zero_context_limit_raises(self):
        with pytest.raises(ValueError, match="context_limit must be positive"):
            darts_to_percentages(DEFAULT_DARTS, 0)

    def test_negative_context_limit_raises(self):
        with pytest.raises(ValueError, match="context_limit must be positive"):
            darts_to_percentages(DEFAULT_DARTS, -100)
