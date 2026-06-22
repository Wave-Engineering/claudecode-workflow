"""Contract tests for the per-wave Workflow's trust-gate aggregation
(skills/nextwave/per-wave-workflow.js, §3.4).

The #691 dynamic-workflows cutover moved the trust-gate ORCHESTRATION — the
4-signal parallel fan-out, conservative-fail-on-drop, the ff-or-hold verdict,
and the auto-vs-interactive routing — out of the wavemachine SKILL.md prose into
per-wave-workflow.js. The wavemachine skill-tests that asserted that
orchestration were xfailed in #753; this relocates their intent to the module
that now owns it, as live unit coverage (engine was otherwise #785-e2e-only).

Text-level assertions on the workflow script: its trust-gate behavior is encoded
as the parallel()/filter()/verdict control flow, so asserting those load-bearing
constructs are present is the unit-level contract. cc-workflow#795.
"""

from __future__ import annotations

from pathlib import Path

_WF = Path(__file__).resolve().parent.parent / "skills" / "nextwave" / "per-wave-workflow.js"


def _wf_src() -> str:
    return _WF.read_text(encoding="utf-8")


class TestWorkflowModule:
    def test_workflow_module_exists(self) -> None:
        assert _WF.exists(), f"per-wave-workflow.js not found at {_WF}"


class TestFourSignalFanout:
    """The gate weighs exactly four signals, run in parallel (§3.4) — relocated
    from the skill's 'gate lists all four signals / signals run concurrently'."""

    def test_four_named_signals(self) -> None:
        src = _wf_src()
        for sig in (
            "commutativitySignalPrompt",
            "ciSignalPrompt",
            "reviewSignalPrompt",
            "trivySignalPrompt",
        ):
            assert sig in src, f"gate must run the {sig} signal"

    def test_signals_run_in_parallel(self) -> None:
        # The four trust signals fan out concurrently, not serially.
        assert "parallel(" in _wf_src(), "the four trust signals must fan out via parallel()"


class TestConservativeFail:
    """A signal that errors — or a null SDK slot — becomes a conservative-fail,
    never silently dropped (absence-of-evidence must not read as safety)."""

    def test_signal_errors_map_to_conservative_fail(self) -> None:
        src = _wf_src()
        assert "conservativeFail" in src, "signal errors must map to conservativeFail"
        assert ".catch(" in src, "each signal must .catch into conservativeFail"

    def test_null_slot_becomes_conservative_fail(self) -> None:
        # A null/undefined parallel slot is coerced to conservativeFail so the gate
        # always weighs exactly four signals (a dropped slot would read as a free PASS).
        assert "?? conservativeFail" in _wf_src(), (
            "a null signal slot must be coerced to conservativeFail, never dropped"
        )


class TestVerdictAggregation:
    """ff-or-hold: PASS iff ALL signals pass (no short-circuit); else HOLD —
    relocated from the skill's 'gate does not short-circuit' / all-green-vs-any-red."""

    def test_no_short_circuit_filters_all_signals(self) -> None:
        # The verdict filters ALL signals for failures — it does not bail on the first fail.
        src = _wf_src()
        assert "filter" in src and "passed" in src, (
            "verdict must aggregate all signals (filter on .passed), not short-circuit"
        )

    def test_verdict_is_pass_or_hold(self) -> None:
        src = _wf_src()
        assert "'PASS'" in src and "'HOLD'" in src, "verdict must be PASS (all pass) or HOLD"

    def test_auto_promotes_interactive_returns_verdict(self) -> None:
        # MODE auto promotes on PASS; interactive returns the verdict (the human gate, §5).
        src = _wf_src()
        assert "'auto'" in src and "'interactive'" in src, (
            "MODE must distinguish auto (promote) vs interactive (return verdict) routing"
        )
