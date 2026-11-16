"""#1460: every skill that tells an agent how to write an issue, epic, plan, PR or MR
carries the one-sentence AC/DoD rule and points at the long-form doc.

A new authoring skill that omits it fails here, so the rule cannot be dropped silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent

RULE = (
    "AC and DoD must be checkable before the item closes. "
    "No acceptance criterion or definition-of-done line, in an issue, epic, plan, PR or MR, "
    "may wait for something that happens after the item is closed: "
    "a merge, release, install, deploy or roll, time passing, a live observation, "
    "or someone's later sign-off."
)
POINTER = "docs/ac-checkable-before-close.md"

AUTHORING_SKILLS = [
    "issue",
    "ibm",
    "scpmr",
    "scpmmr",
    "mmr",
    "devspec",
    "prepwaves",
    "autochain",
    "sdlc",
    "sqtk",
]


def _flat(text: str) -> str:
    """Collapse whitespace and markdown bold so a re-wrapped line still matches."""
    return re.sub(r"\s+", " ", text.replace("**", "")).strip()


# /prepwaves is a pipeline skill under R-11 (tests/skills/test_prepwaves_structure.sh): the
# word "epic" may not appear in it, because its unit is a Plan. It carries the same sentence
# with the one word dropped from the list.
RULE_NO_EPIC = RULE.replace("an issue, epic, plan,", "an issue, plan,")
RULE_FOR = {"prepwaves": RULE_NO_EPIC}


@pytest.mark.parametrize("skill", AUTHORING_SKILLS)
def test_authoring_skills_carry_the_rule(skill: str) -> None:
    text = _flat((_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
    assert RULE_FOR.get(skill, RULE) in text, f"skills/{skill}/SKILL.md lacks the AC/DoD rule sentence"
    assert POINTER in text, f"skills/{skill}/SKILL.md does not point at {POINTER}"


def test_the_doc_exists_and_states_the_rule_in_terms_of_closing() -> None:
    doc = (_ROOT / POINTER).read_text(encoding="utf-8")
    assert "checkable before the item closes" in doc
    assert "closed" in doc and "after the item is closed" in doc


def test_no_skill_still_states_the_narrow_form_alone() -> None:
    """The ruling now reads 'cannot be checked until after the item is closed'.

    A skill may cite the 2026-10-24 merge ruling as history, but only beside the widening.
    """
    for skill in AUTHORING_SKILLS + ["precheck"]:
        text = _flat((_ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8"))
        for m in re.finditer(r"need a merge to assess", text):
            window = text[m.start() : m.start() + 400]
            assert "closed" in window or "2026-11-16" in window, (
                f"skills/{skill}/SKILL.md states the narrow merge-only ruling without the "
                f"2026-11-16 widening near: {window[:120]!r}"
            )
