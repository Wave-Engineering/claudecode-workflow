"""Tests for scripts/hooks/workflow/secret-scan-gate.sh (#1234).

Driven for real: the hook runs as a subprocess on a PreToolUse payload, against a
throwaway git repo (and a bare "remote"), with the real gitleaks. A stub gitleaks is
used only to prove the hook fails closed on gitleaks's exit-0-on-error behaviour.

gitleaks must be on PATH. CI installs the pinned version (scripts/ci/install-gitleaks.sh);
locally the tests skip without it, except under CI, where a missing scanner fails.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "scripts" / "hooks" / "workflow" / "secret-scan-gate.sh"

# Split so this file never contains a detectable key itself.
FAKE_KEY = "AKIA" + "TLQ4V2KXR7NWJ3PZ"

GITLEAKS = shutil.which("gitleaks")
if GITLEAKS is None and os.environ.get("CI"):
    raise RuntimeError("gitleaks is not on PATH in CI; the install step did not run")
needs_gitleaks = pytest.mark.skipif(GITLEAKS is None, reason="gitleaks not on PATH")


# Exactly the tools the hook (and metrics.sh, git and the stub) run. Not /usr/bin itself:
# a distro gitleaks lives there (Ubuntu's package), and would defeat the no-gitleaks tests.
HOOK_TOOLS = ("bash", "git", "jq", "cat", "head", "tr", "sort", "grep", "mktemp", "rm", "cp", "dirname", "date", "sed")


def _tool_path(tmp_path: Path, with_gitleaks: bool = True) -> str:
    """A PATH holding only the hook's tools and (optionally) gitleaks."""
    bin_dir = tmp_path / ("toolbin" if with_gitleaks else "toolbin-no-gitleaks")
    bin_dir.mkdir(exist_ok=True)
    for tool in HOOK_TOOLS:
        link = bin_dir / tool
        if not link.exists():
            link.symlink_to(shutil.which(tool))
    if with_gitleaks and GITLEAKS and not (bin_dir / "gitleaks").exists():
        (bin_dir / "gitleaks").symlink_to(GITLEAKS)
    return str(bin_dir)


def _env(tmp_path: Path, path: str) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        "PATH": path,
        "HOME": str(home),
        "TMPDIR": str(tmp_path),
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }


def _git(repo: Path, *args: str, env: dict[str, str]) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=env
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    env = _env(tmp_path, _tool_path(tmp_path))
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, env=env)
    r = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True, env=env)
    (r / "README").write_text("hello\n")
    _git(r, "add", "README", env=env)
    _git(r, "commit", "-qm", "init", env=env)
    _git(r, "remote", "add", "origin", str(remote), env=env)
    _git(r, "push", "-q", "origin", "main", env=env)
    _git(r, "checkout", "-q", "-b", "feature/1-x", env=env)
    return r


def _run_full(
    tmp_path: Path, command: str, cwd: Path, path: str | None = None
) -> tuple[dict | None, str]:
    path = path if path is not None else _tool_path(tmp_path)
    payload = {"session_id": "test-session", "cwd": str(cwd), "tool_input": {"command": command}}
    result = subprocess.run(
        ["bash", str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=_env(tmp_path, path),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    return (json.loads(out) if out else None), result.stderr


def _run(tmp_path: Path, command: str, cwd: Path, path: str | None = None) -> dict | None:
    return _run_full(tmp_path, command, cwd, path)[0]


def _blocked(decision: dict | None) -> bool:
    return decision is not None and decision.get("decision") == "block"


@needs_gitleaks
def test_staged_secret_blocks_commit(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    decision = _run(tmp_path, "git commit -m x", repo)
    assert _blocked(decision)
    assert "creds.txt:1" in decision["reason"]
    assert "aws-access-token" in decision["reason"]


@needs_gitleaks
def test_block_message_never_contains_the_secret(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    decision = _run(tmp_path, "git commit -m x", repo)
    assert _blocked(decision)
    assert FAKE_KEY not in json.dumps(decision)
    assert FAKE_KEY[4:] not in json.dumps(decision)


@needs_gitleaks
def test_clean_staged_diff_passes(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "notes.txt").write_text("nothing to see\n")
    _git(repo, "add", "notes.txt", env=env)
    assert _run(tmp_path, "git commit -m x", repo) is None


@needs_gitleaks
def test_add_and_commit_catches_a_file_not_yet_staged(tmp_path: Path, repo: Path):
    # The hook runs before the command: `git add -A` has not happened yet, so the real
    # index does not hold creds.txt. The scratch-index superset must still catch it.
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    assert _blocked(_run(tmp_path, "git add -A && git commit -m x", repo))


@needs_gitleaks
def test_staged_secret_blocks_even_after_the_working_tree_dropped_it(tmp_path: Path, repo: Path):
    # Staged with the key, then edited clean without re-staging: the commit records the
    # staged blob, which only the real-index scan sees (the scratch index re-adds the
    # clean working-tree file over it).
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    (repo / "creds.txt").write_text("aws_key = <redacted>\n")
    decision = _run(tmp_path, "git commit -m x", repo)
    assert _blocked(decision)
    assert "creds.txt:1" in decision["reason"]


@needs_gitleaks
def test_commit_scan_leaves_the_real_index_alone(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    before = _git(repo, "status", "--porcelain", env=env)
    _run(tmp_path, "git commit -m x", repo)
    assert _git(repo, "status", "--porcelain", env=env) == before
    assert before.strip() == "?? creds.txt"


@needs_gitleaks
def test_compound_command_from_parent_directory_is_scanned(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    assert _blocked(_run(tmp_path, f"cd {repo.name} && git commit -m x", tmp_path))


@needs_gitleaks
def test_git_dash_c_push_from_outside_the_repo_is_scanned(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    _git(repo, "commit", "-qm", "add", env=env)
    assert _blocked(_run(tmp_path, f"git -C {repo} push origin feature/1-x", tmp_path))


@needs_gitleaks
def test_secret_added_then_removed_blocks_the_push(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    _git(repo, "commit", "-qm", "add key", env=env)
    _git(repo, "rm", "-q", "creds.txt", env=env)
    _git(repo, "commit", "-qm", "remove key", env=env)
    assert not (repo / "creds.txt").exists()  # the tip is clean; only the range has it
    decision = _run(tmp_path, "git push -u origin feature/1-x", repo)
    assert _blocked(decision)
    assert "creds.txt:1" in decision["reason"]
    assert "commit " in decision["reason"]


@needs_gitleaks
def test_push_scans_named_branches_not_every_stale_one(tmp_path: Path, repo: Path):
    # A squash-merged branch whose remote branch was deleted keeps its commits off every
    # remote. It must not block an unrelated push, but must block a push that names it.
    env = _env(tmp_path, _tool_path(tmp_path))
    _git(repo, "checkout", "-q", "-b", "fix/2-stale", "main", env=env)
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    _git(repo, "commit", "-qm", "stale key", env=env)
    _git(repo, "checkout", "-q", "feature/1-x", env=env)
    assert _run(tmp_path, "git push origin feature/1-x", repo) is None
    assert _blocked(_run(tmp_path, "git push origin fix/2-stale", repo))
    assert _blocked(_run(tmp_path, "git push origin fix/2-stale:fix/2-other", repo))
    assert _blocked(_run(tmp_path, "git push --all origin", repo))
    # A shell operator right after the ref or flag still bounds the word.
    assert _blocked(_run(tmp_path, "git push origin fix/2-stale; git status", repo))
    assert _blocked(_run(tmp_path, "(git push origin fix/2-stale)", repo))
    assert _blocked(_run(tmp_path, "git push origin fix/2-stale&&git status", repo))
    assert _blocked(_run(tmp_path, "git push --all origin;", repo))
    assert _blocked(_run(tmp_path, "git push --branches origin", repo))


@needs_gitleaks
def test_failed_rev_list_fails_closed(tmp_path: Path, repo: Path):
    # A rev-list that exits non-zero must read as a failed scan, not as "nothing unpushed".
    # Here an unpushed commit's parent object is missing (a corrupt history).
    env = _env(tmp_path, _tool_path(tmp_path))
    for n in ("1", "2"):
        (repo / f"n{n}.txt").write_text(f"{n}\n")
        _git(repo, "add", f"n{n}.txt", env=env)
        _git(repo, "commit", "-qm", n, env=env)
    parent = _git(repo, "rev-parse", "HEAD~1", env=env).strip()
    (repo / ".git" / "objects" / parent[:2] / parent[2:]).unlink()
    decision = _run(tmp_path, "git push origin feature/1-x", repo)
    assert _blocked(decision)
    assert "rev-list failed" in decision["reason"]


def test_missing_detector_blocks_git_commands(tmp_path: Path, repo: Path):
    # The hook without its git-detect.sh beside it: a git command is blocked, not waved
    # through as "not a commit or push".
    lone = tmp_path / "lone"
    lone.mkdir()
    shutil.copy(HOOK, lone / HOOK.name)
    payload = {"session_id": "s", "cwd": str(repo), "tool_input": {"command": "git commit -m x"}}
    env = _env(tmp_path, _tool_path(tmp_path))

    def run(command: str) -> str:
        payload["tool_input"]["command"] = command
        return subprocess.run(
            ["bash", str(lone / HOOK.name)], input=json.dumps(payload), capture_output=True, text=True, env=env
        ).stdout.strip()

    out = run("git commit -m x")
    assert json.loads(out)["decision"] == "block"
    assert "git-detect.sh" in json.loads(out)["reason"]
    assert run("ls -la") == ""


@needs_gitleaks
def test_push_with_nothing_unpushed_passes(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "notes.txt").write_text("fine\n")
    _git(repo, "add", "notes.txt", env=env)
    _git(repo, "commit", "-qm", "notes", env=env)
    assert _run(tmp_path, "git push origin feature/1-x", repo) is None
    _git(repo, "push", "-q", "origin", "feature/1-x", env=env)
    assert _run(tmp_path, "git push origin feature/1-x", repo) is None


@needs_gitleaks
def test_allowlisted_fingerprint_passes_commit_and_push(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    (repo / ".gitleaksignore").write_text("creds.txt:aws-access-token:1\n")
    _git(repo, "add", "-A", env=env)
    assert _run(tmp_path, "git commit -m x", repo) is None
    _git(repo, "commit", "-qm", "allowlisted", env=env)
    # The short file:rule:line key also covers the commit-range scan.
    assert _run(tmp_path, "git push origin feature/1-x", repo) is None


def _commit_secret_on_head(repo: Path, env: dict[str, str]) -> None:
    (repo / "creds.txt").write_text(f"aws_key = {FAKE_KEY}\n")
    _git(repo, "add", "creds.txt", env=env)
    _git(repo, "commit", "-qm", "add key", env=env)


# #1364: a plain delete of one branch publishes no commits, so it is never scanned.
@needs_gitleaks
def test_delete_only_push_is_not_scanned(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    _commit_secret_on_head(repo, env)
    assert _run(tmp_path, "git push origin --delete scratch-1", repo) is None
    # Control: the same repo's real push is scanned and blocked.
    assert _blocked(_run(tmp_path, "git push -u origin feature/1-x", repo))


def test_delete_only_push_passes_without_gitleaks(tmp_path: Path, repo: Path):
    path = _tool_path(tmp_path, with_gitleaks=False)
    assert _run(tmp_path, "git push origin :scratch-1", repo, path=path) is None


def test_delete_of_branch_unknown_locally_does_not_error(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    _git(repo, "branch", "-q", "scratch-1", env=env)
    _git(repo, "push", "-q", "origin", "scratch-1", env=env)
    _git(repo, "branch", "-q", "-D", "scratch-1", env=env)
    decision, stderr = _run_full(tmp_path, "git push origin --delete scratch-1", repo)
    assert decision is None
    assert stderr == ""


@needs_gitleaks
def test_mixed_push_and_delete_is_still_scanned(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    _commit_secret_on_head(repo, env)
    assert _blocked(_run(tmp_path, "git push origin feature/1-x :scratch-1", repo))


@needs_gitleaks
def test_compound_delete_is_still_scanned(tmp_path: Path, repo: Path):
    env = _env(tmp_path, _tool_path(tmp_path))
    _commit_secret_on_head(repo, env)
    assert _blocked(_run(tmp_path, f"cd {repo} && git push origin --delete scratch-1", repo))


def test_missing_gitleaks_blocks_with_install_hint(tmp_path: Path, repo: Path):
    decision = _run(tmp_path, "git commit -m x", repo, path=_tool_path(tmp_path, with_gitleaks=False))
    assert _blocked(decision)
    assert "gitleaks is not installed" in decision["reason"]
    assert "install-gitleaks.sh" in decision["reason"]


def test_scan_error_fails_closed_even_when_gitleaks_exits_zero(tmp_path: Path, repo: Path):
    # Real gitleaks exits 0 when the git command it runs fails: it logs an error and
    # writes an empty report. A stub reproducing exactly that must still block.
    stub_dir = tmp_path / "stubbin"
    stub_dir.mkdir()
    stub = stub_dir / "gitleaks"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        'prev=""; for a in "$@"; do [[ "$prev" == -r ]] && printf "[]" > "$a"; prev="$a"; done\n'
        'echo "ERR [git] fatal: something broke" >&2\n'
        "exit 0\n"
    )
    stub.chmod(0o755)
    path = f"{stub_dir}:{_tool_path(tmp_path, with_gitleaks=False)}"
    (repo / "notes.txt").write_text("fine\n")
    decision = _run(tmp_path, "git commit -m x", repo, path=path)
    assert _blocked(decision)
    assert "Secret scan failed" in decision["reason"]


def test_no_repository_blocks(tmp_path: Path):
    outside = tmp_path / "not-a-repo"
    outside.mkdir()
    path = _tool_path(tmp_path)
    if GITLEAKS is None:  # the no-repo check comes after the gitleaks check
        pytest.skip("gitleaks not on PATH")
    decision = _run(tmp_path, "git commit -m x", outside, path=path)
    assert _blocked(decision)
    assert "no git repository found" in decision["reason"]


def test_unrelated_command_is_silent(tmp_path: Path, repo: Path):
    assert _run(tmp_path, "ls -la && git status", repo, path=_tool_path(tmp_path, with_gitleaks=False)) is None


def test_hook_is_registered_and_shipped_everywhere():
    settings = json.loads((ROOT / "config" / "settings.template.json").read_text())
    hooks = {
        h["command"]: h
        for group in settings["hooks"]["PreToolUse"]
        if group.get("matcher") == "Bash"
        for h in group["hooks"]
    }
    gate = hooks["~/.claude/scripts/hooks/workflow/secret-scan-gate.sh"]
    # A hook that times out or crashes must block, not wave the command through.
    assert gate.get("onFailure") == "block"
    # One pin for every consumer: the image and CI run the same installer as ./install.
    assert "install-gitleaks.sh" in (ROOT / "containers" / "oakandwave-workflow" / "Dockerfile").read_text()
    assert "install-gitleaks.sh" in (ROOT / ".github" / "workflows" / "validate.yml").read_text()
    assert "install-gitleaks.sh" in (ROOT / "install").read_text()
    deps = json.loads((ROOT / "deps.json").read_text())
    assert any(c["name"] == "gitleaks" and not c.get("optional") for c in deps["commands"])
