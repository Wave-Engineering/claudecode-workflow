"""Skill-text guard for /onboard (#1239).

/onboard hardens BJ's agent-initialize prompt into a kit skill. What BJ ruled on, and what this
file holds the skill to:

- the step order: `/engage`, then `/name`, then the seed check, ending in a hold for tag-up;
- no precheck skip and no auto-merge wording anywhere ("pull that out");
- a design document named `*seed*` is not a session seed, and seeds are dated by `git log`;
- the documentation fan-out and the deep issue review are bounded, with every title listed;
- the exclusion list is present, and the skill's own bash honours it (run, not just grepped).
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "onboard" / "SKILL.md"
ENGAGE = ROOT / "skills" / "engage" / "SKILL.md"
REFERENCE = ROOT / "docs" / "skill-reference.md"

EXCLUDED = (
    "museum",
    "frozen",
    "deprecated",
    "hold",
    "retired",
    "archive",
    "old",
    "legacy",
    "vendor",
    "node_modules",
    "dist",
)

# Wording that would let an agent skip /precheck or merge on its own. BJ's original prompt said
# "you may skip precheck for this specific activity and immediately `/scpmmr`".
FORBIDDEN = (
    re.compile(r"skip\w*\s+(the\s+|a\s+)?/?precheck", re.I),
    re.compile(r"/?precheck\s+skip", re.I),
    re.compile(r"without\s+(a\s+|the\s+)?/?precheck", re.I),
    re.compile(r"auto[- ]?merg", re.I),
    re.compile(r"auto[- ]?approv", re.I),
    re.compile(r"/scpmmr"),
    re.compile(r"bypass", re.I),
)
OLD_PROMPT_LINE = (
    "after updating the files and creating the issue and branch, you may skip precheck for this "
    "specific activity and immediately `/scpmmr`"
)


def _text() -> str:
    return SKILL.read_text(encoding="utf-8")


def _steps() -> list[tuple[int, str, str]]:
    """(number, title, body) for each `## N. title` step, in file order."""
    text = _text()
    heads = list(re.finditer(r"^## (\d+)\. (.+)$", text, re.M))
    out = []
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        out.append((int(m.group(1)), m.group(2), text[m.end() : end]))
    return out


def _step(n: int) -> str:
    return next(body for num, _, body in _steps() if num == n)


def _bash_blocks() -> list[str]:
    blocks = re.findall(r"^[ \t]*```bash\n(.*?)^[ \t]*```", _text(), re.M | re.S)
    return [textwrap.dedent(b) for b in blocks]


def _block(marker: str) -> str:
    found = [b for b in _bash_blocks() if marker in b]
    assert len(found) == 1, f"expected one bash block containing {marker!r}, found {len(found)}"
    return found[0]


def _onboard_reference_section() -> str:
    text = REFERENCE.read_text(encoding="utf-8")
    start = text.index("### `/onboard`")
    return text[start : text.index("### `/engage`", start)]


# --- shape and order ---------------------------------------------------------------------------


def test_frontmatter():
    text = _text()
    assert text.startswith("---\nname: onboard\n")
    assert re.search(r"^description: \S", text, re.M)


def test_step_order_engage_then_name_then_seed_check():
    steps = _steps()
    assert [n for n, _, _ in steps] == list(range(1, 9))
    assert "/engage" in steps[0][1]
    assert "/name" in steps[1][1]
    assert "seed check" in steps[2][1].lower()


def test_ends_in_a_hold_for_tag_up():
    num, title, body = _steps()[-1]
    assert "hold" in title.lower() and "tag up" in title.lower()
    assert "**stop**" in body.lower()
    assert "do no other work until the tag-up" in _text().lower()


def test_welcome_line_verbatim():
    assert "Welcome to the party, partner!!!!! -BJ" in _text()


# --- no precheck skip, no auto-merge -----------------------------------------------------------


def test_forbidden_patterns_catch_the_old_prompt_line():
    # Negative control: a guard that matches nothing would pass every skill text.
    assert any(p.search(OLD_PROMPT_LINE) for p in FORBIDDEN)


@pytest.mark.parametrize("pattern", FORBIDDEN, ids=lambda p: p.pattern)
def test_no_precheck_skip_or_auto_merge_wording(pattern):
    for name, text in (("SKILL.md", _text()), ("skill-reference", _onboard_reference_section())):
        assert not pattern.search(text), f"{name} matches {pattern.pattern!r}"


def test_ccfold_path_follows_ibm_through_the_normal_gates():
    body = _step(7)
    for needle in ("/ccfold", "/issue", "chore/<N>-", "protected branch", "/scpmr", "/precheck", "merge call"):
        assert needle in body, f"step 7 lacks {needle!r}"
    assert "Closes #<N>" in body
    assert "Never stash" in body


# --- seeds -------------------------------------------------------------------------------------


def test_fresh_reseed_seed_hands_off_to_revive():
    body = _step(3)
    assert ".claude/reseed-revive.md" in body
    assert "/reseed revive" in body
    assert "stop" in body.lower()


def test_design_docs_named_seed_are_not_session_seeds():
    body = _step(3)
    assert "`docs/seed-ai-dev.md`" in body
    assert "design document" in body
    assert "never mtime" in body
    assert "git log -1 --format=%cI" in body


# --- bounds ------------------------------------------------------------------------------------


def test_exclusion_list_present_and_defined_before_use():
    text = _text()
    skip = _block("SKIP=")
    for name in EXCLUDED:
        assert re.search(rf"[(|]{name}[|)]", skip), f"{name} missing from SKIP"
    assert text.index("SKIP=") < text.index("## 3. "), "SKIP must be defined before step 3 uses it"
    assert '"$SKIP"' in _block("ls-files") and '"$SKIP"' in _block("git log --name-only")


def test_documentation_fan_out_is_bounded():
    body = _step(5)
    assert "at most 4" in body
    assert "head -8" in _block("git log --name-only")
    for doc in ("README.md", "CLAUDE.md", "docs/"):
        assert doc in body


def test_issue_review_lists_every_title_and_bounds_the_deep_review():
    body = _step(6)
    assert "**every** open issue" in body
    assert "--limit 1000" in body and "--paginate" in body
    assert "at most 10" in body
    assert "--repo" in body, "gh must be pointed at origin, never left to resolve upstream"


# --- the skill's bash, run ---------------------------------------------------------------------


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args], cwd=repo, check=True, capture_output=True
    )


def _commit(repo: Path, path: str, body: str = "x\n") -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", f"add {path}")


def _run(repo: Path, marker: str) -> list[str]:
    script = _block("SKIP=") + "\n" + _block(marker)
    out = subprocess.run(["bash", "-c", script], cwd=repo, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.split()


def test_seed_candidates_skip_excluded_folders_and_the_reseed_file(temp_git_repo):
    repo = temp_git_repo
    _commit(repo, "docs/seed-ai-dev.md")
    _commit(repo, "docs/DDD-SEED-PROMPT.md")
    _commit(repo, "museum/old-seed.md")
    _commit(repo, "Archive/x-SEED.md")
    _commit(repo, "docs/plain.md")
    (repo / "notes").mkdir()
    (repo / "notes" / "session-seed.md").write_text("x\n", encoding="utf-8")
    (repo / ".claude").mkdir()
    (repo / ".claude" / "reseed-revive.md").write_text("x\n", encoding="utf-8")

    got = _run(repo, "ls-files")
    assert sorted(got) == ["docs/DDD-SEED-PROMPT.md", "docs/seed-ai-dev.md", "notes/session-seed.md"]


def test_recent_docs_are_newest_first_bounded_and_skip_excluded(temp_git_repo):
    repo = temp_git_repo
    for i in range(10):
        _commit(repo, f"docs/d{i}.md")
    _commit(repo, "gone.md")
    _git(repo, "rm", "-q", "gone.md")
    _git(repo, "commit", "-q", "-m", "drop gone.md")
    _commit(repo, "legacy/l.md")
    _commit(repo, "node_modules/pkg/README.md")
    _commit(repo, "README.md")
    _commit(repo, "CLAUDE.md")

    got = _run(repo, "git log --name-only")
    assert got == [f"docs/d{i}.md" for i in range(9, 1, -1)]


# --- cross-references --------------------------------------------------------------------------


def test_engage_points_at_onboard():
    assert "`/onboard`" in ENGAGE.read_text(encoding="utf-8")


def test_reference_documents_aoe_first_prompt():
    section = _onboard_reference_section()
    assert 'aoe send <title> "/onboard"' in section
    for name in EXCLUDED:
        assert f"`{name}`" in section
