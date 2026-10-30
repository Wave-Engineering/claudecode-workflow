"""Tests for skills/precheck/SKILL.md — sandbox-aware auto-approval.

Validates the changes from #416:
- Sandbox detection regex `^kahuna/[0-9]+-` is documented in the skill.
- The auto-approval path emits the literal sentinel
  `[AUTO-APPROVED: kahuna sandbox]` before invoking `/mmr` (#1235).
- The non-sandbox path is unchanged: STOP-and-wait for
  the merge call (`/mmr` / `/scpmmr` / affirmative).
- Checklist items (validation, code-reviewer, trivy) still run in full
  inside the sandbox — only the human-approval step is bypassed.
- Discord `#precheck` notification fires regardless of context.

The IT-09 end-to-end proving-ground test is integration-level and tracked
in Dev Spec §6.2 (out of scope for this unit suite). The corresponding
unit-level proxy here is `TestIT09ProxyDocumented` — it asserts the
behaviors that IT-09 will exercise are present in the skill doc.
"""

from __future__ import annotations

import os
import re
import textwrap
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
#       before invoking `/mmr` (#1235: precheck already opened + readied the PR/MR)
# ---------------------------------------------------------------------------


class TestSentinelAndAutoApprove:
    """The sentinel literal must appear, and `/mmr` must follow it."""

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

    def test_sentinel_precedes_mmr_invocation(self, skill_text: str) -> None:
        """The skill describes emitting the sentinel BEFORE invoking
        `/mmr` — not after, which would defeat its 'announcing the
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
        mmr_idx = true_block.find("`/mmr`")
        assert sentinel_idx != -1, (
            "sentinel missing in sandbox_context == true branch"
        )
        assert mmr_idx != -1, (
            "/mmr invocation missing in sandbox_context == true branch"
        )
        assert sentinel_idx < mmr_idx, (
            "Sentinel must be emitted BEFORE /mmr is invoked"
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

    def test_precheck_notification_routes_to_lead(self, skill_text: str) -> None:
        """#1365 (triage #15): the notice goes to BJ (#precheck + vox, both) or, under
        a named lead, to that lead by SendMessage with no #precheck post and no vox.
        The notification itself is still never skipped."""
        assert "ALWAYS do both" not in skill_text
        flat = " ".join(_section_body(skill_text, "Procedure").split())
        assert '"$NOTIFY" <repo_root> <your Dev-Name>' in flat
        assert "`bj` → post to `#precheck`" in flat and "Do both, always." in flat
        assert "`lead <session> <dev>` → `SendMessage` to `<session>`" in flat
        assert "**No `#precheck` post and no `vox`**" in flat
        assert "with `@<dev>` as its first token, still with no `vox`" in flat
        assert "[WARNING: lead field malformed: <its stderr>]" in flat
        # #1373 review: the no-@ rule names the lead fallback as its one exception.
        notice = " ".join(_section_body(skill_text, "The Notification (Discord + vox, or the lead)").split())
        assert "**The one exception is the lead fallback** (Step 4)" in notice
        assert "precheck-notify-target.sh" in skill_text
        assert "BJ approved routing to a named lead (claudecode-workflow:triage #15)." in skill_text
        rules = " ".join(_section_body(skill_text, "Rules").split())
        assert "**The notification is ALWAYS sent** (to BJ: `#precheck` + `vox`; to a named lead: `SendMessage`)" in rules
        tools = _section_body(skill_text, "Tools Used")
        assert "`SendMessage`" in tools


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


# ---------------------------------------------------------------------------
# Issue #462: Platform-specific enforcement prerequisite is documented
#
# The sandbox auto-approval depends on platform-side configuration that
# constrains what a Flight Agent can push to. GitHub uses branch-protection
# rules / rulesets; GitLab uses approval rules scoped via
# `protected_branch_ids`. The skill body and CLAUDE.md exception clause must
# name BOTH platforms' enforcement mechanisms so an operator does not assume
# the safety is platform-symmetric.
# ---------------------------------------------------------------------------


CLAUDE_MD_PATH = _ROOT / "CLAUDE.md"


@pytest.fixture(scope="module")
def claude_md_text() -> str:
    """Read the project CLAUDE.md file."""
    return CLAUDE_MD_PATH.read_text(encoding="utf-8")


class TestPlatformPrerequisiteDocumented:
    """Issue #462: skill must name both GitHub and GitLab enforcement.

    Verifies that the Sandbox Auto-Approval section explicitly documents
    the platform-side configuration prerequisite for both platforms — and
    that the skill mentions a detection / warning path so a missing
    prerequisite surfaces to the operator rather than silently allowing
    a phantom auto-approval.
    """

    def test_sandbox_section_names_github_branch_protection(
        self, skill_text: str
    ) -> None:
        """The sandbox section names GitHub's branch-protection rule
        mechanism as the load-bearing GitHub prerequisite."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        body_lower = body.lower()
        assert "github" in body_lower
        # The GitHub mechanism is "branch protection" / "rulesets"
        assert "branch-protection" in body_lower or "branch protection" in body_lower or "ruleset" in body_lower, (
            "Sandbox section must name GitHub's branch-protection / "
            "ruleset mechanism"
        )

    def test_sandbox_section_names_gitlab_approval_rules(
        self, skill_text: str
    ) -> None:
        """The sandbox section names GitLab's `protected_branch_ids`
        approval-rule mechanism as the load-bearing GitLab prerequisite."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        body_lower = body.lower()
        assert "gitlab" in body_lower
        # The GitLab mechanism is approval rules scoped via
        # `protected_branch_ids`. Both terms must appear.
        assert "protected_branch_ids" in body, (
            "Sandbox section must name `protected_branch_ids` — the "
            "load-bearing GitLab scoping field"
        )
        assert "approval" in body_lower, (
            "Sandbox section must mention GitLab's approval rules"
        )

    def test_sandbox_section_references_gl_settings(self, skill_text: str) -> None:
        """The skill points operators at the deployment automation
        (`gl-settings kahuna-sandbox` / gl-settings#27) so a missing
        prerequisite has an actionable remediation."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        assert "gl-settings" in body, (
            "Sandbox section must reference gl-settings (the GitLab "
            "deployment automation)"
        )

    def test_sandbox_section_warns_against_project_wide_endpoint(
        self, skill_text: str
    ) -> None:
        """The skill explicitly calls out that
        `merge_request_approval_settings` MUST NOT be used — that
        project-wide endpoint would unprotect main and is a known
        footgun documented in `docs/kahuna-devspec.md` §5.3.1."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        assert "merge_request_approval_settings" in body, (
            "Skill must warn against `merge_request_approval_settings` "
            "(would unprotect main)"
        )

    def test_sandbox_section_documents_detection_or_warning(
        self, skill_text: str
    ) -> None:
        """AC-3: skill either detects the missing prerequisite or emits
        a warning. The current contract is best-effort detection +
        non-blocking warning. Verify the section documents the warning
        sentinel pattern for both platforms."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        body_lower = body.lower()
        # The detection step must be documented
        assert "detection" in body_lower or "detect" in body_lower
        # And there must be a warning sentinel pattern (so missing
        # prerequisites surface to the operator)
        assert "[WARNING:" in body or "WARNING" in body, (
            "Skill must document a warning emission for missing "
            "prerequisite detection"
        )

    def test_sandbox_section_warning_is_non_blocking(
        self, skill_text: str
    ) -> None:
        """The warning is documented as non-blocking — the wave
        Orchestrator and operator are the final safety net. We assert
        the doc is explicit so a future maintainer doesn't introduce a
        hard-block that would break legitimate flights when the
        platform CLI is missing or returns 403."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        body_lower = body.lower()
        assert "non-blocking" in body_lower or "not block" in body_lower or "do not block" in body_lower, (
            "Skill must document the prerequisite-detection warning as "
            "non-blocking"
        )

    def test_github_behavior_preserved_no_regression(self, skill_text: str) -> None:
        """AC-4: existing GitHub behavior is preserved. The original
        sentinel + `/mmr` invocation flow on a kahuna sandbox must
        still be present and unconditional — the new platform-detection
        warning must NOT have replaced the auto-approval emission."""
        body = _section_body(
            skill_text, "Sandbox Auto-Approval (KAHUNA Flight Agents)"
        )
        # Original sentinel still emitted (guards against regression
        # where someone replaces the auto-approval with a hard prereq
        # check)
        assert SENTINEL_LITERAL in body
        # /mmr invoked (#1235: precheck has already opened and readied the PR/MR)
        assert "`/mmr`" in body


class TestClaudeMdExceptionDocumentsBothPlatforms:
    """Issue #462 AC-2: CLAUDE.md exception clause documents the GitLab
    equivalent of GitHub's branch-protection model."""

    def test_claude_md_exception_clause_present(
        self, claude_md_text: str
    ) -> None:
        """The CLAUDE.md "Exception: Kahuna Sandbox Auto-Approval"
        clause exists (precondition for the rest of the assertions)."""
        assert "Exception: Kahuna Sandbox Auto-Approval" in claude_md_text

    def test_claude_md_exception_names_github_mechanism(
        self, claude_md_text: str
    ) -> None:
        """The CLAUDE.md exception clause names GitHub's
        branch-protection / ruleset mechanism."""
        # Scope to the exception clause body
        match = re.search(
            r"### Exception: Kahuna Sandbox Auto-Approval\s*\n(.*?)(?=\n---|\n##\s|\Z)",
            claude_md_text,
            re.DOTALL,
        )
        assert match, "Exception clause body could not be located"
        body = match.group(1)
        body_lower = body.lower()
        assert "github" in body_lower
        assert (
            "branch-protection" in body_lower
            or "branch protection" in body_lower
            or "ruleset" in body_lower
        ), (
            "CLAUDE.md exception must name GitHub's branch-protection "
            "/ ruleset mechanism"
        )

    def test_claude_md_exception_names_gitlab_mechanism(
        self, claude_md_text: str
    ) -> None:
        """The CLAUDE.md exception clause names GitLab's
        `protected_branch_ids`-scoped approval rule mechanism."""
        match = re.search(
            r"### Exception: Kahuna Sandbox Auto-Approval\s*\n(.*?)(?=\n---|\n##\s|\Z)",
            claude_md_text,
            re.DOTALL,
        )
        assert match, "Exception clause body could not be located"
        body = match.group(1)
        body_lower = body.lower()
        assert "gitlab" in body_lower
        assert "protected_branch_ids" in body, (
            "CLAUDE.md exception must name `protected_branch_ids` — "
            "the load-bearing GitLab scoping field"
        )

    def test_claude_md_exception_references_gl_settings(
        self, claude_md_text: str
    ) -> None:
        """The CLAUDE.md exception clause points operators at the
        deployment automation."""
        match = re.search(
            r"### Exception: Kahuna Sandbox Auto-Approval\s*\n(.*?)(?=\n---|\n##\s|\Z)",
            claude_md_text,
            re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert "gl-settings" in body

    def test_claude_md_exception_preserves_existing_github_path(
        self, claude_md_text: str
    ) -> None:
        """AC-4: the CLAUDE.md exception still describes the unchanged
        GitHub auto-approval flow (sentinel + /mmr, #1235). The platform
        documentation addition must not have deleted the original
        contract."""
        match = re.search(
            r"### Exception: Kahuna Sandbox Auto-Approval\s*\n(.*?)(?=\n---|\n##\s|\Z)",
            claude_md_text,
            re.DOTALL,
        )
        assert match
        body = match.group(1)
        assert SENTINEL_LITERAL in body
        assert "`/mmr`" in body


def test_precheck_job_c_waits_for_local_lanes() -> None:
    """#1358: validate.sh runs dependency-scan.sh itself, so a Job C started in the
    batch beside B-local's lanes puts two trivy runs on one cache. Job C waits for
    the last lane, and the fallback's scans run one at a time."""
    flat = " ".join(SKILL_PATH.read_text().split())
    assert "When Job B's source is B-local, start Job C after the last lane has printed `exit=`, not in the batch" in flat
    assert "When the source is B-ci, start Job C in the batch as now." in flat
    assert "Run the main scan and each per-file scan below one at a time, never in parallel" in flat


def test_precheck_job_e_gates_the_pass() -> None:
    """#1365: the AC gate is an instrument the orchestrator runs itself, and every
    pass definition requires its exit 0."""
    text = SKILL_PATH.read_text()
    flat = " ".join(text.split())
    step0 = flat.split("### Step 0.5")[0]
    assert "precheck-ac-gate.sh" in step0 and 'ACGATE="$cand"' in step0
    assert "**If `STATUS` or `ACGATE` misses, STOP.**" in step0
    assert "### Step 3.5 — Tick the AC" in text
    assert "Never tick what you did not verify." in flat
    assert '"$ACGATE" pr <repo_root> <PR_NUMBER> <N> > <marker_dir>/ac-gate.log 2>&1; echo "exit=$?"' in flat
    assert text.index("### Step 3.5") < text.index("**Job E — The AC gate**") < text.index("### Step 4")
    step4 = flat.split("### Step 4")[1].split("### Step 5")[0]
    assert "Job C exit 0, Job E exit 0. On a pass:" in step4
    step5 = flat.split("### Step 5")[1].split("### `/precheck rearm`")[0]
    assert "- Job C exit 0; - Job E exit 0, with no `[waived]` or `[override]` line in its log." in step5
    rearm = flat.split("### `/precheck rearm`")[1].split("## Dependency Vulnerability Scan")[0]
    assert "Then run Job E yourself at `HEAD_SHA`" in rearm
    assert "every lane `exit=0`, and Job E exit 0, and no `[waived]`/`[override]` line in the Job E log." in rearm
    assert "AC gate (precheck-ac-gate.sh exit=<n>: <C>/<T> checked, <W> waived, <P> post-merge)" in flat
    assert "Implementation (AC verified)" not in flat


def test_precheck_waiver_forces_human_stop() -> None:
    """#1365: the gate checks a waiver's form, not its author, so on every path where
    BJ is not making the merge call a waiver line forces the STOP, routed to BJ."""
    flat = " ".join(SKILL_PATH.read_text().split())
    step5 = flat.split("### Step 5")[1].split("### `/precheck rearm`")[0]
    rule = "if the Job E log (`<marker_dir>/ac-gate.log`) holds any `[waived]` or `[override]` line, none of these exceptions applies: STOP, and route the notice to BJ (`#precheck` + `vox`), never to a lead"
    assert rule in step5
    assert step5.index(rule) < step5.index("[AUTO-APPROVED: kahuna sandbox]")
    # Each exception carries the condition beside its own terms.
    assert "matches `^kahuna/[0-9]+-` and the Job E log holds no `[waived]` or `[override]` line" in step5
    assert "the same mechanical pass as the autochain bullets above, so no `[waived]` or `[override]` line in the Job E log" in step5
    assert "on this exact head, so no `[waived]` or `[override]` line in the Job E log. A waiver stops a lead's merge too, and goes to BJ." in step5


def test_precheck_waiver_routes_to_bj_and_dirties_rearm() -> None:
    """#1365: Step 4 reads the Job E log before routing, and a rearm with a waiver
    line is not clean, so neither tells a lead it may merge."""
    flat = " ".join(SKILL_PATH.read_text().split())
    step4 = flat.split("### Step 4")[1].split("### Step 5")[0]
    rule = "**any `[waived]` or `[override]` line → the `bj` route below, whatever `$NOTIFY` prints.**"
    assert rule in step4
    assert step4.index(rule) < step4.index('Otherwise run `"$NOTIFY" <repo_root> <your Dev-Name>`')
    rearm = flat.split("### `/precheck rearm`")[1].split("## Dependency Vulnerability Scan")[0]
    assert "and Job E exit 0, and no `[waived]`/`[override]` line in the Job E log. A waiver line makes the rearm not clean: STOP and route the notice to BJ" in rearm
    assert rearm.index("A waiver line makes the rearm not clean") < rearm.index("continue to `/mmr`")
    assert "The STOP prints every `[waived]` and `[override]` line from the Job E log verbatim" in rearm
    assert "his affirmative to that STOP is also the merge call" in rearm


def test_precheck_kahuna_notice_ignores_lead_routing() -> None:
    """#1365: the kahuna sandbox merges with no human, so CLAUDE.md's condition 2 holds:
    its notice is `#precheck` + `vox` even under a lead, and a SendMessage only adds."""
    flat = " ".join(SKILL_PATH.read_text().split())
    step4 = flat.split("### Step 4")[1].split("### Step 5")[0]
    assert "**Not on the kahuna sandbox path.** When the base matches `^kahuna/[0-9]+-`" in step4
    assert "notify as for `bj` (`#precheck`, then `vox`), exactly as CLAUDE.md's kahuna condition 2 requires. The `SendMessage` to the lead goes in addition, never instead." in step4
    assert "the `#precheck` post and `vox`, even when a lead is named; a `SendMessage` to the lead goes in addition, never instead" in flat
    assert "except on the kahuna path, where it is `#precheck` + `vox` regardless of lead routing" in flat
    assert "(Discord and `vox`, or the named lead)" not in flat


def test_precheck_body_patch_resolves_repo_from_origin() -> None:
    """#1365: the Step 3.5 body PATCH defines its placeholders from origin."""
    flat = " ".join(SKILL_PATH.read_text().split())
    tick = flat.split("### Step 3.5 — Tick the AC")[1].split("**Job E — The AC gate**")[0]
    assert "from `git remote get-url origin`, never from the CLI's own repo resolution" in tick
    assert "`<host>` is origin's host, and `<enc>` is that path URL-encoded" in tick
    assert "repos/<owner>/<repo>/pulls/<PR_NUMBER>" in tick and "<slug>" not in tick


def _bash_block_after(text: str, marker: str) -> str:
    rest = text[text.index(marker):]
    m = re.search(r"```bash\n(.*?)```", rest, re.DOTALL)
    assert m, f"no bash block after {marker!r}"
    return textwrap.dedent(m.group(1))


def test_name_preserves_unknown_identity_keys(tmp_path: Path) -> None:
    """#1365: /name merges the identity file, so a `lead` written by /grunt survives."""
    import json
    import subprocess

    text = (_ROOT / "skills" / "name" / "SKILL.md").read_text()
    assert "cat > \"$agent_file\"" not in text and "<< 'EOF'" not in text
    block = _bash_block_after(text, "Persist to the resolved identity file")
    assert "jq " in block
    # Run the documented write up to the move; the /tmp mirror is not this test's business.
    script = block.split("# Also keep /tmp copy fresh")[0]
    script = script.replace("<Dev-Team>", "oaw").replace("<name>", "sorting-hat").replace("<emoji>", "🎩")
    ident = tmp_path / ".claude" / "agent-identity.json"
    ident.parent.mkdir()
    ident.write_text(json.dumps({"dev_name": "old", "lead": {"session": "babelfish", "dev_name": "babelfish"}}))
    r = subprocess.run(["bash", "-c", script], env={"PATH": os.environ["PATH"], "project_root": str(tmp_path)},
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    got = json.loads(ident.read_text())
    assert got == {"dev_name": "sorting-hat", "dev_team": "oaw", "dev_avatar": "🎩",
                   "lead": {"session": "babelfish", "dev_name": "babelfish"}}
    # No file at all: the merge creates one.
    ident.unlink()
    r = subprocess.run(["bash", "-c", script], env={"PATH": os.environ["PATH"], "project_root": str(tmp_path)},
                       capture_output=True, text=True, timeout=30, check=False)
    assert r.returncode == 0, r.stderr
    assert json.loads(ident.read_text())["dev_name"] == "sorting-hat"


def test_grunt_writes_lead_field() -> None:
    """#1365: /grunt step 5 names the lead in the grunt's identity, and the charter no
    longer asks the grunt to send its own ready line (its /precheck does)."""
    grunt = (_ROOT / "skills" / "grunt" / "SKILL.md").read_text()
    step5 = grunt[grunt.index("5. **Stand her up in her OWN worktree.**"):grunt.index("6. **Report + step out")]
    block = _bash_block_after(step5, "Then name yourself as her lead")
    assert "jq --arg s \"<lead>\" --arg d \"<lead-dev-name>\" '.lead = {session: $s, dev_name: $d}'" in block
    assert 'mv "$f.tmp" "$f"' in block
    assert "writes the same field in each report's checkout" in " ".join(step5.split())
    charter = (_ROOT / "skills" / "grunt" / "seed-mission.template.md").read_text()
    flat = " ".join(charter.split())
    assert "ready: <PR/MR url>" not in charter
    assert "Your `/precheck` sends the ready notice to your lead itself (the `lead` field in your identity); send no second one, then idle." in flat
