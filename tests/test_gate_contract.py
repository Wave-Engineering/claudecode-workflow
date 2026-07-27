"""Contract tests for the per-wave trust gate (skills/nextwave/gate.js).

The #691 dynamic-workflows cutover relocated the trust-gate signal logic OUT of
the wavemachine/nextwave SKILL.md driver prose INTO gate.js — the prompt-
generating module the per-wave Workflow runs. The wavemachine/nextwave skill-
tests that asserted those signals lived in the SKILL were xfailed in #753
("relocated to per-wave-workflow.js"); THIS file is the relocation target — it
asserts the gate-signal contract against gate.js itself, where the logic now
lives, at the unit level. (Before this, the engine's only coverage of these
contracts was the #785 e2e smoke.)

Text-level assertions on the prompt-generating module: the gate's "code" is the
prompts it emits, so asserting the load-bearing tokens are present is the
unit-level contract. cc-workflow#795.
"""

from __future__ import annotations

from pathlib import Path

_GATE_JS = Path(__file__).resolve().parent.parent / "skills" / "nextwave" / "gate.js"


def _gate_src() -> str:
    return _GATE_JS.read_text(encoding="utf-8")


class TestGateModule:
    def test_gate_module_exists(self) -> None:
        assert _GATE_JS.exists(), f"gate.js not found at {_GATE_JS}"


class TestCommutativitySignal:
    """Commutativity trust signal — relocated from the wavemachine skill's
    Trust-Score Gate / R-23 / PROBE_UNAVAILABLE assertions."""

    def test_signal_calls_commutativity_verify(self) -> None:
        src = _gate_src()
        assert "commutativitySignalPrompt" in src, "commutativity signal prompt missing"
        assert "commutativity_verify" in src, "gate must call commutativity_verify"

    def test_single_target_mode(self) -> None:
        # The kahuna composed diff is one changeset vs the protected base.
        assert "SINGLE-TARGET" in _gate_src(), "commutativity must run in SINGLE-TARGET mode"

    def test_pass_predicate_is_strong_or_medium(self) -> None:
        src = _gate_src()
        assert "STRONG" in src and "MEDIUM" in src, (
            "pass predicate (verdict in {STRONG, MEDIUM}) missing"
        )

    def test_probe_unavailable_and_oracle_required_conservative_fail(self) -> None:
        # The gate HOLDs (does not auto-promote) on PROBE_UNAVAILABLE / ORACLE_REQUIRED.
        src = _gate_src()
        assert "PROBE_UNAVAILABLE" in src, "PROBE_UNAVAILABLE handling missing"
        assert "ORACLE_REQUIRED" in src, "ORACLE_REQUIRED handling missing"


class TestPromotionContract:
    """kahuna->protected promotion — relocated from the wave_finalize /
    pr_merge / all-green-promotes / any-red-holds assertions."""

    def test_open_promotion_pr_uses_wave_finalize(self) -> None:
        src = _gate_src()
        assert "openPromotionPrPrompt" in src, "promotion PR-open prompt missing"
        assert "wave_finalize" in src, "promotion PR-open must call wave_finalize"

    def test_promotion_merges_without_skip_train(self) -> None:
        # #898: the fleet is queue-less — there is no merge queue or merge train, so there is
        # nothing for skip_train to skip. Asserted NEGATIVELY so re-introducing the flag (and
        # with it the assumption that a queue exists) fails the build.
        src = _gate_src()
        assert "promotePrompt" in src, "promotion prompt missing"
        assert "pr_merge" in src, "promotion must call pr_merge"
        assert "skip_train" not in src, (
            "promotion must NOT pass skip_train — the fleet is queue-less (#898); "
            "the flag presumes a merge queue/train that no longer exists"
        )

    def test_promotion_targets_kahuna_to_integration_base(self) -> None:
        # Flights never merge straight to the integration base — only kahuna->base promotes.
        src = _gate_src()
        assert "kahunaBranch" in src and "integrationBase" in src, (
            "promotion must route kahuna_branch -> integration_base"
        )

    def test_gate_takes_no_protected_branch_target(self) -> None:
        # #1052: the integration base is NOT necessarily the protected branch — inside a campaign
        # it is the campaign branch, and the protected branch is written exactly once, by the
        # campaign's release gate. Asserted NEGATIVELY: a `protectedBranch` PARAMETER on any gate
        # node is how the next wrong-target merge gets written (a caller passing a campaign branch
        # into a param named `protectedBranch` reads as authorization to touch trunk). Prose may
        # name the protected branch; a parameter may not.
        src = _gate_src()
        for bad in ("protectedBranch,", "protectedBranch }", "protectedBranch }}", "${protectedBranch}"):
            assert bad not in src, (
                f"gate.js must not take a protectedBranch parameter (found {bad!r}) — "
                "the merge target is integrationBase (#1052)"
            )


class TestPromotionLifecycle:
    """kahuna-branch lifecycle on promotion — relocated from the all-green /
    any-red kahuna-handling skill assertions (#722, retired in-campaign by #1052)."""

    def test_preserve_kahuna_flag_survives_for_standalone(self) -> None:
        # #722 gave a per-plan kahuna the ability to PERSIST across waves. #1052 retires that
        # NEED inside a campaign (the campaign branch carries cross-wave state, so each wave's
        # kahuna is disposable again — which is what makes a squash merge harmless, #892). The
        # flag itself must still exist: a STANDALONE /nextwave run has no campaign branch, so
        # its caller may still ask for a surviving kahuna.
        assert "preserveKahuna" in _gate_src(), (
            "promotion must still honor preserveKahuna for standalone waves (#722/#1052)"
        )

    def test_deletes_disposable_per_wave_kahuna(self) -> None:
        # Default (non-preserve): the per-wave integration branch is disposable.
        src = _gate_src()
        assert "--delete" in src and "delete the" in src, (
            "promotion must delete the disposable per-wave kahuna after landing"
        )

    def test_promoted_true_only_if_merge_landed(self) -> None:
        # promoted must reflect actually-landed, never merge-requested-but-pending.
        # Promoted = delivered: confirm the merge is observable on the protected branch.
        src = _gate_src()
        assert "promoted" in src, "promote must return a promoted flag"
        assert "pr_merge_wait" in src, (
            "promotion must confirm the merge actually landed on the protected branch "
            "(not treat a pending merge as done)"
        )


class TestCiSignal:
    """CI trust signal — waits on the kahuna->protected MERGE-RESULT pipeline.
    #1035: bounded ci_wait_run + a direct /merge-pipeline fallback so the signal no
    longer over-waits ~30-57 min/wave on GitLab's head_pipeline freshness race."""

    def test_signal_ci_waits_on_the_merge_result(self) -> None:
        src = _gate_src()
        assert "ciSignalPrompt" in src, "ci signal prompt missing"
        assert "ci_wait_run" in src and "require_merge_result" in src, (
            "ci signal must ci_wait_run on the merge-result pipeline"
        )

    def test_ci_wait_run_is_bounded(self) -> None:
        # #1035 bleed fix: with no explicit timeout the tool rode its ~1800s idle default
        # and burned ~30-57 min/wave to confirm a <3-min pipeline. Bound it explicitly.
        src = _gate_src()
        assert "timeout_sec=420" in src, "ci_wait_run must pass an explicit bounded timeout_sec (#1035)"
        assert "poll_interval_sec=15" in src, "ci_wait_run must pass an explicit poll_interval_sec (#1035)"

    def test_direct_merge_pipeline_fallback(self) -> None:
        # #1035: when ci_wait_run does not confirm success (the GitLab head_pipeline
        # freshness race), read the MR's OWN /merge pipeline directly instead of HOLDing.
        src = _gate_src()
        assert "FALLBACK" in src, "ci signal must have the step-2b direct fallback (#1035)"
        assert "merge_requests/" in src and "pipelines" in src, (
            "fallback must read the MR's own pipelines directly"
        )
        assert "refs/merge-requests/" in src, "fallback must target the /merge pipeline ref"

    def test_fallback_never_grades_a_branch_or_head_pipeline(self) -> None:
        # The safety invariant survives the fallback: only a green MERGE-RESULT run passes;
        # a branch or GitLab detached-head pipeline is never graded.
        src = _gate_src()
        assert "refs/merge-requests/N/head" in src, (
            "the GitLab detached-head pipeline must be named as the invalid one"
        )
        assert "branch/head fallback" in src, (
            "the fallback must explicitly disclaim being a branch/head fallback (safety invariant)"
        )

    def test_fallback_binds_to_current_head_sha(self) -> None:
        # #1035 review: step-2b must NOT drop step-2's freshness binding — a green /merge run
        # for a PREVIOUS head is stale. Require the selected pipeline's sha == the MR head SHA.
        src = _gate_src()
        assert "head_sha" in src, "step-2b must read the MR's current head SHA for freshness"
        assert "sha EQUALS" in src, (
            "step-2b must PASS only if the /merge pipeline's sha matches the current head (freshness)"
        )
