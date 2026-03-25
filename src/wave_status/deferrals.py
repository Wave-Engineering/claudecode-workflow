"""Deferral lifecycle management.

Creates, validates, transitions, and queries deferrals. All functions
operate on state-data dicts passed as arguments -- I/O responsibility
stays in state.py.
"""

from __future__ import annotations

VALID_RISK_LEVELS = {"low", "medium", "high"}


# ---------------------------------------------------------------------------
# Mutation operations
# ---------------------------------------------------------------------------

def defer(state_data: dict, description: str, risk: str, current_wave: str) -> None:
    """Append a new deferral with status ``pending``.

    Parameters
    ----------
    state_data:
        The loaded state dict (must contain a ``"deferrals"`` list).
    description:
        Human-readable description of the deferred item.
    risk:
        One of ``low``, ``medium``, or ``high``.
    current_wave:
        The wave identifier (e.g. ``"wave-1"``) under which this
        deferral is recorded.

    Raises
    ------
    ValueError
        If *risk* is not one of the valid levels.
    """
    if risk not in VALID_RISK_LEVELS:
        raise ValueError(
            f"Error: Invalid risk level '{risk}'. "
            f"Use one of: low, medium, high."
        )

    deferral = {
        "wave": current_wave,
        "description": description,
        "risk": risk,
        "status": "pending",
    }
    state_data["deferrals"].append(deferral)


def accept(state_data: dict, index: int) -> None:
    """Transition a deferral from ``pending`` to ``accepted``.

    Parameters
    ----------
    state_data:
        The loaded state dict (must contain a ``"deferrals"`` list).
    index:
        1-based index into the deferrals list.

    Raises
    ------
    ValueError
        If *index* is out of range or the deferral is not ``pending``.
    """
    deferrals = state_data["deferrals"]
    count = len(deferrals)

    if count == 0:
        raise ValueError(
            f"Error: Deferral index {index} out of range. "
            f"No deferrals exist."
        )

    if index < 1 or index > count:
        raise ValueError(
            f"Error: Deferral index {index} out of range. "
            f"Valid range is 1..{count}."
        )

    zero_index = index - 1
    deferral = deferrals[zero_index]

    if deferral["status"] != "pending":
        raise ValueError(
            f"Error: Deferral {index} is already '{deferral['status']}'. "
            f"Only pending deferrals can be accepted."
        )

    deferral["status"] = "accepted"


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def pending_count(state_data: dict) -> int:
    """Return the number of deferrals with status ``pending``."""
    return sum(1 for d in state_data["deferrals"] if d["status"] == "pending")


def accepted_count(state_data: dict) -> int:
    """Return the number of deferrals with status ``accepted``."""
    return sum(1 for d in state_data["deferrals"] if d["status"] == "accepted")


def pending_list(state_data: dict) -> list[dict]:
    """Return the sublist of deferrals with status ``pending``."""
    return [d for d in state_data["deferrals"] if d["status"] == "pending"]


def accepted_list(state_data: dict) -> list[dict]:
    """Return the sublist of deferrals with status ``accepted``."""
    return [d for d in state_data["deferrals"] if d["status"] == "accepted"]
