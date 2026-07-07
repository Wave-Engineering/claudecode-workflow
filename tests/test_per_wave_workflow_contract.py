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


class TestReviewStageThenReview:
    """ENG-5/#847: the review signal is a 2-step stage→review sub-pipeline that
    KEEPS the specialized feature-dev:code-reviewer (a stage agent materializes
    the diff for it); it never provisions off origin/main via isolation:'worktree'."""

    def test_review_is_stage_then_review(self) -> None:
        src = _wf_src()
        # A general-purpose STAGE agent runs before the reviewer.
        assert "reviewStagePrompt" in src, "review must have a stage step (reviewStagePrompt)"
        assert "gate:review:stage" in src, "the stage step must be labelled gate:review:stage"
        # ...and the reviewer runs on the staged workspace.
        assert "reviewSignalPrompt" in src, "review must still run reviewSignalPrompt"
        # Stage precedes review (staged result is awaited, then fed to reviewSignalPrompt).
        assert src.index("reviewStagePrompt") < src.index("reviewSignalPrompt"), (
            "the stage step must precede the review step"
        )

    def test_review_agent_type_preserved(self) -> None:
        # Guard against regression to general-purpose: the REVIEW step keeps the
        # specialized reviewer. (The stage step is the only general-purpose part.)
        src = _wf_src()
        assert "feature-dev:code-reviewer" in src, (
            "the review step must keep agentType feature-dev:code-reviewer (not swap to general-purpose)"
        )

    def test_no_isolation_worktree_call_site(self) -> None:
        # The stale EC-1 leftover: isolation:'worktree' provisioned off origin/main
        # (empty tree on release-branch repos). The stage step replaces it — no call
        # site may pass isolation:'worktree' anymore.
        src = _wf_src()
        assert "isolation: 'worktree'" not in src and 'isolation: "worktree"' not in src, (
            "no agent call site may use isolation:'worktree' (ENG-5 removed the empty-tree provisioning)"
        )


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


class TestFlightContract:
    """Flight kahuna-base directive — relocated from the nextwave skill's
    flight-stub-base-directive / unconditional / pr_create-base assertions."""

    def test_flight_bases_work_on_origin_kahuna(self) -> None:
        # Flights base on origin/<kahuna_branch> (the integration branch), not protected.
        src = _wf_src()
        assert "origin/" in src and "KAHUNA_BRANCH" in src, (
            "flights must base their work on origin/<kahuna_branch>"
        )

    def test_flight_pr_targets_kahuna_never_protected(self) -> None:
        # Flight PRs target the kahuna integration branch, NEVER the protected branch directly.
        src = _wf_src()
        assert "Your PR targets" in src and "NEVER" in src and "PROTECTED_BRANCH" in src, (
            "flight PRs must target KAHUNA_BRANCH, never the protected branch directly"
        )


class TestPrimePlanningAndReconcile:
    """Prime planner (non-conflicting parallel grouping) + reconcile (idempotent
    merge into kahuna) — relocated from the nextwave Prime/reconcile assertions."""

    def test_prime_partitions_non_conflicting_groups(self) -> None:
        src = _wf_src()
        assert "PRIME planner" in src, "the Prime planner node must be present"
        assert "flight_overlap" in src and "flight_partition" in src, (
            "Prime must use flight_overlap + flight_partition for non-conflicting parallel groups"
        )

    def test_reconcile_merges_into_kahuna_idempotently(self) -> None:
        src = _wf_src()
        assert "Integrate this group" in src and "KAHUNA_BRANCH" in src, (
            "reconcile must integrate this group's flights into the kahuna branch"
        )
        assert "IDEMPOTENT" in src, (
            "reconcile merge must be idempotent (skip already-merged branches)"
        )
