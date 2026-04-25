"""Tests for skills/precheck/SKILL.md — sandbox-aware auto-approval.

Validates the changes from #416:
- Sandbox detection regex `^kahuna/[0-9]+-` is documented in the skill.
- The auto-approval path emits the literal sentinel
  `[AUTO-APPROVED: kahuna sandbox]` before invoking `/scpmmr`.
- The non-sandbox path is unchanged: STOP-and-wait for
  `/scp` / `/scpmr` / `/scpmmr` / affirmative.
- Checklist items (validation, code-reviewer, trivy) still run in full
  inside the sandbox — only the human-approval step is bypassed.
- Discord `#precheck` notification fires regardless of context.

The IT-09 end-to-end proving-ground test is integration-level and tracked
in Dev Spec §6.2 (out of scope for this unit suite). The corresponding
unit-level proxy here is `TestIT09ProxyDocumented` — it asserts the
behaviors that IT-09 will exercise are present in the skill doc.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "precheck" / "SKILL.md"

# Canonical strings the spec requires verbatim.
SENTINEL_LITERAL = "[AUTO-APPROVED: kahuna sandbox]"
DETECTION_REGEX = "^kahuna/[0-9]+-"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the precheck SKILL.md file."""
    return SKILL_PATH.read_text(encoding="utf-8")


def _section_body(text: str, heading: str) -> str:
    """Return the body of a `## <heading>` section up to the next `## `.

    Used to scope assertions to a specific section so we don't get false
    positives from an adjacent section's text.
    """
    pattern = rf"##\s+{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# AC 1: Sandbox detection regex added to skills/precheck/SKILL.md
# ---------------------------------------------------------------------------


class TestDetectionRegex:
    """The skill must document the detection regex `^kahuna/[0-9]+-`."""

    def test_detection_regex_literal_present(self, skill_text: str) -> None:
        """The exact regex string `^kahuna/[0-9]+-` appears in the skill."""
        assert DETECTION_REGEX in skill_text, (
            f"Sandbox detection regex {DETECTION_REGEX!r} missing from SKILL.md"
        )

    def test_detection_regex_in_dedicated_section(self, skill_text: str) -> None:
        """The regex lives in a Sandbox Auto-Approval section, not just
        buried in the procedure one-liner — operators need a discoverable
        anchor."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        assert body, "Section 'Sandbox Auto-Approval (KAHUNA Flight Agents)' missing"
        assert DETECTION_REGEX in body, (
            "Detection regex must appear inside the Sandbox Auto-Approval section"
        )

    def test_detection_regex_matches_canonical_branch_names(self) -> None:
        """The documented regex actually matches the branch names it is
        meant to gate on. Guards against typo regressions in the regex
        (e.g. someone writes `kahuna-` instead of `kahuna/`)."""
        compiled = re.compile(DETECTION_REGEX)
        # Positive cases — kahuna sandbox branches we expect to auto-approve
        assert compiled.search("kahuna/411-wave-3-skill-integration")
        assert compiled.search("kahuna/1-bootstrap")
        assert compiled.search("kahuna/999999-edge")
        # Negative cases — non-sandbox branches must NOT match
        assert not compiled.search("main")
        assert not compiled.search("feature/416-sandbox-aware-precheck")
        assert not compiled.search("kahuna-misspelled/411-no-slash")
        assert not compiled.search("fix/kahuna/411-not-anchored")
        assert not compiled.search("kahuna/abc-non-numeric")


# ---------------------------------------------------------------------------
# AC 2: Auto-approval path emits sentinel `[AUTO-APPROVED: kahuna sandbox]`
#       before invoking `/scpmmr`
# ---------------------------------------------------------------------------


class TestSentinelAndAutoApprove:
    """The sentinel literal must appear, and `/scpmmr` must follow it."""

    def test_sentinel_literal_present(self, skill_text: str) -> None:
        """The literal sentinel appears verbatim in the skill."""
        assert SENTINEL_LITERAL in skill_text, (
            f"Sentinel {SENTINEL_LITERAL!r} missing from SKILL.md"
        )

    def test_sentinel_in_sandbox_section(self, skill_text: str) -> None:
        """The sentinel is documented inside the Sandbox Auto-Approval
        section — not in some unrelated paragraph."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        assert SENTINEL_LITERAL in body

    def test_sentinel_precedes_scpmmr_invocation(self, skill_text: str) -> None:
        """The skill describes emitting the sentinel BEFORE invoking
        `/scpmmr` — not after, which would defeat its 'announcing the
        bypass' purpose. We assert ordering inside the
        `sandbox_context == true` behavior-matrix entry, where the
        actual invocation step is documented."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        # Scope to the true-branch behavior-matrix entry
        true_match = re.search(
            r"sandbox_context\s*==\s*true[^\n]*\n?[\s\S]*?(?=\n\n|\Z)",
            body,
            re.IGNORECASE,
        )
        assert true_match, "Behavior matrix entry for sandbox_context == true missing"
        true_block = true_match.group(0)
        sentinel_idx = true_block.find(SENTINEL_LITERAL)
        scpmmr_idx = true_block.find("/scpmmr")
        assert sentinel_idx != -1, (
            "sentinel missing in sandbox_context == true branch"
        )
        assert scpmmr_idx != -1, (
            "/scpmmr invocation missing in sandbox_context == true branch"
        )
        assert sentinel_idx < scpmmr_idx, (
            "Sentinel must be emitted BEFORE /scpmmr is invoked"
        )

    def test_auto_approve_is_no_wait(self, skill_text: str) -> None:
        """The sandbox path explicitly notes the wait is bypassed (so
        future maintainers don't reintroduce the STOP)."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        body_lower = body.lower()
        assert "no wait" in body_lower or "with no wait" in body_lower or "bypass" in body_lower


# ---------------------------------------------------------------------------
# AC 3: Non-sandbox path unchanged — IT-09 negative case (regular feature
#       branch on main base continues to STOP-and-wait)
# ---------------------------------------------------------------------------


class TestNonSandboxPathUnchanged:
    """Non-sandbox flows still STOP and wait for explicit operator input."""

    def test_stop_keyword_preserved(self, skill_text: str) -> None:
        """The skill still says STOP — the existing gate behavior is not
        deleted by the sandbox addition."""
        # `STOP.` (capitalized + period) is the documented hard-stop token
        assert "STOP." in skill_text

    def test_approval_tokens_preserved(self, skill_text: str) -> None:
        """The accepted approval tokens are still listed."""
        for token in ("/scp", "/scpmr", "/scpmmr"):
            assert token in skill_text, f"approval token {token} missing"

    def test_non_sandbox_branch_keeps_stop(self, skill_text: str) -> None:
        """The Sandbox Auto-Approval section explicitly differentiates
        sandbox_context == false from sandbox_context == true and binds
        STOP to the false branch. This is the documentation contract that
        IT-09 negative-case relies on."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        # Look for the false branch and assert STOP is co-located there.
        # Find an occurrence of `sandbox_context == false` (markdown
        # rendering may bold it; allow surrounding markup).
        false_match = re.search(
            r"sandbox_context\s*==\s*false[^\n]*\n?[^\n]*",
            body,
            re.IGNORECASE,
        )
        assert false_match, "Behavior matrix entry for sandbox_context == false missing"
        # The line (and a small window after it) should mention STOP/wait.
        # Use a 400-char window to allow markdown wrapping.
        window_start = false_match.start()
        window = body[window_start : window_start + 400]
        assert "STOP" in window or "stop" in window.lower(), (
            "Non-sandbox path must keep STOP-and-wait behavior"
        )
        assert "wait" in window.lower(), (
            "Non-sandbox path must explicitly say it waits"
        )

    def test_main_base_branch_does_not_match_regex(self) -> None:
        """Sanity: a typical feature branch targeting `main` does NOT
        trigger the sandbox path. This is the IT-09 negative case
        boiled down to a unit assertion."""
        compiled = re.compile(DETECTION_REGEX)
        assert not compiled.search("main")
        # And the *base* of a normal feature branch is `main`:
        assert not compiled.search("feature/416-sandbox-aware-precheck")


# ---------------------------------------------------------------------------
# AC 4: Checklist items (validation, code-reviewer, trivy) still run in
#       full inside sandbox — only the approval step is bypassed
# ---------------------------------------------------------------------------


class TestChecklistFullyRunInSandbox:
    """Validation, code-reviewer, and trivy must still execute under the
    sandbox path."""

    def test_sandbox_section_lists_non_bypassable_items(self, skill_text: str) -> None:
        """The sandbox section explicitly enumerates what is NOT bypassed
        (validation, code-reviewer, trivy, notifications). This is the
        contract that prevents accidental broadening of the bypass."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        body_lower = body.lower()
        assert "validation" in body_lower
        assert "code-reviewer" in body_lower
        assert "trivy" in body_lower

    def test_sandbox_section_says_only_approval_bypassed(self, skill_text: str) -> None:
        """The sandbox section narrows the bypass scope to *only* the
        approval step. Phrasing may vary slightly but the scope-narrowing
        intent must be explicit."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        body_lower = body.lower()
        # Match either "only the ... step" / "only the human-approval"
        # or the equivalent "bypass" framing.
        scope_phrases = [
            "only the human-approval",
            "only the approval step",
            "only the stop",
            "only the stop-and-wait",
        ]
        assert any(p in body_lower for p in scope_phrases), (
            "Sandbox section must explicitly narrow the bypass to the "
            "approval/STOP step"
        )

    def test_procedure_still_lists_validation_codereview_trivy(self, skill_text: str) -> None:
        """The top-level Procedure section still lists the full pipeline.
        The sandbox addition must not have deleted any pre-existing
        gate."""
        proc = _section_body(skill_text, "Procedure")
        assert proc, "Procedure section missing"
        proc_lower = proc.lower()
        assert "spec_validate_structure" in proc_lower or "validate" in proc_lower
        assert "code-reviewer" in proc_lower
        # trivy lives in the Dependency Vulnerability Scan section, but
        # the procedure must reference the scan step
        assert "vulnerability" in proc_lower or "trivy" in proc_lower


# ---------------------------------------------------------------------------
# AC 5: Discord #precheck notification fires regardless of context
# ---------------------------------------------------------------------------


class TestDiscordNotificationAlwaysFires:
    """The disc_send to #precheck happens in both sandbox and non-sandbox
    flows."""

    def test_disc_send_documented_in_procedure(self, skill_text: str) -> None:
        """The procedure section still calls disc_send to #precheck."""
        proc = _section_body(skill_text, "Procedure")
        assert "disc_send" in proc
        assert "#precheck" in proc

    def test_sandbox_section_does_not_skip_notifications(self, skill_text: str) -> None:
        """The sandbox section explicitly says notifications still fire
        — the bypass is approval-only."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        body_lower = body.lower()
        # The section asserts notifications keep firing. Accept either
        # "notifications still fire" or "Discord ... fires" or "vox" in
        # a non-bypass context.
        assert "notification" in body_lower or "discord" in body_lower, (
            "Sandbox section must mention notifications to make clear "
            "they still fire"
        )

    def test_procedure_keeps_always_do_both_invariant(self, skill_text: str) -> None:
        """The 'ALWAYS do both' invariant for disc_send + vox is
        preserved — this guards the rule that notification is not a
        casualty of the auto-approval."""
        proc = _section_body(skill_text, "Procedure")
        assert "ALWAYS do both" in proc


# ---------------------------------------------------------------------------
# AC 6: IT-09 end-to-end on proving-ground
#
# IT-09 is an integration test executed against the real KAHUNA pipeline.
# It is out of scope for this unit suite (Dev Spec §6.2). The unit-level
# proxy here asserts the behaviors IT-09 will exercise are present and
# coherent in the skill doc — i.e. that the artifact under test (this
# SKILL.md) is in a state that IT-09 *can* pass against.
# ---------------------------------------------------------------------------


class TestIT09ProxyDocumented:
    """Unit-level proxies for the IT-09 contract.

    IT-09 negative case: a feature branch on main keeps STOP-and-wait.
    IT-09 positive case: a kahuna/* base auto-approves with the sentinel.
    Both branches of the contract must be present and unambiguous in the
    skill doc.
    """

    def test_both_branches_of_behavior_matrix_present(self, skill_text: str) -> None:
        """The skill documents BOTH branches (sandbox_context true AND
        false) of the behavior switch. A one-sided change would silently
        break IT-09's negative case."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        assert re.search(r"sandbox_context\s*==\s*true", body, re.IGNORECASE), (
            "Behavior matrix missing the sandbox_context == true branch"
        )
        assert re.search(r"sandbox_context\s*==\s*false", body, re.IGNORECASE), (
            "Behavior matrix missing the sandbox_context == false branch"
        )

    def test_sentinel_is_emitted_on_stdout_or_transcript(self, skill_text: str) -> None:
        """The sentinel must be a *visible* artifact — emitted on stdout
        / printed / made grep-able. IT-09 will assert on it. A purely
        internal flag would be invisible to the harness."""
        body = _section_body(skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)")
        body_lower = body.lower()
        # Accept any phrasing that indicates the sentinel is surfaced
        assert any(
            kw in body_lower
            for kw in ("emit", "print", "stdout", "grep-able", "scrollback", "transcript")
        ), "Sentinel must be documented as emitted/visible (stdout/transcript)"

    def test_skill_does_not_introduce_silent_bypass(self, skill_text: str) -> None:
        """Defensive: the doc must NOT say the gate can be skipped on
        notification failure in non-sandbox contexts. The original rule
        'Never bypass the STOP on notification failure' must survive."""
        proc = _section_body(skill_text, "Procedure")
        # Original invariant text
        assert "Never bypass the STOP on notification failure" in proc, (
            "The 'Never bypass STOP on notification failure' invariant "
            "must remain in the Procedure section (non-sandbox contexts)"
        )
