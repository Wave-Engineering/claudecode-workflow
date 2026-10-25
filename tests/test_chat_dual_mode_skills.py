"""Skills that send chat follow the one dual-mode rule (#1330, K-1).

The rule lives in skills/disc/SKILL.md ("Transport: `chat_*` or `disc_*`"). Every other
skill that sends points at it rather than restating it. A skill that names `chat_send`
without the rule would break on every host without the crewchat daemon, which is every
host until BJ approves the deployment. A skill that sends through disc-server with no
reference to the rule would silently skip crewchat where it exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SKILLS = Path(__file__).resolve().parent.parent / "skills"
_RULE_ANCHOR = "Transport: `chat_*` or `disc_*`"

# Skills that send or read chat as part of their procedure.
_SENDERS = ["name", "precheck"]


def _text(skill: str) -> str:
    return (_SKILLS / skill / "SKILL.md").read_text()


def test_disc_defines_the_rule() -> None:
    disc = _text("disc")
    assert f"## {_RULE_ANCHOR}" in disc
    for must in (
        "If `chat_send` is in your tool list",
        'backend: "discord"',
        "Otherwise",
        "mcp__disc-server__disc_",
        "needs_human",
        "chat_set_default",
        "@agents",
    ):
        assert must in disc, f"/disc's dual-mode rule must say {must!r}"


@pytest.mark.parametrize("skill", _SENDERS)
def test_senders_reference_the_rule(skill: str) -> None:
    text = _text(skill)
    assert "dual-mode rule in `/disc`" in text, f"/{skill} must point at /disc's rule"
    assert "chat_send" in text and "disc_send" in text, f"/{skill} must name both paths"


def test_no_skill_uses_chat_tools_without_the_rule() -> None:
    for skill_md in sorted(_SKILLS.glob("*/SKILL.md")):
        text = skill_md.read_text()
        if "chat_send" in text or "chat_read" in text:
            assert "dual-mode rule" in text or _RULE_ANCHOR in text, (
                f"{skill_md.parent.name} uses chat_* without the dual-mode rule"
            )


def test_ccwork_setup_declares_its_exception() -> None:
    # /ccwork setup discord verifies disc-server itself, so it calls disc-server directly.
    assert "one exception to the dual-mode rule in `/disc`" in _text("ccwork")
