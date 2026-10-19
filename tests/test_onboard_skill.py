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

import json
import os
import re
import shutil
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
    body = " ".join(_step(7).split())
    for needle in ("/ccfold", "/issue", "chore/<N>-", "protected branch", "/scpmr", "/precheck", "merge call"):
        assert needle in body, f"step 7 lacks {needle!r}"
    assert "Closes #<N>" in body
    assert "Never stash" in body


def test_ccfold_path_opens_one_refresh_and_survives_a_missing_claude_md():
    body = " ".join(_step(7).split())
    # A refresh waits for its merge call; until then every onboarding agent sees the same staleness.
    assert "Don't open a second refresh" in body
    assert "git ls-remote --heads origin 'chore/*-ccfold'" in body
    # /ccfold stops before Step 9 on a missing or an already-current CLAUDE.md; Steps 9 and 10
    # must still run, or a stale .claude-project.md alone yields an empty refresh.
    assert "stops early in two cases" in body and "already matches upstream" in body
    assert "Steps 9 and 10" in body and "Dev-Team:" in body
    assert "nothing to commit" in body
    assert "git check-ignore -q .claude/agent-identity.json" in body


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


def test_each_block_sets_the_same_complete_skip_list():
    # Every Bash call is a fresh shell: a SKIP set in another block is empty here, and
    # `grep -Eiv ""` drops every line, so a block that leans on an earlier one prints nothing.
    lines = set()
    for marker in ("ls-files", "git log --name-only"):
        block = _block(marker)
        assert '"$SKIP"' in block
        m = re.search(r"^SKIP=.*$", block, re.M)
        assert m, f"the {marker!r} block does not set SKIP itself"
        lines.add(m.group(0))
    assert len(lines) == 1, f"the two blocks skip different folders: {lines}"
    skip = lines.pop()
    preamble = _text()[: _text().index("## 1. ")]
    for name in EXCLUDED:
        assert re.search(rf"[(|]{name}[|)]", skip), f"{name} missing from SKIP"
        assert f"`{name}`" in preamble, f"{name} missing from the list the reader sees"


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


def _hermetic(repo: Path) -> dict[str, str]:
    """The environment with no global git config or excludes, and no SKIP from outside.

    A host's global excludes file (this fleet's ignores `**/.claude/settings.local.json`) would
    otherwise hide files the skill's commands must see, and pass here while failing elsewhere.
    """
    env = {k: v for k, v in os.environ.items() if k != "SKIP"}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, XDG_CONFIG_HOME=str(repo / ".git" / "no-xdg"))
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env=_hermetic(repo),
    )


def _commit(repo: Path, path: str, body: str = "x\n") -> None:
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(body, encoding="utf-8")
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", f"add {path}")


def _run(repo: Path, marker: str) -> list[str]:
    # The block alone, as an agent's Bash call runs it: nothing from any other block.
    out = subprocess.run(["bash", "-c", _block(marker)], cwd=repo, capture_output=True, text=True, env=_hermetic(repo))
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


GITLAB_PAGES = (
    '[{"iid": 1, "title": "a", "description": "LONG BODY", "labels": ["x"],'
    ' "assignees": [{"username": "u", "avatar_url": "z"}], "updated_at": "t1"}]'
    '[{"iid": 2, "title": "b", "description": "LONG BODY", "labels": [],'
    ' "assignees": [], "updated_at": "t2"}]'
)


def _forge_stubs(bin_dir: Path) -> None:
    for name, extra in (("gh", ""), ("glab", f"printf '%s' '{GITLAB_PAGES}'\n")):
        stub = bin_dir / name
        stub.write_text(f"#!/usr/bin/env bash\nprintf '{name} %s\\n' \"$*\" >&2\n{extra}", encoding="utf-8")
        stub.chmod(0o755)


def _issues(repo: Path, bin_dir: Path, origin: str) -> subprocess.CompletedProcess:
    _git(repo, "remote", "add", "origin", origin)
    env = {**_hermetic(repo), "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return subprocess.run(["bash", "-c", _block("gh issue list")], cwd=repo, capture_output=True, text=True, env=env)


@pytest.mark.parametrize(
    "origin,project",
    [("git@github.com:Org/repo.git", "Org/repo"), ("https://github.com/Org/repo", "Org/repo")],
)
def test_issue_listing_on_github_names_origin(temp_git_repo, tmp_path_factory, origin, project):
    bin_dir = tmp_path_factory.mktemp("bin")
    _forge_stubs(bin_dir)
    out = _issues(temp_git_repo, bin_dir, origin)
    assert out.returncode == 0, out.stderr
    assert f"gh issue list --repo {project} --state open --limit 1000" in out.stderr
    assert "glab" not in out.stderr


@pytest.mark.skipif(shutil.which("jq") is None, reason="jq not installed")
@pytest.mark.parametrize(
    "origin,path",
    [
        ("https://gitlab.com/grp/sub/proj.git", "grp%2Fsub%2Fproj"),
        # A project named like the other forge must still go to its own host's CLI.
        ("ssh://git@gitlab.example.com:2222/grp/github-mirror.git", "grp%2Fgithub-mirror"),
    ],
)
def test_issue_listing_on_gitlab_names_origin_and_drops_bodies(temp_git_repo, tmp_path_factory, origin, path):
    bin_dir = tmp_path_factory.mktemp("bin")
    _forge_stubs(bin_dir)
    out = _issues(temp_git_repo, bin_dir, origin)
    assert out.returncode == 0, out.stderr
    assert f"glab api --paginate projects/{path}/issues?state=opened&per_page=100" in out.stderr
    assert "gh issue" not in out.stderr
    assert json.loads(out.stdout) == [
        {"iid": 1, "title": "a", "labels": ["x"], "assignees": ["u"], "updated_at": "t1"},
        {"iid": 2, "title": "b", "labels": [], "assignees": [], "updated_at": "t2"},
    ]


def test_issue_listing_on_another_forge_says_so(temp_git_repo, tmp_path_factory):
    bin_dir = tmp_path_factory.mktemp("bin")
    _forge_stubs(bin_dir)
    out = _issues(temp_git_repo, bin_dir, "git@bitbucket.org:o/r.git")
    assert out.stdout.strip() == "origin is on neither GitHub nor GitLab: bitbucket.org"
    assert out.stderr == ""


def test_clean_tree_check_tolerates_only_the_identity_file(temp_git_repo):
    repo = temp_git_repo
    _commit(repo, "a.md")
    check = _block("--untracked-files=all")

    def dirt() -> str:
        run = subprocess.run(["bash", "-c", check], cwd=repo, capture_output=True, text=True, env=_hermetic(repo))
        # A clean tree must not look like a failed command to the agent reading the result.
        assert run.returncode == 0, run.stderr
        return run.stdout

    assert dirt() == ""
    (repo / ".claude").mkdir()
    (repo / ".claude" / "agent-identity.json").write_text("{}\n", encoding="utf-8")
    assert dirt() == "", "the identity /name writes in step 2 must not block step 7"
    for stray in (".claude/notes.txt", "notes.txt"):
        (repo / stray).write_text("x\n", encoding="utf-8")
        assert stray in dirt()
        (repo / stray).unlink()
    (repo / "a.md").write_text("changed\n", encoding="utf-8")
    assert "a.md" in dirt()


# --- cross-references --------------------------------------------------------------------------


def test_engage_points_at_onboard():
    assert "`/onboard`" in ENGAGE.read_text(encoding="utf-8")


def test_reference_documents_aoe_first_prompt():
    section = _onboard_reference_section()
    assert 'aoe send <title> "/onboard"' in section
    for name in EXCLUDED:
        assert f"`{name}`" in section
