"""scripts/hooks/workflow/pr-ready-gate.sh: no ready PR/MR without a precheck pass (#1235).

The hook runs for real, calling the real scripts/precheck-status.sh, with `gh`/`glab`
replaced by the fake from test_precheck_status.py.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tests.test_precheck_status import FAKE, SCRIPT as STATUS

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOK = REPO_ROOT / "scripts" / "hooks" / "workflow" / "pr-ready-gate.sh"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def world(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("gh", "glab"):
        (bin_dir / tool).write_text(FAKE)
        (bin_dir / tool).chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "remote", "add", "origin", "git@github.com:Owner/Repo.git")
    _git(repo, "checkout", "-q", "-b", "feature/1-x")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "work")
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_STATE": str(tmp_path / "state.json"),
        "FAKE_HOST": "gitlab.example.com",
    }
    return repo, env


def _prs(repo: Path, extra: dict | None = None) -> str:
    """The fake platform's open PRs: #12 (and MR !5) from the current branch at its HEAD."""
    head = {"sha": _git(repo, "rev-parse", "HEAD"), "ref": _git(repo, "rev-parse", "--abbrev-ref", "HEAD")}
    return json.dumps({"12": head, "5": head, **(extra or {})})


def _hook(world, command: str, prs: dict | None = None, **extra: str) -> str:
    repo, env = world
    extra.setdefault("FAKE_PRS", _prs(repo, prs))
    payload = json.dumps({"session_id": "s", "cwd": str(repo), "tool_input": {"command": command}})
    r = subprocess.run(["bash", str(HOOK)], input=payload, env={**env, **extra}, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def _blocked(out: str) -> bool:
    return bool(out) and json.loads(out)["decision"] == "block"


def _pass_precheck(world, ref: str = "HEAD") -> None:
    repo, env = world
    sha = _git(repo, "rev-parse", ref)
    r = subprocess.run(["bash", str(STATUS), "post", str(repo), sha, "ok"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


GATED = [
    "gh pr create --fill",
    "gh pr ready",
    "gh pr ready 12",
    "glab mr create --fill",
    "glab mr update 5 --ready",
    "glab mr update 5 -r",
    "cd . && gh pr create --title x --body-file b.md",
    "gh pr create --draft; gh pr create --fill",
    'bash -c "gh pr create --fill"',
    "GH_PROMPT_DISABLED=1 /usr/bin/gh pr create --fill",
    "echo hi\ngh pr create --fill",
    "gh pr create \\\n  --fill",
    "gh -R Owner/Repo pr ready 12",
    "gh pr -R Owner/Repo ready 12",
    # The value attached to -R (pflag accepts it) does not hide the command.
    "gh -ROwner/Repo pr ready 12",
    "gh pr -R=Owner/Repo ready 12",
    "gh pr ready https://github.com/Owner/Repo/pull/12",
    # A word in front of the tool never hides it.
    "timeout 60 gh pr create --fill",
    "env -u GH_TOKEN gh pr create --fill",
    "if gh pr ready 12; then echo ok; fi",
    "while true; do gh pr ready 12; break; done",
    "sudo gh pr ready 12",
    "command gh pr ready 12",
    "echo 12 | xargs gh pr ready",
    "{ gh pr ready 12; }",
    "! gh pr ready 12",
    # A draft flag inside a quoted value, or set false, is no draft.
    'gh pr create --body "use -d for drafts" --fill',
    "gh pr create --body 'see --draft' --fill",
    "gh pr create --draft=false --fill",
    'glab mr create --description "not --wip" --fill',
    # GitLab's draft state is the title prefix: a plain retitle makes a draft ready.
    "glab mr update 5 --title x",
    'glab mr update 5 -t "Fix the thing"',
    "glab mr update 5 --title=x",
    "glab mr update 5 --fill",
    "glab mr update 5 -f",
    # The title's words are not the selector: this is the current branch's MR.
    'glab mr update --title "fix: x"',
    # WIP: is not a draft on GitLab 14.0+, and glab --wip only adds that prefix.
    "glab mr create --wip --fill",
    'glab mr update 5 --title "WIP: x"',
    "glab mr update 5 --wip --title x",
    # Every glab mr update without --draft: glab rewrites the title on most flags, and
    # GitLab's draft state IS the title prefix, so the gate stopped modelling which.
    "glab mr update 5 --wip",
    'glab mr update 5 --wip --title "Draft: x"',
    'glab mr update 5 --title "Draft: x"',
    "glab mr update 5 --label bug",
    "glab mr update --description-file b.md --ready",
    "glab mr create -H fork/thing --fill",
]

FREE = [
    "gh pr create --draft --fill",
    "gh pr create -d --fill",
    "gh pr create --draft=true --fill",
    'gh pr create --title "x" --draft --body "y"',
    "timeout 60 gh pr create --draft --fill",
    "ghost pr create --fill",
    "my-gh pr create --fill",
    "gh pr ready --undo",
    "glab mr create --draft",
    "glab mr update 5 --fill --draft",
    "glab mr update 5 --draft --title x",
    "glab mr update 5 --draft --label bug",
    "gh pr list",
    "gh pr view 3 --json state",
    "git push -u origin feature/1-x",
]


@pytest.mark.parametrize("command", GATED)
def test_making_a_pr_ready_without_precheck_is_blocked(world, command):
    out = _hook(world, command)
    assert _blocked(out), f"not blocked: {command!r}"
    assert "precheck" in json.loads(out)["reason"]


@pytest.mark.parametrize("command", GATED)
def test_a_precheck_pass_on_head_lets_it_through(world, command):
    _pass_precheck(world)
    assert _hook(world, command) == ""


@pytest.mark.parametrize("command", FREE)
def test_drafts_and_other_commands_are_free(world, command):
    assert _hook(world, command) == ""


def test_a_pass_on_an_older_commit_does_not_count(world):
    repo, _ = world
    _pass_precheck(world)
    _git(repo, "commit", "-q", "--allow-empty", "-m", "pushed after precheck")
    assert _blocked(_hook(world, "gh pr ready"))


def test_an_unreadable_status_blocks(world):
    out = _hook(world, "gh pr create --fill", FAKE_FAIL="1")
    assert _blocked(out)
    assert "could not be read" in json.loads(out)["reason"]


def test_head_flag_checks_that_branch_not_local_head(world):
    repo, _ = world
    _git(repo, "branch", "other", "main")
    pushed = json.dumps({"other": _git(repo, "rev-parse", "other")})
    _pass_precheck(world)  # local HEAD passes, `other` does not
    assert _blocked(_hook(world, "gh pr create --head other --fill", FAKE_BRANCHES=pushed))
    assert _blocked(_hook(world, "glab mr create --source-branch other --fill", FAKE_BRANCHES=pushed))
    _pass_precheck(world, "other")
    assert _hook(world, "gh pr create --head other --fill", FAKE_BRANCHES=pushed) == ""
    assert _hook(world, "glab mr create -s other --fill", FAKE_BRANCHES=pushed) == ""


@pytest.mark.parametrize(
    "cmd",
    ["gh pr create -Hother --fill", "gh pr create -H=other --fill",
     "glab mr create -sother --fill", "glab mr create -s=other --fill"],
)
def test_attached_shorthand_head_checks_that_branch(world, cmd):
    # pflag accepts the value attached to a shorthand flag. Ignored, the gate would check
    # local HEAD's pass while the PR/MR opens from `other`.
    repo, _ = world
    _git(repo, "branch", "other", "main")
    pushed = json.dumps({"other": _git(repo, "rev-parse", "other")})
    _pass_precheck(world)
    assert _blocked(_hook(world, cmd, FAKE_BRANCHES=pushed))
    _pass_precheck(world, "other")
    assert _hook(world, cmd, FAKE_BRANCHES=pushed) == ""


def test_glab_head_is_a_repository_not_a_branch(world):
    # glab's -H names a head REPOSITORY. Read as a branch, `fork/thing` would be looked up
    # (and, as `kahuna/…`, exempted); the source branch stays the current one.
    _pass_precheck(world)
    assert _hook(world, "glab mr create -H fork/thing --fill") == ""
    assert _blocked(_hook(world, "glab mr create -H kahuna/56-w1 --fill", FAKE_PRS="{}"))
    # The `=` forms too: the shared `--head=*` arm would read them as gh's branch.
    assert _hook(world, "glab mr create --head=fork/thing --fill") == ""
    assert _blocked(_hook(world, "glab mr create --head=kahuna/56-w1 --fill", FAKE_PRS="{}"))
    assert _blocked(_hook(world, "glab mr create -H=kahuna/56-w1 --fill", FAKE_PRS="{}"))


def test_create_checks_where_the_branch_points_on_the_platform(world):
    repo, _ = world
    _pass_precheck(world)  # local HEAD passes, and it is what local origin/<branch> would say
    remote_head = _git(repo, "rev-parse", "main")  # another sandbox pushed: the platform disagrees
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    out = _hook(world, "gh pr create --fill", FAKE_PRS="{}", FAKE_BRANCHES=json.dumps({branch: remote_head}))
    assert _blocked(out)


def test_create_from_a_branch_never_pushed_blocks(world):
    out = _hook(world, "gh pr create --fill", FAKE_PRS="{}")
    assert _blocked(out)
    assert "could not be read" in json.loads(out)["reason"]


def test_a_cd_first_checks_the_repository_it_moves_to(world):
    repo, env = world
    other = repo.parent / "other"
    other.mkdir()
    _git(other, "init", "-q", "-b", "main")
    _git(other, "config", "user.email", "t@example.invalid")
    _git(other, "config", "user.name", "t")
    _git(other, "commit", "-q", "--allow-empty", "-m", "other")
    _git(other, "remote", "add", "origin", "git@github.com:Other/Thing.git")
    _git(other, "checkout", "-q", "-b", "feature/9-o")
    _pass_precheck(world)  # the session repo's branch passes; the other repo's does not
    pushed = json.dumps({"feature/9-o": _git(other, "rev-parse", "HEAD")})
    assert _blocked(_hook(world, f"cd {other} && gh pr create --fill", FAKE_BRANCHES=pushed))
    assert _blocked(_hook(world, f'bash -c "cd {other} && gh pr create --fill"', FAKE_BRANCHES=pushed))
    assert "repos/Other/Thing/git/ref/heads/feature/9-o" in Path(env["FAKE_LOG"]).read_text()


def test_a_cd_it_cannot_resolve_blocks_without_repo(world):
    _pass_precheck(world)
    out = _hook(world, 'cd "$OTHER_REPO" && gh pr ready 12')
    assert _blocked(out)
    assert "-R" in json.loads(out)["reason"]
    assert _hook(world, 'cd "$OTHER_REPO" && gh -R Owner/Repo pr ready 12') == ""
    # -R's attached-value forms name the repository too.
    assert _hook(world, 'cd "$OTHER_REPO" && gh -R=Owner/Repo pr ready 12') == ""
    assert _hook(world, 'cd "$OTHER_REPO" && gh pr -ROwner/Repo ready 12') == ""
    # A create there follows the advice: -R plus --head needs no repository.
    repo, _ = world
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    out = _hook(world, 'cd "$OTHER_REPO" && gh pr create --fill')
    assert _blocked(out) and "--head" in json.loads(out)["reason"]
    out = _hook(world, 'cd "$OTHER_REPO" && glab mr create --fill')
    assert _blocked(out) and "--source-branch" in json.loads(out)["reason"]
    assert _hook(world, f'cd "$OTHER_REPO" && gh pr create -R Owner/Repo --head {branch} --fill') == ""


def test_a_cd_to_a_non_repo_names_the_cd_target(world):
    out = _hook(world, "cd /nonexistent-dir && gh pr ready 12")
    assert _blocked(out)
    assert "/nonexistent-dir" in json.loads(out)["reason"]


def test_a_pr_url_is_asked_of_its_own_repository(world):
    repo, env = world
    _pass_precheck(world)
    assert _hook(world, "gh pr ready https://github.com/Other/Thing/pull/12") == ""
    calls = Path(env["FAKE_LOG"]).read_text()
    assert "repos/Other/Thing/pulls/12" in calls
    assert "repos/Owner/Repo/pulls/12" not in calls


def test_hook_is_registered_and_fails_closed():
    settings = json.loads((REPO_ROOT / "config" / "settings.template.json").read_text())
    hooks = {
        h["command"]: h
        for group in settings["hooks"]["PreToolUse"]
        if group.get("matcher") == "Bash"
        for h in group["hooks"]
    }
    # It calls the platform API, so a timeout must block rather than wave the PR through.
    assert hooks["~/.claude/scripts/hooks/workflow/pr-ready-gate.sh"].get("onFailure") == "block"


def test_ready_checks_the_prs_own_head_not_local_head(world):
    repo, _ = world
    base_sha = _git(repo, "rev-parse", "main")
    _pass_precheck(world)  # local HEAD passes; PR #13's head (main's tip) does not
    prs = {"13": {"sha": base_sha, "ref": "feature/2-y"}}
    assert _blocked(_hook(world, "gh pr ready 13", prs=prs))
    assert _hook(world, "gh pr ready 12", prs=prs) == ""


@pytest.mark.parametrize("ref", ["kahuna/56-w1", "campaign/56-orion"])
def test_integration_heads_are_governed_by_the_wave_gate(world, ref):
    prs = {"77": {"sha": "b" * 40, "ref": ref}}
    assert _hook(world, "gh -R Owner/Repo pr ready 77", prs=prs) == ""
    assert _hook(world, f"gh pr create --head {ref} --fill", prs=prs) == ""


@pytest.mark.parametrize("repo_opt", ["-R group/proj", "-R=group/proj", "-Rgroup/proj"])
def test_glab_repo_flag_is_asked_of_that_project(world, repo_opt):
    repo, env = world
    _git(repo, "remote", "set-url", "origin", "https://gitlab.example.com/group/proj.git")
    cmd = f"glab {repo_opt} mr update 5 --ready"
    assert _blocked(_hook(world, cmd))
    _pass_precheck(world)
    assert _hook(world, cmd) == ""


def test_a_flight_into_its_kahuna_branch_is_governed_by_the_wave_gate(world):
    prs = {"88": {"sha": "c" * 40, "ref": "feature/9-z", "base": "kahuna/56-w1"}}
    assert _hook(world, "gh pr ready 88", prs=prs) == ""
    assert _hook(world, "gh pr create --base kahuna/56-w1 --fill") == ""
    assert _hook(world, "glab mr create --target-branch kahuna/56-w1 --fill") == ""
    # The same flight into main is not exempt.
    assert _blocked(_hook(world, "gh pr create --base main --fill"))


def test_an_unknown_pr_blocks(world):
    out = _hook(world, "gh pr ready 999")
    assert _blocked(out)
    assert "could not be read" in json.loads(out)["reason"]


def test_disable_switch(world):
    assert _hook(world, "gh pr create --fill", PR_READY_GATE_DISABLED="1") == ""
