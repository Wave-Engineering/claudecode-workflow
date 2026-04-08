"""Tests for docs/devspec-template.md — co-produce rule and checklist updates.

Validates:
- Co-produce rule is present in Section 8 preamble
- Foundation Story Checklist references Deliverables Manifest
- Foundation Story Checklist specifies unified build system (CI = terminal)
- Closing Story Checklist verifies manifest rows for the phase are delivered
- Closing Story Checklist verifies verification procedures are executed
- Test tier guidance is present in Section 6 preamble
- No orphaned references to old section names (5.A Artifact Manifest, 7.1 Documentation Kit)
- Internal cross-references are consistent
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Fixture: load the Dev Spec template once per module
# ---------------------------------------------------------------------------

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "docs" / "devspec-template.md"


@pytest.fixture(scope="module")
def template_text() -> str:
    """Read the Dev Spec template file."""
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def _extract_section(text: str, heading: str) -> str:
    """Extract content from a markdown heading until the next heading of same or higher level.

    Parameters
    ----------
    text:
        Full markdown document text.
    heading:
        The heading text to search for (e.g., "### Co-production Rule").
        The leading '#' characters determine the heading level.

    Returns
    -------
    str
        The content from the heading line to the next heading of same or higher level,
        or to end of file.
    """
    level = len(heading) - len(heading.lstrip("#"))
    # Build pattern: match the heading, capture everything until next heading of same/higher level
    escaped = re.escape(heading.strip())
    pattern = rf"^{escaped}\s*\n(.*?)(?=^#{{1,{level}}} |\Z)"
    match = re.search(pattern, text, re.MULTILINE | re.DOTALL)
    if match:
        return heading + "\n" + match.group(1)
    return ""


# ---------------------------------------------------------------------------
# 1. Co-produce Rule
# ---------------------------------------------------------------------------


class TestCoproduceRule:
    """Verify the co-produce rule subsection exists in Section 8 preamble."""

    def test_coproduce_heading_exists(self, template_text: str) -> None:
        """Co-production Rule heading is present as a subsection in Section 8."""
        assert "### Co-production Rule" in template_text

    def test_coproduce_rule_content(self, template_text: str) -> None:
        """The rule states that waves producing deployable artifacts must also
        produce verification procedures in the same wave."""
        section = _extract_section(template_text, "### Co-production Rule")
        assert "deployable artifact" in section
        assert "verification procedure" in section
        assert "must not be deferred" in section.lower() or "must also include" in section.lower()

    def test_coproduce_after_wave_map(self, template_text: str) -> None:
        """Co-production Rule appears after the Wave Map subsection."""
        wave_map_pos = template_text.find("### Wave Map")
        coproduce_pos = template_text.find("### Co-production Rule")
        assert wave_map_pos != -1, "Wave Map heading not found"
        assert coproduce_pos != -1, "Co-production Rule heading not found"
        assert coproduce_pos > wave_map_pos, (
            "Co-production Rule should appear after Wave Map"
        )

    def test_coproduce_before_phase_template(self, template_text: str) -> None:
        """Co-production Rule appears before the Phase N template."""
        coproduce_pos = template_text.find("### Co-production Rule")
        phase_pos = template_text.find("### Phase N:")
        assert coproduce_pos != -1, "Co-production Rule heading not found"
        assert phase_pos != -1, "Phase N heading not found"
        assert coproduce_pos < phase_pos, (
            "Co-production Rule should appear before Phase N template"
        )


# ---------------------------------------------------------------------------
# 2. Foundation Story Checklist
# ---------------------------------------------------------------------------


class TestFoundationStoryChecklist:
    """Verify Foundation Story Checklist references Deliverables Manifest
    and specifies unified build system."""

    def test_deliverables_manifest_coverage_item(self, template_text: str) -> None:
        """Checklist includes a 'Verify Deliverables Manifest coverage' item."""
        section = _extract_section(template_text, "### Foundation Story Checklist")
        assert "Deliverables Manifest" in section
        assert "Wave 1" in section
        # Must reference Section 5.A
        assert "Section 5.A" in section or "5.A" in section

    def test_unified_build_system_item(self, template_text: str) -> None:
        """Checklist includes a unified build system item specifying CI = terminal."""
        section = _extract_section(template_text, "### Foundation Story Checklist")
        assert "Unified build system" in section
        assert "CI and terminal use identical commands" in section

    def test_artifact_build_references_deliverables_manifest(self, template_text: str) -> None:
        """Artifact build & install references the Deliverables Manifest."""
        section = _extract_section(template_text, "### Foundation Story Checklist")
        # Find the artifact build line and ensure it references the manifest
        lines = section.split("\n")
        artifact_lines = [l for l in lines if "Artifact build" in l]
        assert len(artifact_lines) > 0, "No 'Artifact build' item found"
        assert "Deliverables Manifest" in artifact_lines[0]


# ---------------------------------------------------------------------------
# 3. Closing Story Checklist
# ---------------------------------------------------------------------------


class TestClosingStoryChecklist:
    """Verify Closing Story Checklist references Deliverables Manifest."""

    def test_manifest_rows_verification(self, template_text: str) -> None:
        """Checklist verifies all manifest rows for the phase are delivered."""
        section = _extract_section(template_text, "### Closing Story Checklist")
        assert "Deliverables Manifest rows" in section
        assert "Produced In" in section

    def test_verification_procedures_executed(self, template_text: str) -> None:
        """Checklist verifies verification procedures are executed and recorded."""
        section = _extract_section(template_text, "### Closing Story Checklist")
        assert "verification procedure" in section.lower()
        assert "executed and recorded" in section.lower()

    def test_existing_mv_items_remain(self, template_text: str) -> None:
        """Existing MV-XX execution items still present."""
        section = _extract_section(template_text, "### Closing Story Checklist")
        assert "MV-XX" in section
        assert "pass/fail" in section.lower()
        assert "VRTM" in section


# ---------------------------------------------------------------------------
# 4. Test Tier Guidance
# ---------------------------------------------------------------------------


class TestTestTierGuidance:
    """Verify test tier guidance in Section 6 preamble."""

    def test_tier_guidance_present(self, template_text: str) -> None:
        """Test tier expectations block is present in the Section 6 preamble."""
        # The guidance should appear between "## 6. Test Plan" and "### 6.1"
        section_6_start = template_text.find("## 6. Test Plan")
        section_6_1_start = template_text.find("### 6.1")
        assert section_6_start != -1, "Section 6 not found"
        assert section_6_1_start != -1, "Section 6.1 not found"
        preamble = template_text[section_6_start:section_6_1_start]
        assert "Test tier expectations" in preamble

    def test_unit_test_tier(self, template_text: str) -> None:
        """Unit tests are described as always expected."""
        section_6_start = template_text.find("## 6. Test Plan")
        section_6_1_start = template_text.find("### 6.1")
        preamble = template_text[section_6_start:section_6_1_start]
        assert "Unit tests" in preamble
        assert "always expected" in preamble

    def test_integration_test_tier(self, template_text: str) -> None:
        """Integration tests are expected when component boundaries exist."""
        section_6_start = template_text.find("## 6. Test Plan")
        section_6_1_start = template_text.find("### 6.1")
        preamble = template_text[section_6_start:section_6_1_start]
        assert "Integration tests" in preamble
        assert "component boundaries" in preamble

    def test_e2e_test_tier(self, template_text: str) -> None:
        """E2E tests are expected when user-facing flows exist."""
        section_6_start = template_text.find("## 6. Test Plan")
        section_6_1_start = template_text.find("### 6.1")
        preamble = template_text[section_6_start:section_6_1_start]
        assert "End-to-end tests" in preamble or "E2E tests" in preamble
        assert "user-facing flows" in preamble

    def test_manual_verification_tier(self, template_text: str) -> None:
        """Manual verification must be executed AND documented."""
        section_6_start = template_text.find("## 6. Test Plan")
        section_6_1_start = template_text.find("### 6.1")
        preamble = template_text[section_6_start:section_6_1_start]
        assert "Manual verification" in preamble
        assert "executed" in preamble.lower()
        assert "documented" in preamble.lower()


# ---------------------------------------------------------------------------
# 5. No orphaned references to old section names
# ---------------------------------------------------------------------------


class TestNoOrphanedReferences:
    """Verify no references to old Section 5.A 'Artifact Manifest' or
    Section 7.1 'Documentation Kit' remain (outside of negative references
    in the finalization checklist)."""

    def test_no_old_artifact_manifest_reference(self, template_text: str) -> None:
        """No references to '5.A Artifact Manifest' (old name) as a section heading
        or positive reference. The negative reference in finalization checklist
        ('not separate Artifact Manifest + Documentation Kit') is acceptable."""
        # Remove the finalization checklist line that uses the old name as a negative reference
        lines = template_text.split("\n")
        filtered = [
            l for l in lines
            if "not separate Artifact Manifest" not in l
        ]
        filtered_text = "\n".join(filtered)
        # Should NOT contain "Artifact Manifest" as a standalone term (the section is now "Deliverables Manifest")
        assert "Artifact Manifest" not in filtered_text, (
            "Found orphaned reference to old 'Artifact Manifest' name"
        )

    def test_no_section_7_1_reference(self, template_text: str) -> None:
        """No references to Section 7.1 or 'Documentation Kit' remain."""
        lines = template_text.split("\n")
        filtered = [
            l for l in lines
            if "not separate Artifact Manifest" not in l
        ]
        filtered_text = "\n".join(filtered)
        assert "Section 7.1" not in filtered_text, (
            "Found orphaned reference to old Section 7.1"
        )
        assert "Documentation Kit" not in filtered_text, (
            "Found orphaned reference to old 'Documentation Kit' name"
        )


# ---------------------------------------------------------------------------
# 6. Cross-reference consistency
# ---------------------------------------------------------------------------


class TestCrossReferenceConsistency:
    """Verify internal cross-references are consistent."""

    def test_section_5a_exists(self, template_text: str) -> None:
        """Section 5.A Deliverables Manifest exists and is referenced correctly."""
        assert "### 5.A Deliverables Manifest" in template_text

    def test_section_5b_exists(self, template_text: str) -> None:
        """Section 5.B Installation & Deployment exists."""
        assert "### 5.B Installation" in template_text

    def test_section_6_exists(self, template_text: str) -> None:
        """Section 6 Test Plan exists."""
        assert "## 6. Test Plan" in template_text

    def test_section_7_exists(self, template_text: str) -> None:
        """Section 7 Definition of Done exists."""
        assert "## 7. Definition of Done" in template_text

    def test_section_8_exists(self, template_text: str) -> None:
        """Section 8 Phased Implementation Plan exists."""
        assert "## 8. Phased Implementation Plan" in template_text

    def test_foundation_checklist_references_section_5a(self, template_text: str) -> None:
        """Foundation Story Checklist references to Section 5.A are valid."""
        section = _extract_section(template_text, "### Foundation Story Checklist")
        refs_5a = section.count("Section 5.A") + section.count("(Section 5.A)")
        assert refs_5a >= 1, "Foundation checklist should reference Section 5.A"
        # Verify 5.A actually exists
        assert "### 5.A" in template_text

    def test_foundation_checklist_references_section_5b(self, template_text: str) -> None:
        """Foundation Story Checklist references to Section 5.B are valid."""
        section = _extract_section(template_text, "### Foundation Story Checklist")
        assert "Section 5.B" in section or "5.B" in section
        # Verify 5.B actually exists
        assert "### 5.B" in template_text

    def test_closing_checklist_references_section_6_4(self, template_text: str) -> None:
        """Closing Story Checklist references Section 6.4."""
        section = _extract_section(template_text, "### Closing Story Checklist")
        assert "Section 6.4" in section or "6.4" in section
        # Verify 6.4 actually exists
        assert "### 6.4" in template_text

    def test_closing_checklist_references_vrtm(self, template_text: str) -> None:
        """Closing Story Checklist references VRTM (Section 9, Appendix V)."""
        section = _extract_section(template_text, "### Closing Story Checklist")
        assert "VRTM" in section
        assert "Section 9" in section or "Appendix V" in section
        # Verify Appendix V exists
        assert "### Appendix V:" in template_text
