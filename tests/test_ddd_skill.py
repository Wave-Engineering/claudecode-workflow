"""Tests for skills/ddd/SKILL.md — ddd accept refactor into concept handoff.

Validates:
- /ddd accept no longer references PRD generation
- /ddd accept includes domain model verification steps (exists, committed)
- /ddd accept includes domain model summary (aggregate/command/policy counts)
- /ddd accept suggests running /prd create
- /ddd begin, /ddd draft, /ddd resume templates are unchanged in structure
- docs/DDD-to-PRD-protocol.md is preserved (not deleted)
- Help text reflects new /ddd accept behavior
- Skill frontmatter description updated
- docs/skill-reference.md updated with new /ddd accept description
- README.md updated with new DDD row description
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "ddd" / "SKILL.md"
PROTOCOL_PATH = _ROOT / "docs" / "DDD-to-PRD-protocol.md"
SKILL_REF_PATH = _ROOT / "docs" / "skill-reference.md"
README_PATH = _ROOT / "README.md"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the DDD SKILL.md file."""
    return SKILL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def skill_ref_text() -> str:
    """Read the skill-reference.md file."""
    return SKILL_REF_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def readme_text() -> str:
    """Read the README.md file."""
    return README_PATH.read_text(encoding="utf-8")


def _extract_template(text: str, template_name: str) -> str:
    """Extract content between BEGIN TEMPLATE and END TEMPLATE markers."""
    pattern = (
        rf"<!-- BEGIN TEMPLATE: {re.escape(template_name)} -->\n"
        rf"(.*?)"
        rf"<!-- END TEMPLATE: {re.escape(template_name)} -->"
    )
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# 1. /ddd accept no longer generates a PRD
# ---------------------------------------------------------------------------


class TestAcceptNoPrdGeneration:
    """Verify /ddd accept does not generate a PRD file."""

    def test_no_prd_file_creation_in_accept(self, skill_text: str) -> None:
        """The ddd-accept template must not reference writing a PRD file."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert accept, "ddd-accept template not found"
        assert "Write `docs/" not in accept
        assert "-PRD.md`" not in accept

    def test_no_prd_template_reading(self, skill_text: str) -> None:
        """The ddd-accept template must not read PRD templates."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "PRD-template.md" not in accept

    def test_no_translation_steps(self, skill_text: str) -> None:
        """The ddd-accept template must not contain DDD-to-PRD translation steps."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "8-step translation" not in accept
        assert "Apply 8-step" not in accept
        assert "Step 1:" not in accept or "Actors" not in accept

    def test_no_ddd_to_prd_protocol_reading(self, skill_text: str) -> None:
        """The ddd-accept template must not read DDD-to-PRD-protocol.md."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "DDD-to-PRD-protocol.md" not in accept

    def test_stop_directive_present(self, skill_text: str) -> None:
        """The ddd-accept template must include an explicit stop directive."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "Stop here" in accept or "Do not generate a PRD" in accept


# ---------------------------------------------------------------------------
# 2. /ddd accept verifies domain model exists and is committed
# ---------------------------------------------------------------------------


class TestAcceptVerification:
    """Verify /ddd accept includes domain model verification."""

    def test_checks_domain_model_exists(self, skill_text: str) -> None:
        """The ddd-accept template checks DOMAIN-MODEL.md exists."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "DOMAIN-MODEL.md" in accept
        assert "exists" in accept.lower() or "missing" in accept.lower()

    def test_checks_domain_model_committed(self, skill_text: str) -> None:
        """The ddd-accept template checks DOMAIN-MODEL.md is committed."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "committed" in accept.lower() or "git status" in accept.lower()

    def test_error_message_for_missing_model(self, skill_text: str) -> None:
        """If DOMAIN-MODEL.md is missing, directs user to /ddd draft."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "/ddd draft" in accept

    def test_error_message_for_uncommitted_changes(self, skill_text: str) -> None:
        """If DOMAIN-MODEL.md has uncommitted changes, tells user to commit."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "uncommitted" in accept.lower()


# ---------------------------------------------------------------------------
# 3. /ddd accept prints summary with counts
# ---------------------------------------------------------------------------


class TestAcceptSummary:
    """Verify /ddd accept prints a domain model summary."""

    def test_summary_mentions_aggregates(self, skill_text: str) -> None:
        """Summary references aggregate counts."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "Aggregate" in accept or "aggregate" in accept

    def test_summary_mentions_commands(self, skill_text: str) -> None:
        """Summary references command counts."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "Command" in accept or "command" in accept

    def test_summary_mentions_policies(self, skill_text: str) -> None:
        """Summary references policy counts."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "Polic" in accept or "polic" in accept

    def test_domain_model_ready_message(self, skill_text: str) -> None:
        """Summary includes a 'Domain model ready' message."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "Domain model ready" in accept


# ---------------------------------------------------------------------------
# 4. /ddd accept suggests running /prd create
# ---------------------------------------------------------------------------


class TestAcceptHandoff:
    """Verify /ddd accept suggests /prd create."""

    def test_suggests_prd_create(self, skill_text: str) -> None:
        """The ddd-accept template suggests running /prd create."""
        accept = _extract_template(skill_text, "ddd-accept")
        assert "/prd create" in accept


# ---------------------------------------------------------------------------
# 5. /ddd begin, /ddd draft, /ddd resume are unchanged
# ---------------------------------------------------------------------------


class TestOtherTemplatesPreserved:
    """Verify begin, draft, and resume templates still exist and have expected content."""

    def test_begin_template_exists(self, skill_text: str) -> None:
        """The ddd-begin template still exists."""
        begin = _extract_template(skill_text, "ddd-begin")
        assert begin, "ddd-begin template not found"

    def test_begin_has_event_storming(self, skill_text: str) -> None:
        """The ddd-begin template still references event storming."""
        begin = _extract_template(skill_text, "ddd-begin")
        assert "Event Storming" in begin

    def test_begin_has_8_stages(self, skill_text: str) -> None:
        """The ddd-begin template still has all 8 stages."""
        begin = _extract_template(skill_text, "ddd-begin")
        assert "Stage 1" in begin
        assert "Stage 8" in begin

    def test_draft_template_exists(self, skill_text: str) -> None:
        """The ddd-draft template still exists."""
        draft = _extract_template(skill_text, "ddd-draft")
        assert draft, "ddd-draft template not found"

    def test_draft_reads_sketchbook(self, skill_text: str) -> None:
        """The ddd-draft template still reads SKETCHBOOK.md."""
        draft = _extract_template(skill_text, "ddd-draft")
        assert "SKETCHBOOK.md" in draft

    def test_resume_template_exists(self, skill_text: str) -> None:
        """The ddd-resume template still exists."""
        resume = _extract_template(skill_text, "ddd-resume")
        assert resume, "ddd-resume template not found"

    def test_resume_checks_sketchbook(self, skill_text: str) -> None:
        """The ddd-resume template still checks for SKETCHBOOK.md."""
        resume = _extract_template(skill_text, "ddd-resume")
        assert "SKETCHBOOK.md" in resume


# ---------------------------------------------------------------------------
# 6. DDD-to-PRD protocol is preserved
# ---------------------------------------------------------------------------


class TestProtocolPreserved:
    """Verify docs/DDD-to-PRD-protocol.md is not deleted."""

    def test_protocol_file_exists(self) -> None:
        """The DDD-to-PRD-protocol.md file must still exist."""
        assert PROTOCOL_PATH.exists(), (
            f"DDD-to-PRD-protocol.md was deleted: {PROTOCOL_PATH}"
        )

    def test_protocol_file_not_empty(self) -> None:
        """The DDD-to-PRD-protocol.md file must not be empty."""
        content = PROTOCOL_PATH.read_text(encoding="utf-8")
        assert len(content.strip()) > 0, "DDD-to-PRD-protocol.md is empty"


# ---------------------------------------------------------------------------
# 7. Help text reflects new /ddd accept behavior
# ---------------------------------------------------------------------------


class TestHelpText:
    """Verify the ddd-help template reflects the new accept behavior."""

    def test_help_accept_no_generate_prd(self, skill_text: str) -> None:
        """Help text for /ddd accept does not say 'Generate PRD'."""
        help_text = _extract_template(skill_text, "ddd-help")
        # Find the accept section in help
        accept_idx = help_text.find("/ddd accept")
        assert accept_idx != -1, "/ddd accept not found in help text"
        # Get the text from /ddd accept to the next ### heading
        after_accept = help_text[accept_idx:]
        next_heading = after_accept.find("\n###", 1)
        accept_help = after_accept[:next_heading] if next_heading != -1 else after_accept
        assert "Generate PRD" not in accept_help

    def test_help_accept_mentions_verify(self, skill_text: str) -> None:
        """Help text for /ddd accept mentions verification."""
        help_text = _extract_template(skill_text, "ddd-help")
        accept_idx = help_text.find("/ddd accept")
        assert accept_idx != -1
        after_accept = help_text[accept_idx:]
        next_heading = after_accept.find("\n###", 1)
        accept_help = after_accept[:next_heading] if next_heading != -1 else after_accept
        assert "Verif" in accept_help or "verif" in accept_help

    def test_help_accept_mentions_prd_create(self, skill_text: str) -> None:
        """Help text for /ddd accept mentions /prd create."""
        help_text = _extract_template(skill_text, "ddd-help")
        accept_idx = help_text.find("/ddd accept")
        assert accept_idx != -1
        after_accept = help_text[accept_idx:]
        next_heading = after_accept.find("\n###", 1)
        accept_help = after_accept[:next_heading] if next_heading != -1 else after_accept
        assert "/prd create" in accept_help


# ---------------------------------------------------------------------------
# 8. Frontmatter description updated
# ---------------------------------------------------------------------------


class TestFrontmatter:
    """Verify SKILL.md frontmatter description reflects the change."""

    def test_frontmatter_no_prd_generation(self, skill_text: str) -> None:
        """Frontmatter description must not say 'PRD generation'."""
        # Extract frontmatter (between --- markers)
        lines = skill_text.split("\n")
        assert lines[0].strip() == "---"
        end_idx = skill_text.index("---", 4)
        frontmatter = skill_text[: end_idx + 3]
        assert "PRD generation" not in frontmatter

    def test_frontmatter_mentions_handoff(self, skill_text: str) -> None:
        """Frontmatter description mentions concept handoff or similar."""
        lines = skill_text.split("\n")
        assert lines[0].strip() == "---"
        end_idx = skill_text.index("---", 4)
        frontmatter = skill_text[: end_idx + 3]
        assert "handoff" in frontmatter.lower() or "hand off" in frontmatter.lower()


# ---------------------------------------------------------------------------
# 9. skill-reference.md updated
# ---------------------------------------------------------------------------


class TestSkillReference:
    """Verify docs/skill-reference.md has updated /ddd accept description."""

    def test_ddd_section_exists(self, skill_ref_text: str) -> None:
        """The /ddd section exists in skill-reference.md."""
        assert "### `/ddd`" in skill_ref_text

    def test_no_translate_domain_model_to_prd(self, skill_ref_text: str) -> None:
        """The /ddd section does not say 'Translate Domain Model to PRD'."""
        # Find the /ddd section
        ddd_start = skill_ref_text.find("### `/ddd`")
        assert ddd_start != -1
        # Find the next ## heading
        next_section = skill_ref_text.find("\n## ", ddd_start + 1)
        ddd_section = skill_ref_text[ddd_start:next_section] if next_section != -1 else skill_ref_text[ddd_start:]
        assert "Translate Domain Model to PRD" not in ddd_section

    def test_accept_described_as_handoff(self, skill_ref_text: str) -> None:
        """The /ddd accept example line reflects handoff behavior."""
        ddd_start = skill_ref_text.find("### `/ddd`")
        assert ddd_start != -1
        next_section = skill_ref_text.find("\n## ", ddd_start + 1)
        ddd_section = skill_ref_text[ddd_start:next_section] if next_section != -1 else skill_ref_text[ddd_start:]
        # The accept line in the examples block should mention verify/handoff
        assert "hand off" in ddd_section.lower() or "verify" in ddd_section.lower()

    def test_pipeline_includes_prd_create(self, skill_ref_text: str) -> None:
        """The pipeline description includes /prd create as the next step."""
        ddd_start = skill_ref_text.find("### `/ddd`")
        assert ddd_start != -1
        next_section = skill_ref_text.find("\n## ", ddd_start + 1)
        ddd_section = skill_ref_text[ddd_start:next_section] if next_section != -1 else skill_ref_text[ddd_start:]
        assert "/prd create" in ddd_section


# ---------------------------------------------------------------------------
# 10. README.md updated
# ---------------------------------------------------------------------------


class TestReadme:
    """Verify README.md has updated DDD row description."""

    def test_ddd_row_exists(self, readme_text: str) -> None:
        """The DDD row exists in the skills table."""
        assert "| ddd |" in readme_text

    def test_ddd_row_no_prd_generation(self, readme_text: str) -> None:
        """The DDD row does not say 'PRD generation'."""
        for line in readme_text.split("\n"):
            if "| ddd |" in line:
                assert "PRD generation" not in line
                break

    def test_ddd_row_mentions_handoff(self, readme_text: str) -> None:
        """The DDD row mentions concept handoff."""
        for line in readme_text.split("\n"):
            if "| ddd |" in line:
                assert "handoff" in line.lower() or "hand off" in line.lower()
                break
