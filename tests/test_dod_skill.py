"""Tests for skills/dod/SKILL.md — DoD verification skill.

Validates:
- SKILL.md frontmatter has correct name and description
- Introduction gate is present
- dod-check template exists with all 8 steps
- Verification categories documented (Docs, Code, Test, Trace)
- N/A opt-out handling documented
- Report format with status indicators
- Approval flow with yes/no/fix responses
- Campaign integration (campaign-status stage-review dod)
- VRTM completeness check
- Remediation suggestions for failures
- docs/skill-reference.md has /dod section
- README.md has dod row in skills table
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "dod" / "SKILL.md"
INTRO_PATH = _ROOT / "skills" / "dod" / "introduction.md"
SKILL_REF_PATH = _ROOT / "docs" / "skill-reference.md"
README_PATH = _ROOT / "README.md"

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the DoD SKILL.md file."""
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
# 1. Frontmatter and structure
# ---------------------------------------------------------------------------


class TestFrontmatter:
    """Verify SKILL.md frontmatter and basic structure."""

    def test_frontmatter_name(self, skill_text: str) -> None:
        """Frontmatter has name: dod."""
        assert "name: dod" in skill_text

    def test_frontmatter_description(self, skill_text: str) -> None:
        """Frontmatter has a description mentioning DoD or verification."""
        lines = skill_text.split("\n")
        assert lines[0].strip() == "---"
        end_idx = skill_text.index("---", 4)
        frontmatter = skill_text[:end_idx + 3]
        assert "verification" in frontmatter.lower() or "definition of done" in frontmatter.lower()

    def test_introduction_gate_present(self, skill_text: str) -> None:
        """Introduction gate comment is present."""
        assert "introduction-gate" in skill_text
        assert "/tmp/.skill-intro-dod" in skill_text

    def test_introduction_file_exists(self) -> None:
        """introduction.md exists in the dod skill directory."""
        assert INTRO_PATH.exists()

    def test_introduction_not_empty(self) -> None:
        """introduction.md is not empty."""
        assert len(INTRO_PATH.read_text(encoding="utf-8").strip()) > 0


# ---------------------------------------------------------------------------
# 2. Template structure
# ---------------------------------------------------------------------------


class TestTemplate:
    """Verify the dod-check template exists with expected steps."""

    def test_dod_check_template_exists(self, skill_text: str) -> None:
        """The dod-check template exists."""
        check = _extract_template(skill_text, "dod-check")
        assert check, "dod-check template not found"

    def test_has_locate_prd_step(self, skill_text: str) -> None:
        """Template has a step to locate the Dev Spec."""
        check = _extract_template(skill_text, "dod-check")
        assert "Locate the Dev Spec" in check or "*-devspec.md" in check

    def test_has_read_prd_step(self, skill_text: str) -> None:
        """Template has a step to read and parse the Dev Spec."""
        check = _extract_template(skill_text, "dod-check")
        assert "Deliverables Manifest" in check
        assert "Section 5.A" in check

    def test_has_verify_step(self, skill_text: str) -> None:
        """Template has a step to verify each deliverable."""
        check = _extract_template(skill_text, "dod-check")
        assert "Verify Each Deliverable" in check or "verify each" in check.lower()

    def test_has_global_dod_step(self, skill_text: str) -> None:
        """Template has a step to check Global DoD (Section 7)."""
        check = _extract_template(skill_text, "dod-check")
        assert "Section 7" in check
        assert "Global DoD" in check or "Definition of Done" in check

    def test_has_vrtm_step(self, skill_text: str) -> None:
        """Template has a step to check VRTM completeness."""
        check = _extract_template(skill_text, "dod-check")
        assert "VRTM" in check

    def test_has_report_step(self, skill_text: str) -> None:
        """Template has a step to present the verification report."""
        check = _extract_template(skill_text, "dod-check")
        assert "Verification Report" in check

    def test_has_approval_step(self, skill_text: str) -> None:
        """Template has a step for the approval flow."""
        check = _extract_template(skill_text, "dod-check")
        assert "Approval Flow" in check or "approval" in check.lower()


# ---------------------------------------------------------------------------
# 3. Verification categories
# ---------------------------------------------------------------------------


class TestVerificationCategories:
    """Verify all verification categories are documented."""

    def test_docs_category(self, skill_text: str) -> None:
        """Docs category checks file existence and non-empty."""
        check = _extract_template(skill_text, "dod-check")
        assert "Category: Docs" in check
        assert "non-empty" in check

    def test_code_binary_category(self, skill_text: str) -> None:
        """Code binary/package category checks file and build."""
        check = _extract_template(skill_text, "dod-check")
        assert "Code (binary" in check or "Code (CI" in check
        assert "build" in check.lower()

    def test_code_cicd_category(self, skill_text: str) -> None:
        """Code CI/CD category checks pipeline config and last run."""
        check = _extract_template(skill_text, "dod-check")
        assert "CI/CD" in check
        assert "pipeline" in check.lower() or "workflow" in check.lower()

    def test_code_build_system_category(self, skill_text: str) -> None:
        """Code build system category checks Makefile and tests."""
        check = _extract_template(skill_text, "dod-check")
        assert "build system" in check.lower()
        assert "Makefile" in check or "task runner" in check

    def test_test_results_category(self, skill_text: str) -> None:
        """Test results category checks JUnit XML or equivalent."""
        check = _extract_template(skill_text, "dod-check")
        assert "Test (results)" in check or "test results" in check.lower()

    def test_test_coverage_category(self, skill_text: str) -> None:
        """Test coverage category checks coverage report."""
        check = _extract_template(skill_text, "dod-check")
        assert "coverage" in check.lower()

    def test_test_manual_category(self, skill_text: str) -> None:
        """Manual procedures category checks execution evidence."""
        check = _extract_template(skill_text, "dod-check")
        assert "manual" in check.lower()
        assert "execution" in check.lower() or "executed" in check.lower()

    def test_trace_vrtm_category(self, skill_text: str) -> None:
        """Trace VRTM category checks for Pending rows."""
        check = _extract_template(skill_text, "dod-check")
        assert "Trace (VRTM)" in check or "VRTM" in check
        assert "Pending" in check


# ---------------------------------------------------------------------------
# 4. N/A handling
# ---------------------------------------------------------------------------


class TestNAHandling:
    """Verify N/A opt-out handling."""

    def test_na_rows_documented(self, skill_text: str) -> None:
        """N/A row handling is documented."""
        check = _extract_template(skill_text, "dod-check")
        assert "N/A" in check

    def test_na_not_failure(self, skill_text: str) -> None:
        """N/A rows do not count as failures."""
        check = _extract_template(skill_text, "dod-check")
        # Strip markdown bold markers for matching
        plain = check.replace("**", "").lower()
        assert "not count as failure" in plain or "do not fail" in plain or "not a failure" in plain

    def test_na_rationale_required(self, skill_text: str) -> None:
        """N/A rows must have a rationale."""
        check = _extract_template(skill_text, "dod-check")
        assert "rationale" in check.lower()


# ---------------------------------------------------------------------------
# 5. Report format
# ---------------------------------------------------------------------------


class TestReportFormat:
    """Verify the report format."""

    def test_report_has_project_name(self, skill_text: str) -> None:
        """Report includes project name."""
        check = _extract_template(skill_text, "dod-check")
        assert "project-name" in check.lower() or "Project:" in check

    def test_report_has_prd_path(self, skill_text: str) -> None:
        """Report includes Dev Spec file path."""
        check = _extract_template(skill_text, "dod-check")
        assert "Dev Spec:" in check or "docs/" in check

    def test_report_has_status_indicators(self, skill_text: str) -> None:
        """Report uses V/X/O status indicators."""
        check = _extract_template(skill_text, "dod-check")
        assert "V" in check  # checkmark
        assert "X" in check  # failing
        assert "O" in check  # N/A


# ---------------------------------------------------------------------------
# 6. Approval flow
# ---------------------------------------------------------------------------


class TestApprovalFlow:
    """Verify the approval flow."""

    def test_all_pass_flow(self, skill_text: str) -> None:
        """All-pass flow suggests closing the project."""
        check = _extract_template(skill_text, "dod-check")
        assert "all" in check.lower() and "pass" in check.lower()

    def test_failure_flow(self, skill_text: str) -> None:
        """Failure flow offers yes/no/fix options."""
        check = _extract_template(skill_text, "dod-check")
        assert "fix" in check.lower()

    def test_campaign_integration(self, skill_text: str) -> None:
        """Approval integrates with campaign-status."""
        check = _extract_template(skill_text, "dod-check")
        assert "campaign-status" in check
        assert "stage-review dod" in check

    def test_remediation_on_fix(self, skill_text: str) -> None:
        """Fix flow provides specific remediation suggestions."""
        check = _extract_template(skill_text, "dod-check")
        assert "remediation" in check.lower() or "Create" in check or "Fix build" in check

    def test_rejection_flow(self, skill_text: str) -> None:
        """Rejection flow defers verification."""
        check = _extract_template(skill_text, "dod-check")
        assert "reject" in check.lower() or "deferred" in check.lower()


# ---------------------------------------------------------------------------
# 7. Important rules
# ---------------------------------------------------------------------------


class TestImportantRules:
    """Verify Important Rules section."""

    def test_mechanical_verification_rule(self, skill_text: str) -> None:
        """Rule: mechanical verification only."""
        assert "Mechanical verification" in skill_text or "mechanical" in skill_text.lower()

    def test_na_not_failure_rule(self, skill_text: str) -> None:
        """Rule: N/A is not a failure."""
        assert "N/A is not a failure" in skill_text

    def test_vrtm_mandatory_rule(self, skill_text: str) -> None:
        """Rule: VRTM completeness is mandatory."""
        assert "VRTM completeness" in skill_text

    def test_human_approval_rule(self, skill_text: str) -> None:
        """Rule: human approval is required."""
        assert "Human approval" in skill_text or "human approval" in skill_text

    def test_manifest_source_of_truth_rule(self, skill_text: str) -> None:
        """Rule: Deliverables Manifest is the source of truth."""
        assert "source of truth" in skill_text.lower()


# ---------------------------------------------------------------------------
# 8. docs/skill-reference.md
# ---------------------------------------------------------------------------


class TestSkillReference:
    """Verify docs/skill-reference.md has /dod section."""

    def test_dod_section_exists(self, skill_ref_text: str) -> None:
        """The /dod section exists."""
        assert "### `/dod`" in skill_ref_text or "### `/dod" in skill_ref_text

    def test_dod_section_mentions_deliverables(self, skill_ref_text: str) -> None:
        """The /dod section mentions Deliverables Manifest."""
        dod_start = skill_ref_text.find("/dod")
        assert dod_start != -1
        after = skill_ref_text[dod_start:dod_start + 2000]
        assert "Deliverables Manifest" in after or "deliverable" in after.lower()


# ---------------------------------------------------------------------------
# 9. README.md
# ---------------------------------------------------------------------------


class TestReadme:
    """Verify README.md has dod row in skills table."""

    def test_dod_row_exists(self, readme_text: str) -> None:
        """The dod row exists in the skills table."""
        assert "| dod |" in readme_text

    def test_dod_row_has_command(self, readme_text: str) -> None:
        """The dod row has the /dod command."""
        for line in readme_text.split("\n"):
            if "| dod |" in line:
                assert "`/dod`" in line
                break
