"""Tests for src/wave_status/deferrals.py — deferral lifecycle management.

Tests exercise real code paths against the deferrals module.
No mocking of the module under test.
"""

from __future__ import annotations

import copy
import sys
import os

import pytest

# Ensure the src directory is on the import path so we can import the module
# directly without installing it as a package.
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), os.pardir, "src"),
)

from wave_status.deferrals import (
    VALID_RISK_LEVELS,
    accept,
    accepted_count,
    accepted_list,
    defer,
    pending_count,
    pending_list,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _empty_state() -> dict:
    """Return a minimal state_data dict with an empty deferrals list."""
    return {"deferrals": []}


def _state_with_deferrals() -> dict:
    """Return state_data with three deferrals (2 pending, 1 accepted)."""
    return {
        "deferrals": [
            {
                "wave": "wave-1",
                "description": "First deferral",
                "risk": "low",
                "status": "pending",
            },
            {
                "wave": "wave-1",
                "description": "Second deferral",
                "risk": "medium",
                "status": "accepted",
            },
            {
                "wave": "wave-2",
                "description": "Third deferral",
                "risk": "high",
                "status": "pending",
            },
        ]
    }


# ---------------------------------------------------------------------------
# defer() tests
# ---------------------------------------------------------------------------

class TestDefer:
    """Tests for the defer() function."""

    def test_defer_appends_pending_deferral(self) -> None:
        """defer() appends a deferral dict with status 'pending' [R-09]."""
        state = _empty_state()
        defer(state, "CP-01 human review", "low", "wave-1")

        assert len(state["deferrals"]) == 1
        d = state["deferrals"][0]
        assert d["description"] == "CP-01 human review"
        assert d["risk"] == "low"
        assert d["status"] == "pending"
        assert d["wave"] == "wave-1"

    def test_defer_appends_to_existing_deferrals(self) -> None:
        """defer() appends without disturbing existing entries."""
        state = _state_with_deferrals()
        original_count = len(state["deferrals"])
        defer(state, "New item", "high", "wave-3")

        assert len(state["deferrals"]) == original_count + 1
        new = state["deferrals"][-1]
        assert new["description"] == "New item"
        assert new["risk"] == "high"
        assert new["status"] == "pending"
        assert new["wave"] == "wave-3"

    @pytest.mark.parametrize("risk", ["low", "medium", "high"])
    def test_defer_accepts_valid_risk_levels(self, risk: str) -> None:
        """defer() succeeds for each valid risk level."""
        state = _empty_state()
        defer(state, f"Test {risk}", risk, "wave-1")
        assert state["deferrals"][-1]["risk"] == risk

    @pytest.mark.parametrize(
        "bad_risk",
        ["critical", "LOW", "Medium", "HIGH", "", "none", "urgent", "5"],
    )
    def test_defer_rejects_invalid_risk_levels(self, bad_risk: str) -> None:
        """defer() raises ValueError for risk levels outside {low, medium, high} [R-15]."""
        state = _empty_state()
        with pytest.raises(ValueError, match="Error:.*Invalid risk level"):
            defer(state, "Should fail", bad_risk, "wave-1")
        # State must be unmodified on failure
        assert len(state["deferrals"]) == 0

    def test_defer_error_message_format(self) -> None:
        """Error message follows 'Error: <what>. <fix>.' pattern [R-32]."""
        state = _empty_state()
        with pytest.raises(ValueError) as exc_info:
            defer(state, "Bad risk", "critical", "wave-1")
        msg = str(exc_info.value)
        assert msg.startswith("Error:")
        # Should contain guidance on valid values
        assert "low" in msg
        assert "medium" in msg
        assert "high" in msg

    def test_defer_records_current_wave(self) -> None:
        """defer() records the current_wave in the deferral dict."""
        state = _empty_state()
        defer(state, "Wave 2 item", "medium", "wave-2")
        assert state["deferrals"][0]["wave"] == "wave-2"

    def test_defer_modifies_in_place(self) -> None:
        """defer() mutates state_data in place and returns None."""
        state = _empty_state()
        result = defer(state, "In-place test", "low", "wave-1")
        assert result is None
        assert len(state["deferrals"]) == 1


# ---------------------------------------------------------------------------
# accept() tests
# ---------------------------------------------------------------------------

class TestAccept:
    """Tests for the accept() function."""

    def test_accept_transitions_pending_to_accepted(self) -> None:
        """accept() transitions a pending deferral to accepted [R-10]."""
        state = _empty_state()
        defer(state, "To accept", "low", "wave-1")
        accept(state, 1)
        assert state["deferrals"][0]["status"] == "accepted"

    def test_accept_uses_one_based_index(self) -> None:
        """accept() treats index as 1-based (matches dashboard display)."""
        state = _empty_state()
        defer(state, "First", "low", "wave-1")
        defer(state, "Second", "medium", "wave-1")
        defer(state, "Third", "high", "wave-1")

        accept(state, 2)
        assert state["deferrals"][0]["status"] == "pending"
        assert state["deferrals"][1]["status"] == "accepted"
        assert state["deferrals"][2]["status"] == "pending"

    def test_accept_rejects_index_zero(self) -> None:
        """accept() rejects index 0 (1-based, so 0 is out of range) [R-16]."""
        state = _empty_state()
        defer(state, "Item", "low", "wave-1")
        with pytest.raises(ValueError, match="Error:.*out of range"):
            accept(state, 0)
        # Deferral must remain pending
        assert state["deferrals"][0]["status"] == "pending"

    def test_accept_rejects_negative_index(self) -> None:
        """accept() rejects negative indices [R-16]."""
        state = _empty_state()
        defer(state, "Item", "low", "wave-1")
        with pytest.raises(ValueError, match="Error:.*out of range"):
            accept(state, -1)

    def test_accept_rejects_index_too_high(self) -> None:
        """accept() rejects index beyond the deferrals list [R-16]."""
        state = _empty_state()
        defer(state, "Item", "low", "wave-1")
        with pytest.raises(ValueError, match="Error:.*out of range"):
            accept(state, 2)

    def test_accept_rejects_index_on_empty_list(self) -> None:
        """accept() rejects any index when there are no deferrals [R-16]."""
        state = _empty_state()
        with pytest.raises(ValueError, match="Error:.*out of range"):
            accept(state, 1)

    def test_accept_rejects_already_accepted_deferral(self) -> None:
        """accept() rejects a deferral that is already accepted [R-16]."""
        state = _empty_state()
        defer(state, "Already done", "low", "wave-1")
        accept(state, 1)
        with pytest.raises(ValueError, match="Error:.*already"):
            accept(state, 1)

    def test_accept_error_message_format_out_of_range(self) -> None:
        """Out-of-range error follows 'Error: <what>. <fix>.' pattern [R-32]."""
        state = _empty_state()
        with pytest.raises(ValueError) as exc_info:
            accept(state, 5)
        msg = str(exc_info.value)
        assert msg.startswith("Error:")

    def test_accept_error_message_format_already_accepted(self) -> None:
        """Already-accepted error follows 'Error: <what>. <fix>.' pattern [R-32]."""
        state = _empty_state()
        defer(state, "Item", "low", "wave-1")
        accept(state, 1)
        with pytest.raises(ValueError) as exc_info:
            accept(state, 1)
        msg = str(exc_info.value)
        assert msg.startswith("Error:")
        assert "accepted" in msg.lower()

    def test_accept_preserves_other_fields(self) -> None:
        """accept() only changes status, preserving wave/description/risk."""
        state = _empty_state()
        defer(state, "Preserve me", "high", "wave-3")
        accept(state, 1)
        d = state["deferrals"][0]
        assert d["wave"] == "wave-3"
        assert d["description"] == "Preserve me"
        assert d["risk"] == "high"
        assert d["status"] == "accepted"

    def test_accept_modifies_in_place(self) -> None:
        """accept() mutates state_data in place and returns None."""
        state = _empty_state()
        defer(state, "In-place", "low", "wave-1")
        result = accept(state, 1)
        assert result is None


# ---------------------------------------------------------------------------
# Query helper tests
# ---------------------------------------------------------------------------

class TestPendingCount:
    """Tests for pending_count()."""

    def test_zero_on_empty(self) -> None:
        assert pending_count(_empty_state()) == 0

    def test_counts_only_pending(self) -> None:
        state = _state_with_deferrals()
        # Fixture has 2 pending, 1 accepted
        assert pending_count(state) == 2

    def test_decreases_after_accept(self) -> None:
        state = _empty_state()
        defer(state, "A", "low", "wave-1")
        defer(state, "B", "medium", "wave-1")
        assert pending_count(state) == 2
        accept(state, 1)
        assert pending_count(state) == 1


class TestAcceptedCount:
    """Tests for accepted_count()."""

    def test_zero_on_empty(self) -> None:
        assert accepted_count(_empty_state()) == 0

    def test_counts_only_accepted(self) -> None:
        state = _state_with_deferrals()
        # Fixture has 2 pending, 1 accepted
        assert accepted_count(state) == 1

    def test_increases_after_accept(self) -> None:
        state = _empty_state()
        defer(state, "A", "low", "wave-1")
        assert accepted_count(state) == 0
        accept(state, 1)
        assert accepted_count(state) == 1


class TestPendingList:
    """Tests for pending_list()."""

    def test_empty_on_empty_state(self) -> None:
        assert pending_list(_empty_state()) == []

    def test_returns_only_pending_deferrals(self) -> None:
        state = _state_with_deferrals()
        result = pending_list(state)
        assert len(result) == 2
        assert all(d["status"] == "pending" for d in result)

    def test_returns_copies_in_correct_order(self) -> None:
        """pending_list() returns items in their original order."""
        state = _state_with_deferrals()
        result = pending_list(state)
        assert result[0]["description"] == "First deferral"
        assert result[1]["description"] == "Third deferral"

    def test_empty_when_all_accepted(self) -> None:
        state = _empty_state()
        defer(state, "A", "low", "wave-1")
        accept(state, 1)
        assert pending_list(state) == []


class TestAcceptedList:
    """Tests for accepted_list()."""

    def test_empty_on_empty_state(self) -> None:
        assert accepted_list(_empty_state()) == []

    def test_returns_only_accepted_deferrals(self) -> None:
        state = _state_with_deferrals()
        result = accepted_list(state)
        assert len(result) == 1
        assert all(d["status"] == "accepted" for d in result)
        assert result[0]["description"] == "Second deferral"

    def test_grows_after_accepting(self) -> None:
        state = _empty_state()
        defer(state, "A", "low", "wave-1")
        defer(state, "B", "high", "wave-1")
        accept(state, 1)
        accept(state, 2)
        result = accepted_list(state)
        assert len(result) == 2
        assert result[0]["description"] == "A"
        assert result[1]["description"] == "B"


# ---------------------------------------------------------------------------
# VALID_RISK_LEVELS constant test
# ---------------------------------------------------------------------------

class TestValidRiskLevels:
    """Tests for the VALID_RISK_LEVELS constant."""

    def test_contains_exactly_three_levels(self) -> None:
        assert VALID_RISK_LEVELS == {"low", "medium", "high"}

    def test_is_a_set(self) -> None:
        assert isinstance(VALID_RISK_LEVELS, set)


# ---------------------------------------------------------------------------
# No external imports test
# ---------------------------------------------------------------------------

class TestNoExternalImports:
    """Verify deferrals.py uses only Python stdlib [CT-01]."""

    def test_no_third_party_imports(self) -> None:
        """Read the source and verify no non-stdlib imports."""
        import ast

        src_path = os.path.join(
            os.path.dirname(__file__),
            os.pardir,
            "src",
            "wave_status",
            "deferrals.py",
        )
        with open(src_path) as f:
            tree = ast.parse(f.read())

        # Collect all imported module names
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module is not None:
                    imports.add(node.module.split(".")[0])

        # __future__ is always acceptable
        imports.discard("__future__")

        # All remaining imports should be stdlib
        # For Python 3.10+, we check against sys.stdlib_module_names
        stdlib = sys.stdlib_module_names
        non_stdlib = imports - stdlib
        assert non_stdlib == set(), (
            f"Non-stdlib imports found: {non_stdlib}"
        )
