"""Tests for BJ's comms rules (#1367): triage squawks #35, #36 and #52.

1. #35: after a compaction or a `/reseed revive`, the agent re-reads CLAUDE.md and
   carries on. It sends no rules confirmation. Session start is unchanged.
2. #36: a reminder of an unanswered question goes to #call-4-bj in the same turn,
   with `⏰⏰⏰⏰` as the first line when the agent is blocked.
3. #52: CLAUDE.md and the settings template describe the Stop hook as it is since
   #818 (the godspeed mandate model), not as a wording detector.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def read(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


CLAUDE = read("CLAUDE.md")
ENGAGE = read("skills/engage/SKILL.md")
RESEED = read("skills/reseed/SKILL.md")
SQTK = read("skills/sqtk/SKILL.md")


def section(text: str, heading: str) -> str:
    """The body of the `## <heading>` section, up to the next `## ` heading."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no '## {heading}' section"
    return m.group(1)


POST_COMPACTION = "MANDATORY: Post-Compaction Rules Confirmation"

# --- #35: no rules confirmation after a compaction or revive -------------------


def test_post_compaction_heading_kept():
    # /ccfold matches sections by heading. A renamed heading would be "Local only"
    # in every consumer, and the old instruction would survive beside the new one.
    assert re.search(rf"^## {re.escape(POST_COMPACTION)}$", CLAUDE, re.M)


def test_post_compaction_keeps_reread():
    s = section(CLAUDE, POST_COMPACTION)
    assert "re-read this file in full" in s
    assert "/reseed revive" in s


def test_post_compaction_drops_confirmation():
    s = section(CLAUDE, POST_COMPACTION)
    assert "confirm rules of engagement with the user" not in s
    assert "Do not send the user a rules confirmation" in s


def test_engage_has_reload_mode():
    s = section(ENGAGE, "`/engage reload` — after a compaction or a revive")
    assert "step 1" in s and "step 3" in s
    assert "Do not run step 2" in s and "step 4" in s
    # Plain /engage keeps its session-start steps.
    steps = section(ENGAGE, "Steps")
    assert "**Confirm Rules of Engagement**" in steps
    assert "**Present Ready State**" in steps


def test_engage_drops_protocol_line():
    assert "required by the post-compaction protocol" not in ENGAGE


def test_reseed_revive_uses_engage_reload():
    s = section(RESEED, "`/reseed revive` — continue from the seed")
    assert "`/engage reload`" in s
    assert "Run `/engage`," not in s


def test_post_compact_hook_output(tmp_path):
    env = {**os.environ, "HOME": str(tmp_path)}
    (tmp_path / ".claude" / "logs").mkdir(parents=True)
    r = subprocess.run(
        ["bash", str(REPO / "scripts/hooks/workflow/post-compact-reread.sh")],
        input="{}",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert r.returncode == 0, r.stderr
    assert "Re-read CLAUDE.md" in r.stdout
    assert "Confirm rules" not in r.stdout


def test_docs_drop_post_compaction_confirm():
    re_engage = re.search(
        r"^### Post-Compaction Re-Engagement\n(.*?)(?=^#{2,3} )",
        read("docs/concepts.md"),
        re.M | re.S,
    )
    assert re_engage, "no Post-Compaction Re-Engagement section"
    assert "confirm the mandatory rules" not in re_engage.group(1)
    assert "no confirmation message is sent" in re_engage.group(1)
    assert "| Post-Compaction Rules |" not in read("docs/concepts.md")

    intro = read("skills/engage/introduction.md")
    assert "post-compaction (or session-start) ritual that reloads CLAUDE.md, confirms" not in intro
    assert "`/engage reload`" in intro

    assert "`/engage reload`" in read("docs/getting-started.md")


def test_no_after_compaction_row_maps_to_plain_engage():
    # The entry-point tables an agent checks must send a compacted session to the reload.
    row = re.compile(r"^\|[^|\n]*\bafter (a )?compaction\b[^\n]*`/engage`\s*\|\s*$", re.I | re.M)
    for rel in (
        "skills/onboard/SKILL.md",
        "docs/skill-reference.md",
        "skills/ccwork/tours/orientation.md",
        "skills/ccwork/tours/foundations.md",
    ):
        text = read(rel)
        assert not row.search(text), rel
    assert "| The same session, after a compaction | `/engage reload` |" in read(
        "skills/onboard/SKILL.md"
    )
    # A Skill | When | What table has the skill first, which the row regex can't see.
    assert "| `/engage` | Session start (`/engage reload` after compaction) |" in read(
        "skills/ccwork/tours/foundations.md"
    )
    onboard_intro = read("skills/onboard/introduction.md")
    assert "`/engage` alone is enough" not in onboard_intro
    assert "after a compaction, run `/engage reload`" in onboard_intro
    assert "or a revive: `/engage reload`" in read("docs/skill-reference.md")


def test_session_start_paths_name_the_reload():
    # A revive is a SessionStart{clear}, and a grunt's appended prompt survives compaction:
    # both must point a compacted session at the reload, not plain /engage.
    onboarding = read("CLAUDE.md").split("## Session Onboarding", 1)[1].split("\n## ", 1)[0]
    assert "`/engage reload` takes its place" in onboarding
    assert "FIRST run /engage (after a compaction, /engage reload)" in read("skills/grunt/SKILL.md")
    assert "`/engage reload` is the single entry point for resume" in read("docs/concepts.md")


def test_engage_important_scoped_to_plain_engage():
    s = section(ENGAGE, "Important")
    assert "Plain `/engage` only: do NOT start doing work" in s


# --- #36: reminders go to #call-4-bj ------------------------------------------


def test_sqtk_reminder_rule():
    s = section(SQTK, "The rules for `bj:needs`")
    m = re.search(r"^14\. (.*?)(?=^\d+\. |^\*\*|\Z)", s, re.M | re.S)
    assert m, "no rule 14"
    rule = m.group(1)
    for needle in ("#call-4-bj", "same turn", "⏰⏰⏰⏰", "first", "line"):
        assert needle in rule, needle
    assert ":alarm_clock:" in rule  # named only to say it is NOT used
    assert 'backend: "discord"' not in rule  # #1348: the default backend applies


def test_disc_points_to_reminder_rule():
    for rel in ("skills/owtx/SKILL.md", "skills/disc/SKILL.md"):
        s = section(read(rel), "Reminding BJ: #call-4-bj")
        assert "/sqtk" in s, rel
        assert "⏰⏰⏰⏰" in s, rel


# --- #52: the Stop hook is described as it is ---------------------------------


def test_default_to_action_describes_mandate_model():
    s = section(CLAUDE, "MANDATORY: Default to Action — never stop on a question you can answer")
    assert "godspeed" in s
    assert "precheck-asking-detector.sh" in s
    assert "blocks a turn that ends by asking permission" not in s
    assert "no hook reads your wording" not in s  # precheck-asking-detector is one


def test_stop_hook_comment_current():
    tmpl = json.loads(read("config/settings.template.json"))
    comments = [
        h.get("_comment", "")
        for group in tmpl["hooks"]["Stop"]
        for h in group["hooks"]
        if h.get("command", "").endswith("stop-action-bias-detector.sh")
    ]
    assert comments, "stop-action-bias-detector.sh not wired in Stop"
    for c in comments:
        assert "#818" in c
        assert "block a turn that ends by asking permission" not in c
