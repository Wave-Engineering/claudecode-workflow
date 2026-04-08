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


# ---------------------------------------------------------------------------
# 8. MCP tool invocations (Phase 2 rewrite — Family 3)
# ---------------------------------------------------------------------------


class TestMcpToolInvocations:
    """Verify the rewritten templates invoke the new sdlc-server MCP tool handlers
    instead of running hand-written procedural checks.

    Added for #333 (Family 3 Phase 2 — devspec skill rewrite to use Phase 1 MCP tools).
    """

    def test_finalize_calls_devspec_locate(self, skill_text: str) -> None:
        """The devspec-finalize template calls devspec_locate to find the file."""
        finalize = _extract_template(skill_text, "devspec-finalize")
        assert "devspec_locate" in finalize

    def test_finalize_calls_devspec_finalize_tool(self, skill_text: str) -> None:
        """The devspec-finalize template calls the devspec_finalize MCP tool."""
        finalize = _extract_template(skill_text, "devspec-finalize")
        assert "devspec_finalize(path)" in finalize or "devspec_finalize" in finalize

    def test_approve_calls_devspec_locate(self, skill_text: str) -> None:
        """The devspec-approve template calls devspec_locate."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "devspec_locate" in approve

    def test_approve_calls_devspec_finalize_tool(self, skill_text: str) -> None:
        """The devspec-approve template calls devspec_finalize for the checklist."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "devspec_finalize" in approve

    def test_approve_calls_devspec_summary(self, skill_text: str) -> None:
        """The devspec-approve template calls devspec_summary for the counts."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "devspec_summary" in approve

    def test_approve_calls_devspec_approve_tool(self, skill_text: str) -> None:
        """The devspec-approve template calls the devspec_approve MCP tool
        to write the approval metadata (not hand-written)."""
        approve = _extract_template(skill_text, "devspec-approve")
        assert "devspec_approve(path" in approve or "devspec_approve(" in approve

    def test_upshift_calls_devspec_locate(self, skill_text: str) -> None:
        """The devspec-upshift template calls devspec_locate."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "devspec_locate" in upshift

    def test_upshift_calls_devspec_verify_approved(self, skill_text: str) -> None:
        """The devspec-upshift template calls devspec_verify_approved
        instead of hand-searching for the approval metadata comment."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "devspec_verify_approved" in upshift

    def test_upshift_calls_devspec_parse_section_8(self, skill_text: str) -> None:
        """The devspec-upshift template calls devspec_parse_section_8
        instead of hand-parsing Section 8."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "devspec_parse_section_8" in upshift

    def test_upshift_calls_work_item_for_epics(self, skill_text: str) -> None:
        """The devspec-upshift template calls work_item for epic creation."""
        upshift = _extract_template(skill_text, "devspec-upshift")
        assert "work_item" in upshift
        # Must still describe epic creation
        assert "epic" in upshift.lower()

    def test_create_calls_devspec_locate_before_write(self, skill_text: str) -> None:
        """The devspec-create template calls devspec_locate before writing
        to detect existing Dev Specs (avoids silent overwrite)."""
        create = _extract_template(skill_text, "devspec-create")
        assert "devspec_locate" in create


# ---------------------------------------------------------------------------
# 9. Load-bearing decoupling regression (#333 AC)
# ---------------------------------------------------------------------------


class TestDevSpecCreateDecoupledFromDdd:
    """Regression guard for the #333 load-bearing acceptance criterion:

    /devspec create MUST work end-to-end without any DDD artifact on disk.
    The skill body's Step 1 (Determine Input Source) supports three input
    modes — DDD domain model, external document, verbal description — and
    all three must be preserved as equally first-class. Do NOT add any
    implicit assumption that docs/DOMAIN-MODEL.md or docs/SKETCHBOOK.md
    exists.
    """

    def test_create_template_lists_three_input_sources(self, skill_text: str) -> None:
        """The devspec-create template lists all three input sources."""
        create = _extract_template(skill_text, "devspec-create")
        assert "DDD Domain Model" in create or "DDD domain model" in create.lower()
        assert "External Document" in create or "external document" in create.lower()
        assert "Verbal Description" in create or "verbal description" in create.lower()

    def test_create_template_declares_inputs_first_class(self, skill_text: str) -> None:
        """The devspec-create template explicitly declares that all three
        input modes are equally first-class (not DDD-required)."""
        create = _extract_template(skill_text, "devspec-create")
        # Must explicitly call out that verbal/external work without DDD artifacts
        lower = create.lower()
        assert "first-class" in lower or "equally" in lower

    def test_create_template_verbal_path_does_not_require_domain_model(
        self, skill_text: str
    ) -> None:
        """The devspec-create verbal input path must NOT require
        docs/DOMAIN-MODEL.md to exist. The skill explicitly scopes the DDD
        protocol reading to the DDD input mode only.
        """
        create = _extract_template(skill_text, "devspec-create")
        # The verbal path must be described in a way that makes clear no
        # DDD artifact is required. Verify by finding the verbal branch and
        # confirming it does not point at DOMAIN-MODEL.md.
        lower = create.lower()
        assert "verbal" in lower
        # The decoupling rule must be explicit somewhere in the create template
        assert (
            "must never fail" in lower
            or "decoupl" in lower
            or "without any ddd" in lower
            or "without a ddd" in lower
        )

    def test_create_template_does_not_hardcode_domain_model_read(
        self, skill_text: str
    ) -> None:
        """The devspec-create template must not unconditionally read
        docs/DOMAIN-MODEL.md — any reference to that file must be guarded
        by the DDD input mode."""
        create = _extract_template(skill_text, "devspec-create")
        # Any DOMAIN-MODEL.md reference must appear in a conditional context.
        # We check that the template does NOT say "read docs/DOMAIN-MODEL.md"
        # as an unconditional instruction.
        lines = create.split("\n")
        for line in lines:
            # Flag unconditional reads
            lower = line.lower().strip()
            if lower.startswith("read docs/domain-model.md") or lower.startswith(
                "read `docs/domain-model.md`"
            ):
                pytest.fail(
                    f"devspec-create unconditionally reads DOMAIN-MODEL.md: {line!r}"
                )

    def test_create_template_does_not_hardcode_sketchbook_read(
        self, skill_text: str
    ) -> None:
        """The devspec-create template must not unconditionally read
        docs/SKETCHBOOK.md. Only /ddd commands should touch the sketchbook."""
        create = _extract_template(skill_text, "devspec-create")
        lines = create.split("\n")
        for line in lines:
            lower = line.lower().strip()
            if lower.startswith("read docs/sketchbook.md") or lower.startswith(
                "read `docs/sketchbook.md`"
            ):
                pytest.fail(
                    f"devspec-create unconditionally reads SKETCHBOOK.md: {line!r}"
                )
