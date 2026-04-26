"""Tests for skills/issue/SKILL.md — wave-pattern-ready issue templates.

Issue #427 — Update /issue templates so every sub-issue type emits the H2
sections that /prepwaves and spec_validate_structure expect:

  Required H2 sections (canonical names used by /issue):
    ## Summary
    ## Implementation Steps   (alias accepted by parser: ## Changes)
    ## Test Procedures        (alias accepted by parser: ## Tests)
    ## Acceptance Criteria
    ## Dependencies
    ## Metadata

The parser (spec_validate_structure) treats ## Implementation Steps and
## Test Procedures as the canonical sub-issue heading aliases for the
required `changes` and `tests` keys (see docs/issue-body-grammar.md in
mcp-server-sdlc). This skill is the authoring side of that contract.

These tests guard the contract:

1. Frontmatter & usage block list `feature`, `story`, `chore`, `docs`, `bug`
   as supported types and reference the wave-pattern-ready guarantee.
2. Each of the five sub-issue templates emits the six required H2 headings.
3. The `epic` template is intentionally excluded — epics are parents, not
   sub-issues, and have a different shape.
4. The `introduction.md` documents the wave-pattern-ready output guarantee
   so first-time users see it.
5. Smoke check: a representative rendered issue body for each sub-issue
   type satisfies the same `spec_validate_structure` rules in-process
   (required canonical keys all present, dependencies optional).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "issue" / "SKILL.md"
INTRO_PATH = _ROOT / "skills" / "issue" / "introduction.md"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Canonical H2 headings emitted by the /issue sub-issue templates.
REQUIRED_H2_HEADINGS = (
    "## Summary",
    "## Implementation Steps",
    "## Test Procedures",
    "## Acceptance Criteria",
    "## Dependencies",
    "## Metadata",
)

# Sub-issue types that must be wave-pattern-ready.
SUB_ISSUE_TYPES = ("feature", "story", "chore", "docs", "bug")

# Section-name → set of H2 headings that satisfy the parser contract,
# mirroring spec_validate_structure / docs/issue-body-grammar.md.
PARSER_REQUIRED = {
    "changes": ("## Changes", "## Implementation Steps"),
    "tests": ("## Tests", "## Test Procedures"),
    "acceptance_criteria": ("## Acceptance Criteria",),
}

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the /issue SKILL.md file."""
    return SKILL_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def intro_text() -> str:
    """Read the /issue introduction.md file."""
    return INTRO_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_template_block(text: str, header: str) -> str:
    """Extract the fenced ```markdown block immediately following an H3
    heading like `### Feature Template`. Returns the block contents
    (without the fence lines) or empty string if not found.

    We intentionally do not assume <!-- BEGIN/END --> markers because the
    /issue skill keeps each template inline as a fenced block under its
    H3 heading, which is the human-readable shape we want to preserve.
    """
    # Find the H3 heading.
    pattern = re.compile(
        rf"^###\s+{re.escape(header)}\s*$", re.MULTILINE
    )
    m = pattern.search(text)
    if not m:
        return ""
    # From the heading position, find the next ```markdown fence.
    rest = text[m.end():]
    fence_open = re.search(r"^```markdown\s*$", rest, re.MULTILINE)
    if not fence_open:
        return ""
    body_start = fence_open.end()
    fence_close = re.search(r"^```\s*$", rest[body_start:], re.MULTILINE)
    if not fence_close:
        return ""
    return rest[body_start:body_start + fence_close.start()]


def _h2_headings(body: str) -> list[str]:
    """Return all H2 headings in `body`, in order."""
    return [
        line.strip()
        for line in body.splitlines()
        if line.startswith("## ") and not line.startswith("### ")
    ]


# Mirror of spec_parser.parseSections for the in-process smoke check.
# Only `## H2` headings create sections. Heading titles are normalized:
# lowercase, punctuation stripped, whitespace/hyphens collapsed to `_`.
def _normalize_key(title: str) -> str:
    # Strip leading "## " then normalize.
    t = title[3:].strip() if title.startswith("## ") else title.strip()
    # Lowercase, replace hyphens/spaces with `_`, drop other punctuation.
    t = t.lower()
    t = re.sub(r"[^\w\s-]", "", t)
    t = re.sub(r"[\s\-]+", "_", t).strip("_")
    return t


def _parse_sections(body: str) -> dict[str, str]:
    """Mimic spec_parser.parseSections. Returns canonical_key -> content."""
    lines = body.splitlines()
    sections: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []
    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            # Flush previous section.
            if current_key is not None:
                sections[current_key] = "\n".join(buf).strip()
            current_key = _normalize_key(line)
            buf = []
        else:
            if current_key is not None:
                buf.append(line)
    if current_key is not None:
        sections[current_key] = "\n".join(buf).strip()
    return sections


def _spec_validate_structure(body: str) -> dict:
    """In-process replica of mcp__sdlc-server__spec_validate_structure
    for testing without a network round-trip. Returns a dict with
    `valid: bool`, `missing: list[str]`, and `present: list[str]`.

    Required canonical keys: `changes`, `tests`, `acceptance_criteria`.
    Each is satisfied by any of its accepted H2 alias headings.
    """
    sections = _parse_sections(body)
    present: list[str] = []
    missing: list[str] = []
    for canonical, aliases in PARSER_REQUIRED.items():
        # The parser normalizes alias headings the same way; check via
        # normalized keys.
        alias_keys = {_normalize_key(a) for a in aliases}
        satisfied = any(
            sections.get(k, "").strip() != "" for k in alias_keys
        )
        if satisfied:
            present.append(canonical)
        else:
            missing.append(canonical)
    return {"valid": not missing, "present": present, "missing": missing}


# Sample minimal-but-realistic fillings of each template, used for the
# in-process spec_validate_structure smoke check. These mirror what an
# implementing agent would produce after the /issue skill draft is filled
# in — the goal is to verify the *shape*, not the prose.
SAMPLE_BODIES: dict[str, str] = {
    "feature": """## Summary

Add dark mode support to the settings page.

## Implementation Steps

1. Add `theme` field to `UserSettings` in `src/models/user.py`.
2. Wire the toggle in `src/ui/settings_page.tsx`.
3. Persist via `PUT /api/user/settings`.

## Test Procedures

*Unit tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_theme_toggle_persists` | round-trip the new field | `tests/test_user_settings.py` |

*Integration coverage:* IT-12

## Acceptance Criteria

- [ ] `theme` field round-trips through the API
- [ ] Toggle visible in the settings page
- [ ] Selection persists across reloads

## Dependencies

- None

## Metadata

**Wave:** 2
**Parent Epic:** #100
**Wave Master:** #110
""",
    "bug": """## Summary

Login fails on Safari 17 with `TypeError: undefined is not an object`.

**Steps to reproduce:**

1. Open `/login` in Safari 17.
2. Enter valid credentials, click Sign In.
3. Observe console error.

**Expected:** Successful login.
**Actual:** Console error and the form does not submit.

## Implementation Steps

1. Reproduce locally with Safari Technology Preview.
2. Add a guard in `src/ui/login.tsx` for the missing global.
3. Patch the polyfill in `src/lib/compat.ts`.

## Test Procedures

*Regression test:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_safari_login_no_typeerror` | reproduces and proves fix | `tests/test_login.py` |

*Manual verification:* sign in from Safari 17 on macOS 14.

## Acceptance Criteria

- [ ] Regression test added and passing
- [ ] Login works on Safari 17

## Dependencies

- None

## Metadata

**Severity:** severity::major
**Wave:** N/A
**Artifacts:** browser console screenshot
**Workaround:** use Chrome
""",
    "chore": """## Summary

Bump `requests` from 2.31.0 to 2.32.3 to pick up the urllib3 security fix.

## Implementation Steps

1. Update `pyproject.toml` and lockfile.
2. Run the test suite locally.
3. Verify no API surface change in callers.

## Test Procedures

*Verification:* `pytest tests/test_http_client.py`.

## Acceptance Criteria

- [ ] `requests` pinned to 2.32.3
- [ ] All existing tests pass

## Dependencies

- None

## Metadata

**Wave:** N/A
**Parent Epic:** N/A
""",
    "docs": """## Summary

Document the wave-pattern-ready output guarantee for the /issue skill.

**Target audience:** Claude Code agents and human contributors.
**What's missing:** the guarantee is implicit in the templates but never stated.
**Source material:** issue #427.

## Implementation Steps

1. Update `skills/issue/SKILL.md` with a guarantee section.
2. Mention it in `skills/issue/introduction.md`.
3. Cross-link to `docs/issue-body-grammar.md` in mcp-server-sdlc.

## Test Procedures

*Verification:*

- [ ] Markdown lint passes
- [ ] Cross-references resolve

## Acceptance Criteria

- [ ] Guarantee documented in SKILL.md
- [ ] Mentioned in introduction.md

## Dependencies

- None

## Metadata

**Wave:** N/A
**Parent Epic:** N/A
""",
    "story": """## Summary

User can reset their password from the profile page.

## Implementation Steps

1. Add `Reset password` button to `src/ui/profile.tsx`.
2. Wire to `POST /api/account/password-reset`.
3. Email template lives in `templates/email/password_reset.html`.

## Test Procedures

*Unit tests:*

| Test Name | Purpose | File Location |
|-----------|---------|---------------|
| `test_password_reset_email_sent` | verifies email dispatch | `tests/test_account.py` |

*Integration coverage:* IT-22

## Acceptance Criteria

- [ ] Reset link works end-to-end
- [ ] Old password invalidated after reset

## Dependencies

- None

## Metadata

**Wave:** 1
**Parent Epic:** #200
**Wave Master:** #210
""",
}


# ---------------------------------------------------------------------------
# 1. Frontmatter
# ---------------------------------------------------------------------------


class TestFrontmatter:
    """Frontmatter advertises wave-pattern-ready output and lists all types."""

    def test_frontmatter_lists_all_sub_issue_types(self, skill_text: str) -> None:
        """The frontmatter description references every sub-issue type."""
        end = skill_text.index("---", 4)
        frontmatter = skill_text[:end + 3]
        for t in SUB_ISSUE_TYPES:
            assert t in frontmatter.lower(), (
                f"frontmatter description omits sub-issue type {t!r}"
            )

    def test_frontmatter_mentions_wave_pattern_ready(self, skill_text: str) -> None:
        """The frontmatter advertises the wave-pattern-ready guarantee."""
        end = skill_text.index("---", 4)
        frontmatter = skill_text[:end + 3]
        lower = frontmatter.lower()
        # Either the literal phrase or the parser tool name should appear.
        assert (
            "wave-pattern" in lower
            or "spec_validate_structure" in lower
            or "/prepwaves" in lower
        ), "frontmatter must advertise wave-pattern-ready guarantee"

    def test_usage_lists_story(self, skill_text: str) -> None:
        """Usage block exposes the new `story` alias."""
        end = skill_text.index("---", 4)
        frontmatter = skill_text[:end + 3]
        # The `usage:` literal block is part of the frontmatter.
        assert "/issue story" in frontmatter, (
            "usage block must expose `/issue story`"
        )


# ---------------------------------------------------------------------------
# 2. Wave-pattern-ready output guarantee — documented in body
# ---------------------------------------------------------------------------


class TestGuaranteeDocumented:
    """The skill body and introduction document the guarantee."""

    def test_skill_body_lists_required_h2_sections(self, skill_text: str) -> None:
        """SKILL.md body lists each of the six required H2 sections so the
        contract is visible to a reader without going to the parser docs."""
        for h in REQUIRED_H2_HEADINGS:
            assert h in skill_text, (
                f"SKILL.md body missing reference to required heading {h!r}"
            )

    def test_skill_body_references_parser(self, skill_text: str) -> None:
        """SKILL.md body links the guarantee to the parser tool name."""
        lower = skill_text.lower()
        assert (
            "spec_validate_structure" in lower or "/prepwaves" in lower
        ), "SKILL.md must name the downstream parser/tool"

    def test_introduction_documents_guarantee(self, intro_text: str) -> None:
        """introduction.md mentions the wave-pattern-ready guarantee."""
        lower = intro_text.lower()
        assert (
            "wave-pattern" in lower
            or "/prepwaves" in lower
            or "spec_validate_structure" in lower
        )

    def test_introduction_lists_all_sub_issue_types(self, intro_text: str) -> None:
        """introduction.md lists every sub-issue type."""
        for t in SUB_ISSUE_TYPES:
            assert t in intro_text.lower(), (
                f"introduction.md omits sub-issue type {t!r}"
            )


# ---------------------------------------------------------------------------
# 3. Each sub-issue template emits the six required H2 headings
# ---------------------------------------------------------------------------


# Mapping from issue type → H3 heading used in SKILL.md for that template.
TEMPLATE_HEADERS = {
    "feature": "Feature Template (alias: Story)",
    "bug": "Bug Template",
    "chore": "Chore Template",
    "docs": "Docs Template",
}


@pytest.mark.parametrize("issue_type", ["feature", "bug", "chore", "docs"])
class TestSubIssueTemplateHeadings:
    """Every fenced sub-issue template in SKILL.md emits the six required
    H2 headings, in the canonical names this skill commits to."""

    def test_template_block_present(
        self, skill_text: str, issue_type: str
    ) -> None:
        """The fenced markdown block exists under its H3 heading."""
        body = _extract_template_block(skill_text, TEMPLATE_HEADERS[issue_type])
        assert body, (
            f"could not locate fenced ```markdown block under H3 "
            f"`### {TEMPLATE_HEADERS[issue_type]}`"
        )

    def test_template_emits_all_required_h2s(
        self, skill_text: str, issue_type: str
    ) -> None:
        """Every required H2 heading appears in the template body."""
        body = _extract_template_block(skill_text, TEMPLATE_HEADERS[issue_type])
        headings = _h2_headings(body)
        for required in REQUIRED_H2_HEADINGS:
            assert required in headings, (
                f"{issue_type} template missing required H2 heading "
                f"{required!r}; saw {headings!r}"
            )

    def test_template_required_h2s_in_canonical_order(
        self, skill_text: str, issue_type: str
    ) -> None:
        """The required H2 headings appear in their canonical order so
        the rendered issue reads top-to-bottom the way agents expect."""
        body = _extract_template_block(skill_text, TEMPLATE_HEADERS[issue_type])
        headings = _h2_headings(body)
        # Filter to just the required ones, preserving order of appearance.
        required_set = set(REQUIRED_H2_HEADINGS)
        seen_in_order = [h for h in headings if h in required_set]
        assert seen_in_order == list(REQUIRED_H2_HEADINGS), (
            f"{issue_type} template H2 ordering is "
            f"{seen_in_order!r}, expected {list(REQUIRED_H2_HEADINGS)!r}"
        )


class TestStoryAliasDocumented:
    """Story is an explicit alias of feature, documented in SKILL.md."""

    def test_story_template_section_present(self, skill_text: str) -> None:
        """SKILL.md has an H3 specifically calling out the Story alias."""
        assert "### Story Template" in skill_text

    def test_story_aliases_feature(self, skill_text: str) -> None:
        """The Story Template section explains it is identical to Feature."""
        idx = skill_text.find("### Story Template")
        assert idx != -1
        # Take the section up to the next H3.
        rest = skill_text[idx:]
        next_h3 = rest.find("\n### ", 1)
        section = rest if next_h3 == -1 else rest[:next_h3]
        lower = section.lower()
        assert "alias" in lower
        assert "feature" in lower


# ---------------------------------------------------------------------------
# 4. Epic template is intentionally excluded
# ---------------------------------------------------------------------------


class TestEpicExcluded:
    """The epic template is intentionally NOT held to the sub-issue grammar.

    Epics are parents (decompose into sub-issues), not sub-issues themselves.
    This guard documents and preserves that distinction so a future edit
    doesn't accidentally break the epic shape while "fixing" issue grammar.
    """

    def test_epic_template_present(self, skill_text: str) -> None:
        """The Epic Template still exists."""
        body = _extract_template_block(skill_text, "Epic Template")
        assert body, "Epic Template block is missing entirely"

    def test_epic_template_keeps_epic_specific_headings(
        self, skill_text: str
    ) -> None:
        """The epic template retains its epic-specific structure
        (Goal / Scope / Definition of Done / Sub-Issues / Wave Map)."""
        body = _extract_template_block(skill_text, "Epic Template")
        headings = _h2_headings(body)
        for required in ("## Goal", "## Scope", "## Definition of Done", "## Sub-Issues"):
            assert required in headings, (
                f"Epic template missing epic-specific heading {required!r}"
            )


# ---------------------------------------------------------------------------
# 5. Smoke check: representative bodies pass spec_validate_structure rules
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("issue_type", list(SAMPLE_BODIES.keys()))
class TestRenderedBodiesValidate:
    """A filled-in body for each sub-issue type satisfies the
    spec_validate_structure contract (in-process replica)."""

    def test_rendered_body_validates(self, issue_type: str) -> None:
        body = SAMPLE_BODIES[issue_type]
        result = _spec_validate_structure(body)
        assert result["valid"], (
            f"{issue_type} sample body failed in-process "
            f"spec_validate_structure: missing={result['missing']!r}"
        )

    def test_rendered_body_has_dependencies_section(
        self, issue_type: str
    ) -> None:
        """Dependencies is optional for the parser but required by this
        skill's templates so wave assembly can mechanically harvest deps."""
        body = SAMPLE_BODIES[issue_type]
        sections = _parse_sections(body)
        assert "dependencies" in sections, (
            f"{issue_type} sample body missing ## Dependencies"
        )

    def test_rendered_body_has_metadata_section(
        self, issue_type: str
    ) -> None:
        """Metadata is required by this skill's templates so wave/epic
        backrefs are always present."""
        body = SAMPLE_BODIES[issue_type]
        sections = _parse_sections(body)
        assert "metadata" in sections, (
            f"{issue_type} sample body missing ## Metadata"
        )


# ---------------------------------------------------------------------------
# 6. Internal parser-replica self-check
# ---------------------------------------------------------------------------


class TestParserReplicaSanity:
    """The in-process spec_validate_structure replica must reject the
    obvious failure cases — otherwise the smoke checks above are vacuous."""

    def test_empty_body_invalid(self) -> None:
        result = _spec_validate_structure("")
        assert not result["valid"]
        assert set(result["missing"]) == {
            "changes",
            "tests",
            "acceptance_criteria",
        }

    def test_missing_acceptance_criteria_invalid(self) -> None:
        body = """## Summary

Body.

## Implementation Steps

1. step

## Test Procedures

*Unit tests:* none
"""
        result = _spec_validate_structure(body)
        assert not result["valid"]
        assert "acceptance_criteria" in result["missing"]

    def test_changes_alias_satisfies_changes_key(self) -> None:
        """The parser accepts `## Changes` as an alias for the `changes` key."""
        body = """## Summary

Body.

## Changes

- thing

## Tests

- thing

## Acceptance Criteria

- [ ] thing
"""
        result = _spec_validate_structure(body)
        assert result["valid"]
        assert set(result["present"]) == {
            "changes",
            "tests",
            "acceptance_criteria",
        }

    def test_empty_section_does_not_satisfy(self) -> None:
        """A heading with no non-whitespace content does not count."""
        body = """## Summary

Body.

## Implementation Steps


## Test Procedures

- thing

## Acceptance Criteria

- [ ] thing
"""
        result = _spec_validate_structure(body)
        assert not result["valid"]
        assert "changes" in result["missing"]
