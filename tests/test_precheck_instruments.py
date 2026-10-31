"""/precheck's Jobs A, B and C are instruments the orchestrator runs itself (#1275).

They used to be haiku sub-agents, and the gate read what the sub-agent WROTE, not what
the instrument returned. On 2026-10-19 that misreported twice: a Job A agent never
called spec_validate_structure and labelled its own reading of the issue a raw tool
response, and a Job B agent reported `shellcheck exit=0` while its own output listed
SC1091 (rc 1; through xargs, 123). These guards pin the skill text that removes the
layer: no Agent dispatch in A/B/C, the orchestrator runs each command in a form whose
`$?` is the instrument's own, and only Job D, a judgment, stays delegated.

Doc-drift guard in the style of test_precheck_gates.py: the skill is the instruction
agents actually follow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "precheck" / "SKILL.md"

# A job header is a bold line opening `**Job <letter>[-<variant>]`, outside a code fence.
JOB_HEADER = re.compile(r"^\*\*Job ([A-D](?:-[a-z]+)?)\b")
HEADING = re.compile(r"^#{1,6} ")

RULE = (
    "No sub-agent report is a gate value. Jobs A, B and C are instruments the "
    "orchestrator runs itself; their JSON or exit code goes on the checklist as read. "
    "Only Job D, a judgment, is delegated."
)


def _flat(s: str) -> str:
    return " ".join(s.split())


@pytest.fixture(scope="module")
def text() -> str:
    return SKILL.read_text()


@pytest.fixture(scope="module")
def jobs(text: str) -> dict[str, str]:
    """Each job header mapped to its text, up to the next job header or markdown
    heading. Both are ignored inside code fences, where a `# comment` is not a heading."""
    sections: dict[str, list[str]] = {}
    name, fence = None, False
    for line in text.splitlines():
        if not fence and not line.startswith("```"):
            m = JOB_HEADER.match(line)
            if m or HEADING.match(line):
                name = m.group(1) if m else None
        if name:
            sections.setdefault(name, []).append(line)
        if line.startswith("```"):
            fence = not fence
    return {k: "\n".join(v) for k, v in sections.items()}


def test_parser_finds_every_job(jobs: dict[str, str]) -> None:
    """A renamed header would otherwise make every test below pass over nothing."""
    for job in ("A", "B", "B-ci", "B-local", "C", "D", "D-full", "D-delta"):
        assert jobs.get(job, "").strip(), f"Job {job} section not found; update the parser with the skill"


def test_precheck_jobs_abc_not_delegated(jobs: dict[str, str]) -> None:
    """No Agent dispatch in A, B, B-ci, B-local or C; Job D's two prompts go to the code
    reviewer and name no model, so its agent definition or a router picks one (#1387)."""
    for job in ("A", "B", "B-ci", "B-local", "C"):
        body = jobs[job]
        assert "subagent_type" not in body, f"Job {job} still dispatches a sub-agent"
        assert not re.search(r"\bmodel:\s*\w", body), f"Job {job} still names a model to dispatch"
    for job in ("D", "D-full", "D-delta"):
        assert not re.search(r"\bmodel:\s*\w", jobs[job]), f"Job {job} pins a model again"
    for job in ("D-full", "D-delta"):
        assert "subagent_type: feature-dev:code-reviewer" in jobs[job], f"Job {job} is no longer the code-reviewer agent"


def test_precheck_no_subagent_gate_rule(text: str) -> None:
    """The rule sits in Step 2's preamble, verbatim, and the dispatch wording matches it."""
    step2 = text[text.index("### Step 2") : text.index("**Job A")]
    flat = _flat(step2)
    assert RULE in flat, "Step 2 must state the no-sub-agent gate rule verbatim"
    assert "dispatch Job D as an Agent call" in flat
    assert "start A, B and C directly in the same message" in flat
    assert "parallel Agent calls" not in flat, "Step 2 still launches all four jobs as Agent calls"


def test_precheck_lane_no_filter_before_rc(jobs: dict[str, str]) -> None:
    """B-local runs each lane as `<cmd> > <log> 2>&1; echo "exit=$?"`, bans every filter
    before `$?` by name, and gives a multi-file linter one argv instead of xargs."""
    body = jobs["B-local"]
    assert '<cmd> > <log> 2>&1; echo "exit=$?"' in body, "the lane form is not given verbatim"
    sentences = re.split(r"(?<=[.!?])\s+", _flat(body))
    bans = [s for s in sentences if re.search(r"\bnever\b", s, re.I) and "$?" in s]
    assert any(all(f"`{f}`" in s for f in ("tail", "head", "grep", "xargs")) for s in bans), (
        "B-local must ban tail, head, grep and xargs before `$?` in one explicit sentence"
    )
    assert "shellcheck -f gcc <files...>" in body, "the single-argv linter form is missing"
    assert "Run the lanes one at a time, never in parallel with each other" in _flat(body)


def test_precheck_fallback_captures_every_trivy_run_to_a_file(jobs: dict[str, str]) -> None:
    """The raw-trivy fallback never prints trivy's JSON into the tool output. trivy
    lists a target's Packages before its Vulnerabilities, and the tool cuts output
    near 30k characters (one pinned django==2.2.0 is ~95 KB of JSON), so a cut can
    land between them and read as ingested with 0 HIGH/CRITICAL: a false PASS.
    Every trivy command line is captured to a file, and jq reads it from there."""
    c = jobs["C"]
    runs = [ln.strip() for ln in c.splitlines() if "trivy fs " in ln and ln.strip().startswith(("trivy fs ", "d=$("))]
    assert len(runs) >= 2, f"expected the main and the per-file fallback scans, found {runs}"
    for run in runs:
        # `\s>` and not a bare `>`: `2> <marker_dir>/trivy-0.err` contains `> <marker_dir>/trivy-`.
        assert re.search(r"\s>\s*<marker_dir>/trivy-\S+\.json\s", run), f"stdout not captured: {run}"
        assert re.search(r"\s2>\s*<marker_dir>/trivy-\S+\.err", run), f"stderr not captured: {run}"
        assert 'echo "exit=$?"' in run, f"trivy run without its own exit=: {run}"
    flat = _flat(c)
    assert "Capture every trivy run to a file, never to the tool output" in flat
    assert "jq '[.Results[]? | {Target, pkgs: (.Packages // [] | length)" in c, "packages are not read from the file"
    assert "or left a file jq cannot parse scanned nothing: every lock it was to cover is UNSCANNED" in flat
    assert re.search(r"main scan, and each per-file scan below, with run_in_background: true", flat)


def test_precheck_instruments_name_what_they_read(jobs: dict[str, str]) -> None:
    """Each instrument job names the call or command, and the field or `$?` it reads."""
    a = _flat(jobs["A"])
    assert "spec_validate_structure" in a and "`valid`" in a and "`missing_sections`" in a
    assert "A tool error" in a and "never a pass" in a, "Job A must FAIL on a tool error"
    ci = _flat(jobs["B-ci"])
    assert "ci_wait_run" in ci and "expected_sha" in ci and "final_status" in ci
    assert "`No CI run found`" in ci, "NO-RUN must be decided from ci_wait_run's own JSON"
    assert 'echo "exit=$?"' in jobs["B-local"]
    c = jobs["C"]
    assert 'bash <repo_root>/scripts/ci/dependency-scan.sh <repo_root> > <log> 2>&1; echo "exit=$?"' in c
    assert "git -C <repo_root> rev-parse HEAD" in c
    # trivy may run past the Bash tool's foreground limit; a killed scan prints no exit=.
    flat_c = _flat(c)
    # The script's own sentence, not a bare substring: the fallback says run_in_background too.
    assert "Run the scan with `run_in_background: true`." in flat_c, "Job C must run the scan in the background"
    assert "has not printed `exit=` has no result, and is never a pass" in flat_c


def test_precheck_ci_cross_checks_the_check_run(jobs: dict[str, str]) -> None:
    """On GitHub, final_status is cross-checked against the check-runs, and the run
    summary that `gh run watch --exit-status` reports is never evidence (squawk #8)."""
    ci = _flat(jobs["B-ci"])
    # --paginate: the endpoint returns 30 check-runs a page, and a failure on page 2 is
    # exactly what the cross-check exists to catch.
    assert "gh api --paginate repos/<repo>/commits/<HEAD_SHA>/check-runs --jq '.check_runs[] | {name,conclusion}'" in ci
    assert re.search(r"`gh run watch --exit-status` is never evidence", ci)


def test_precheck_names_no_haiku_job(text: str) -> None:
    """No text calls A, B or C a haiku job: the only delegated job is Job D."""
    assert not re.search(r"haiku", text, re.I), "SKILL.md still names a haiku job"
