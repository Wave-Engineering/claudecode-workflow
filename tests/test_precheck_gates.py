"""The four gates — commit, push, MR, merge — are described the same way everywhere (#1233, #1235).

Doc-drift guard in the style of test_body_never_inline.py. The skills and the CLAUDE.md
template are the instructions agents actually follow; when one of them still described
the old pre-commit gate, an agent following it would refuse to commit, or wait for an
approval that is no longer the gate (keymaker found exactly that drift on 2026-10-18).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE_SKILLS = ["precheck", "scp", "scpmr", "scpmmr", "mmr", "autochain"]
INSTRUCTIONS = [ROOT / "CLAUDE.md"] + [ROOT / "skills" / s / f for s in GATE_SKILLS for f in ("SKILL.md", "introduction.md")]
INSTRUCTIONS = [p for p in INSTRUCTIONS if p.exists()]

# The old gate, as it was worded. Mentioning it as history is fine; prescribing it is not.
OLD_GATE = [
    r"never commit without (running )?`?/precheck",
    r"pre-commit gate \(`/precheck`\)",
    r"mandatory verification before any commit",
    r"requires `/precheck` approval first",
    r"use it after `/precheck` has been approved",
]


def _text(p: Path) -> str:
    return p.read_text()


@pytest.mark.parametrize("path", INSTRUCTIONS, ids=lambda p: str(p.relative_to(ROOT)))
@pytest.mark.parametrize("pattern", OLD_GATE)
def test_no_instruction_prescribes_the_pre_commit_gate(path, pattern):
    assert not re.search(pattern, _text(path), re.IGNORECASE), f"{path.relative_to(ROOT)} still prescribes: {pattern}"


def _gate_table(text: str) -> list[str]:
    rows = re.findall(r"^\|\s*\**([a-zA-Z/ ()]+?)\**\s*\|", text, re.MULTILINE)
    return [r.strip().lower() for r in rows if r.strip().lower() not in ("gate",)]


@pytest.mark.parametrize("path", [ROOT / "CLAUDE.md", ROOT / "skills" / "precheck" / "SKILL.md"], ids=lambda p: p.name)
def test_the_gate_table_names_the_same_four_gates(path):
    text = _text(path)
    start = text.index("| Gate |")
    table = text[start : text.index("\n\n", start)]
    gates = _gate_table(table)
    assert gates[0] == "commit" and gates[1] == "push" and gates[3] == "merge", gates
    assert gates[2] in ("mr", "mr (this skill)"), gates


def test_claude_md_puts_approval_at_merge():
    text = _text(ROOT / "CLAUDE.md")
    section = text[text.index("## MANDATORY: MR Gate") : text.index("### Exception: Kahuna")]
    assert "merge call" in section
    assert "Commit and push your working branch freely" in section
    assert "docs/precheck-status.md" in section


def test_precheck_reviews_pushed_commits_and_posts_the_status():
    s = _text(ROOT / "skills" / "precheck" / "SKILL.md")
    assert '"$SCOPE" ready' in s, "precheck must refuse a dirty or unpushed tree"
    assert '"$STATUS" post' in s, "a pass must post the precheck status"
    assert "draft: true" in s, "precheck opens a draft when no PR/MR exists"
    assert "ci_wait_run" in s and "expected_sha" in s, "Job B reads CI for the pushed HEAD"
    assert "### `/precheck rearm`" in s and '"$STATUS" last-success' in s
    assert "BEHAVIOUR-CHANGE" in s, "rearm escalates on a behaviour change (K-11)"


def test_precheck_marks_ready_through_the_kit_not_glab():
    """glab rewrites the title on most `mr update` flags, and GitLab's draft state IS the
    title, so the kit's one path to ready is precheck-status.sh mark-ready (#1235)."""
    s = _text(ROOT / "skills" / "precheck" / "SKILL.md")
    step4 = s[s.index("### Step 4") : s.index("### Step 5")]
    assert '"$STATUS" mark-ready' in step4
    assert not re.search(r"`glab mr update[^`]*--ready`", step4)
    assert not re.search(r"`gh pr ready <PR_NUMBER>`", step4)


def test_exception_paths_invoke_mmr_not_scpmmr():
    s = _text(ROOT / "skills" / "precheck" / "SKILL.md")
    step5 = s[s.index("### Step 5") : s.index("### `/precheck rearm`")]
    assert "invoke `/mmr` immediately" in step5
    assert "invoke `/scpmmr`" not in step5, "precheck runs inside /scpmr; invoking /scpmmr would recurse"
    claude = _text(ROOT / "CLAUDE.md")
    assert claude.count("invokes `/mmr`") >= 2  # kahuna + autochain


def test_workflow_flights_are_exempt():
    # #1209: Workflow flights never run /precheck; the kahuna exception is for a PR/MR opened into kahuna/* by hand.
    claude = _text(ROOT / "CLAUDE.md")
    mr_gate = claude[claude.index("## MANDATORY: MR Gate") : claude.index("## MANDATORY: Story Completion")]
    assert "Workflow flight workers are exempt" in mr_gate
    s = _text(ROOT / "skills" / "precheck" / "SKILL.md")
    sandbox = s[s.index("## Sandbox Auto-Approval") : s.index("## Rules")]
    assert "Workflow flights do not run `/precheck`" in sandbox
    # No gate instruction may still describe a flight that runs precheck, lands itself, or auto-merges.
    stale = re.compile(
        r"The Flight Agent is operating inside|Flight Agents? (inside|working inside|land into)|"
        r"sandbox flight|Flight Agent's auto-merge|Flights implement, run precheck",
    )
    for path in INSTRUCTIONS + [ROOT / "skills" / "ccwork" / "tours" / "sdlc.md"]:
        m = stale.search(_text(path))
        assert not m, f"{path.relative_to(ROOT)} still says {m.group(0)!r}"


def test_scp_is_free_and_opens_no_pr():
    s = _text(ROOT / "skills" / "scp" / "SKILL.md")
    assert "**This is free**" in s
    assert "pr_create" not in s


def test_scpmr_opens_a_draft_then_prechecks():
    s = _text(ROOT / "skills" / "scpmr" / "SKILL.md")
    assert s.index("draft: true") < s.index("**`/precheck`**")


def test_mmr_checks_the_status_and_rearms():
    s = _text(ROOT / "skills" / "mmr" / "SKILL.md")
    assert "precheck-status.sh get" in s
    assert "/precheck rearm" in s


def test_the_status_contract_matches_its_producer_and_consumer():
    doc = _text(ROOT / "docs" / "precheck-status.md")
    producer = _text(ROOT / "scripts" / "precheck-status.sh")
    hook = _text(ROOT / "scripts" / "hooks" / "workflow" / "pr-ready-gate.sh")
    assert 'CONTEXT="precheck"' in producer
    assert "`context` = `precheck`" in doc and "`name` = `precheck`" in doc
    assert "docs/precheck-status.md" in producer and "docs/precheck-status.md" in hook
    assert "pr-ready-gate.sh" in doc
