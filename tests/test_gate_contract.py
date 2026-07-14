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

    def test_promotion_targets_kahuna_to_protected(self) -> None:
        # Flights never merge straight to the protected branch — only kahuna->protected promotes.
        src = _gate_src()
        assert "kahunaBranch" in src and "protectedBranch" in src, (
            "promotion must route kahuna_branch -> protected_branch"
        )


class TestPromotionLifecycle:
    """kahuna-branch lifecycle on promotion — relocated from the all-green /
    any-red kahuna-handling skill assertions (#722 per-plan persistence)."""

    def test_can_preserve_per_plan_kahuna(self) -> None:
        # #722: a per-plan kahuna shared across waves 1..N must PERSIST, else
        # deleting it after wave 1 strands the later waves off a diverged base.
        assert "preserveKahuna" in _gate_src(), (
            "promotion must support preserveKahuna (#722 per-plan kahuna persistence)"
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
