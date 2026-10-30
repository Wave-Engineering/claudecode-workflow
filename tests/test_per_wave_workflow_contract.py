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


class TestFlightCiBeforeReconcile:
    """#1356 (triage #39): reconcile merged flight PRs into kahuna/* on red CI. Each flight is
    now graded on its own head first, and reconcile merges only the green ones, pinned."""

    def _reconcile_prompt(self) -> str:
        src = _wf_src()
        start = src.index("function primeReconcilePrompt(")
        return src[start:src.index("\n}\n", start)]

    def test_reconcile_prompt_pins_head_and_opens_no_pr(self) -> None:
        p = self._reconcile_prompt()
        assert 'pr_merge(number=<its PR>, expected_head_sha="<its graded head>")' in p, (
            "reconcile must merge each flight PR pinned to its graded head"
        )
        assert "pr_create" not in p, "reconcile must not open PRs: the flight CI node does"
        assert "Merge ONLY the PRs listed above" in p

    def test_flight_ci_node_runs_before_reconcile(self) -> None:
        src = _wf_src()
        assert src.index("label: `flight-ci:#${w.issue}`") < src.index("primeReconcilePrompt(proceeding,"), (
            "the flight CI node must run before reconcile, and reconcile gets only the proceed set"
        )
        assert "flightCiVerdict(flightCi[i] ?? null" in src, "a null flight-CI result must grade as blocked"
        assert "halt = `flight-ci-blocked:" in src, "a blocked flight must halt the wave after persisting"

    def test_reconcile_never_skips_a_merge(self) -> None:
        """#1356 review: flight-CI step 0 grades an already-integrated flight, so the old "already
        in kahuna, SKIP it" rule could only let reconcile report merged without calling pr_merge."""
        p = self._reconcile_prompt()
        assert "SKIP it" not in p, "reconcile must not skip a merge it was handed"
        assert "{issue, merged, merge_commit_sha, pinned_head_sha}" in p, "reconcile must report each merge's proof"
        assert "no echo means no pin" in p, "the prompt must name why the echo is required"
        assert "needs_rework ONLY (never in merged or merges" in p, "an undone merge must not also be reported merged"

    def test_pinned_merge_unproven_is_a_legal_exit(self) -> None:
        skill = (_WF.parent / "SKILL.md").read_text(encoding="utf-8")
        assert "| pinned-merge-unproven |" in skill, "the halt must be in the closed legal-exits table"
        assert "halts.join('; also: ')" in _wf_src(), "every halt that fired is reported, the unproven merge first"

    def test_merges_count_only_on_the_pin_echo(self) -> None:
        src = _wf_src()
        assert "const pinned = reconciledMerges(rec, proceeding)" in src
        assert "[...integrated, ...pinned.merged]" in src, "only proven merges (and resumes) count as merged"
        assert "rec.merged || []).filter((n) => handed.has" not in src, "reconcile's merged claim alone must not count"
        assert "halt = `pinned-merge-unproven:" in src, "an unproven merge must halt the wave"
        assert "const promoted = !!(promo && promo.promoted) && pin.landed" in src, (
            "promote counts only when pr_merge echoed the graded head"
        )


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


class TestCiWaitBudget:
    """#1302: the gate's CI wait is a per-repo budget, reaching the CI signal from both
    launch paths (a /nextwave launch and the campaign Workflow's per-wave args)."""

    def test_per_wave_passes_ci_wait_sec(self) -> None:
        src = _wf_src()
        assert "const CI_WAIT_SEC = params.ciWaitSec ?? CI_WAIT_DEFAULT_SEC" in src
        assert "prNumber: promotionPrNumber, ciWaitSec: CI_WAIT_SEC })" in src, (
            "the gate:ci node must hand ciSignalPrompt the budget"
        )

    def test_campaign_threads_ci_wait_sec(self) -> None:
        src = _WF.with_name("campaign-workflow.js").read_text(encoding="utf-8")
        per_wave_args = src[src.index("const perWaveArgs = {") :]
        per_wave_args = per_wave_args[: per_wave_args.index("\n  }\n")]
        assert "ciWaitSec: params.ciWaitSec," in per_wave_args, (
            "the campaign Workflow must pass ciWaitSec through perWaveArgs"
        )


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
        # A flight's branch lands on the kahuna integration branch (through reconcile), NEVER the protected branch.
        src = _worker_prompt_src()
        assert "lands on" in src and "NEVER" in src and "PROTECTED_BRANCH" in src, (
            "a flight must land on KAHUNA_BRANCH, never the protected branch directly"
        )

    def test_flight_does_not_run_precheck(self) -> None:
        # #1209: a flight is a subagent (no Agent tool) told not to push, so it cannot satisfy /precheck.
        # The prompt says so; the trust gate's review is its review, and reconcile opens and merges its PR.
        src = _worker_prompt_src()
        for needle in (
            "Do NOT run /precheck, /scp, /scpmr, /scpmmr or /mmr",
            "do NOT call pr_create, pr_ready or pr_merge",
            "trust gate's review signal is this change's review",
            "do NOT push",
        ):
            assert needle in src, f"workerPrompt must say {needle!r}"
        assert "Your PR targets" not in src, "a flight opens no PR; reconcile does"


def _worker_prompt_src() -> str:
    src = _wf_src()
    start = src.index("function workerPrompt(")
    return src[start : src.index("\n}\n", start)]


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


class TestKahunaBootstrap:
    """#1052 — the wave's integration branch is established off the INTEGRATION BASE
    before the flight loop, by this engine.

    Before #1052 nothing in this repo created `origin/<kahuna>`; the only creator was
    server-side `wave_init`, which cuts ONE plan-scoped branch off trunk. Inside a
    campaign that is wrong twice over (shared across waves, so wave 1's promote deletes
    wave 2's base; and trunk-based, so wave 2's flights miss wave 1's integrated work),
    while every downstream node — worktree setup, the gate's diff, the promote merge —
    reads `origin/<kahuna>` as a precondition.
    """

    def test_bootstrap_node_exists(self) -> None:
        src = _wf_src()
        assert "KAHUNA-BOOTSTRAP" in src, (
            "per-wave workflow must establish this wave's kahuna branch (nothing else creates it)"
        )

    def test_bootstrap_bases_on_integration_base_not_protected(self) -> None:
        # The whole point: cut from INTEGRATION_BASE. Basing on the protected branch inside a
        # campaign hands the wave a baseline missing every previously-integrated wave.
        src = _wf_src()
        assert "branch ${KAHUNA_BRANCH} origin/${INTEGRATION_BASE}" in src, (
            "the kahuna branch must be cut from origin/<integrationBase>"
        )

    def test_bootstrap_reuses_never_recuts(self) -> None:
        # An existing kahuna carries this wave's already-integrated flights; re-cutting
        # (or resetting/force-pushing) it silently discards them.
        src = _wf_src()
        assert "REUSE it" in src and "Do NOT re-cut" in src, (
            "bootstrap must reuse an existing kahuna branch, never re-cut it"
        )

    def test_bootstrap_verifies_then_fails_loud(self) -> None:
        # Read-back verification, and abort rather than fall back — least of all to trunk.
        src = _wf_src()
        assert "rev-parse refs/remotes/origin/${KAHUNA_BRANCH}" in src, (
            "bootstrap must verify the branch by reading it back from origin"
        )
        assert "could not establish the wave's integration branch" in src, (
            "an unestablished kahuna must abort the wave (throw), not proceed"
        )

    def test_bootstrap_requires_a_verified_sha(self) -> None:
        # `head_sha` is optional in the schema, so a schema-valid `{ready: true}` carrying no sha would
        # pass a bare `ready` check — "reported ready" wearing "verified ready"'s clothes, over a branch
        # nobody read back. Same defect the promotion-PR node closes by requiring a concrete pr_number.
        src = _wf_src()
        assert "/^[0-9a-f]{7,40}$/.test(bootstrapSha)" in src, (
            "bootstrap must require a sha-shaped head_sha, not merely ready:true"
        )

    def test_kahuna_may_not_be_the_base_or_trunk(self) -> None:
        # Flights merge INTO the kahuna and the gate diffs it AGAINST the base. If they are the same ref
        # every flight lands on the base ungated, and by the time the gate looked its diff would be empty.
        src = _wf_src()
        assert "must not equal ${label}" in src, (
            "bootstrap must reject a kahuna branch equal to the integration base or the protected branch"
        )

    def test_reuse_log_does_not_assert_unverified_ancestry(self) -> None:
        # Catalog G: report the observed post-state, not the assumption. Existence != descended-from-base.
        src = _wf_src()
        assert "merge-base --is-ancestor" in src, "the reuse path must actually CHECK ancestry"
        assert "based_on_base" in src, "and report it as a field rather than asserting it in the log"
        assert "reused (already based on)" not in src, (
            "the log must not claim an ancestry the node never verified"
        )

    def test_trajectory_entry_carries_integrated(self) -> None:
        # #1052: the durable trajectory entry must carry `integrated`, not `promoted` alone.
        # A record with only `promoted` is indistinguishable from a pre-#1052 one, and the
        # campaign's (deliberately conservative) rehydrate would decline to count the wave —
        # re-running an already-integrated wave, whose now-empty diff conservative-fails the
        # review signal into a HOLD, stalling the campaign short of its release gate.
        src = _wf_src()
        assert "integrated: disposition === 'promoted'" in src, (
            "the trajectory entry must carry `integrated` (current vocabulary), not only `promoted`"
        )
