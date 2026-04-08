"""Tests for skills/devspec/SKILL.md — approve and upshift subcommands.

Validates:
- Frontmatter description updated to include approval and backlog population
- Commands section lists all four subcommands
- Routing block dispatches approve and upshift
- Help template documents approve and upshift subcommands
- devspec-approve template: runs finalization, presents summary, hard-stops, records metadata, handles rejection
- devspec-upshift template: verifies approval, parses Section 8, creates epics/stories/wave masters, backfills
- docs/skill-reference.md updated with approve and upshift
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "devspec" / "SKILL.md"
SKILL_REF_PATH = _ROOT / "docs" / "skill-reference.md"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the Dev Spec SKILL.md file."""
    return SKILL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def skill_ref_text() -> str:
    """Read the skill-reference.md file."""
    return SKILL_REF_PATH.read_text(encoding="utf-8")


def _extract_template(text: str, template_name: str) -> str:
    """Extract content between BEGIN TEMPLATE and END TEMPLATE markers."""
    pattern = (
        rf"<!-- BEGIN TEMPLATE: {re.escape(template_name)} -->\n"
        rf"(.*?)"
        rf"<!-- END TEMPLATE: {re.escape(template_name)} -->"
    )
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else ""


def _extract_devspec_section(text: str) -> str:
    """Extract the /devspec section from skill-reference.md."""
    start = text.find("### `/devspec`")
    if start == -1:
        return ""
    # Find next ### heading or ## heading
    next_heading = text.find("\n---", start + 1)
    return text[start:next_heading] if next_heading != -1 else text[start:]


# ---------------------------------------------------------------------------
# 1. Frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatter:
    """Verify SKILL.md frontmatter description includes approval and backlog."""

    def test_frontmatter_mentions_approval(self, skill_text: str) -> None:
        """Frontmatter description mentions approval gate."""
        lines = skill_text.split("\n")
        assert lines[0].strip() == "---"
        end_idx = skill_text.index("---", 4)
        frontmatter = skill_text[:end_idx + 3]
        assert "approval" in frontmatter.lower()

    def test_frontmatter_mentions_backlog(self, skill_text: str) -> None:
        """Frontmatter description mentions backlog population."""
        lines = skill_text.split("\n")
        assert lines[0].strip() == "---"
        end_idx = skill_text.index("---", 4)
        frontmatter = skill_text[:end_idx + 3]
        assert "backlog" in frontmatter.lower()


# ---------------------------------------------------------------------------
# 2. Commands section
# ---------------------------------------------------------------------------


class TestCommandsSection:
    """Verify the Commands section lists all four subcommands."""

    def test_commands_lists_create(self, skill_text: str) -> None:
        """Commands section lists /devspec create."""
        assert "`/devspec create`" in skill_text

    def test_commands_lists_finalize(self, skill_text: str) -> None:
        """Commands section lists /devspec finalize."""
        assert "`/devspec finalize`" in skill_text

    def test_commands_lists_approve(self, skill_text: str) -> None:
        """Commands section lists /devspec approve."""
        assert "`/devspec approve`" in skill_text

    def test_commands_lists_upshift(self, skill_text: str) -> None:
        """Commands section lists /devspec upshift."""
        assert "`/devspec upshift`" in skill_text


# ---------------------------------------------------------------------------
# 3. Routing block
# ---------------------------------------------------------------------------


class TestRoutingBlock:
    """Verify the routing conditional dispatches all four subcommands."""

    def test_routing_create(self, skill_text: str) -> None:
        """Routing block handles create."""
        assert 'eq args "create"' in skill_text

    def test_routing_finalize(self, skill_text: str) -> None:
        """Routing block handles finalize."""
        assert 'eq args "finalize"' in skill_text

    def test_routing_approve(self, skill_text: str) -> None:
        """Routing block handles approve."""
        assert 'eq args "approve"' in skill_text

    def test_routing_upshift(self, skill_text: str) -> None:
        """Routing block handles upshift."""
        assert 'eq args "upshift"' in skill_text

    def test_routing_approve_dispatches_to_template(self, skill_text: str) -> None:
        """Routing block dispatches approve to devspec-approve template."""
        assert "devspec-approve" in skill_text

    def test_routing_upshift_dispatches_to_template(self, skill_text: str) -> None:
        """Routing block dispatches upshift to devspec-upshift template."""
        assert "devspec-upshift" in skill_text


# ---------------------------------------------------------------------------
# 4. Help template
# ---------------------------------------------------------------------------


class TestHelpTemplate:
    """Verify the help template documents approve and upshift."""

    def test_help_template_exists(self, skill_text: str) -> None:
        """The devspec-help template exists."""
        help_text = _extract_template(skill_text, "devspec-help")
        assert help_text, "devspec-help template not found"

    def test_help_lists_approve(self, skill_text: str) -> None:
        """Help template lists /devspec approve."""
        help_text = _extract_template(skill_text, "devspec-help")
        assert "/devspec approve" in help_text

    def test_help_lists_upshift(self, skill_text: str) -> None:
        """Help template lists /devspec upshift."""
        help_text = _extract_template(skill_text, "devspec-help")
        assert "/devspec upshift" in help_text

    def test_help_approve_describes_approval_gate(self, skill_text: str) -> None:
        """Help text for /devspec approve mentions approval gate behavior."""
        help_text = _extract_template(skill_text, "devspec-help")
        approve_idx = help_text.find("/devspec approve")
        assert approve_idx != -1
        after_approve = help_text[approve_idx:]
        next_heading = after_approve.find("\n###", 1)
        approve_help = after_approve[:next_heading] if next_heading != -1 else after_approve
        assert "approval" in approve_help.lower()

    def test_help_upshift_describes_backlog(self, skill_text: str) -> None:
        """Help text for /devspec upshift mentions backlog population."""
        help_text = _extract_template(skill_text, "devspec-help")
        upshift_idx = help_text.find("/devspec upshift")
        assert upshift_idx != -1
        after_upshift = help_text[upshift_idx:]
        next_heading = after_upshift.find("\n###", 1)
        upshift_help = after_upshift[:next_heading] if next_heading != -1 else after_upshift
        assert "backlog" in upshift_help.lower() or "issue" in upshift_help.lower()

    def test_help_approve_prerequisite(self, skill_text: str) -> None:
        """Help text for /devspec approve mentions prerequisite."""
        help_text = _extract_template(skill_text, "devspec-help")
        approve_idx = help_text.find("/devspec approve")
        assert approve_idx != -1
        after_approve = help_text[approve_idx:]
        next_heading = after_approve.find("\n###", 1)
        approve_help = after_approve[:next_heading] if next_heading != -1 else after_approve
        assert "prerequisite" in approve_help.lower() or "finalize" in approve_help.lower()

    def test_help_upshift_prerequisite(self, skill_text: str) -> None:
        """Help text for /devspec upshift mentions approved Dev Spec prerequisite."""
        help_text = _extract_template(skill_text, "devspec-help")
        upshift_idx = help_text.find("/devspec upshift")
        assert upshift_idx != -1
        after_upshift = help_text[upshift_idx:]
        next_heading = after_upshift.find("\n###", 1)
        upshift_help = after_upshift[:next_heading] if next_heading != -1 else after_upshift
        assert "approved" in upshift_help.lower()


# ---------------------------------------------------------------------------
# 5. devspec-approve template
# ---------------------------------------------------------------------------


class TestApproveTemplate:
    """Verify the devspec-approve template implements the approval gate."""

    def test_approve_template_exists(self, skill_text: str) -> None:
        """The devspec-approve template exists."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert approve, "devspec-approve template not found"

    def test_approve_runs_finalization(self, skill_text: str) -> None:
        """The approve template runs the finalization checklist."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "finalization" in approve.lower() or "finalize" in approve.lower()
        assert "checklist" in approve.lower() or "check" in approve.lower()

    def test_approve_presents_summary(self, skill_text: str) -> None:
        """The approve template presents a Dev Spec summary with counts."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "summary" in approve.lower()
        assert "section" in approve.lower()
        assert "stor" in approve.lower()  # story/stories
        assert "wave" in approve.lower()
        assert "deliverable" in approve.lower()

    def test_approve_hard_stop(self, skill_text: str) -> None:
        """The approve template includes a hard stop for human approval."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "approve" in approve.lower() and "yes/no" in approve.lower()

    def test_approve_waits_for_response(self, skill_text: str) -> None:
        """The approve template explicitly waits for the user's response."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "wait" in approve.lower()

    def test_approve_records_metadata(self, skill_text: str) -> None:
        """The approve template records approval metadata in the Dev Spec."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "DEV-SPEC-APPROVAL" in approve
        assert "approved: true" in approve
        assert "approved_by" in approve
        assert "approved_at" in approve

    def test_approve_records_timestamp(self, skill_text: str) -> None:
        """The approve template records an ISO 8601 timestamp."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "ISO 8601" in approve or "timestamp" in approve.lower()

    def test_approve_records_finalization_score(self, skill_text: str) -> None:
        """The approve template records the finalization score."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "finalization_score" in approve

    def test_approve_handles_rejection(self, skill_text: str) -> None:
        """The approve template handles rejection (user says no)."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "rejection" in approve.lower() or "reject" in approve.lower()

    def test_approve_rejects_on_finalization_failure(self, skill_text: str) -> None:
        """The approve template rejects if finalization checks fail."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "fail" in approve.lower()
        # Must stop if checks fail
        assert "stop" in approve.lower()

    def test_approve_suggests_next_step(self, skill_text: str) -> None:
        """The approve template suggests /devspec upshift as the next step."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "/devspec upshift" in approve

    def test_approve_locates_devspec(self, skill_text: str) -> None:
        """The approve template includes Dev Spec file location logic."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "docs/*-devspec.md" in approve or "*-devspec.md" in approve


# ---------------------------------------------------------------------------
# 6. devspec-upshift template
# ---------------------------------------------------------------------------


class TestUpshiftTemplate:
    """Verify the devspec-upshift template implements backlog population."""

    def test_upshift_template_exists(self, skill_text: str) -> None:
        """The devspec-upshift template exists."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert upshift, "devspec-upshift template not found"

    def test_upshift_verifies_approval(self, skill_text: str) -> None:
        """The upshift template verifies the Dev Spec is approved."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "DEV-SPEC-APPROVAL" in upshift or "approved" in upshift.lower()
        assert "approved: true" in upshift

    def test_upshift_refuses_unapproved(self, skill_text: str) -> None:
        """The upshift template refuses to run on an unapproved Dev Spec."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "/devspec approve" in upshift
        assert "stop" in upshift.lower() or "do not" in upshift.lower()

    def test_upshift_parses_section_8(self, skill_text: str) -> None:
        """The upshift template parses Section 8 (Phased Implementation Plan)."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "Section 8" in upshift
        assert "Phased Implementation Plan" in upshift

    def test_upshift_creates_epic_per_phase(self, skill_text: str) -> None:
        """The upshift template creates one epic issue per Phase."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "epic" in upshift.lower()
        assert "phase" in upshift.lower()

    def test_upshift_epic_includes_dod(self, skill_text: str) -> None:
        """The upshift template includes Phase DoD in epic acceptance criteria."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "DoD" in upshift or "Definition of Done" in upshift

    def test_upshift_creates_story_issues(self, skill_text: str) -> None:
        """The upshift template creates one issue per Story."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "story" in upshift.lower()
        assert "issue" in upshift.lower()

    def test_upshift_story_has_implementation_steps(self, skill_text: str) -> None:
        """The upshift template includes implementation steps in story issues."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "Implementation Steps" in upshift or "implementation steps" in upshift.lower()

    def test_upshift_story_has_test_procedures(self, skill_text: str) -> None:
        """The upshift template includes test procedures in story issues."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "Test Procedures" in upshift or "test procedures" in upshift.lower()

    def test_upshift_story_has_acceptance_criteria(self, skill_text: str) -> None:
        """The upshift template includes acceptance criteria in story issues."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "Acceptance Criteria" in upshift or "acceptance criteria" in upshift.lower()

    def test_upshift_story_has_wave_assignment(self, skill_text: str) -> None:
        """The upshift template includes wave assignment in story issues."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "wave" in upshift.lower()

    def test_upshift_creates_wave_masters(self, skill_text: str) -> None:
        """The upshift template creates wave master issues."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "Wave" in upshift and "Master" in upshift

    def test_upshift_wave_master_links_stories(self, skill_text: str) -> None:
        """The upshift template links constituent stories in wave master issues."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "Constituent Stories" in upshift or "constituent" in upshift.lower()

    def test_upshift_reports_summary(self, skill_text: str) -> None:
        """The upshift template reports a creation summary."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "summary" in upshift.lower()
        assert "epic" in upshift.lower()
        assert "stor" in upshift.lower()

    def test_upshift_backfills_issue_numbers(self, skill_text: str) -> None:
        """The upshift template backfills issue numbers into the Dev Spec."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "backfill" in upshift.lower() or "Backfill" in upshift

    def test_upshift_suggests_prepwaves(self, skill_text: str) -> None:
        """The upshift template suggests /prepwaves as the next step."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "/prepwaves" in upshift

    def test_upshift_locates_devspec(self, skill_text: str) -> None:
        """The upshift template includes Dev Spec file location logic."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "docs/*-devspec.md" in upshift or "*-devspec.md" in upshift

    def test_upshift_links_stories_to_epics(self, skill_text: str) -> None:
        """The upshift template links story issues to parent epic."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "parent epic" in upshift.lower() or "Parent Epic" in upshift


# ---------------------------------------------------------------------------
# 7. docs/skill-reference.md
# ---------------------------------------------------------------------------


class TestSkillReference:
    """Verify docs/skill-reference.md has updated /devspec section."""

    def test_devspec_section_exists(self, skill_ref_text: str) -> None:
        """The /devspec section exists in skill-reference.md."""
        assert "### `/devspec`" in skill_ref_text

    def test_devspec_examples_include_approve(self, skill_ref_text: str) -> None:
        """The /devspec examples include /devspec approve."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "/devspec approve" in prd_section

    def test_devspec_examples_include_upshift(self, skill_ref_text: str) -> None:
        """The /devspec examples include /devspec upshift."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "/devspec upshift" in prd_section

    def test_devspec_pipeline_includes_approve(self, skill_ref_text: str) -> None:
        """The pipeline description includes /devspec approve."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "/devspec approve" in prd_section

    def test_devspec_pipeline_includes_upshift(self, skill_ref_text: str) -> None:
        """The pipeline description includes /devspec upshift."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "/devspec upshift" in prd_section

    def test_devspec_approve_flow_documented(self, skill_ref_text: str) -> None:
        """The /devspec approve flow is documented."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "/devspec approve" in prd_section
        assert "approval" in prd_section.lower()
        assert "finalization" in prd_section.lower()

    def test_devspec_upshift_flow_documented(self, skill_ref_text: str) -> None:
        """The /devspec upshift flow is documented."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "/devspec upshift" in prd_section
        assert "epic" in prd_section.lower()
        assert "story" in prd_section.lower() or "stories" in prd_section.lower()

    def test_devspec_description_mentions_approval(self, skill_ref_text: str) -> None:
        """The /devspec description mentions approval gate."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "approval" in prd_section.lower()

    def test_devspec_description_mentions_backlog(self, skill_ref_text: str) -> None:
        """The /devspec description mentions backlog population."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "backlog" in prd_section.lower()

    def test_devspec_when_to_use_includes_approval(self, skill_ref_text: str) -> None:
        """The 'When to use it' section includes approval use case."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "approval" in prd_section.lower()

    def test_devspec_when_to_use_includes_backlog(self, skill_ref_text: str) -> None:
        """The 'When to use it' section includes backlog use case."""
        prd_section = _extract_devspec_section(skill_ref_text)
        assert "backlog" in prd_section.lower()
