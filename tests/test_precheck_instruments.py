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
    """No Agent dispatch in A, B, B-ci, B-local or C; Job D's two prompts still go to opus."""
    for job in ("A", "B", "B-ci", "B-local", "C"):
        body = jobs[job]
        assert "subagent_type" not in body, f"Job {job} still dispatches a sub-agent"
        assert not re.search(r"\bmodel:\s*\w", body), f"Job {job} still names a model to dispatch"
    assert "`model: opus`" in jobs["D"].splitlines()[0], "Job D's header lost `model: opus`"
    for job in ("D-full", "D-delta"):
        assert "subagent_type: feature-dev:code-reviewer" in jobs[job], f"Job {job} is no longer the code-reviewer agent"
        assert "model: opus" in jobs[job], f"Job {job} is no longer dispatched to opus"


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
    assert "run_in_background: true" in flat_c, "Job C must run the scan in the background"
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
    """No text calls A, B or C a haiku job: the only delegated job is Job D, on opus."""
    assert not re.search(r"haiku", text, re.I), "SKILL.md still names a haiku job"
