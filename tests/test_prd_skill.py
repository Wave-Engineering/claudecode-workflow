"""Tests for skills/prd/SKILL.md — approve and upshift subcommands.

Validates:
- Frontmatter description updated to include approval and backlog population
- Commands section lists all four subcommands
- Routing block dispatches approve and upshift
- Help template documents approve and upshift subcommands
- prd-approve template: runs finalization, presents summary, hard-stops, records metadata, handles rejection
- prd-upshift template: verifies approval, parses Section 8, creates epics/stories/wave masters, backfills
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
SKILL_PATH = _ROOT / "skills" / "prd" / "SKILL.md"
SKILL_REF_PATH = _ROOT / "docs" / "skill-reference.md"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the PRD SKILL.md file."""
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


def _extract_prd_section(text: str) -> str:
    """Extract the /prd section from skill-reference.md."""
    start = text.find("### `/prd`")
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
        """Commands section lists /prd create."""
        assert "`/prd create`" in skill_text

    def test_commands_lists_finalize(self, skill_text: str) -> None:
        """Commands section lists /prd finalize."""
        assert "`/prd finalize`" in skill_text

    def test_commands_lists_approve(self, skill_text: str) -> None:
        """Commands section lists /prd approve."""
        assert "`/prd approve`" in skill_text

    def test_commands_lists_upshift(self, skill_text: str) -> None:
        """Commands section lists /prd upshift."""
        assert "`/prd upshift`" in skill_text


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
        """Routing block dispatches approve to prd-approve template."""
        assert "prd-approve" in skill_text

    def test_routing_upshift_dispatches_to_template(self, skill_text: str) -> None:
        """Routing block dispatches upshift to prd-upshift template."""
        assert "prd-upshift" in skill_text


# ---------------------------------------------------------------------------
# 4. Help template
# ---------------------------------------------------------------------------


class TestHelpTemplate:
    """Verify the help template documents approve and upshift."""

    def test_help_template_exists(self, skill_text: str) -> None:
        """The prd-help template exists."""
        help_text = _extract_template(skill_text, "prd-help")
        assert help_text, "prd-help template not found"

    def test_help_lists_approve(self, skill_text: str) -> None:
        """Help template lists /prd approve."""
        help_text = _extract_template(skill_text, "prd-help")
        assert "/prd approve" in help_text

    def test_help_lists_upshift(self, skill_text: str) -> None:
        """Help template lists /prd upshift."""
        help_text = _extract_template(skill_text, "prd-help")
        assert "/prd upshift" in help_text

    def test_help_approve_describes_approval_gate(self, skill_text: str) -> None:
        """Help text for /prd approve mentions approval gate behavior."""
        help_text = _extract_template(skill_text, "prd-help")
        approve_idx = help_text.find("/prd approve")
        assert approve_idx != -1
        after_approve = help_text[approve_idx:]
        next_heading = after_approve.find("\n###", 1)
        approve_help = after_approve[:next_heading] if next_heading != -1 else after_approve
        assert "approval" in approve_help.lower()

    def test_help_upshift_describes_backlog(self, skill_text: str) -> None:
        """Help text for /prd upshift mentions backlog population."""
        help_text = _extract_template(skill_text, "prd-help")
        upshift_idx = help_text.find("/prd upshift")
        assert upshift_idx != -1
        after_upshift = help_text[upshift_idx:]
        next_heading = after_upshift.find("\n###", 1)
        upshift_help = after_upshift[:next_heading] if next_heading != -1 else after_upshift
        assert "backlog" in upshift_help.lower() or "issue" in upshift_help.lower()

    def test_help_approve_prerequisite(self, skill_text: str) -> None:
        """Help text for /prd approve mentions prerequisite."""
        help_text = _extract_template(skill_text, "prd-help")
        approve_idx = help_text.find("/prd approve")
        assert approve_idx != -1
        after_approve = help_text[approve_idx:]
        next_heading = after_approve.find("\n###", 1)
        approve_help = after_approve[:next_heading] if next_heading != -1 else after_approve
        assert "prerequisite" in approve_help.lower() or "finalize" in approve_help.lower()

    def test_help_upshift_prerequisite(self, skill_text: str) -> None:
        """Help text for /prd upshift mentions approved PRD prerequisite."""
        help_text = _extract_template(skill_text, "prd-help")
        upshift_idx = help_text.find("/prd upshift")
        assert upshift_idx != -1
        after_upshift = help_text[upshift_idx:]
        next_heading = after_upshift.find("\n###", 1)
        upshift_help = after_upshift[:next_heading] if next_heading != -1 else after_upshift
        assert "approved" in upshift_help.lower()


# ---------------------------------------------------------------------------
# 5. prd-approve template
# ---------------------------------------------------------------------------


class TestApproveTemplate:
    """Verify the prd-approve template implements the approval gate."""

    def test_approve_template_exists(self, skill_text: str) -> None:
        """The prd-approve template exists."""
        approve = _extract_template(skill_text, "prd-approve")
        assert approve, "prd-approve template not found"

    def test_approve_runs_finalization(self, skill_text: str) -> None:
        """The approve template runs the finalization checklist."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "finalization" in approve.lower() or "finalize" in approve.lower()
        assert "checklist" in approve.lower() or "check" in approve.lower()

    def test_approve_presents_summary(self, skill_text: str) -> None:
        """The approve template presents a PRD summary with counts."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "summary" in approve.lower()
        assert "section" in approve.lower()
        assert "stor" in approve.lower()  # story/stories
        assert "wave" in approve.lower()
        assert "deliverable" in approve.lower()

    def test_approve_hard_stop(self, skill_text: str) -> None:
        """The approve template includes a hard stop for human approval."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "approve" in approve.lower() and "yes/no" in approve.lower()

    def test_approve_waits_for_response(self, skill_text: str) -> None:
        """The approve template explicitly waits for the user's response."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "wait" in approve.lower()

    def test_approve_records_metadata(self, skill_text: str) -> None:
        """The approve template records approval metadata in the PRD."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "PRD-APPROVAL" in approve
        assert "approved: true" in approve
        assert "approved_by" in approve
        assert "approved_at" in approve

    def test_approve_records_timestamp(self, skill_text: str) -> None:
        """The approve template records an ISO 8601 timestamp."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "ISO 8601" in approve or "timestamp" in approve.lower()

    def test_approve_records_finalization_score(self, skill_text: str) -> None:
        """The approve template records the finalization score."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "finalization_score" in approve

    def test_approve_handles_rejection(self, skill_text: str) -> None:
        """The approve template handles rejection (user says no)."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "rejection" in approve.lower() or "reject" in approve.lower()

    def test_approve_rejects_on_finalization_failure(self, skill_text: str) -> None:
        """The approve template rejects if finalization checks fail."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "fail" in approve.lower()
        # Must stop if checks fail
        assert "stop" in approve.lower()

    def test_approve_suggests_next_step(self, skill_text: str) -> None:
        """The approve template suggests /prd upshift as the next step."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "/prd upshift" in approve

    def test_approve_locates_prd(self, skill_text: str) -> None:
        """The approve template includes PRD file location logic."""
        approve = _extract_template(skill_text, "prd-approve")
        assert "docs/*-PRD.md" in approve or "*-PRD.md" in approve


# ---------------------------------------------------------------------------
# 6. prd-upshift template
# ---------------------------------------------------------------------------


class TestUpshiftTemplate:
    """Verify the prd-upshift template implements backlog population."""

    def test_upshift_template_exists(self, skill_text: str) -> None:
        """The prd-upshift template exists."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert upshift, "prd-upshift template not found"

    def test_upshift_verifies_approval(self, skill_text: str) -> None:
        """The upshift template verifies the PRD is approved."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "PRD-APPROVAL" in upshift or "approved" in upshift.lower()
        assert "approved: true" in upshift

    def test_upshift_refuses_unapproved(self, skill_text: str) -> None:
        """The upshift template refuses to run on an unapproved PRD."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "/prd approve" in upshift
        assert "stop" in upshift.lower() or "do not" in upshift.lower()

    def test_upshift_parses_section_8(self, skill_text: str) -> None:
        """The upshift template parses Section 8 (Phased Implementation Plan)."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "Section 8" in upshift
        assert "Phased Implementation Plan" in upshift

    def test_upshift_creates_epic_per_phase(self, skill_text: str) -> None:
        """The upshift template creates one epic issue per Phase."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "epic" in upshift.lower()
        assert "phase" in upshift.lower()

    def test_upshift_epic_includes_dod(self, skill_text: str) -> None:
        """The upshift template includes Phase DoD in epic acceptance criteria."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "DoD" in upshift or "Definition of Done" in upshift

    def test_upshift_creates_story_issues(self, skill_text: str) -> None:
        """The upshift template creates one issue per Story."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "story" in upshift.lower()
        assert "issue" in upshift.lower()

    def test_upshift_story_has_implementation_steps(self, skill_text: str) -> None:
        """The upshift template includes implementation steps in story issues."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "Implementation Steps" in upshift or "implementation steps" in upshift.lower()

    def test_upshift_story_has_test_procedures(self, skill_text: str) -> None:
        """The upshift template includes test procedures in story issues."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "Test Procedures" in upshift or "test procedures" in upshift.lower()

    def test_upshift_story_has_acceptance_criteria(self, skill_text: str) -> None:
        """The upshift template includes acceptance criteria in story issues."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "Acceptance Criteria" in upshift or "acceptance criteria" in upshift.lower()

    def test_upshift_story_has_wave_assignment(self, skill_text: str) -> None:
        """The upshift template includes wave assignment in story issues."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "wave" in upshift.lower()

    def test_upshift_creates_wave_masters(self, skill_text: str) -> None:
        """The upshift template creates wave master issues."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "Wave" in upshift and "Master" in upshift

    def test_upshift_wave_master_links_stories(self, skill_text: str) -> None:
        """The upshift template links constituent stories in wave master issues."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "Constituent Stories" in upshift or "constituent" in upshift.lower()

    def test_upshift_reports_summary(self, skill_text: str) -> None:
        """The upshift template reports a creation summary."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "summary" in upshift.lower()
        assert "epic" in upshift.lower()
        assert "stor" in upshift.lower()

    def test_upshift_backfills_issue_numbers(self, skill_text: str) -> None:
        """The upshift template backfills issue numbers into the PRD."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "backfill" in upshift.lower() or "Backfill" in upshift

    def test_upshift_suggests_prepwaves(self, skill_text: str) -> None:
        """The upshift template suggests /prepwaves as the next step."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "/prepwaves" in upshift

    def test_upshift_locates_prd(self, skill_text: str) -> None:
        """The upshift template includes PRD file location logic."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "docs/*-PRD.md" in upshift or "*-PRD.md" in upshift

    def test_upshift_links_stories_to_epics(self, skill_text: str) -> None:
        """The upshift template links story issues to parent epic."""
        upshift = _extract_template(skill_text, "prd-upshift")
        assert "parent epic" in upshift.lower() or "Parent Epic" in upshift


# ---------------------------------------------------------------------------
# 7. docs/skill-reference.md
# ---------------------------------------------------------------------------


class TestSkillReference:
    """Verify docs/skill-reference.md has updated /prd section."""

    def test_prd_section_exists(self, skill_ref_text: str) -> None:
        """The /prd section exists in skill-reference.md."""
        assert "### `/prd`" in skill_ref_text

    def test_prd_examples_include_approve(self, skill_ref_text: str) -> None:
        """The /prd examples include /prd approve."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "/prd approve" in prd_section

    def test_prd_examples_include_upshift(self, skill_ref_text: str) -> None:
        """The /prd examples include /prd upshift."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "/prd upshift" in prd_section

    def test_prd_pipeline_includes_approve(self, skill_ref_text: str) -> None:
        """The pipeline description includes /prd approve."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "/prd approve" in prd_section

    def test_prd_pipeline_includes_upshift(self, skill_ref_text: str) -> None:
        """The pipeline description includes /prd upshift."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "/prd upshift" in prd_section

    def test_prd_approve_flow_documented(self, skill_ref_text: str) -> None:
        """The /prd approve flow is documented."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "/prd approve" in prd_section
        assert "approval" in prd_section.lower()
        assert "finalization" in prd_section.lower()

    def test_prd_upshift_flow_documented(self, skill_ref_text: str) -> None:
        """The /prd upshift flow is documented."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "/prd upshift" in prd_section
        assert "epic" in prd_section.lower()
        assert "story" in prd_section.lower() or "stories" in prd_section.lower()

    def test_prd_description_mentions_approval(self, skill_ref_text: str) -> None:
        """The /prd description mentions approval gate."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "approval" in prd_section.lower()

    def test_prd_description_mentions_backlog(self, skill_ref_text: str) -> None:
        """The /prd description mentions backlog population."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "backlog" in prd_section.lower()

    def test_prd_when_to_use_includes_approval(self, skill_ref_text: str) -> None:
        """The 'When to use it' section includes approval use case."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "approval" in prd_section.lower()

    def test_prd_when_to_use_includes_backlog(self, skill_ref_text: str) -> None:
        """The 'When to use it' section includes backlog use case."""
        prd_section = _extract_prd_section(skill_ref_text)
        assert "backlog" in prd_section.lower()
