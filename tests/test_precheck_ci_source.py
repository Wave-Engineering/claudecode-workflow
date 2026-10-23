"""/precheck Job B's source decision is code, not prose (#1268).

Job B used to wait out `ci_wait_run(timeout_sec: 1800)` and then run the full local
suite whenever CI had nothing for HEAD: every time on GitLab before mcp-server-sdlc#585,
and every time on a repo whose branch pipelines start only on demand.
`precheck-ci-source.sh` decides before any wait: a run exists, one can be started by
the repo's declared `CI on demand` command (exactly once), or the lanes run locally,
with the reason named. `coverage` then refuses a run missing a declared job.

`gh` and `glab` are stubs on PATH. Each logs its argv and answers from files in a
per-test state directory, so every case runs offline.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "precheck-ci-source.sh"
SKILL = ROOT / "skills" / "precheck" / "SKILL.md"

SHA = "0123456789abcdef0123456789abcdef01234567"
BRANCH = "feature/1268-x"

STUB = """#!/bin/sh
echo "$(basename "$0") $*" >>"$STUB_DIR/calls.log"
case "$*" in
*/jobs*) cat "$STUB_DIR/jobs.json"; exit 0 ;;
*"runs?"* | *"pipelines?"*)
	[ -f "$STUB_DIR/api_fail" ] && exit 1
	if [ -f "$STUB_DIR/triggered" ] && [ -f "$STUB_DIR/runs_after.json" ]; then
		cat "$STUB_DIR/runs_after.json"
	else
		cat "$STUB_DIR/runs.json"
	fi
	exit 0 ;;
*"ci run"* | *"workflow run"*)
	touch "$STUB_DIR/triggered"
	[ -f "$STUB_DIR/trigger_fail" ] && exit 1
	exit 0 ;;
esac
exit 3
"""

GH_NO_RUNS = '{"total_count":0,"workflow_runs":[]}'
GH_RUN = '{"total_count":1,"workflow_runs":[{"id":555,"head_branch":"%s"}]}' % BRANCH
GL_NO_RUNS = "[]"
GL_RUN = '[{"id":777,"sha":"%s","ref":"%s"}]' % (SHA, BRANCH)
GL_MR_RUN = '[{"id":778,"sha":"%s","ref":"refs/merge-requests/1/head"}]' % SHA


def _repo(tmp_path: Path, platform: str, *, ci: bool = True, project: str = "") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    url = (
        "git@github.com:Org/proj.git"
        if platform == "github"
        else "git@gitlab.com:group/sub/proj.git"
    )
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)
    if ci and platform == "github":
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / ".github" / "workflows" / "validate.yml").write_text("on: push\n")
    if ci and platform == "gitlab":
        (repo / ".gitlab-ci.yml").write_text("stages: [test]\n")
    if project:
        (repo / ".claude-project.md").write_text("# Project Configuration\n\n## Toolchain\n" + project)
    return repo


def _state(tmp_path: Path, **files: str) -> Path:
    state = tmp_path / "stub"
    state.mkdir(exist_ok=True)
    for name, body in files.items():
        (state / name).write_text(body)
    return state


def _run(repo: Path, state: Path, *args: str, wait: str = "0") -> subprocess.CompletedProcess[str]:
    bindir = state / "bin"
    bindir.mkdir(exist_ok=True)
    for tool in ("gh", "glab"):
        (bindir / tool).write_text(STUB)
        (bindir / tool).chmod(0o755)
    env = {
        "PATH": f"{bindir}:/usr/bin:/bin",
        "HOME": str(state),
        "STUB_DIR": str(state),
        "PRECHECK_CI_TRIGGER_WAIT": wait,
        "PRECHECK_CI_POLL": "1",
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60, env=env
    )


def _resolve(repo: Path, state: Path, branch: str = BRANCH, **kw) -> str:
    proc = _run(repo, state, "resolve", str(repo), str(state / "marker"), branch, SHA, **kw)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    lines = proc.stdout.splitlines()
    assert len(lines) == 1, f"resolve must print exactly one line, got {proc.stdout!r}"
    return lines[0]


def _calls(state: Path) -> list[str]:
    log = state / "calls.log"
    return log.read_text().splitlines() if log.exists() else []


def _triggers(state: Path) -> list[str]:
    return [c for c in _calls(state) if " ci run " in c or " workflow run " in c]


DECLARED_GL = "- **CI on demand:** `glab ci run --branch <branch>`\n"


# --- resolve: the source decision, one case per branch of it ---------------------------


def test_no_ci_config_runs_locally(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "github", ci=False)
    state = _state(tmp_path, **{"runs.json": GH_RUN})
    assert _resolve(repo, state) == "local no-ci"
    assert _calls(state) == [], "with no CI config, CI must not be queried"


def test_github_run_at_head_is_the_source(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "github")
    state = _state(tmp_path, **{"runs.json": GH_RUN})
    assert _resolve(repo, state) == f"ci run=555 ref={BRANCH}"
    assert any(f"repos/Org/proj/actions/runs?head_sha={SHA}" in c for c in _calls(state))
    assert _triggers(state) == []


def test_gitlab_run_at_head_is_read_directly_by_sha(tmp_path: Path) -> None:
    """The direct read #1268 asks for: by SHA (MR pipelines carry a merge-request ref,
    not the branch), against the URL-encoded project path on origin's host."""
    repo = _repo(tmp_path, "gitlab")
    state = _state(tmp_path, **{"runs.json": GL_RUN})
    assert _resolve(repo, state) == f"ci run=777 ref={BRANCH}"
    reads = [c for c in _calls(state) if "pipelines?" in c]
    assert reads == [
        f"glab api --hostname gitlab.com projects/group%2Fsub%2Fproj/pipelines?sha={SHA}&per_page=20"
    ]


def test_gitlab_mr_pipeline_reports_its_own_ref(tmp_path: Path) -> None:
    """Job B-ci waits with the ref printed here. `ci_wait_run` filters by ref AND sha,
    so handing it the branch name would miss an MR pipeline (review finding, #1282)."""
    repo = _repo(tmp_path, "gitlab")
    state = _state(tmp_path, **{"runs.json": GL_MR_RUN})
    assert _resolve(repo, state) == "ci run=778 ref=refs/merge-requests/1/head"


@pytest.mark.parametrize(
    "url, platform, expected",
    [
        ("https://github.com/Org/proj.git", "github", "repos/Org/proj/actions/runs?"),
        ("https://user:tok@github.com/Org/proj", "github", "repos/Org/proj/actions/runs?"),
        ("ssh://git@gitlab.example.com:2222/g/sub/proj.git", "gitlab",
         "--hostname gitlab.example.com projects/g%2Fsub%2Fproj/pipelines?"),
        ("https://gitlab.example.com/g/proj.git", "gitlab",
         "--hostname gitlab.example.com projects/g%2Fproj/pipelines?"),
        ("git@gitlab.example.com:g/sub/proj.git", "gitlab",
         "--hostname gitlab.example.com projects/g%2Fsub%2Fproj/pipelines?"),
    ],
)
def test_origin_url_forms(tmp_path: Path, url: str, platform: str, expected: str) -> None:
    repo = _repo(tmp_path, platform)
    subprocess.run(["git", "-C", str(repo), "remote", "set-url", "origin", url], check=True)
    state = _state(tmp_path, **{"runs.json": GH_RUN if platform == "github" else GL_RUN})
    assert _resolve(repo, state).startswith("ci run=")
    assert any(expected in c for c in _calls(state)), _calls(state)


def test_no_run_declared_triggers_exactly_once(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project=DECLARED_GL)
    state = _state(tmp_path, **{"runs.json": GL_NO_RUNS, "runs_after.json": GL_RUN})
    assert _resolve(repo, state, wait="5") == f"ci triggered run=777 ref={BRANCH}"
    assert _triggers(state) == [f"glab ci run --branch {BRANCH}"]


def test_failed_trigger_is_reported_as_failed_and_not_retried(tmp_path: Path) -> None:
    """Once per SHA holds even when the trigger fails, and the later line keeps its
    exit code instead of claiming it ran (review finding, #1282)."""
    repo = _repo(tmp_path, "gitlab", project=DECLARED_GL)
    state = _state(tmp_path, **{"runs.json": GL_NO_RUNS, "trigger_fail": ""})
    first = _resolve(repo, state)
    second = _resolve(repo, state)
    assert first.startswith("local NO-RUN `CI on demand` exited 1")
    assert "(exit 1)" in second and "already ran once" in second
    assert len(_triggers(state)) == 1


def test_declared_trigger_never_runs_twice_for_one_sha(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project=DECLARED_GL)
    state = _state(tmp_path, **{"runs.json": GL_NO_RUNS})
    first = _resolve(repo, state)
    second = _resolve(repo, state)
    assert first.startswith("local NO-RUN") and "no run for 0123456 appeared" in first
    assert second.startswith("local NO-RUN") and "already ran once" in second
    assert len(_triggers(state)) == 1


def test_no_run_undeclared_never_triggers_and_never_waits(tmp_path: Path) -> None:
    """No declaration, no trigger: a generic trigger can start publish or deploy jobs.
    And no dead wait: the answer comes back at once, with a large wait configured."""
    repo = _repo(tmp_path, "gitlab")
    state = _state(tmp_path, **{"runs.json": GL_NO_RUNS})
    start = time.monotonic()
    line = _resolve(repo, state, wait="600")
    assert time.monotonic() - start < 10
    assert line.startswith("local NO-RUN no run for 0123456")
    assert "CI on demand" in line, "the checklist must say why CI could not answer"
    assert _triggers(state) == []


def test_unreadable_ci_falls_back_locally_with_the_reason(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "github", project="- **CI on demand:** `gh workflow run v.yml --ref <branch>`\n")
    state = _state(tmp_path, **{"runs.json": GH_RUN, "api_fail": ""})
    assert _resolve(repo, state) == "local NO-RUN cannot read CI runs for 0123456"
    assert _triggers(state) == [], "an unreadable CI is not a reason to start a pipeline"


def test_unsafe_branch_name_is_never_substituted(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project=DECLARED_GL)
    state = _state(tmp_path, **{"runs.json": GL_NO_RUNS})
    line = _resolve(repo, state, branch="x;touch pwned")
    assert line.startswith("local NO-RUN branch name unsafe")
    assert _triggers(state) == []


def test_shared_host_local_line_says_book_first(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project="- **Shared host:** lanebox-1\n")
    state = _state(tmp_path, **{"runs.json": GL_NO_RUNS})
    assert _resolve(repo, state).endswith("; shared host: book a slot before running lanes")


# --- coverage: a run missing a declared job is not the lane result -----------------------


def _coverage(repo: Path, state: Path, run_id: str = "777") -> str:
    proc = _run(repo, state, "coverage", str(repo), run_id)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout.strip()


GL_JOBS = '[{"name":"validate","status":"success"},{"name":"test","status":"success"}]'


def test_coverage_without_declared_jobs_is_covered(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab")
    state = _state(tmp_path, **{"jobs.json": GL_JOBS})
    assert _coverage(repo, state) == "covered"
    assert _calls(state) == []


def test_coverage_all_declared_green(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project="- **CI jobs:** validate, test\n")
    state = _state(tmp_path, **{"jobs.json": GL_JOBS})
    assert _coverage(repo, state) == "covered"


def test_coverage_missing_declared_job(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project="- **CI jobs:** validate, test, integration\n")
    state = _state(tmp_path, **{"jobs.json": GL_JOBS})
    assert _coverage(repo, state) == "missing integration"


def test_coverage_declared_job_not_green(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "github", project="- **CI jobs:** `validate`\n")
    jobs = '{"jobs":[{"name":"validate","status":"completed","conclusion":"failure"}]}'
    state = _state(tmp_path, **{"jobs.json": jobs})
    assert _coverage(repo, state, "555") == "not-green validate=failure"


def test_coverage_unreadable_jobs_is_never_covered(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gitlab", project="- **CI jobs:** validate\n")
    state = _state(tmp_path, **{"jobs.json": "not json"})
    assert _coverage(repo, state).startswith("unknown ")


# --- the skill wires it in, and keeps the line Step 5 reads ------------------------------


@pytest.fixture(scope="module")
def skill() -> str:
    return SKILL.read_text()


def test_skill_resolves_the_source_before_waiting(skill: str) -> None:
    assert "precheck-ci-source.sh resolve" in skill or '"$CISRC" resolve' in skill
    assert '"$CISRC" coverage' in skill


def test_skill_waits_with_the_resolved_ref(skill: str) -> None:
    assert 'ci_wait_run({ ref: "<ref>", expected_sha: "<HEAD_SHA>"' in skill
    assert 'ci_wait_run({ ref: "<branch>"' not in skill


def test_lane_line_shape_unchanged(skill: str) -> None:
    """Step 5's autochain path reads this exact shape."""
    assert "LANE ci:<workflow_name> | exit=<0 if final_status is success, else 1> | run=<run_id> sha=<sha>" in skill
