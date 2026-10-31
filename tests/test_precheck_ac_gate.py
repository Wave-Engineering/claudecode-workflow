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
    nodes = [{"number": c["number"], "body": c["body"], "repository": {"nameWithOwner": c.get("repo", "Owner/Repo")}} for c in closing]
    print(json.dumps({"data": {"repository": {"pullRequest": {"body": pr_body, "closingIssuesReferences": {"nodes": nodes}}}}})); sys.exit(0)
if tool == "gh":
    m = re.fullmatch(r"repos/Owner/Repo/issues/([0-9]+)", endpoint)
    if m and m.group(1) in issues:
        print(json.dumps({"number": int(m.group(1)), "body": issues[m.group(1)]})); sys.exit(0)
    if m:
        sys.exit(1)  # gh exits non-zero on a 404
if tool == "glab":
    p = "projects/group%2Fproj/"
    if endpoint == p + "merge_requests/7":
        print(json.dumps({"iid": 7, "project_id": 11, "description": pr_body})); sys.exit(0)
    if endpoint == p + "merge_requests/7/closes_issues":
        print(json.dumps([{"iid": c["number"], "project_id": c.get("project_id", 11), "description": c["body"]} for c in closing])); sys.exit(0)
    m = re.fullmatch(re.escape(p) + r"issues/([0-9]+)", endpoint)
    if m and m.group(1) in issues:
        print(json.dumps({"iid": int(m.group(1)), "project_id": 11, "description": issues[m.group(1)]})); sys.exit(0)
    if m:
        print(json.dumps({"message": "404 Not found"})); sys.exit(0)
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
