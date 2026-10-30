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
# #1211: the merge-result rule gate.js grades the CI signal with, shared with the release gate.
_MERGE_RESULT_JS = _GATE_JS.with_name("merge-result.js")
_WF_JS = _GATE_JS.with_name("per-wave-workflow.js")


def _gate_src() -> str:
    return _GATE_JS.read_text(encoding="utf-8")


def _merge_result_src() -> str:
    return _MERGE_RESULT_JS.read_text(encoding="utf-8")


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

    def test_promote_without_graded_head_is_stop(self) -> None:
        # #1356 (triage #6): the promote merge is pinned to the head CI graded. With no graded
        # head there is nothing to pin, so the prompt is a STOP, never an unpinned pr_merge.
        src = _gate_src()
        assert "if (!isMergeSha(headSha)) {" in src, "promotePrompt must fail closed on a missing graded head"
        assert "No graded head SHA was handed to" in src, "the fail-closed branch must be the STOP prompt"
        assert 'expected_head_sha="${headSha}"' in src, "the pinned merge must pass expected_head_sha"

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
    longer over-waits ~30-57 min/wave on GitLab's head_pipeline freshness race.
    #1211: the agent returns evidence and ciVerdict() grades it with merge-result.js,
    the rule the campaign release gate shares, so the direct-read rules live in code."""

    def test_signal_ci_waits_on_the_merge_result(self) -> None:
        src = _gate_src()
        assert "ciSignalPrompt" in src, "ci signal prompt missing"
        assert "ci_wait_run" in src and "require_merge_result" in src, (
            "ci signal must ci_wait_run on the merge-result pipeline"
        )

    def test_ci_wait_run_is_bounded(self) -> None:
        # #1035 bleed fix: with no explicit timeout the tool rode its ~1800s idle default
        # and burned ~30-57 min/wave to confirm a <3-min pipeline. Bound it explicitly.
        # #1302: the bound is a per-repo budget whose default stays 420s.
        src = _gate_src()
        assert "export const CI_WAIT_DEFAULT_SEC = 420" in src, "the CI wait must default to 420s (#1035/#1302)"
        assert "timeout_sec=${waitSec}" in src, "ci_wait_run must pass an explicit bounded timeout_sec (#1035)"
        assert "windowSec: waitSec" in src, "the direct-read window must follow the same budget (#1302)"
        assert "poll_interval_sec=15" in src, "ci_wait_run must pass an explicit poll_interval_sec (#1035)"

    def test_direct_merge_pipeline_fallback(self) -> None:
        # #1035: when ci_wait_run does not confirm success (the GitLab head_pipeline
        # freshness race), read the MR's OWN /merge pipeline directly instead of HOLDing.
        # #1211: the steps are the shared directMergeReadSteps, so both gates ask alike.
        src = _gate_src()
        assert "from './merge-result.js'" in src, "gate.js must take the direct read from merge-result.js (#1211)"
        assert "...directMergeReadSteps(" in src, "the ci signal must carry the shared direct-read steps"
        mr = _merge_result_src()
        assert "DIRECT READ" in mr, "the shared steps must name the direct read"
        assert "merge_requests/${n}/pipelines" in mr, "the direct read must list the MR's own pipelines"
        assert "refs/merge-requests/${n}/merge" in mr, "the direct read must target the /merge pipeline ref"

    def test_fallback_never_grades_a_branch_or_head_pipeline(self) -> None:
        # The safety invariant survives the fallback: only a green MERGE-RESULT run passes;
        # a branch or GitLab detached-head pipeline is never graded. #1211: in code, too.
        src = _gate_src()
        assert "refs/merge-requests/N/head" in src, (
            "the GitLab detached-head pipeline must be named as the invalid one"
        )
        assert "branch/head fallback" in src, (
            "the fallback must explicitly disclaim being a branch/head fallback (safety invariant)"
        )
        mr = _merge_result_src()
        assert "const want = `refs/merge-requests/${n}/merge`" in mr and "p?.ref === want" in mr, (
            "mergeResultVerdict must count only this MR's /merge pipelines"
        )

    def test_fallback_binds_to_current_head_sha(self) -> None:
        # #1035 review: the direct read must NOT drop step-2's freshness binding — a green /merge
        # run for a PREVIOUS head is stale. #1211: #1035 bound it with "sha EQUALS the MR head",
        # which a merged-results pipeline never satisfies (it runs on an ephemeral merge commit:
        # 0 of 15 measured), so the rule binds through the merge commit's second parent, in code.
        src = _gate_src()
        assert "head_sha" in src, "the ci signal must read the MR's current head SHA for freshness"
        assert "sha EQUALS the MR head SHA" not in src, (
            "the unsatisfiable #1035 rule must not come back into the prompt"
        )
        mr = _merge_result_src()
        assert "p[1] !== head" in mr, (
            "a green /merge pipeline must be bound to the head through its merge commit's parents"
        )
        # #1356 (triage #7): and its first parent must be the target tip, read last.
        assert "p[0] !== target" in mr and "isMergeSha(target)" in mr, (
            "a merge commit must be built on the current target tip"
        )
        # #1211 review I-1: the head is read before the wait AND after the last read, and a pass
        # needs both equal, so a head that moved while it was graded can never pass.
        assert "...head('head_sha')," in src and "...head('head_sha_final')," in src, (
            "the ci signal must read the head both first and last"
        )
        assert "ev.head_sha_final !== head" in mr, "mergeResultVerdict must HOLD a head that moved during grading"

    def test_ci_signal_is_graded_in_code(self) -> None:
        # #1211: as trivyCoverage() is for trivy, the CI signal returns evidence and code grades it,
        # against the PR the gate opened rather than one the agent names.
        assert "export function ciVerdict(ev, prNumber)" in _gate_src(), "gate.js must export ciVerdict"
        wf = _WF_JS.read_text(encoding="utf-8")
        assert "schema: MERGE_RESULT_EVIDENCE" in wf, "the gate:ci node must return merge-result evidence"
        assert ".then((ev) => ciVerdict(ev, promotionPrNumber))" in wf, (
            "the gate:ci node must be graded by ciVerdict against the gate's own PR number"
        )


class TestTrivySignal:
    """Trivy trust signal — #1206: scans a detached worktree of origin/<kahuna>, never the
    operator's checkout, and code binds the verdict to the kahuna tip by SHA."""

    def test_scan_root_is_kahuna_worktree(self) -> None:
        src = _gate_src()
        assert "worktree add --detach <w>/tree origin/${kahunaBranch}" in src, (
            "the trivy signal must stage a detached worktree of origin/<kahuna>"
        )
        assert "  find <w>/tree \\\\(" in src, "the enumeration must be rooted at the kahuna worktree"
        assert "--quiet <w>/tree > <w>/trivy-0.json" in src, "the main scan must be rooted at the kahuna worktree"
        assert "find ${targetRepoDir}" not in src and "--quiet ${targetRepoDir}" not in src, (
            "no find or trivy fs may be rooted at the operator's checkout"
        )
        assert "Do NOT run git checkout or git switch in ${targetRepoDir}" in src
        assert "worktree remove --force <w>/tree" in src, "the kahuna worktree must be removed"

    def test_trivy_sig_requires_scanned_sha(self) -> None:
        src = _gate_src()
        assert "'declared', 'scanned_sha', 'kahuna_sha']" in src, "TRIVY_SIG must require both SHAs"
        assert "export function trivyTreeBound(sig)" in src
        wf = _WF_JS.read_text(encoding="utf-8")
        assert ".then(trivyTreeBound).then(trivyCoverage)" in wf, (
            "the gate:trivy node must bind the verdict to the kahuna tip before the coverage rule"
        )
