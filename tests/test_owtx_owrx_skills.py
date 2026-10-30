"""/owtx and /owrx send and read on the default backend; /disc is deprecated, not changed (#1348).

- /owtx documents the `> <route>` rule: the last pair only, after the closing quote, known
  routes only; and examples for a channel, a DM, a route and the check-in.
- Neither skill passes `backend` when no route is given, and both carry the no-crewchat
  Discord fallback, said out loud.
- /disc carries its deprecation line verbatim, and every intent still goes to Discord.
- `./install` deploys every `skills/*/` directory, so both new skills ship with no wiring.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SKILLS = _REPO / "skills"
_DEPRECATION = (
    "/disc is deprecated: use /owtx and /owrx "
    '(OaW Mattermost by default; add "> discord" for Discord).'
)


def _text(skill: str) -> str:
    return (_SKILLS / skill / "SKILL.md").read_text()


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_owtx_route_grammar() -> None:
    owtx = _text("owtx")
    flat = _flat(owtx)
    for must in (
        "`/owtx [#<channel> | @<user>] \"<message>\" [> <route>]`",
        "only the **last** token pair",
        "only when `<route>` is a known name",
        "the pair must come after the closing quote",
        "`discord` → `backend: \"discord\"`",
        "`<server_id>` → `backend: \"mattermost:<server_id>\"`",
        "chat_health()",
    ):
        assert must in flat, f"/owtx must say {must!r}"
    for example in (
        '`/owtx #general "msg"`',
        '`/owtx @bakerb "msg"`',
        '`/owtx #general "msg" > discord`',
        "| `/owtx` |",
    ):
        assert example in owtx, f"/owtx needs the example {example}"
    # `>` inside the quotes, and an unknown route, are message text.
    assert '`/owtx #general "a > b"` | `chat_send(to: "general", text: "a > b")`' in owtx
    assert 'text: "ship it > typo")`' in owtx
    # A DM is `@<user>` → chat_dm; there is no `dm` verb.
    assert '`chat_dm(to: "bakerb", text: "msg")`' in owtx
    assert "roll-call" in owtx and "online — team" in owtx, "the check-in uses /name's format"


@pytest.mark.parametrize("skill", ["owtx", "owrx"])
def test_owtx_owrx_no_backend_by_default(skill: str) -> None:
    text = _text(skill)
    flat = _flat(text)
    assert "No route → omit `backend`" in flat or "**No route → omit `backend`**" in flat
    assert "docs/chat-tools.md" in text, "point at the rules, don't restate them"
    # Every call example with a backend is a routed one.
    for line in text.splitlines():
        if line.startswith("| `/ow") and "backend:" in line:
            assert re.search(r"> (discord|oaw-dev)`", line), f"/{skill}: unrouted backend: {line}"
    # The no-crewchat fallback exists, and says where the message went.
    assert "## Without crewchat (no `chat_send` in your tool list)" in text
    assert "mcp__disc-server__disc_" in text
    assert "because this host has no crewchat" in flat
    assert "Never fail silently." in text


def test_owrx_reads_and_lists() -> None:
    owrx = _text("owrx")
    assert '`chat_read(channel: "general", limit: 20)`' in owrx
    assert '`chat_thread(post_id: "<post_id>")`' in owrx
    # Discord-only ops stay on disc_* on both kinds of host (docs/chat-tools.md), so list
    # must not switch to chat_list_channels now and switch again later.
    assert "`mcp__disc-server__disc_list(guild_id, type: \"text\")`, on both kinds of host" in owrx
    assert "chat_list_channels" not in owrx
    assert "there is no channel listing" in owrx


def test_disc_is_deprecated_but_unchanged() -> None:
    disc = _text("disc")
    assert f"`{_DEPRECATION}`" in disc, "the banner line, verbatim"
    assert "Begin every `/disc` response with this line, verbatim" in disc
    assert disc.split("---", 2)[1].count("DEPRECATED") >= 1, "the frontmatter says so too"
    # Every intent still maps to Discord.
    for intent in (
        "send / check-in / no args → `disc_send(",
        "read → `disc_read(",
        "list → `disc_list(",
        "create channel → `disc_create_channel(",
        "create thread → `disc_create_thread(",
        "doorbell → ",
    ):
        assert intent in disc, f"/disc lost the intent {intent!r}"
    assert 'always with `backend: "discord"`' in disc, "on crewchat, /disc stays on Discord"


def test_install_deploys_every_skill_dir() -> None:
    install = (_REPO / "install").read_text()
    assert 'for skill_dir in "$REPO_DIR"/skills/*/; do' in install
    for skill in ("owtx", "owrx"):
        assert (_SKILLS / skill / "SKILL.md").is_file()
