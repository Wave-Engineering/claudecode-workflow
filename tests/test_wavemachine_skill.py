"""Tests for skills/wavemachine/SKILL.md — trust-score gate + auto-merge (issue #418).

Validates Dev Spec §5.2.2:
- Pre-wave kahuna bootstrap step group exists, references ``wave_init`` with
  ``kahuna: { plan_id, slug }``, is idempotent on resume.
- Trust-score gate step group exists, lists the four signals, runs them
  CONCURRENTLY in a single tool-use block (R-23).
- All-green path documents ``pr_merge`` with ``skip_train: true``,
  ``kahuna_branches`` history record, kahuna branch deletion, notification
  + vox.
- Any-red path documents ``gate_blocked`` transition, notification, kahuna
  preservation, exit-loop.
- ``PROBE_UNAVAILABLE`` synthesized verdict treated as conservative-fail.
- Procedure D (crash recovery) at gate re-enters idempotently.

Tests assert content of the live SKILL.md file. They exercise the real
markdown — no mocks, no stubs, no live binaries (no trivy, no
commutativity-probe required).

IT-01 / IT-03 / IT-04 / IT-05 (AC-6 + AC-7) are integration-test-level
acceptance criteria covered by the end-to-end harness (Dev Spec §6.2);
they are out of scope for this unit-level skill test file. This is the same
scoping convention used by ``test_nextwave_skill.py`` for AC-5/AC-6 of #417.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths and fixtures
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "wavemachine" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the wavemachine SKILL.md file once per module."""
    return SKILL_PATH.read_text(encoding="utf-8")


def _section(text: str, header: str) -> str:
    """Return the slice of ``text`` from the matching header to the next
    sibling/parent header (``## `` or ``### ``).

    ``header`` is matched by substring on the line. The slice ends at the
    next line beginning with ``## `` or ``### ``. Used to scope assertions
    to a specific step rather than the whole document.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if header in line and (line.startswith("## ") or line.startswith("### ")):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## ") or lines[j].startswith("### "):
            end = j
            break
    return "".join(lines[start:end])


def _bootstrap(text: str) -> str:
    return _section(text, "Pre-Wave Kahuna Bootstrap")


def _gate(text: str) -> str:
    """Return the entire gate section, including its ### subsections.

    The ``_section`` helper stops at the first ``### `` heading, but the
    gate section's ### subsections (gate procedure, PROBE_UNAVAILABLE,
    Procedure D) are part of the same step group conceptually. Here we
    take everything from the ``## Trust-Score Gate`` heading down to the
    next top-level ``## `` heading.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if line.startswith("## Trust-Score Gate"):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## ") and not lines[j].startswith("## Trust-Score Gate"):
            end = j
            break
    return "".join(lines[start:end])


# ---------------------------------------------------------------------------
# Existence + framing
# ---------------------------------------------------------------------------


class TestSkillFileShape:
    """Sanity checks: file exists, frontmatter intact, gate / kahuna
    terminology present at the document level."""

    def test_skill_file_exists(self) -> None:
        assert SKILL_PATH.is_file(), f"missing: {SKILL_PATH}"

    def test_frontmatter_name(self, skill_text: str) -> None:
        assert skill_text.startswith("---\nname: wavemachine\n")

    def test_kahuna_branch_referenced(self, skill_text: str) -> None:
        assert "kahuna_branch" in skill_text

    def test_gate_evaluating_referenced(self, skill_text: str) -> None:
        """Both new ``action`` values from §5.2.2 must appear."""
        assert "gate_evaluating" in skill_text
        assert "gate_blocked" in skill_text


# ---------------------------------------------------------------------------
# AC-1: Pre-wave kahuna bootstrap
# ---------------------------------------------------------------------------


class TestAC1_PreWaveBootstrap:
    """Pre-wave kahuna bootstrap section exists and references ``wave_init``
    with the ``kahuna: { plan_id, slug }`` argument, runs once per Plan, is
    idempotent on resume."""

    def test_bootstrap_section_exists(self, skill_text: str) -> None:
        bootstrap = _bootstrap(skill_text)
        assert bootstrap, "Pre-Wave Kahuna Bootstrap section not found"

    def test_bootstrap_calls_wave_init_with_kahuna_arg(
        self, skill_text: str
    ) -> None:
        """The bootstrap step must name ``wave_init`` and pass the
        ``kahuna: { plan_id, slug }`` argument shape per §5.1.2 (Plan/Phase
        taxonomy locked 2026-04-26; the legacy ``epic_id`` parameter has
        been renamed to ``plan_id``)."""
        bootstrap = _bootstrap(skill_text)
        assert "wave_init" in bootstrap
        # Tolerate small whitespace variations around the JSON-ish object.
        assert re.search(
            r"kahuna:\s*\{\s*plan_id\s*,\s*slug\s*\}",
            bootstrap,
        ), "Bootstrap must call wave_init with `kahuna: { plan_id, slug }`"

    def test_bootstrap_skips_when_kahuna_branch_present(
        self, skill_text: str
    ) -> None:
        """Resume path: when ``kahuna_branch`` is already in wave state,
        the bootstrap is a no-op."""
        bootstrap = _bootstrap(skill_text)
        assert re.search(
            r"kahuna_branch.*(present|non-empty).*SKIP|SKIP.*kahuna_branch",
            bootstrap,
            re.IGNORECASE | re.DOTALL,
        ), "Bootstrap must skip when kahuna_branch is already present (resume path)"

    def test_bootstrap_runs_once_per_plan(self, skill_text: str) -> None:
        """Bootstrap is anchored as once-per-Plan, not per-wave."""
        bootstrap = _bootstrap(skill_text)
        assert re.search(
            r"once per (plan|epic)|first.*invocation",
            bootstrap,
            re.IGNORECASE,
        ), "Bootstrap must declare once-per-Plan semantics"


# ---------------------------------------------------------------------------
# AC-2 + AC-5 (R-23): Gate documents the four signals AND mandates
# concurrent invocation in a single tool-use block.
# ---------------------------------------------------------------------------


class TestAC2_GateStepGroupAndConcurrency:
    """Gate step group documents the four trust signals, calls them
    concurrently in a single tool-use block, and explicitly cites R-23."""

    def test_gate_section_exists(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        assert gate, "Trust-Score Gate and Auto-Merge section not found"

    def test_gate_runs_at_plan_completion(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        # The gate must be anchored to the loop's clean-completion path
        # (after wave_next_pending() returns null and DoD passes).
        assert re.search(
            r"wave_next_pending.*null|plan completion|epic completion|"
            r"after.*final wave|clean.completion",
            gate,
            re.IGNORECASE | re.DOTALL,
        ), "Gate must be anchored at Plan completion / clean completion path"

    def test_gate_invokes_wave_finalize(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        assert "wave_finalize" in gate

    def test_gate_transitions_to_gate_evaluating(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        # The transition must be explicit and tied to action ->
        # gate_evaluating.
        assert re.search(
            r"action.*gate_evaluating|gate_evaluating",
            gate,
        ), "Gate must transition wave state action to gate_evaluating"

    def test_gate_lists_all_four_signals(self, skill_text: str) -> None:
        """All four trust-score signals must be enumerated by name within
        the gate section. They are the contract being implemented."""
        gate = _gate(skill_text)
        assert "commutativity_verify" in gate, "missing commutativity_verify"
        assert "ci_wait_run" in gate, "missing ci_wait_run"
        # Code-reviewer Agent — accept either bare subagent_type form or
        # explicit Agent(... feature-dev:code-reviewer ...).
        assert re.search(
            r"feature-dev:code-reviewer|code-reviewer",
            gate,
        ), "missing feature-dev:code-reviewer Agent signal"
        assert "trivy" in gate, "missing trivy Bash signal"

    def test_gate_signals_run_concurrently_per_r23(self, skill_text: str) -> None:
        """R-23: the four signals must run concurrently in a single
        tool-use block. This is the load-bearing assertion — the test
        exists specifically to catch regressions where signals get
        sequenced behind one another."""
        gate = _gate(skill_text)
        # Literal R-23 reference must be present.
        assert "R-23" in gate, "Gate must cite R-23"
        # "concurrent" wording (catches both "concurrently" and
        # "concurrent").
        assert re.search(
            r"concurrent", gate, re.IGNORECASE
        ), "Gate must declare concurrent invocation"
        # "single tool-use block" wording — the wave-pattern parallelism
        # idiom that maps to actual concurrent tool calls in CC.
        assert re.search(
            r"single tool.use block",
            gate,
            re.IGNORECASE,
        ), "Gate must require a single tool-use block for the four signals"

    def test_gate_does_not_short_circuit(self, skill_text: str) -> None:
        """Procedure C, §4.4.4: collect all four results before evaluating.
        Do not bail out on the first failure."""
        gate = _gate(skill_text)
        assert re.search(
            r"do.*not.*short.circuit|collect all four",
            gate,
            re.IGNORECASE | re.DOTALL,
        ), "Gate must explicitly forbid short-circuit on first failure"


# ---------------------------------------------------------------------------
# AC-3: All-green path — auto-merge, history, branch deletion,
# notifications.
# ---------------------------------------------------------------------------


class TestAC3_AllGreenPath:
    """When all four trust signals pass, the gate auto-merges
    kahuna→main, records disposition in ``kahuna_branches`` history,
    deletes the kahuna branch, and emits notifications + vox."""

    def test_all_green_invokes_pr_merge_skip_train(
        self, skill_text: str
    ) -> None:
        gate = _gate(skill_text)
        assert "pr_merge" in gate
        # skip_train: true is the load-bearing flag — without it the
        # auto-merge falls into the project's standard merge train and
        # the autonomous gate is moot.
        assert re.search(
            r"skip_train\s*:\s*true",
            gate,
        ), "All-green path must call pr_merge with skip_train: true"

    def test_all_green_records_kahuna_branches_history(
        self, skill_text: str
    ) -> None:
        gate = _gate(skill_text)
        assert "kahuna_branches" in gate, (
            "All-green path must record disposition in kahuna_branches "
            "history"
        )
        assert re.search(
            r'disposition\s*:\s*"merged"|"merged"',
            gate,
        ), "kahuna_branches entry must record disposition: 'merged'"

    def test_all_green_deletes_kahuna_branch(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        # R-03 — branch must be deleted on success. Tolerate either an
        # English description or platform-specific commands.
        assert re.search(
            r"[Dd]elete the kahuna branch|R-03",
            gate,
        ), "All-green path must delete the kahuna branch (R-03)"

    def test_all_green_emits_notification_and_vox(
        self, skill_text: str
    ) -> None:
        gate = _gate(skill_text)
        # R-19 — Discord notification must fire.
        assert re.search(
            r"#wave-status.*[Kk]ahuna gate passed|[Kk]ahuna gate passed.*"
            r"#wave-status",
            gate,
            re.DOTALL,
        ), "All-green path must emit a #wave-status 'kahuna gate passed' notification"
        # Vox announcement.
        assert re.search(
            r"[Vv]ox.*kahuna gate passed",
            gate,
            re.IGNORECASE | re.DOTALL,
        ), "All-green path must emit a vox announcement"


# ---------------------------------------------------------------------------
# AC-4: Any-red path — gate_blocked transition, notification, kahuna
# preservation, exit loop.
# ---------------------------------------------------------------------------


class TestAC4_AnyRedPath:
    """When one or more signals fail, the gate transitions to
    ``gate_blocked``, emits Procedure C notifications, preserves the
    kahuna branch, and exits the loop."""

    def test_any_red_transitions_to_gate_blocked(
        self, skill_text: str
    ) -> None:
        gate = _gate(skill_text)
        assert re.search(
            r"action.*gate_blocked",
            gate,
            re.DOTALL,
        ), "Any-red path must transition action -> gate_blocked"

    def test_any_red_preserves_kahuna_branch(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        assert re.search(
            r"[Pp]reserve the kahuna branch|kahuna branch.*preserved|"
            r"[Dd]o NOT delete",
            gate,
            re.DOTALL,
        ), "Any-red path must preserve the kahuna branch"

    def test_any_red_exits_loop(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        # Exit condition. wave_status wavemachine-stop or exit the loop.
        assert re.search(
            r"exit the loop|wavemachine-stop",
            gate,
            re.IGNORECASE,
        ), "Any-red path must exit the loop"

    def test_any_red_emits_procedure_c_notification(
        self, skill_text: str
    ) -> None:
        gate = _gate(skill_text)
        # Procedure C — must be cited.
        assert re.search(
            r"Procedure C|§\s*4\.4\.4",
            gate,
        ), "Any-red path must cite Procedure C / §4.4.4"
        # Notification must list the failing signals + the open MR URL.
        assert re.search(
            r"#wave-status.*[Kk]ahuna gate blocked|"
            r"failing signal|MR.*open for review",
            gate,
            re.DOTALL,
        ), "Any-red path must emit #wave-status notification with failing signals + MR URL"

    def test_any_red_calls_wave_waiting(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        assert "wave_waiting" in gate, (
            "Any-red path must call wave_waiting to mark the plan paused"
        )


# ---------------------------------------------------------------------------
# PROBE_UNAVAILABLE: synthesized verdict, conservative-fail treatment.
# ---------------------------------------------------------------------------


class TestProbeUnavailable:
    """The synthesized ``PROBE_UNAVAILABLE`` verdict (cross-server
    contract per ``mcp-server-sdlc#218``) must be treated as
    conservative-fail in the gate — no auto-merge."""

    def test_probe_unavailable_documented(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        assert "PROBE_UNAVAILABLE" in gate, (
            "Gate must document the PROBE_UNAVAILABLE verdict"
        )

    def test_probe_unavailable_is_conservative_fail(
        self, skill_text: str
    ) -> None:
        """The treatment must be explicit: same dispatch as
        ``ORACLE_REQUIRED`` — never auto-merge when commutativity is
        unavailable."""
        gate = _gate(skill_text)
        assert re.search(
            r"PROBE_UNAVAILABLE.*conservative.fail|"
            r"conservative.fail.*PROBE_UNAVAILABLE|"
            r"PROBE_UNAVAILABLE.*equivalent.*ORACLE_REQUIRED|"
            r"PROBE_UNAVAILABLE.*ORACLE_REQUIRED",
            gate,
            re.IGNORECASE | re.DOTALL,
        ), (
            "Gate must declare PROBE_UNAVAILABLE as conservative-fail / "
            "equivalent to ORACLE_REQUIRED"
        )

    def test_probe_unavailable_no_auto_merge(self, skill_text: str) -> None:
        """Belt-and-suspenders: the must-not-auto-merge contract is
        spelled out so it cannot be silently relaxed."""
        gate = _gate(skill_text)
        assert re.search(
            r"MUST NOT auto.merge|not auto.merge",
            gate,
            re.IGNORECASE,
        ), "Gate must explicitly forbid auto-merge when commutativity is unavailable"

    def test_probe_unavailable_cross_server_contract_cited(
        self, skill_text: str
    ) -> None:
        """The contract source must be findable — the
        ``mcp-server-sdlc#218`` cross-reference anchors the synthesized
        verdict to its authoritative spec."""
        gate = _gate(skill_text)
        assert re.search(
            r"mcp-server-sdlc#218",
            gate,
        ), "Gate must cite the cross-server contract (mcp-server-sdlc#218)"


# ---------------------------------------------------------------------------
# AC-8: Procedure D — idempotent re-evaluation when re-entering at
# gate_evaluating.
# ---------------------------------------------------------------------------


class TestAC8_ProcedureDReentry:
    """When ``/wavemachine`` is restarted with wave state in
    ``gate_evaluating``, the gate is re-invoked idempotently — pure-read
    signals are safe to retry."""

    def test_procedure_d_documented(self, skill_text: str) -> None:
        gate = _gate(skill_text)
        assert re.search(
            r"Procedure D|§\s*4\.4\.5",
            gate,
        ), "Gate must cite Procedure D / §4.4.5 for crash recovery"

    def test_re_entry_at_gate_evaluating(self, skill_text: str) -> None:
        """The skill must specify the re-entry trigger: state
        ``action == gate_evaluating``."""
        gate = _gate(skill_text)
        assert re.search(
            r"gate_evaluating.*re.invoke|re.invoke.*gate_evaluating|"
            r"gate_evaluating.*re.enter|re.enter.*gate",
            gate,
            re.IGNORECASE | re.DOTALL,
        ), "Gate must specify re-entry behavior when action == gate_evaluating"

    def test_signals_safe_to_retry(self, skill_text: str) -> None:
        """Signals are pure reads (or upstream-idempotent) — the rationale
        for safe retry must be documented."""
        gate = _gate(skill_text)
        assert re.search(
            r"pure read|safe to retry|idempoten",
            gate,
            re.IGNORECASE,
        ), "Gate must explain why re-invoking signals is safe (pure reads / idempotent)"

    def test_resuming_section_documents_gate_re_entry(
        self, skill_text: str
    ) -> None:
        """The "Resuming After an Abort" section also documents gate
        re-entry — readers approaching the skill from the abort-recovery
        angle need this signpost too."""
        resuming = _section(skill_text, "Resuming After an Abort")
        assert resuming, "Resuming After an Abort section not found"
        assert re.search(
            r"gate_evaluating",
            resuming,
        ), "Resuming section must mention gate_evaluating re-entry"
        assert "wave_finalize" in resuming, (
            "Resuming section must call out wave_finalize idempotency"
        )


# ---------------------------------------------------------------------------
# Cross-reference: Dev Spec §5.2.2 must be cited at least once.
# ---------------------------------------------------------------------------


class TestDevSpecCrossReference:
    """The Dev Spec §5.2.2 reference must remain in the skill so future
    readers can find the authoritative gate contract."""

    def test_devspec_5_2_2_referenced(self, skill_text: str) -> None:
        assert re.search(r"§\s*5\.2\.2|Dev Spec.*5\.2\.2", skill_text), (
            "Dev Spec §5.2.2 must be cross-referenced from the skill"
        )


# ---------------------------------------------------------------------------
# Non-Negotiables: R-23 and PROBE_UNAVAILABLE must appear as hard rules.
# Catches regressions where the gate body documents the rule but the
# Non-Negotiables list (the load-bearing summary) drifts out of sync.
# ---------------------------------------------------------------------------


class TestNonNegotiables:
    def test_r23_in_non_negotiables(self, skill_text: str) -> None:
        non_neg = _section(skill_text, "Non-Negotiables")
        assert non_neg, "Non-Negotiables section not found"
        assert "R-23" in non_neg
        assert re.search(
            r"single tool.use block", non_neg, re.IGNORECASE
        ), "Non-Negotiables must encode 'single tool-use block' for R-23"

    def test_probe_unavailable_in_non_negotiables(
        self, skill_text: str
    ) -> None:
        non_neg = _section(skill_text, "Non-Negotiables")
        assert "PROBE_UNAVAILABLE" in non_neg, (
            "Non-Negotiables must encode the PROBE_UNAVAILABLE rule"
        )
        assert re.search(
            r"conservative.fail",
            non_neg,
            re.IGNORECASE,
        ), "Non-Negotiables must mark PROBE_UNAVAILABLE as conservative-fail"

    def test_no_short_circuit_in_non_negotiables(
        self, skill_text: str
    ) -> None:
        non_neg = _section(skill_text, "Non-Negotiables")
        assert re.search(
            r"short.circuit",
            non_neg,
            re.IGNORECASE,
        ), "Non-Negotiables must encode 'do not short-circuit the gate'"


# ---------------------------------------------------------------------------
# Story 3.1 (#512) — Plan/Phase rename + Exhaustive Legal Exits section.
# AC-1: zero unqualified "epic" in pipeline contexts [R-09].
# AC-2: ``## Exhaustive Legal Exits`` section present matching §5.3.2 [R-17].
# AC-3: cross-reference to the two principle_* memory files present.
# ---------------------------------------------------------------------------


class TestAC1_NoUnqualifiedEpic:
    """R-09: the skill body contains zero unqualified 'epic' in
    pipeline-operational contexts. Allowed exceptions:

    - PM-layer annotations (``type::plan``/``type::epic`` label family names,
      the ``Plan/Phase/Epic taxonomy`` proper-noun reference).
    - Nothing else. ``epic_id`` is specifically forbidden — Phase 2 renamed
      the sdlc-server handler parameter to ``plan_id``.
    """

    def test_no_epic_id_parameter(self, skill_text: str) -> None:
        assert "epic_id" not in skill_text, (
            "epic_id is forbidden — Phase 2 renamed to plan_id (R-05..R-07)"
        )

    def test_no_unqualified_epic_in_body(self, skill_text: str) -> None:
        """Every residual ``epic`` occurrence must be inside a PM-layer
        annotation. The whitelist enumerates the only legitimate mentions:
        the ``Plan/Phase/Epic taxonomy`` proper-noun reference to the
        locked decision document. Any other occurrence is a rot bug per
        the heuristic in ``decision_plan_phase_epic_taxonomy.md``."""
        # Case-insensitive word-boundary match.
        matches = list(re.finditer(r"\bepic\b", skill_text, re.IGNORECASE))
        # Filter out whitelisted contexts by looking at a ~40-char window
        # around each hit.
        unqualified: list[str] = []
        for m in matches:
            lo = max(0, m.start() - 40)
            hi = min(len(skill_text), m.end() + 40)
            window = skill_text[lo:hi]
            if "Plan/Phase/Epic taxonomy" in window:
                continue
            unqualified.append(window)
        assert not unqualified, (
            "Unqualified 'epic' references in pipeline contexts "
            "(should be Plan or Phase):\n"
            + "\n---\n".join(unqualified)
        )


class TestAC2_ExhaustiveLegalExits:
    """R-17: the skill body contains a ``## Exhaustive Legal Exits``
    section matching the §5.3.2 structural template — exact heading, with
    ``### Mechanical exits`` (numbered), ``### Plan-reality drift exits``
    (numbered), and ``### Explicit non-exits`` (bulleted) subsections."""

    def test_section_heading_present(self, skill_text: str) -> None:
        assert re.search(
            r"^## Exhaustive Legal Exits\s*$",
            skill_text,
            re.MULTILINE,
        ), "Must contain '## Exhaustive Legal Exits' heading (exact)"

    def test_closed_list_framing_present(self, skill_text: str) -> None:
        """The opening sentence must assert the closed-list contract."""
        section = _section(skill_text, "Exhaustive Legal Exits")
        assert section, "Exhaustive Legal Exits section not found"
        assert re.search(
            r"closed.*no other condition warrants stopping",
            section,
            re.IGNORECASE | re.DOTALL,
        ), "Section must declare the closed-list contract"

    def test_mechanical_exits_subsection(self, skill_text: str) -> None:
        section = _section(skill_text, "Exhaustive Legal Exits")
        # _section stops at the next ## or ### — so grab a wider window.
        lines = skill_text.splitlines(keepends=True)
        start = next(
            i for i, l in enumerate(lines)
            if l.startswith("## Exhaustive Legal Exits")
        )
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].startswith("## ")
             and not lines[i].startswith("## Exhaustive Legal Exits")),
            len(lines),
        )
        body = "".join(lines[start:end])
        assert "### Mechanical exits" in body, (
            "Must contain '### Mechanical exits' subsection"
        )
        # At least 4 numbered mechanical exits (matches §5.3.3 template).
        mech_start = body.index("### Mechanical exits")
        mech_body = body[mech_start:]
        numbered = re.findall(r"^\d+\.\s+\*\*", mech_body, re.MULTILINE)
        assert len(numbered) >= 4, (
            f"Mechanical exits must enumerate at least 4 numbered items "
            f"(found {len(numbered)})"
        )

    def test_plan_reality_drift_exits_subsection(
        self, skill_text: str
    ) -> None:
        lines = skill_text.splitlines(keepends=True)
        start = next(
            i for i, l in enumerate(lines)
            if l.startswith("## Exhaustive Legal Exits")
        )
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].startswith("## ")
             and not lines[i].startswith("## Exhaustive Legal Exits")),
            len(lines),
        )
        body = "".join(lines[start:end])
        assert "### Plan-reality drift exits" in body, (
            "Must contain '### Plan-reality drift exits' subsection"
        )

    def test_explicit_non_exits_subsection(self, skill_text: str) -> None:
        lines = skill_text.splitlines(keepends=True)
        start = next(
            i for i, l in enumerate(lines)
            if l.startswith("## Exhaustive Legal Exits")
        )
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].startswith("## ")
             and not lines[i].startswith("## Exhaustive Legal Exits")),
            len(lines),
        )
        body = "".join(lines[start:end])
        assert "### Explicit non-exits" in body, (
            "Must contain '### Explicit non-exits' subsection"
        )
        # Must have at least 5 bulleted non-exits.
        nonexit_start = body.index("### Explicit non-exits")
        nonexit_body = body[nonexit_start:]
        bullets = re.findall(
            r"^-\s+\*\*", nonexit_body, re.MULTILINE
        )
        assert len(bullets) >= 5, (
            f"Explicit non-exits must enumerate at least 5 bulleted items "
            f"(found {len(bullets)})"
        )

    def test_cross_reference_to_principle_memory_files(
        self, skill_text: str
    ) -> None:
        """AC-3: the section must cross-reference both
        ``principle_user_attention_is_the_cost.md`` and
        ``principle_cost_asymmetry_continue_vs_exit.md``."""
        lines = skill_text.splitlines(keepends=True)
        start = next(
            i for i, l in enumerate(lines)
            if l.startswith("## Exhaustive Legal Exits")
        )
        end = next(
            (i for i in range(start + 1, len(lines))
             if lines[i].startswith("## ")
             and not lines[i].startswith("## Exhaustive Legal Exits")),
            len(lines),
        )
        body = "".join(lines[start:end])
        assert "principle_user_attention_is_the_cost.md" in body, (
            "Must cross-reference principle_user_attention_is_the_cost.md"
        )
        assert "principle_cost_asymmetry_continue_vs_exit.md" in body, (
            "Must cross-reference principle_cost_asymmetry_continue_vs_exit.md"
        )
