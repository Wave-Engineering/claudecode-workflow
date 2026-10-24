"""Tests for squawk curation (#1320) across /issue, /reseed and /sqtk.

Squawks go stale when the work that resolved them lands, or when they become an
issue, and nothing prompts anyone to settle them. Agents settle them at the two
moments they know for certain:

1. /issue Step 4.5, after creation: record the triage items the new issue covers.
2. /reseed Step 1, before the seed: retire stale `sqtk mine` items, carry live ones.

These tests pin the contract each skill states: where the step sits, the
commands it names, retired-never-rejected, the reason after the arrow, and that
neither step can block or reach another agent's bj:needs item.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ISSUE = (REPO / "skills" / "issue" / "SKILL.md").read_text(encoding="utf-8")
RESEED = (REPO / "skills" / "reseed" / "SKILL.md").read_text(encoding="utf-8")
SQTK = (REPO / "skills" / "sqtk" / "SKILL.md").read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    """The body of the `## <heading>` section, up to the next `## ` heading."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no '## {heading}' section"
    return m.group(1)


# --- /issue -------------------------------------------------------------------


def test_issue_settle_step_sits_between_create_and_report():
    heads = re.findall(r"^## (Step [0-9.]+:[^\n]*)", ISSUE, re.M)
    names = [h.split(":")[0] for h in heads]
    assert "Step 4.5" in names, heads
    assert names.index("Step 4") < names.index("Step 4.5") < names.index("Step 5")


def test_issue_settle_step_names_its_commands():
    s = section(ISSUE, "Step 4.5: Settle what this issue covers")
    assert "sqtk walk triage" in s
    assert "--state recorded" in s
    assert "→ <ref>" in s
    assert "plainly covers" in s


def test_issue_settle_step_qualifies_a_cross_repo_answer():
    s = section(ISSUE, "Step 4.5: Settle what this issue covers")
    assert "sqtk walk <target-repo>:triage" in s
    assert "without its owner" in s
    assert "`<owner>/<repo>#<N>`" in s
    assert "only on the issue's own repo's list" in s


def test_issue_batch_returns_what_it_recorded():
    assert "the triage items Step 4.5 recorded" in ISSUE
    assert "{number, url, recorded}" in ISSUE
    assert "| Recorded |" in ISSUE


def test_issue_settle_step_never_blocks():
    s = section(ISSUE, "Step 4.5: Settle what this issue covers")
    assert "never blocks the issue" in s
    assert "SQUAWK_URL" in s


# --- /reseed ------------------------------------------------------------------


def test_reseed_step1_opens_with_curation():
    s = section(RESEED, "Step 1 — Author the seed")
    first = s.strip().split("\n\n")[0]
    assert "curate your squawks" in first.lower()
    assert s.index("sqtk mine") < s.index("Then write the seed")


def test_reseed_curation_retires_with_a_reason_and_carries_the_rest():
    s = section(RESEED, "Step 1 — Author the seed")
    assert "--state retired" in s
    assert "→ OBE:" in s
    assert "<list>#<seq>" in s
    assert "never rejected" in s


def test_reseed_curation_leaves_other_agents_needs_alone():
    s = section(RESEED, "Step 1 — Author the seed")
    assert "never touch another" in s
    assert "bj:needs" in s


# --- /sqtk --------------------------------------------------------------------


def test_sqtk_documents_the_reserved_names():
    s = section(SQTK, "Which list")
    assert "`triage`" in s and "`<repo>:triage`" in s
    assert "`needs`" in s and "`bj:needs`" in s
    assert "rmlist" in s  # the literal-name guard


def test_sqtk_commands_use_the_reserved_names():
    s = section(SQTK, "Commands")
    assert "sqtk add  needs" in s
    assert "sqtk walk triage" in s


def test_sqtk_curation_section_states_the_three_rules():
    s = section(SQTK, "Curation: settle what went stale")
    assert "/issue" in s and "/reseed" in s
    assert "retired" in s and "never rejected" in s
    assert "after the `→`" in s
    assert "only your own" in s
