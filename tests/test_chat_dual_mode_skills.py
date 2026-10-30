"""Skills that send chat follow the one dual-mode rule (#1330, K-1; moved by #1348).

The rule lives in docs/chat-tools.md ("Transport: `chat_*` or `disc_*`"). Every skill that
sends points at it rather than restating it. A skill that names `chat_send` without the rule
would break on every host without the crewchat daemon. A skill that sends through
disc-server with no reference to the rule would silently skip crewchat where it exists.

Since #1348 the kit's own notifications name channels and pass no `backend`, so they land on
the default (OaW Mattermost). Discord IDs survive only in the no-crewchat fallback lines, and
`backend: "discord"` only in /disc and the `> discord` routes of /owtx and /owrx.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SKILLS = _REPO / "skills"
_CHAT_TOOLS = _REPO / "docs" / "chat-tools.md"
_RULE_ANCHOR = "Transport: `chat_*` or `disc_*`"
_RULE_POINTER = "dual-mode rule in `docs/chat-tools.md`"

# Skills that send or read chat as part of their procedure.
_SENDERS = ["name", "precheck"]
# Skills that may name `backend: "discord"`: /disc always means Discord, and /owtx and /owrx
# define the `> discord` route.
_DISCORD_BY_DESIGN = {"disc", "owtx", "owrx"}
# A Discord snowflake. Example IDs in /ccwork's setup are 10 digits, below this.
_SNOWFLAKE = re.compile(r"\b\d{17,20}\b")


def _text(skill: str) -> str:
    return (_SKILLS / skill / "SKILL.md").read_text()


def test_chat_tools_defines_the_rule() -> None:
    doc = _CHAT_TOOLS.read_text()
    assert f"## {_RULE_ANCHOR}" in doc
    for must in (
        "If `chat_send` is in your tool list",
        "pass no `backend`",
        'backend: "discord"',
        "Otherwise",
        "mcp__disc-server__disc_",
        "say once that it went to Discord",
        "needs_human",
        "chat_set_default",
        "@agents",
        "crewchat-send",
    ):
        assert must in doc, f"docs/chat-tools.md's dual-mode rule must say {must!r}"


def test_disc_points_at_the_moved_rules() -> None:
    disc = _text("disc")
    assert f"## {_RULE_ANCHOR}" not in disc, "the rule moved to docs/chat-tools.md (#1348)"
    assert "docs/chat-tools.md" in disc
    assert _RULE_ANCHOR in disc, "name the section it moved to"


@pytest.mark.parametrize("skill", _SENDERS)
def test_senders_reference_the_rule(skill: str) -> None:
    text = _text(skill)
    assert _RULE_POINTER in text, f"/{skill} must point at the rule in docs/chat-tools.md"
    assert "chat_send" in text and "disc_send" in text, f"/{skill} must name both paths"


def test_no_skill_points_at_the_rule_in_disc() -> None:
    for skill_md in sorted(_SKILLS.glob("*/SKILL.md")):
        assert "dual-mode rule in `/disc`" not in skill_md.read_text(), (
            f"{skill_md.parent.name} still points at /disc for the rule (#1348)"
        )


# The doorbell's arm rule and exit table moved from /disc to docs/chat-tools.md with the
# dual-mode rule (#1348). These are the shapes the old pointers took in the docs.
_STALE_DOORBELL_POINTERS = (
    "dual-mode rule in `/disc`",
    '(`/disc`, "Doorbell")',
    "table in `/disc`",
    "(see `/disc`)",
)


def test_no_doc_points_at_the_doorbell_in_disc() -> None:
    docs = sorted((_REPO / "docs").rglob("*.md"))
    assert docs, "no docs found"
    for doc in docs:
        text = doc.read_text()
        for stale in _STALE_DOORBELL_POINTERS:
            assert stale not in text, (
                f"{doc.relative_to(_REPO)} still points at /disc for the doorbell: {stale!r} (#1348)"
            )


def test_no_skill_uses_chat_tools_without_the_rule() -> None:
    for skill_md in sorted(_SKILLS.glob("*/SKILL.md")):
        text = skill_md.read_text()
        if "chat_send" in text or "chat_read" in text:
            assert "dual-mode rule" in text or _RULE_ANCHOR in text, (
                f"{skill_md.parent.name} uses chat_* without the dual-mode rule"
            )


def test_kit_notifications_use_channel_names() -> None:
    for skill_md in sorted(_SKILLS.glob("*/SKILL.md")):
        skill = skill_md.parent.name
        for n, line in enumerate(skill_md.read_text().splitlines(), 1):
            where = f"skills/{skill}/SKILL.md:{n}"
            if skill not in _DISCORD_BY_DESIGN:
                assert 'backend: "discord"' not in line, (
                    f'{where} pins backend: "discord"; name the channel and pass no backend'
                )
            if skill != "disc" and _SNOWFLAKE.search(line):
                assert "disc_send" in line or "disc_read" in line, (
                    f"{where} names a Discord channel ID outside a no-crewchat fallback"
                )


def test_ccwork_setup_declares_its_exception() -> None:
    # /ccwork setup discord verifies disc-server itself, so it calls disc-server directly.
    assert "one exception to the dual-mode rule in `docs/chat-tools.md`" in _text("ccwork")
