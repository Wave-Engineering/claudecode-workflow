"""Nerf config read/write library.

Manages session-scoped nerf configuration files at /tmp/nerf-<session_id>.json.
Provides dart scaling, mode mapping, and threshold conversion logic used by
both the /nerf skill and the post-tool-use hook.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_MODES = ("not-too-rough", "hurt-me-plenty", "ultraviolence")

DEFAULT_MODE = "hurt-me-plenty"

DEFAULT_DARTS = {
    "soft": 150_000,
    "hard": 180_000,
    "ouch": 200_000,
}

# Map doom mode names to CRYSTALLIZE_MODE values used by the crystallizer hooks
MODE_TO_CRYSTALLIZE: dict[str, str] = {
    "not-too-rough": "manual",
    "hurt-me-plenty": "prompt",
    "ultraviolence": "yolo",
}

# Reverse mapping
CRYSTALLIZE_TO_MODE: dict[str, str] = {v: k for k, v in MODE_TO_CRYSTALLIZE.items()}

# Scaling ratios for /nerf <limit> shortcut
SOFT_RATIO = 0.75
HARD_RATIO = 0.90


# ---------------------------------------------------------------------------
# Token value parsing
# ---------------------------------------------------------------------------

def parse_token_value(value: str | int | float) -> int:
    """Parse a token value like '200k', '200000', or 200000 into an integer.

    Accepts:
      - Plain integers or floats: 200000, 200000.0
      - Strings with 'k' suffix: '200k', '200K', '150.5k'
      - Strings with 'm' suffix: '1m', '1M', '0.5m'
      - Plain numeric strings: '200000'

    Returns the value as an integer (rounded down).

    Raises ValueError for unparseable input.
    """
    if isinstance(value, (int, float)):
        return int(value)

    if not isinstance(value, str):
        raise ValueError(f"Cannot parse token value: {value!r}")

    s = value.strip().lower()
    if not s:
        raise ValueError("Empty token value")

    # Match number with optional k/m suffix
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*(k|m)?$", s)
    if not m:
        raise ValueError(f"Cannot parse token value: {value!r}")

    num = float(m.group(1))
    suffix = m.group(2)

    if suffix == "k":
        num *= 1_000
    elif suffix == "m":
        num *= 1_000_000

    return int(num)


# ---------------------------------------------------------------------------
# Dart scaling
# ---------------------------------------------------------------------------

def scale_darts(ouch: int) -> dict[str, int]:
    """Given an ouch (critical) threshold, scale soft and hard proportionally.

    soft = 75% of ouch
    hard = 90% of ouch

    All values are rounded to the nearest integer.
    """
    return {
        "soft": round(ouch * SOFT_RATIO),
        "hard": round(ouch * HARD_RATIO),
        "ouch": ouch,
    }


# ---------------------------------------------------------------------------
# Config file path
# ---------------------------------------------------------------------------

def config_path(session_id: str) -> Path:
    """Return the path to the nerf config file for a given session."""
    return Path(f"/tmp/nerf-{session_id}.json")


# ---------------------------------------------------------------------------
# Config read/write
# ---------------------------------------------------------------------------

def default_config(session_id: str = "") -> dict[str, Any]:
    """Return the default nerf configuration."""
    return {
        "mode": DEFAULT_MODE,
        "darts": dict(DEFAULT_DARTS),
        "session_id": session_id,
    }


def read_config(session_id: str) -> dict[str, Any]:
    """Read the nerf config for a session.

    Returns default config if the file doesn't exist or is invalid.
    """
    p = config_path(session_id)
    if not p.exists():
        return default_config(session_id)

    try:
        data = json.loads(p.read_text())
        # Validate required fields exist
        if "mode" not in data or "darts" not in data:
            return default_config(session_id)
        # Ensure all dart fields present
        for key in ("soft", "hard", "ouch"):
            if key not in data["darts"]:
                return default_config(session_id)
        return data
    except (json.JSONDecodeError, OSError):
        return default_config(session_id)


def write_config(session_id: str, config: dict[str, Any]) -> Path:
    """Write the nerf config for a session. Returns the path written."""
    p = config_path(session_id)
    p.write_text(json.dumps(config, indent=2) + "\n")
    return p


def update_mode(session_id: str, mode: str) -> dict[str, Any]:
    """Update the mode in the session config. Returns the updated config.

    Raises ValueError if mode is invalid.
    """
    if mode not in VALID_MODES:
        raise ValueError(
            f"Invalid mode: {mode!r}. Valid modes: {', '.join(VALID_MODES)}"
        )
    cfg = read_config(session_id)
    cfg["mode"] = mode
    cfg["session_id"] = session_id
    write_config(session_id, cfg)
    return cfg


def update_darts(
    session_id: str,
    soft: int,
    hard: int,
    ouch: int,
) -> dict[str, Any]:
    """Update all three dart thresholds. Returns the updated config.

    Raises ValueError if soft >= hard or hard >= ouch.
    """
    if soft >= hard:
        raise ValueError(f"soft ({soft}) must be less than hard ({hard})")
    if hard >= ouch:
        raise ValueError(f"hard ({hard}) must be less than ouch ({ouch})")

    cfg = read_config(session_id)
    cfg["darts"] = {"soft": soft, "hard": hard, "ouch": ouch}
    cfg["session_id"] = session_id
    write_config(session_id, cfg)
    return cfg


def update_ouch_scaled(session_id: str, ouch: int) -> dict[str, Any]:
    """Set ouch and scale soft/hard proportionally. Returns the updated config."""
    darts = scale_darts(ouch)
    cfg = read_config(session_id)
    cfg["darts"] = darts
    cfg["session_id"] = session_id
    write_config(session_id, cfg)
    return cfg


# ---------------------------------------------------------------------------
# Threshold conversion for crystallizer hooks
# ---------------------------------------------------------------------------

def darts_to_percentages(darts: dict[str, int], context_limit: int) -> dict[str, float]:
    """Convert absolute dart values to percentage thresholds.

    The crystallizer hooks use percentage thresholds (0-100) of CONTEXT_LIMIT.
    This converts our absolute dart values into those percentages.

    Example: soft=150000 with context_limit=1000000 -> soft=15.0%
    """
    if context_limit <= 0:
        raise ValueError(f"context_limit must be positive, got {context_limit}")

    return {
        "warn": (darts["soft"] / context_limit) * 100,
        "danger": (darts["hard"] / context_limit) * 100,
        "critical": (darts["ouch"] / context_limit) * 100,
    }


def get_crystallize_mode(config: dict[str, Any]) -> str:
    """Get the CRYSTALLIZE_MODE value for the current nerf mode."""
    mode = config.get("mode", DEFAULT_MODE)
    return MODE_TO_CRYSTALLIZE.get(mode, "prompt")
