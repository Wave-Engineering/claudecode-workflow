"""scripts/precheck-ac-gate.sh: the mechanical AC gate and the post-merge lint (#1365).

`lint` and `boxes` run on files. `pr` runs against a throwaway git repo whose origin names
the platform, with `gh` and `glab` replaced by a fake that answers only the endpoints the
script is meant to use, so a wrong path fails loudly instead of passing.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "precheck-ac-gate.sh"

FAKE = r'''#!/usr/bin/env python3
import json, os, re, sys
tool = os.path.basename(sys.argv[0])
args = sys.argv[1:]
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([tool] + args) + "\n")
if os.environ.get("FAKE_FAIL") == "1":
    sys.exit(1)
assert args[0] == "api", args
args = args[1:]
if tool == "glab":
    assert args[:2] == ["--hostname", os.environ["FAKE_HOST"]], args
    args = args[2:]
    if os.environ.get("FAKE_GLAB_ERROR_BODY") == "1":
        print(json.dumps({"message": "500 Internal Server Error"})); sys.exit(0)  # glab exits 0 on HTTP errors
fields, rest, i = {}, [], 0
while i < len(args):
    if args[i] in ("-f", "-F"):
        k, v = args[i + 1].split("=", 1); fields[k] = v; i += 2
    else:
        rest.append(args[i]); i += 1
(endpoint,) = rest
issues = json.loads(os.environ.get("FAKE_ISSUES", "{}"))  # {"<n>": "<body>"}
closing = json.loads(os.environ.get("FAKE_CLOSING", "[]"))  # [{"number", "body", "repo"}]
pr_body = os.environ.get("FAKE_PR_BODY", "")
if tool == "gh" and endpoint == "graphql":
    assert "closingIssuesReferences" in fields["query"], fields
    assert (fields["o"], fields["n"]) == ("Owner", "Repo"), fields
    own = os.environ.get("FAKE_REPO_NAME", "Owner/Repo")  # the repository's own name, after a rename
    nodes = [{"number": c["number"], "body": c["body"], "repository": {"nameWithOwner": c.get("repo", own)}} for c in closing]
    total = int(os.environ.get("FAKE_TOTAL", len(nodes)))
    print(json.dumps({"data": {"repository": {"nameWithOwner": own, "pullRequest": {"body": pr_body,
          "closingIssuesReferences": {"totalCount": total, "nodes": nodes}}}}})); sys.exit(0)
if tool == "gh":
    m = re.fullmatch(r"repos/Owner/Repo/issues/([0-9]+)", endpoint)
    prs = json.loads(os.environ.get("FAKE_PRS", "[]"))  # numbers that are PRs, which /issues answers too
    if m and int(m.group(1)) in prs:
        print(json.dumps({"number": int(m.group(1)), "body": "", "pull_request": {"url": "x"}})); sys.exit(0)
    if m and m.group(1) in issues:
        print(json.dumps({"number": int(m.group(1)), "body": issues[m.group(1)]})); sys.exit(0)
    if m:
        sys.exit(1)  # gh exits non-zero on a 404
if tool == "glab":
    p = "projects/group%2Fproj/"
    if endpoint == p + "merge_requests/7":
        print(json.dumps({"iid": 7, "project_id": 11, "description": pr_body})); sys.exit(0)
    if endpoint == p + "merge_requests/7/closes_issues?per_page=100":
        print(json.dumps([{"iid": c["number"], "project_id": c.get("project_id", 11), "description": c["body"],
                           **({"references": {"full": c["full"]}} if "full" in c else {})} for c in closing])); sys.exit(0)
    m = re.fullmatch(re.escape(p) + r"issues/([0-9]+)", endpoint)
    if m and m.group(1) in issues:
        print(json.dumps({"iid": int(m.group(1)), "project_id": 11, "description": issues[m.group(1)]})); sys.exit(0)
    if m:
        print(json.dumps({"message": "404 Not found"})); sys.exit(0)
    m = re.fullmatch(r"projects/group%2Fother/issues/([0-9]+)", endpoint)
    foreign = json.loads(os.environ.get("FAKE_FOREIGN", "{}"))  # group/other's issues
    if m and m.group(1) in foreign:
        print(json.dumps({"iid": int(m.group(1)), "project_id": 22, "description": foreign[m.group(1)]})); sys.exit(0)
print("fake: unexpected call", tool, endpoint, file=sys.stderr)
sys.exit(97)
'''

ISSUE_DONE = "## Summary\n\nx\n\n## Acceptance Criteria\n\n- [x] one\n- [X] two\n\n## Dependencies\n\n- [ ] not AC\n"
WAIVER = "WAIVED by BJ 2026-10-24: post-merge criteria are waived (https://example.invalid/i/1#c-2)"


def _run(*args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60)


def _file(tmp: Path, body: str, name: str = "body.md") -> str:
    p = tmp / name
    p.write_text(body)
    return str(p)


def _ac(*lines: str) -> str:
    return "## Acceptance Criteria\n\n" + "\n".join(lines) + "\n"


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
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "FAKE_LOG": str(tmp_path / "calls.log"),
        "FAKE_HOST": "gitlab.example.com",
    }
    return repo, env, tmp_path


def _origin(repo: Path, url: str) -> None:
    subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", url], check=True)


def _pr(world, issues: dict, pr_body: str = "", closing: list | None = None, issue_n: str = "5", **extra: str):
    repo, env, _ = world
    _origin(repo, "git@github.com:Owner/Repo.git")
    e = {**env, "FAKE_ISSUES": json.dumps(issues), "FAKE_PR_BODY": pr_body,
         "FAKE_CLOSING": json.dumps(closing or []), **extra}
    return _run("pr", str(repo), "9", issue_n, env=e)


# --- boxes ---------------------------------------------------------------------------


def test_all_checked_passes(world):
    r = _pr(world, {"5": ISSUE_DONE}, pr_body="## Summary\n\nno boxes here\n")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: Owner/Repo#5 | boxes=2 checked=2 waived=0 unchecked=0 post-merge=0" in r.stdout
    assert "ac-gate: PR Owner/Repo#9 | boxes=0" in r.stdout
    assert r.stdout.rstrip().endswith("VERDICT: PASS")


def test_unchecked_box_fails_naming_it(tmp_path):
    body = _ac("- [x] one", "- [ ] two is not done")
    r = _run("boxes", "issue#1", _file(tmp_path, body))
    assert r.returncode == 1
    assert "  [unchecked] issue#1:4 two is not done" in r.stdout
    assert "VERDICT: FAIL" in r.stdout


def test_valid_waiver_passes_and_is_listed(tmp_path):
    body = _ac("- [x] one", f"- [ ] fleet shows the banner — {WAIVER}")
    r = _run("boxes", "issue#1", _file(tmp_path, body), "--section", "Acceptance Criteria")
    assert r.returncode == 0, r.stdout
    assert "boxes=2 checked=1 waived=1 unchecked=0" in r.stdout
    assert "  [waived] issue#1:4 BJ 2026-10-24 https://example.invalid/i/1#c-2" in r.stdout


_FUTURE = (datetime.datetime.now(datetime.timezone.utc).date() + datetime.timedelta(days=2)).isoformat()


@pytest.mark.parametrize("tail", [
    "WAIVED by babelfish 2026-10-24: r (https://x.invalid/y)",
    "WAIVED by BJ 2026-10-24: r",
    "WAIVED by BJ 2026-13-01: r (https://x.invalid/y)",
    f"WAIVED by BJ {_FUTURE}: r (https://x.invalid/y)",
], ids=["another-approver", "no-url", "bad-date", "future-date"])
def test_invalid_waivers_count_as_unchecked(tmp_path, tail):
    r = _run("boxes", "issue#1", _file(tmp_path, _ac(f"- [ ] thing — {tail}")))
    assert r.returncode == 1, r.stdout
    assert "[unchecked]" in r.stdout and "[waived]" not in r.stdout


def test_boxes_in_code_fences_are_ignored(tmp_path):
    # A shorter fence, or one with an info string, never closes the open one.
    body = _ac("- [x] real", "", "````markdown", "- [ ] quoted template line", "```", "- [ ] still fenced",
               "```python", "- [ ] still fenced too", "````", "", "~~~", "- [ ] tilde fenced", "~~~")
    r = _run("boxes", "issue#1", _file(tmp_path, body))
    assert r.returncode == 0, r.stdout
    assert "boxes=1 checked=1" in r.stdout


def test_issue_with_no_ac_box_fails(tmp_path):
    body = "## Acceptance Criteria\n\nIt works, trust me.\n\n## Notes\n\n- [x] elsewhere\n"
    r = _run("boxes", "issue#1", _file(tmp_path, body))
    assert r.returncode == 1
    assert "boxes=0" in r.stdout and "no AC checkbox" in r.stdout


def test_pr_body_unchecked_box_fails(world):
    r = _pr(world, {"5": ISSUE_DONE}, pr_body="## Test Plan\n\n- [x] unit\n- [ ] the lane nobody ran\n")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "  [unchecked] PR Owner/Repo#9:4 the lane nobody ran" in r.stdout


def test_every_closing_issue_is_graded(world):
    closing = [
        {"number": 5, "body": ISSUE_DONE},  # ISSUE_N again: graded once
        {"number": 6, "body": _ac("- [x] a")},
        {"number": 8, "body": _ac("- [x] a", "- [ ] b is open")},
    ]
    r = _pr(world, {"5": ISSUE_DONE}, closing=closing)
    assert r.returncode == 1, r.stdout + r.stderr
    assert r.stdout.count("ac-gate: Owner/Repo#5 |") == 1
    assert "ac-gate: Owner/Repo#6 |" in r.stdout
    assert "  [unchecked] Owner/Repo#8:4 b is open" in r.stdout


# --- lint ----------------------------------------------------------------------------


@pytest.mark.parametrize("pid,line", [
    ("P1", "the banner shows post-install"),
    ("P2", "the fleet reports it after the release"),
    ("P3", "All story PRs merged clean into main"),
    ("P4", "CI is green on main"),
    ("P5", "v2.0 is tagged and the image pushed"),
    ("P5", "the release is tagged"),
    ("P5", "1.4.0 gets tagged"),
    ("P5", "the commit is tagged v1.4.0"),
    ("P5", "it is tagged as 2.1"),
    ("P5", "the image is tagged :stable"),
    ("P5", "the commit is tagged `v1.4.0`"),
    ("P5", "the release will be tagged"),
    ("P5", "the rc is tagged"),
    ("P5", "a tagged release exists"),
    ("P5", "v2 is tagged"),
    ("P5", "the release is then tagged"),
    ("P5", "it is tagged \"v1.4\""),
    ("P5", "the fix is released"),
    ("P5", "the service is deployed"),
    ("P6", "the new path is observed live"),
])
@pytest.mark.parametrize("box", ["[ ]", "[x]"])
def test_each_post_merge_pattern_flags(tmp_path, pid, line, box):
    r = _run("lint", _file(tmp_path, f"- {box} {line}\n"))
    assert r.returncode == 2, r.stdout
    assert f"[post-merge] {tmp_path / 'body.md'}:1 {pid}: {line}" in r.stdout


@pytest.mark.parametrize("line", [
    "the merge-result predicate is read",
    "pr_merge refuses a stale head",
    "a pre-merge review runs",
    "the mergeable state is checked",
    "a merge commit is never pushed",
    # #1389: a tagged channel is not a release tag
    "a public channel is tagged that neither the broker nor the bot is in",
    "A mint adds the new bot to tagged channels as well as `default_channels`",
    "the unreachable-tagged-channel WARNING is logged",
    "tagged 403: one POST, one WARNING naming it",
])
def test_pre_merge_phrases_do_not_flag(tmp_path, line):
    r = _run("lint", _file(tmp_path, f"- [ ] {line}\n"))
    assert r.returncode == 0, r.stdout


def test_override_marker_passes_and_is_listed(tmp_path):
    line = "the merged-results pipeline is read <!-- ac-gate: pre-merge -->"
    r = _run("lint", _file(tmp_path, f"- [ ] {line}\n"))
    assert r.returncode == 0, r.stdout
    assert f"[override] {tmp_path / 'body.md'}:1 {line}" in r.stdout


def test_waived_post_merge_line_passes_the_lint(tmp_path):
    r = _run("lint", _file(tmp_path, f"- [ ] All story PRs merged clean — {WAIVER}\n"))
    assert r.returncode == 0, r.stdout
    assert "[waived]" in r.stdout


@pytest.mark.parametrize("body", [f"- [ ] x — {WAIVER}\n", _ac(f"- [ ] x — {WAIVER}")], ids=["no-heading", "under-ac"])
def test_lint_lists_every_waiver(tmp_path, body):
    r = _run("lint", _file(tmp_path, body))
    assert r.returncode == 0, r.stdout
    assert r.stdout.count("[waived]") == 1


def test_waiver_outside_ac_is_still_listed_in_pr_mode(world):
    """#1373 review: a waived DoD line in a closing issue is not graded, but its waiver
    still reaches the checklist, because the script checks only its form."""
    body = _ac("- [x] a") + f"\n## Definition of Done\n\n- [ ] All story PRs merged clean — {WAIVER}\n"
    r = _pr(world, {"5": body})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "  [waived] Owner/Repo#5:7 BJ 2026-10-24 https://example.invalid/i/1#c-2" in r.stdout
    assert "boxes=1 checked=1 waived=0" in r.stdout, "the DoD box is listed, not graded"


def test_lint_reads_every_box_not_only_ac(tmp_path):
    r = _run("lint", _file(tmp_path, "## Definition of Done\n\n- [ ] Kahuna→main MR merged clean\n"))
    assert r.returncode == 2, r.stdout


# --- precedence and failures ----------------------------------------------------------


def test_exit_precedence(world, tmp_path):
    r = _run("boxes", "x", _file(tmp_path, _ac("- [ ] open", "- [ ] merged into main")), "--all")
    assert r.returncode == 1, "boxes grades only the checkbox rule"
    r = _pr(world, {"5": _ac("- [ ] open", "- [x] merged into main")})
    assert r.returncode == 2, r.stdout + r.stderr
    assert "[unchecked]" in r.stdout and "[post-merge]" in r.stdout
    r = _run("pr", str(world[0]), "9", "5", env={**world[1], "FAKE_FAIL": "1"})
    assert r.returncode == 4


@pytest.mark.parametrize("platform", ["github", "gitlab"])
def test_fetch_failure_is_exit_4(world, platform):
    repo, env, _ = world
    _origin(repo, "git@github.com:Owner/Repo.git" if platform == "github" else "git@gitlab.example.com:group/proj.git")
    for extra in ({"FAKE_FAIL": "1"}, {"FAKE_GLAB_ERROR_BODY": "1"}, {"FAKE_ISSUES": "{}"}):
        if platform == "github" and "FAKE_GLAB_ERROR_BODY" in extra:
            continue
        r = _run("pr", str(repo), "7", "5", env={**env, "FAKE_ISSUES": json.dumps({"5": ISSUE_DONE}), **extra})
        assert r.returncode == 4, (extra, r.stdout, r.stderr)
        assert "VERDICT: PASS" not in r.stdout


def test_gitlab_closes_issues_path(world):
    repo, env, tmp = world
    _origin(repo, "git@gitlab.example.com:group/proj.git")
    e = {**env, "FAKE_ISSUES": json.dumps({"5": ISSUE_DONE}), "FAKE_PR_BODY": "- [x] mr box\n",
         "FAKE_CLOSING": json.dumps([{"number": 6, "body": _ac("- [ ] gl open")}])}
    r = _run("pr", str(repo), "7", "5", env=e)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "ac-gate: MR group/proj!7 | boxes=1 checked=1" in r.stdout
    assert "  [unchecked] group/proj#6:3 gl open" in r.stdout
    calls = [json.loads(line) for line in (tmp / "calls.log").read_text().splitlines()]
    assert all(c[0] == "glab" for c in calls)


@pytest.mark.parametrize("args", [[], ["lint"], ["boxes", "x"], ["pr", "r", "x", "5"], ["nope"]])
def test_usage_is_exit_3(args):
    assert _run(*args).returncode == 3


# --- the closing set (#1397, #1407; design fork resolved by babelfish 2026-10-31: A) ---------

# An epic: a DoD the lint flags, and no AC box at all. Graded, it fails with exit 2.
EPIC = "## Summary\n\nan epic\n\n## Definition of Done\n\n- [ ] all story PRs merged into main\n"
GL = "git@gitlab.example.com:group/proj.git"
GH = "git@github.com:Owner/Repo.git"


def _gate(world, origin: str, issue_n: str, issues: dict, closing: list, pr: str = "7",
          body: str = "", **extra: str):
    repo, env, tmp = world
    _origin(repo, origin)
    e = {**env, "FAKE_ISSUES": json.dumps(issues), "FAKE_CLOSING": json.dumps(closing),
         "FAKE_PR_BODY": body, **extra}
    r = _run("pr", str(repo), pr, issue_n, env=e)
    calls = [json.loads(line) for line in (tmp / "calls.log").read_text().splitlines()]
    return r, calls


def _fetched(calls: list, suffix: str) -> bool:
    return any(c[-1].endswith(suffix) for c in calls)


@pytest.mark.parametrize("origin,story,branch_ref", [
    (GH, {"number": 12, "body": ISSUE_DONE, "repo": "Owner/Other"}, "Owner/Repo#5"),
    (GL, {"number": 12, "body": ISSUE_DONE, "project_id": 22, "full": "group/other#12"}, "group/proj#5"),
])
def test_branch_epic_not_in_closing_set_is_info_only(world, origin, story, branch_ref):
    # #1397's layout: the branch names the epic, and the MR closes a story in another project.
    r, calls = _gate(world, origin, "5", {"5": EPIC}, [story])
    assert r.returncode == 0, r.stdout + r.stderr
    assert f"ac-gate: [info] {branch_ref} is not among the closing issues; not graded" in r.stdout
    assert "#12 | boxes=2 checked=2 waived=0 unchecked=0 post-merge=0" in r.stdout
    assert "[post-merge]" not in r.stdout and "[no-ac]" not in r.stdout
    assert not _fetched(calls, "issues/5"), calls  # never read, so a 404 there can't fail it
    assert r.stdout.rstrip().endswith("VERDICT: PASS")


@pytest.mark.parametrize("origin,ref", [(GH, "Owner/Repo#5"), (GL, "group/proj#5")])
def test_empty_closing_set_grades_issue_n(world, origin, ref):
    # The fallback that keeps a PR/MR with no Closes from passing on its body alone.
    r, calls = _gate(world, origin, "5", {"5": _ac("- [x] one", "- [ ] two is open")}, [])
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"  [unchecked] {ref}:4 two is open" in r.stdout
    assert "[info]" not in r.stdout
    assert _fetched(calls, "issues/5"), calls


@pytest.mark.parametrize("origin,closing,ref", [
    (GH, [{"number": 5, "body": ISSUE_DONE}], "Owner/Repo#5"),
    (GL, [{"number": 5, "body": ISSUE_DONE}], "group/proj#5"),
    (GL, [{"number": 5, "body": ISSUE_DONE, "full": "group/proj#5"}], "group/proj#5"),
])
def test_issue_n_in_closing_set_graded_once(world, origin, closing, ref):
    r, calls = _gate(world, origin, "5", {"5": ISSUE_DONE}, closing)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count(f"ac-gate: {ref} |") == 1
    assert "[info]" not in r.stdout
    assert not _fetched(calls, "issues/5"), "graded from the closing set, not fetched again"


def test_gitlab_foreign_closing_issue_skips_local_same_number(world):
    # #1407's steps: the MR closes group/other#12, and group/proj#12 also exists, unfinished.
    local = _ac("- [ ] open locally", "- [x] the change is merged")
    foreign = {"number": 12, "project_id": 22, "full": "group/other#12",
               "body": _ac("- [x] a", "- [x] b", "- [x] c", "- [x] d")}
    r, calls = _gate(world, GL, "12", {"12": local}, [foreign])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: group/other#12 | boxes=4 checked=4 waived=0 unchecked=0 post-merge=0" in r.stdout
    assert "ac-gate: [info] group/proj#12 is not among the closing issues; not graded" in r.stdout
    assert "open locally" not in r.stdout
    assert not _fetched(calls, "group%2Fproj/issues/12"), calls


@pytest.mark.parametrize("issue_n,info", [
    ("group/other#12", None),
    ("GROUP/Other#12", None),  # paths compare case-insensitively
    ("group/third#12", "group/third#12"),
    ("group/proj#12", "group/proj#12"),
])
def test_issue_n_accepts_path_form(world, issue_n, info):
    foreign = {"number": 12, "project_id": 22, "full": "group/other#12", "body": ISSUE_DONE}
    r, _ = _gate(world, GL, issue_n, {"12": _ac("- [ ] open locally")}, [foreign])
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ac-gate: group/other#12 |") == 1
    if info:
        assert f"ac-gate: [info] {info} is not among the closing issues; not graded" in r.stdout
    else:
        assert "[info]" not in r.stdout


def test_path_form_with_empty_closing_set_reads_that_repo(world):
    r, calls = _gate(world, GH, "Owner/Repo#5", {"5": ISSUE_DONE}, [])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: Owner/Repo#5 | boxes=2 checked=2" in r.stdout
    assert _fetched(calls, "repos/Owner/Repo/issues/5"), calls


def test_gitlab_path_form_with_empty_closing_set_reads_that_project(world):
    # The local #12 is unfinished; the named project's #12 is done. Only the named one is read.
    repo, env, tmp = world
    _origin(repo, GL)
    e = {**env, "FAKE_ISSUES": json.dumps({"12": _ac("- [ ] open locally")}),
         "FAKE_FOREIGN": json.dumps({"12": ISSUE_DONE}), "FAKE_CLOSING": "[]"}
    r = _run("pr", str(repo), "7", "group/other#12", env=e)
    calls = [json.loads(line) for line in (tmp / "calls.log").read_text().splitlines()]
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: group/other#12 | boxes=2 checked=2" in r.stdout
    assert _fetched(calls, "group%2Fother/issues/12") and not _fetched(calls, "group%2Fproj/issues/12"), calls


@pytest.mark.parametrize("issue_n", ["group#12", "#12", "group/other#", "group/other#x", "a b/c#1",
                                     "../x#1", "group/../x#1", "./x#1"])
def test_malformed_issue_ref_is_exit_3(world, issue_n):
    repo, env, _ = world
    _origin(repo, GL)
    assert _run("pr", str(repo), "7", issue_n, env=env).returncode == 3


# --- ruling A refined by babelfish 2026-10-31: the closing set includes the body's Closes
# references to ISSUE_N, because the post-merge rule closes every `Closes #N` in the body.

@pytest.mark.parametrize("origin,ref", [(GH, "Owner/Repo#6"), (GL, "group/proj#6")])
@pytest.mark.parametrize("body", ["Closes #5, #6", "closes #5 and #6", "Fixes: #5\nResolves #6",
                                  "closes #5,#6", "Closes #5, and #6",
                                  "Closes #4, #5, and #6", "Closes\n#6", "Resolved #5 and\n#6"])
def test_body_closes_issue_n_unticked_fails(world, origin, ref, body):
    # GitHub links only `#5` from `Closes #5, #6`; #6 still closes on merge, so it's graded.
    r, calls = _gate(world, origin, "6", {"4": ISSUE_DONE, "6": _ac("- [ ] six is open")},
                     [{"number": 5, "body": ISSUE_DONE}], body=body)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"  [unchecked] {ref}:3 six is open" in r.stdout
    assert "[info]" not in r.stdout
    assert _fetched(calls, "issues/6"), calls


@pytest.mark.parametrize("origin,ref", [(GH, "Owner/Repo#6"), (GL, "group/proj#6")])
def test_body_closes_issue_n_ticked_passes_graded_once(world, origin, ref):
    r, _ = _gate(world, origin, "6", {"6": ISSUE_DONE}, [{"number": 5, "body": ISSUE_DONE}],
                 body="Closes #5, #6")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count(f"ac-gate: {ref} |") == 1
    assert "[info]" not in r.stdout


@pytest.mark.parametrize("origin,issue_n", [(GH, "Other/Proj#12"), (GL, "group/third#12")])
def test_body_closes_unreadable_foreign_issue_n_is_exit_4(world, origin, issue_n):
    # The token can't read that repository: a fetch failure, never an [info] line and a pass.
    r, _ = _gate(world, origin, issue_n, {}, [{"number": 5, "body": ISSUE_DONE}],
                 body=f"Closes #5, {issue_n}")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "[info]" not in r.stdout and "VERDICT: PASS" not in r.stdout


@pytest.mark.parametrize("origin", [GH, GL])
def test_body_naming_issue_n_without_keyword_stays_info(world, origin):
    # A bare mention ("see #6", "Part of #6") closes nothing, so #1397's epic case holds.
    r, calls = _gate(world, origin, "6", {"6": EPIC}, [{"number": 5, "body": ISSUE_DONE}],
                     body="Closes #5\n\nPart of #6; see #6")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "is not among the closing issues; not graded" in r.stdout
    assert not _fetched(calls, "issues/6"), calls


def test_github_decision_needs_no_jq(world):
    # A broken jq used to skip the fetch, and the grader then crashed on a missing file.
    (world[2] / "bin" / "jq").write_text("#!/bin/sh\nexit 127\n")
    (world[2] / "bin" / "jq").chmod(0o755)
    r, calls = _gate(world, GH, "5", {"5": ISSUE_DONE}, [])
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: Owner/Repo#5 | boxes=2 checked=2" in r.stdout
    assert _fetched(calls, "issues/5"), calls


def test_github_more_closing_issues_than_a_page_is_exit_4(world):
    r, _ = _gate(world, GH, "5", {"5": ISSUE_DONE}, [{"number": 5, "body": ISSUE_DONE}], FAKE_TOTAL="101")
    assert r.returncode == 4, r.stdout + r.stderr


def test_gitlab_full_page_of_closing_issues_is_exit_4(world):
    closing = [{"number": i, "body": ISSUE_DONE} for i in range(1, 101)]
    r, _ = _gate(world, GL, "500", {}, closing)
    assert r.returncode == 4, r.stdout + r.stderr
    assert "VERDICT: PASS" not in r.stdout


def test_github_renamed_repo_closing_entry_matches_origin_slug(world):
    # origin still says Owner/Repo; the repository is now Owner/Renamed.
    r, _ = _gate(world, GH, "5", {}, [{"number": 5, "body": ISSUE_DONE}], FAKE_REPO_NAME="Owner/Renamed")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: Owner/Renamed#5 | boxes=2 checked=2" in r.stdout
    assert "[info]" not in r.stdout


@pytest.mark.parametrize("origin,body", [(GH, "Closes #5, Owner/Repo#6"), (GL, "Closes #5, group/proj#6"),
                                         (GH, "Closes #5, owner/REPO#6")])
def test_body_closes_issue_n_by_path_is_graded(world, origin, body):
    r, _ = _gate(world, origin, "6", {"6": _ac("- [ ] six is open")}, [{"number": 5, "body": ISSUE_DONE}], body=body)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "six is open" in r.stdout and "[info]" not in r.stdout


@pytest.mark.parametrize("issue_n,body", [
    ("6", "Closes #5, Owner/Renamed#6"),
    ("Owner/Renamed#6", "Closes #5, #6"),
    ("6", "Closes #5, owner/REPO#6"),
])
def test_github_renamed_repo_body_reference_is_graded(world, issue_n, body):
    # origin says Owner/Repo, the repository is Owner/Renamed: either name, in any case, is
    # this repository, so the reference is read once, by origin's name, and graded.
    r, calls = _gate(world, GH, issue_n, {"6": _ac("- [ ] six is open")}, [{"number": 5, "body": ISSUE_DONE}],
                     body=body, FAKE_REPO_NAME="Owner/Renamed")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "  [unchecked] Owner/Repo#6:3 six is open" in r.stdout
    assert "[info]" not in r.stdout
    assert [c[-1] for c in calls if c[-1].endswith("issues/6")] == ["repos/Owner/Repo/issues/6"], calls


# --- ruling A generalized by babelfish 2026-10-31: every body closing reference is graded.

@pytest.mark.parametrize("origin,ref", [(GH, "Owner/Repo#6"), (GL, "group/proj#6")])
def test_body_only_reference_is_graded_beside_issue_n(world, origin, ref):
    # ISSUE_N=5 is linked; the platform didn't link #6, but the merge closes it too.
    r, calls = _gate(world, origin, "5", {"6": _ac("- [ ] six is open")},
                     [{"number": 5, "body": ISSUE_DONE}], body="Closes #5, #6")
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"  [unchecked] {ref}:3 six is open" in r.stdout
    assert "[info]" not in r.stdout


@pytest.mark.parametrize("origin,refs", [(GH, ("Owner/Repo#5", "Owner/Repo#6")), (GL, ("group/proj#5", "group/proj#6"))])
def test_body_only_reference_ticked_passes_each_graded_once(world, origin, refs):
    r, calls = _gate(world, origin, "5", {"6": ISSUE_DONE}, [{"number": 5, "body": ISSUE_DONE}],
                     body="Closes #5, #6\n\nFixes #6")
    assert r.returncode == 0, r.stdout + r.stderr
    for ref in refs:
        assert r.stdout.count(f"ac-gate: {ref} |") == 1, r.stdout
    assert not _fetched(calls, "issues/5"), "linked by the platform, so never read again"
    assert sum(c[-1].endswith("issues/6") for c in calls) == 1, calls


@pytest.mark.parametrize("origin,p", [(GH, "Owner/Repo"), (GL, "group/proj")])
def test_several_body_only_references_keep_their_own_bodies(world, origin, p):
    # Two reads: each answer is graded under its own label, never shifted by one.
    r, _ = _gate(world, origin, "5", {"6": ISSUE_DONE, "7": _ac("- [ ] seven is open")},
                 [{"number": 5, "body": ISSUE_DONE}], body="Closes #5, #6, #7")
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"ac-gate: {p}#6 | boxes=2 checked=2 waived=0 unchecked=0" in r.stdout
    assert f"  [unchecked] {p}#7:3 seven is open" in r.stdout


def test_gitlab_body_reference_dedupes_against_full_reference(world):
    closing = [{"number": 5, "body": ISSUE_DONE, "full": "group/proj#5"}]
    r, calls = _gate(world, GL, "5", {"6": ISSUE_DONE}, closing, body="Closes #5, group/proj#5, #6")
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.count("ac-gate: group/proj#5 |") == 1
    assert not _fetched(calls, "issues/5"), calls
    assert _fetched(calls, "issues/6"), calls


SQUASH_BODY = ("## Summary\n\nx\n\n## Linked Issues\n\nCloses #5\n\n## Squash commit\n\n"
               "```text\nfix(x): y\n\nCloses #5\nCloses #6\n```\n")


@pytest.mark.parametrize("origin,ref", [(GH, "Owner/Repo#6"), (GL, "group/proj#6")])
@pytest.mark.parametrize("body", [
    SQUASH_BODY,  # load-bearing: the squash block is plain text inside a fence, and it lands
    "Closes #5. Also see `Closes #6` above.",
    "Closes #5\n<!-- Closes #6 -->",
], ids=["squash-fence", "code-span", "html-comment"])
def test_closing_reference_in_code_or_comment_is_graded(world, origin, ref, body):
    # The commit message the squash lands is plain text: backticks and fences protect nothing.
    r, calls = _gate(world, origin, "5", {"6": _ac("- [ ] six is open")},
                     [{"number": 5, "body": ISSUE_DONE}], body=body)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"  [unchecked] {ref}:3 six is open" in r.stdout
    assert _fetched(calls, "issues/6"), calls


# --- babelfish 2026-10-31: the body parser is a superset of both platforms' closing patterns.

COMMON_FORMS = [
    "Closing #9", "Fixing #9", "Resolving #9", "Implements #9", "implemented #9", "Implementing #9",
    "implement #9", "Fixed #9", "Resolved: #9", "Closes issue #9", "Closes issues #5 and #9",
    "Closes #5 #9", "closes #5  #9", "Fixes #5, issue #9",
    "Fixes:#9", "Closes `#9`", "**Closes** #9", "Closes **#5** and _#9_", "Closes (#9).",
    "Closes issue#9", "Closes [#5](x), [#9](y)",
]


@pytest.mark.parametrize("origin,p,body", [
    *[(GH, "Owner/Repo", b) for b in COMMON_FORMS],
    *[(GL, "group/proj", b) for b in COMMON_FORMS],
    (GH, "Owner/Repo", "Closes #5\n\n```text\nFixes https://github.com/Owner/Repo/issues/9\n```"),
    (GH, "Owner/Repo", "Fixes HTTPS://GITHUB.COM/Owner/Repo/issues/9"),
    (GH, "Owner/Repo", "Closes Repo#9"),
    (GH, "Owner/Repo", "closes GH-9"),
    (GH, "Owner/Repo", "Closes https://github.com/Owner/Repo/issues/5#issuecomment-1, #9"),
    (GH, "Owner/Repo", "Closes https://github.com/Owner/Repo/issues/5?x=1 and #9"),
    (GH, "Owner/Repo", "Closes <https://github.com/Owner/Repo/issues/9>"),
    (GH, "Owner/Repo", "Closes [#9](https://github.com/Owner/Repo/issues/9)"),
    (GL, "group/proj", "Closes https://gitlab.example.com:8443/group/proj/-/issues/9"),
    (GL, "group/proj", "Closes https://gitlab.example.com/group/proj/-/issues/9"),
    (GL, "group/proj", "Closes https://gitlab.example.com/group/proj/-/work_items/9"),
    (GL, "group/proj", "Closes https://gitlab.example.com/group/proj/issues/9"),
    (GL, "group/proj", "Closes proj#9"),
])
def test_every_platform_closing_form_is_graded(world, origin, p, body):
    # The platform linked #5 alone; each of these forms still closes #9 on merge.
    r, calls = _gate(world, origin, "9", {"9": _ac("- [ ] nine is open")},
                     [{"number": 5, "body": ISSUE_DONE}], body=body)
    assert r.returncode == 1, r.stdout + r.stderr
    assert f"  [unchecked] {p}#9:3 nine is open" in r.stdout
    assert "[info]" not in r.stdout


@pytest.mark.parametrize("origin,url", [
    (GH, "https://gitlab.com/Owner/Repo/-/issues/9"),
    (GH, "https://github.example.com/Owner/Repo/issues/9"),
    (GL, "https://gitlab.com/group/proj/-/issues/9"),
])
def test_closing_url_on_another_host_is_exit_4(world, origin, url):
    r, calls = _gate(world, origin, "5", {"9": ISSUE_DONE}, [{"number": 5, "body": ISSUE_DONE}],
                     body=f"Closes #5\nFixes {url}")
    assert r.returncode == 4, r.stdout + r.stderr
    assert "on a host other than origin's" in r.stderr
    assert not _fetched(calls, "issues/9"), calls


def test_github_closing_reference_to_a_pr_is_info(world):
    # /issues/8 answers a PR, and no closing keyword closes a PR: [info], never [no-ac].
    r, _ = _gate(world, GH, "5", {}, [{"number": 5, "body": ISSUE_DONE}], body="Closes #5, #8", FAKE_PRS="[8]")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "ac-gate: [info] Owner/Repo#8 is a pull request, not an issue; not graded" in r.stdout
    assert "[no-ac]" not in r.stdout


def test_issue_n_fallback_naming_a_pr_is_still_graded(world):
    # Nothing closes, and ISSUE_N is a PR's number: grading it fails [no-ac], so the gate
    # never passes on the PR body alone.
    r, _ = _gate(world, GH, "8", {}, [], FAKE_PRS="[8]")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "[no-ac] Owner/Repo#8" in r.stdout
    assert "is a pull request" not in r.stdout


@pytest.mark.parametrize("origin,foreign", [(GH, "Other/Proj#12"), (GL, "group/third#12")])
def test_body_only_reference_unreadable_is_exit_4(world, origin, foreign):
    r, _ = _gate(world, origin, "5", {}, [{"number": 5, "body": ISSUE_DONE}], body=f"Closes #5, {foreign}")
    assert r.returncode == 4, r.stdout + r.stderr
    assert f"read issue {foreign} (named in the body; the platform didn't link it)" in r.stderr
    assert "VERDICT: PASS" not in r.stdout


@pytest.mark.parametrize("origin", [GH, GL])
def test_body_reference_with_empty_platform_list_replaces_the_fallback(world, origin):
    # Nothing linked, the body closes #6: #6 is the closing set, so ISSUE_N=5 is [info].
    r, calls = _gate(world, origin, "5", {"5": _ac("- [ ] five is open"), "6": ISSUE_DONE}, [], body="Closes #6")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "#5 is not among the closing issues; not graded" in r.stdout
    assert not _fetched(calls, "issues/5"), calls


@pytest.mark.parametrize("ref", ["../x#1", "a/../b#1", "./x#2"])
def test_body_reference_with_dot_segment_is_exit_4(world, ref):
    r, calls = _gate(world, GH, "5", {}, [{"number": 5, "body": ISSUE_DONE}], body=f"Closes {ref}")
    assert r.returncode == 4, r.stdout + r.stderr
    assert not any(".." in c[-1] or "/./" in c[-1] for c in calls), calls


def test_precheck_skill_lists_info_lines():
    skill = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text(encoding="utf-8")
    assert "ac-gate: [info] <ref> is not among the closing issues; not graded" in skill
    assert "any `[info]` not-graded line verbatim" in skill
