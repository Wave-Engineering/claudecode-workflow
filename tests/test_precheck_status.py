"""scripts/precheck-status.sh: the `precheck` commit status the MR gate posts and reads (#1235).

Driven for real against a throwaway git repo, with `gh` and `glab` replaced by a fake
that keeps statuses in a JSON file and logs every call. The fake answers only the
endpoints the script is meant to use, so a wrong path fails loudly instead of passing.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "precheck-status.sh"

FAKE = r'''#!/usr/bin/env python3
import json, os, re, sys
tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([tool] + args) + "\n")
if os.environ.get("FAKE_FAIL") == "1":
    sys.exit(1)
path = os.environ["FAKE_STATE"]
state = json.load(open(path)) if os.path.exists(path) else {"next": 1, "s": {}}
assert args[0] == "api", args
args = args[1:]
if tool == "glab":
    assert args[:2] == ["--hostname", os.environ["FAKE_HOST"]], args
    args = args[2:]
method, fields, rest = "GET", {}, []
i = 0
while i < len(args):
    if args[i] == "-X":
        method = args[i + 1]; i += 2
    elif args[i] == "-f":
        k, v = args[i + 1].split("=", 1); fields[k] = v; i += 2
    else:
        rest.append(args[i]); i += 1
(endpoint,) = rest
def save():
    json.dump(state, open(path, "w"))
prs = json.loads(os.environ.get("FAKE_PRS", "{}"))  # {"<n>": {"sha":..., "ref":...}}
branches = {v["ref"]: v["sha"] for v in prs.values()}  # a PR's head branch is pushed
branches.update(json.loads(os.environ.get("FAKE_BRANCHES", "{}")))
if tool == "glab" and os.environ.get("FAKE_GLAB_ERROR_BODY") == "1":
    print(json.dumps({"message": "500 Internal Server Error"})); sys.exit(0)  # glab exits 0 on HTTP errors
def gl_title(n, pr):
    return state.get("titles", {}).get(n, pr.get("title", "Draft: x"))
def gl_mr(n, pr):
    t = gl_title(n, pr)
    draft = bool(re.match(r"\s*(\[draft\]|\(draft\)|draft:)", t, re.I))  # GitLab's own rule; WIP: no longer counts
    mr = {"iid": int(n), "sha": pr["sha"], "source_branch": pr["ref"], "target_branch": pr.get("base", "main"), "title": t, "draft": draft}
    hp = os.environ.get("FAKE_HEAD_PIPELINE")
    if state["s"] and os.environ.get("FAKE_HEAD_PIPELINE_AFTER_POST"):
        hp = os.environ["FAKE_HEAD_PIPELINE_AFTER_POST"]  # what GitLab shows once a status was posted
    if hp:
        mr["head_pipeline"] = {"id": int(hp)}
    return mr
if tool == "gh" and endpoint == "graphql":
    assert "markPullRequestReadyForReview" in fields["query"], fields
    state.setdefault("ready", {})[fields["id"].removeprefix("PR_")] = True
    save()
    print(json.dumps({"data": {"markPullRequestReadyForReview": {"pullRequest": {"isDraft": False}}}})); sys.exit(0)
if tool == "gh" and method == "GET":
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/pulls/([0-9]+)", endpoint)
    if m:
        pr = prs.get(m.group(2))
        if not pr:
            sys.exit(1)  # gh exits non-zero on a 404
        draft = pr.get("draft", True) and not state.get("ready", {}).get(m.group(2))
        print(json.dumps({"number": int(m.group(2)), "node_id": "PR_" + m.group(2), "draft": draft, "head": {"sha": pr["sha"], "ref": pr["ref"]}, "base": {"ref": pr.get("base", "main")}})); sys.exit(0)
    m = re.fullmatch(r"repos/([^/]+)/([^/]+)/pulls\?state=open&head=([^:]+):(.+)", endpoint)
    if m:
        assert m.group(3) == m.group(1), "head= must be qualified with the repo owner"
        print(json.dumps([{"head": {"sha": v["sha"], "ref": v["ref"]}, "base": {"ref": v.get("base", "main")}} for v in prs.values() if v["ref"] == m.group(4)])); sys.exit(0)
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/git/ref/heads/(.+)", endpoint)
    if m:
        if m.group(2) not in branches:
            sys.exit(1)  # gh exits non-zero on a 404
        print(json.dumps({"ref": "refs/heads/" + m.group(2), "object": {"sha": branches[m.group(2)]}})); sys.exit(0)
if tool == "glab" and method == "GET":
    m = re.fullmatch(r"projects/([^/]+)/repository/branches/([^/]+)", endpoint)
    if m:
        from urllib.parse import unquote
        b = unquote(m.group(2))
        if b not in branches:
            print(json.dumps({"message": "404 Branch Not Found"})); sys.exit(0)
        print(json.dumps({"name": b, "commit": {"id": branches[b]}})); sys.exit(0)
    m = re.fullmatch(r"projects/([^/]+)/merge_requests/([0-9]+)", endpoint)
    if m:
        pr = prs.get(m.group(2))
        if not pr:
            print(json.dumps({"message": "404 Not found"})); sys.exit(0)
        print(json.dumps(gl_mr(m.group(2), pr))); sys.exit(0)
    m = re.fullmatch(r"projects/([^/]+)/repository/commits/([0-9a-f]{40})/merge_requests", endpoint)
    if m:
        if os.environ.get("FAKE_COMMIT_MRS_ERROR") == "1":
            print(json.dumps({"message": "500 Internal Server Error"})); sys.exit(0)
        print(os.environ.get("FAKE_COMMIT_MRS", "[]")); sys.exit(0)
    m = re.fullmatch(r"projects/([^/]+)/merge_requests\?state=opened&source_branch=(.+)", endpoint)
    if m:
        from urllib.parse import unquote
        b = unquote(m.group(2))
        print(json.dumps([{"sha": v["sha"], "source_branch": v["ref"], "target_branch": v.get("base", "main")} for v in prs.values() if v["ref"] == b])); sys.exit(0)
if tool == "glab" and method == "PUT":
    m = re.fullmatch(r"projects/([^/]+)/merge_requests/([0-9]+)", endpoint)
    if m and m.group(2) in prs:
        if os.environ.get("FAKE_IGNORE_PUT") != "1":
            state.setdefault("titles", {})[m.group(2)] = fields["title"]
            save()
        print(json.dumps(gl_mr(m.group(2), prs[m.group(2)]))); sys.exit(0)
if tool == "gh":
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/statuses/([0-9a-f]{40})", endpoint)
    if method == "POST" and m:
        if os.environ.get("FAKE_DROP_POST") != "1":
            state["s"].setdefault(m.group(2), []).append({"context": fields["context"], "state": fields["state"], "description": fields["description"]})
            save()
        print("{}"); sys.exit(0)
    m = re.fullmatch(r"repos/([^/]+/[^/]+)/commits/([0-9a-f]{40})/status", endpoint)
    if method == "GET" and m:
        latest = {}
        for s in state["s"].get(m.group(2), []):
            latest[s["context"]] = s
        print(json.dumps({"statuses": list(latest.values())[::-1]})); sys.exit(0)
else:
    m = re.fullmatch(r"projects/([^/]+)/pipelines\?sha=([0-9a-f]{40})&order_by=id&sort=desc&per_page=1", endpoint)
    if method == "GET" and m:
        if os.environ.get("FAKE_PIPELINE_FAIL") == "1":
            print(json.dumps({"message": "500 Internal Server Error"})); sys.exit(0)
        pid = os.environ.get("FAKE_PIPELINE")
        print(json.dumps([{"id": int(pid)}] if pid else [])); sys.exit(0)
    m = re.fullmatch(r"projects/([^/]+)/statuses/([0-9a-f]{40})", endpoint)
    if method == "POST" and m:
        n = state["next"]; state["next"] = n + 1
        state["s"].setdefault(m.group(2), []).append({"id": n, "name": fields["name"], "status": fields["state"], "pipeline_id": fields.get("pipeline_id")})
        save(); print("{}"); sys.exit(0)
    m = re.fullmatch(r"projects/([^/]+)/repository/commits/([0-9a-f]{40})/statuses\?name=precheck&all=true&per_page=100", endpoint)
    if method == "GET" and m:
        print(json.dumps([s for s in state["s"].get(m.group(2), []) if s["name"] == "precheck"])); sys.exit(0)
print("fake: unexpected call", tool, method, endpoint, file=sys.stderr)
sys.exit(97)
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def world(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("gh", "glab"):
        p = bin_dir / tool
        p.write_text(FAKE)
        p.chmod(0o755)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature/1-x")
    shas = []
    for i in range(3):
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"c{i}")
        shas.append(_git(repo, "rev-parse", "HEAD"))
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_STATE": str(tmp_path / "state.json"),
        "FAKE_HOST": "gitlab.example.com",
    }
    return repo, env, shas, tmp_path


def _run(env: dict, *args: str, **extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], env={**env, **extra}, capture_output=True, text=True, timeout=60)


def _calls(tmp: Path) -> list[list[str]]:
    log = tmp / "calls.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _github(repo: Path) -> None:
    _git(repo, "remote", "add", "origin", "git@github.com:Owner/Repo.git")
    # A fork's `upstream` must never be the target (bare gh resolves it first).
    _git(repo, "remote", "add", "upstream", "https://github.com/Third/Party.git")


def _gitlab(repo: Path) -> None:
    _git(repo, "remote", "add", "origin", "https://gitlab.example.com/group/sub/proj.git")


def test_github_post_then_get_reads_success_on_origin(world):
    repo, env, shas, tmp = world
    _github(repo)
    r = _run(env, "post", str(repo), shas[-1], "#1 review full clean; lanes ci")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == f"success {shas[-1]}"
    assert _run(env, "get", str(repo), shas[-1]).stdout.strip() == "success"
    endpoints = [c[-1] if c[2] != "-X" else c[4] for c in _calls(tmp)]
    assert f"repos/Owner/Repo/statuses/{shas[-1]}" in endpoints
    assert all("Third/Party" not in " ".join(c) for c in _calls(tmp))


def test_get_without_a_status_is_none(world):
    repo, env, shas, _ = world
    _github(repo)
    r = _run(env, "get", str(repo), shas[0])
    assert (r.returncode, r.stdout.strip()) == (0, "none")


def test_api_failure_is_exit_3_never_a_state(world):
    repo, env, shas, _ = world
    _github(repo)
    r = _run(env, "get", str(repo), shas[0], FAKE_FAIL="1")
    assert r.returncode == 3
    assert r.stdout.strip() == ""


def test_post_that_does_not_read_back_fails(world):
    repo, env, shas, _ = world
    _github(repo)
    r = _run(env, "post", str(repo), shas[0], "x", FAKE_DROP_POST="1")
    assert r.returncode == 3
    assert "reads back 'none'" in r.stderr


def test_description_is_one_line_and_cut_at_140(world):
    repo, env, shas, tmp = world
    _github(repo)
    assert _run(env, "post", str(repo), shas[0], "a\nb" + "x" * 300).returncode == 0
    desc = json.loads((tmp / "state.json").read_text())["s"][shas[0]][0]["description"]
    assert desc.startswith("a b") and len(desc) == 140


def test_last_success_finds_the_newest_marked_commit(world):
    repo, env, shas, _ = world
    _github(repo)
    assert _run(env, "last-success", str(repo), "main").stdout.strip() == "none"
    _run(env, "post", str(repo), shas[0], "first")
    _run(env, "post", str(repo), shas[1], "second")
    r = _run(env, "last-success", str(repo), "main")
    assert (r.returncode, r.stdout.strip()) == (0, shas[1])


def test_last_success_api_failure_is_not_a_quiet_none(world):
    repo, env, _, _ = world
    _github(repo)
    r = _run(env, "last-success", str(repo), "main", FAKE_FAIL="1")
    assert r.returncode == 3
    assert "none" not in r.stdout


def test_last_success_reads_the_remote_base(world):
    repo, env, shas, _ = world
    _github(repo)
    # origin/main has moved on: shas[0..1] landed from another PR, which carried a pass.
    # The local main is stale, then gone. Neither may lend this branch that pass.
    _git(repo, "update-ref", "refs/remotes/origin/main", shas[1])
    _run(env, "post", str(repo), shas[0], "another PR's pass")
    r = _run(env, "last-success", str(repo), "main")
    assert (r.returncode, r.stdout.strip()) == (0, "none"), r.stderr
    _git(repo, "branch", "-D", "main")
    r = _run(env, "last-success", str(repo), "main")
    assert (r.returncode, r.stdout.strip()) == (0, "none"), r.stderr


def test_gitlab_post_fails_when_the_pipeline_lookup_fails(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    r = _run(env, "post", str(repo), shas[0], "ok", FAKE_PIPELINE_FAIL="1")
    assert r.returncode == 3
    assert not (tmp / "state.json").exists(), "a bare post is the external pipeline that hides CI"


def test_gitlab_post_attaches_to_the_existing_pipeline(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    r = _run(env, "post", str(repo), shas[-1], "ok", FAKE_PIPELINE="77")
    assert r.returncode == 0, r.stderr
    st = json.loads((tmp / "state.json").read_text())["s"][shas[-1]]
    assert st[0]["pipeline_id"] == "77"
    assert any(f"projects/group%2Fsub%2Fproj/statuses/{shas[-1]}" in c for c in _calls(tmp))


def test_gitlab_post_without_a_pipeline_is_bare(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    assert _run(env, "post", str(repo), shas[0], "ok").returncode == 0
    assert json.loads((tmp / "state.json").read_text())["s"][shas[0]][0]["pipeline_id"] is None


# #1357: a merged-results MR's head has no pipeline (its pipelines run on an ephemeral merge
# commit), so the post is bare by necessity, and each open MR's head_pipeline is guarded.
def _merged_results_mr(shas: list[str]) -> dict[str, str]:
    prs = json.dumps({"3": {"sha": shas[-1], "ref": "feature/1-x"}})
    mrs = json.dumps([
        {"iid": 3, "state": "opened", "sha": shas[-1]},
        {"iid": 2, "state": "merged", "sha": shas[-1]},  # never read: not open
        {"iid": 4, "state": "opened", "sha": shas[0]},  # never read: an older head
    ])
    return {"FAKE_PRS": prs, "FAKE_COMMIT_MRS": mrs, "FAKE_HEAD_PIPELINE": "2983401888"}


def test_gitlab_merged_results_post_stays_on_head(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    extra = _merged_results_mr(shas)
    r = _run(env, "post", str(repo), shas[-1], "ok", **extra)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp / "state.json").read_text())["s"][shas[-1]][0]["pipeline_id"] is None
    reads = [c for c in _calls(tmp) if c[-1] == "projects/group%2Fsub%2Fproj/merge_requests/3"]
    assert len(reads) == 2, "head_pipeline is read before and after the post"
    assert not any(c[-1].endswith(("merge_requests/2", "merge_requests/4")) for c in _calls(tmp))
    # The readers agree: pr-head names the head, and get reads the pass on it.
    head = _run(env, "pr-head", str(repo), "3", **extra).stdout.split()[0]
    assert head == shas[-1]
    assert _run(env, "get", str(repo), head).stdout.strip() == "success"


def test_gitlab_post_fails_when_head_pipeline_moves(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    extra = {**_merged_results_mr(shas), "FAKE_HEAD_PIPELINE_AFTER_POST": "2983506881"}
    r = _run(env, "post", str(repo), shas[-1], "ok", **extra)
    assert r.returncode == 3
    assert "MR !3's head_pipeline moved from 2983401888 to 2983506881" in r.stderr
    assert "hides its CI verdict" in r.stderr


def test_gitlab_post_mr_lookup_failure_posts_nothing(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    r = _run(env, "post", str(repo), shas[-1], "ok", **_merged_results_mr(shas), FAKE_COMMIT_MRS_ERROR="1")
    assert r.returncode == 3
    assert f"list MRs of {shas[-1]}" in r.stderr
    assert not (tmp / "state.json").exists(), "no status is written when the guard cannot read"


def test_gitlab_post_with_a_pipeline_skips_the_guard(world):
    repo, env, shas, tmp = world
    _gitlab(repo)
    r = _run(env, "post", str(repo), shas[-1], "ok", FAKE_PIPELINE="77", **_merged_results_mr(shas))
    assert r.returncode == 0, r.stderr
    assert not any("merge_requests" in c[-1] for c in _calls(tmp))


@pytest.mark.parametrize(("status", "want"), [("failed", "failure"), ("running", "pending"), ("canceled", "failure")])
def test_gitlab_latest_status_wins_and_is_normalised(world, status, want):
    repo, env, shas, tmp = world
    _gitlab(repo)
    _run(env, "post", str(repo), shas[0], "ok")
    state = json.loads((tmp / "state.json").read_text())
    state["s"][shas[0]].append({"id": 99, "name": "precheck", "status": status, "pipeline_id": None})
    (tmp / "state.json").write_text(json.dumps(state))
    assert _run(env, "get", str(repo), shas[0]).stdout.strip() == want


def test_unknown_platform_refuses(world):
    repo, env, shas, _ = world
    _git(repo, "remote", "add", "origin", "https://example.invalid/a/b.git")
    r = _run(env, "get", str(repo), shas[0])
    assert r.returncode == 2
    assert "PRECHECK_PLATFORM" in r.stderr


def test_pr_head_by_number_url_and_branch_github(world):
    repo, env, shas, _ = world
    _github(repo)
    prs = json.dumps({"12": {"sha": shas[1], "ref": "feature/1-x"}})
    for sel in ("12", "https://github.com/Owner/Repo/pull/12", "feature/1-x"):
        r = _run(env, "pr-head", str(repo), sel, FAKE_PRS=prs)
        assert (r.returncode, r.stdout.strip()) == (0, f"{shas[1]} feature/1-x main"), (sel, r.stderr)
    # No selector: the open PR from the current branch.
    assert _run(env, "pr-head", str(repo), FAKE_PRS=prs).stdout.strip() == f"{shas[1]} feature/1-x main"


def test_pr_head_unknown_pr_is_exit_3(world):
    repo, env, _, _ = world
    _github(repo)
    assert _run(env, "pr-head", str(repo), "999").returncode == 3
    assert _run(env, "pr-head", str(repo), "no-such-branch").returncode == 3


def test_pr_head_gitlab_and_its_404_body(world):
    repo, env, shas, _ = world
    _gitlab(repo)
    prs = json.dumps({"7": {"sha": shas[0], "ref": "feature/1-x"}})
    r = _run(env, "pr-head", str(repo), "https://gitlab.example.com/group/sub/proj/-/merge_requests/7", FAKE_PRS=prs)
    assert r.stdout.strip() == f"{shas[0]} feature/1-x main", r.stderr
    # glab prints a 404 body and exits 0; that must not read as a head.
    assert _run(env, "pr-head", str(repo), "8", FAKE_PRS=prs).returncode == 3


@pytest.mark.parametrize("forge", ["github", "gitlab"])
def test_branch_head_is_the_platforms_answer(world, forge):
    repo, env, shas, _ = world
    (_github if forge == "github" else _gitlab)(repo)
    branches = json.dumps({"feature/1-x": shas[0]})  # local HEAD is shas[-1]; the platform says shas[0]
    r = _run(env, "branch-head", str(repo), "feature/1-x", FAKE_BRANCHES=branches)
    assert (r.returncode, r.stdout.strip()) == (0, shas[0]), r.stderr
    # Never pushed: gh exits non-zero, glab prints a 404 body and exits 0. Both are exit 3.
    assert _run(env, "branch-head", str(repo), "feature/2-never").returncode == 3


@pytest.mark.parametrize("forge", ["github", "gitlab"])
def test_mark_ready_refuses_a_head_without_a_pass(world, forge):
    repo, env, shas, tmp = world
    (_github if forge == "github" else _gitlab)(repo)
    prs = json.dumps({"12": {"sha": shas[-1], "ref": "feature/1-x"}})
    _run(env, "post", str(repo), shas[0], "an older commit's pass")  # not the head
    r = _run(env, "mark-ready", str(repo), "12", FAKE_PRS=prs)
    assert r.returncode == 4, r.stderr
    assert not any(c[1:3] == ["api", "graphql"] or "PUT" in c for c in _calls(tmp)), "refused, so nothing may be written"


def test_mark_ready_github_uses_the_graphql_mutation_and_reads_back(world):
    repo, env, shas, tmp = world
    _github(repo)
    prs = json.dumps({"12": {"sha": shas[-1], "ref": "feature/1-x"}})
    _run(env, "post", str(repo), shas[-1], "ok")
    r = _run(env, "mark-ready", str(repo), "12", FAKE_PRS=prs)
    assert (r.returncode, r.stdout.strip()) == (0, f"ready 12 {shas[-1]}"), r.stderr
    assert any(c[:3] == ["gh", "api", "graphql"] for c in _calls(tmp))
    # Already ready: no second mutation, still ready.
    n = sum(c[:3] == ["gh", "api", "graphql"] for c in _calls(tmp))
    assert _run(env, "mark-ready", str(repo), "12", FAKE_PRS=prs).returncode == 0
    assert sum(c[:3] == ["gh", "api", "graphql"] for c in _calls(tmp)) == n


@pytest.mark.parametrize(
    ("title", "want"),
    [("Draft: fix(x): y", "fix(x): y"), ("[Draft] fix", "fix"), ("(draft) draft: fix", "fix"), ("DRAFT:fix", "fix")],
)
def test_mark_ready_gitlab_strips_every_draft_prefix(world, title, want):
    repo, env, shas, tmp = world
    _gitlab(repo)
    prs = json.dumps({"5": {"sha": shas[-1], "ref": "feature/1-x", "title": title}})
    _run(env, "post", str(repo), shas[-1], "ok")
    r = _run(env, "mark-ready", str(repo), "5", FAKE_PRS=prs)
    assert r.returncode == 0, r.stderr
    assert json.loads((tmp / "state.json").read_text())["titles"]["5"] == want


def test_mark_ready_gitlab_fails_closed(world):
    repo, env, shas, _ = world
    _gitlab(repo)
    _run(env, "post", str(repo), shas[-1], "ok")
    # A title that is nothing but a draft prefix has no ready form.
    only = json.dumps({"5": {"sha": shas[-1], "ref": "feature/1-x", "title": "Draft: [Draft]"}})
    assert _run(env, "mark-ready", str(repo), "5", FAKE_PRS=only).returncode == 3
    # The platform accepted the PUT but the MR still reads draft: verify the post-state.
    prs = json.dumps({"5": {"sha": shas[-1], "ref": "feature/1-x"}})
    assert _run(env, "mark-ready", str(repo), "5", FAKE_PRS=prs, FAKE_IGNORE_PUT="1").returncode == 3


def test_gitlab_error_body_never_reads_as_a_state(world):
    repo, env, shas, _ = world
    _gitlab(repo)
    r = _run(env, "get", str(repo), shas[0], FAKE_GLAB_ERROR_BODY="1")
    assert r.returncode == 3
    assert r.stdout.strip() == ""


def test_slug_override_needs_no_local_repo_or_object(world, tmp_path):
    _, env, _, tmp = world
    elsewhere = tmp_path / "not-a-repo"
    elsewhere.mkdir()
    foreign = "a" * 40  # a commit this clone has never seen
    state = {"next": 1, "s": {foreign: [{"context": "precheck", "state": "success", "description": "x"}]}}
    (tmp / "state.json").write_text(json.dumps(state))
    r = _run(env, "get", str(elsewhere), foreign, PRECHECK_SLUG="Other/Repo", PRECHECK_PLATFORM="github")
    assert (r.returncode, r.stdout.strip()) == (0, "success"), r.stderr
    assert any("repos/Other/Repo/commits/" in " ".join(c) for c in _calls(tmp))
