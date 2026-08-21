"""The post-scan denominator: what did the scanner actually ingest? (#1137)

`check-scannable.sh` answers "is there anything to scan?" — PRE-scan. This script
answers "what did the scanner cover?" — POST-scan. They sit on opposite sides of
the same stage, and two green checks either side of a stage prove nothing about
the stage between them.

flightdeck lives in that gap: manifests present and countable, trivy parsing none
of them (bun.lock unsupported, flightdeck#8), both checks green. cc-workflow is a
partial instance — 2 scannable, 1 ingested — which nothing stated out loud until
the coverage line existed.

The other half closed here: the kit never ran the scan at all. It lived only as
prose in /precheck's Job C asking a sub-agent to report the denominator. An
instruction can be forgotten; a tool that emits the number cannot.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci" / "dependency-scan.sh"

trivy_required = pytest.mark.skipif(
    shutil.which("trivy") is None, reason="trivy not installed"
)


def run(root: Path | str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(root)],
        capture_output=True, text=True, timeout=300,
    )


def test_the_script_exists_and_is_wired_into_validate():
    assert SCRIPT.is_file(), "dependency-scan.sh missing"
    body = (REPO_ROOT / "scripts" / "ci" / "validate.sh").read_text()
    assert "dependency-scan.sh" in body, (
        "the scan must run in the lane CI runs, not only in /precheck's prose — "
        "that is the whole point of #1137"
    )


def test_precheck_invokes_the_tool_rather_than_describing_the_report():
    """The structural half: Job C must call the script, not ask an agent to count.

    Pinned because the failure mode is invisible — an agent that complies produces
    output indistinguishable from a tool that emits. It is the agent that stops
    complying, later, that reveals the difference.
    """
    body = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    assert "dependency-scan.sh" in body, "Job C does not invoke the script"


@trivy_required
def test_reports_the_denominator_before_the_verdict():
    """DENOMINATOR FIRST, on every path including the passing one."""
    proc = run(REPO_ROOT)
    out = proc.stdout
    assert "manifests ingested:" in out
    assert "packages scanned:" in out
    verdict_at = out.find("dependency-scan: PASS")
    count_at = out.find("manifests ingested:")
    assert count_at != -1 and verdict_at != -1, out
    assert count_at < verdict_at, (
        "the count must precede the verdict — a verdict without the number that "
        "qualifies it is the failure this whole family of checks exists to prevent"
    )


@trivy_required
def test_partial_coverage_is_stated_not_hidden():
    """cc-workflow itself covers 1 of 2 manifests. That must be visible.

    Zero-ingested is only the extreme case; partial coverage is the same defect
    wearing a pass, and it is the common one.
    """
    proc = run(REPO_ROOT)
    assert "coverage:" in proc.stdout, "no coverage ratio emitted"


@trivy_required
def test_present_but_uningested_FAILS_with_its_own_exit_code(tmp_path: Path):
    """The gap: input exists, scanner covered none of it.

    Distinct exit code and distinct wording from "nothing scannable" — they are
    opposite conditions that previously both surfaced as an unremarkable green.
    """
    # A lockfile trivy cannot parse, with no manifest it can.
    (tmp_path / "bun.lock").write_text('# bun lockfile v1\n"foo@1.0.0": {}\n')
    (tmp_path / "package.json").write_text('{"name":"x","dependencies":{"foo":"1.0.0"}}\n')

    proc = run(tmp_path)
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, (
        f"expected rc=2 (present-but-uningested), got {proc.returncode}\n{combined}"
    )
    assert "ingested ZERO" in combined
    assert "NOT \"nothing to scan\"" in combined or 'NOT "nothing to scan"' in combined, (
        "the message must distinguish itself from the nothing-scannable case"
    )


@trivy_required
def test_declared_absence_still_passes(tmp_path: Path):
    """A repo with genuinely nothing to scan declares it, and is not punished."""
    (tmp_path / ".no-scannable-dependencies").write_text(
        "No runtime dependencies; the service uses only stdlib.\n"
    )
    proc = run(tmp_path)
    assert proc.returncode == 0, (proc.stdout + proc.stderr)


def test_trivy_absence_is_a_skip_not_a_failure(tmp_path: Path):
    """rc=3, so validate.sh can treat it as [SKIPPED].

    A hard dependency on trivy would make validate.sh unrunnable on a fresh box,
    which is how a check gets commented out rather than fixed.
    """
    # /usr/bin:/bin keeps bash, python3 and the coreutils the script needs, while
    # dropping /usr/local/bin where trivy lives. An empty PATH would remove bash
    # too and the test would "pass" on a FileNotFoundError instead of on rc=3 —
    # which is the kind of green this whole file exists to distrust.
    trivy_path = shutil.which("trivy")
    if trivy_path and not trivy_path.startswith("/usr/local/"):
        pytest.skip(f"trivy at {trivy_path} is not excluded by a /usr/bin:/bin PATH")
    proc = subprocess.run(
        ["bash", str(SCRIPT), str(REPO_ROOT)],
        capture_output=True, text=True, timeout=60,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)},
    )
    assert proc.returncode == 3, (proc.stdout + proc.stderr)
    assert "SKIP" in proc.stdout


# --- hermetic: a STUB trivy, so these run where CI actually runs -----------------
#
# Five of the tests above need a real trivy. CI installs shellcheck, shfmt and
# Python — not trivy — so in the lane that gates every PR they all skip, and the
# only things executing are two string-greps. Every behavioural property was
# unpinned exactly where drift lands.
#
# A stub emitting canned JSON closes that. It would have caught BOTH review
# findings on this changeset: the `set -e` bug (validate aborting on a non-zero
# rc, which only ever happens when trivy is absent or unhappy) and the question of
# whether `packages` is really measured. Follow the lead of
# tests/regression/test_check_scannable.sh, which builds its cases red-first.


def _stub_trivy(tmp_path: Path, payload: str, *, rc: int = 0) -> dict[str, str]:
    """PATH with a fake `trivy` that prints `payload` and exits `rc`."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / "trivy"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "Version: 9.9.9-stub"; exit 0; fi\n'
        f"cat <<'JSON'\n{payload}\nJSON\n"
        f"exit {rc}\n"
    )
    stub.chmod(0o755)
    return {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path)}


def _run_env(root: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), str(root)],
        capture_output=True, text=True, timeout=120, env=env,
    )


def _scannable_repo(tmp_path: Path) -> Path:
    """A repo check-scannable.sh accepts: one requirements.txt with a pinned entry."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    return repo


CLEAN_JSON = '{"Results":[{"Target":"requirements.txt","Type":"pip","Packages":[{"Name":"flask"}]}]}'
FINDING_JSON = (
    '{"Results":[{"Target":"requirements.txt","Type":"pip","Packages":[{"Name":"flask"}],'
    '"Vulnerabilities":[{"PkgName":"flask","VulnerabilityID":"CVE-9999-1","Severity":"HIGH",'
    '"FixedVersion":"3.0.1"}]}]}'
)


def test_stub_clean_scan_passes_and_reports_its_denominator(tmp_path: Path):
    repo = _scannable_repo(tmp_path)
    proc = _run_env(repo, _stub_trivy(tmp_path, CLEAN_JSON))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "manifests ingested: 1" in proc.stdout
    assert "packages scanned: 1" in proc.stdout
    assert "scanner: Version: 9.9.9-stub" in proc.stdout, (
        "the scanner version must be reported — a coverage shortfall is "
        "unattributable without it"
    )


def test_stub_findings_exit_1_and_are_rendered(tmp_path: Path):
    """rc=1 and the per-CVE rendering were entirely uncovered."""
    repo = _scannable_repo(tmp_path)
    proc = _run_env(repo, _stub_trivy(tmp_path, FINDING_JSON))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    combined = proc.stdout + proc.stderr
    assert "CVE-9999-1" in combined, "the finding must be named, not just counted"
    assert "flask" in combined and "3.0.1" in combined, (
        "package and fixed-version must render — this sed/awk path was untested, "
        "and on BSD sed it silently emits nothing"
    )


def test_stub_present_but_uningested_exits_2(tmp_path: Path):
    """The gap this script exists for: input present, scanner covered none."""
    repo = _scannable_repo(tmp_path)
    proc = _run_env(repo, _stub_trivy(tmp_path, '{"Results":[]}'))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "ingested ZERO" in proc.stdout + proc.stderr


def test_stub_scanner_error_exits_5_NOT_2(tmp_path: Path):
    """A broken scanner is not an unparseable lockfile.

    Conflating them sends the operator hunting an ecosystem problem that does not
    exist — the misattribution review flagged. Distinct code, distinct message.
    """
    repo = _scannable_repo(tmp_path)
    proc = _run_env(repo, _stub_trivy(tmp_path, "", rc=1))
    assert proc.returncode == 5, (
        f"expected 5 (scanner error), got {proc.returncode} — 2 would blame the "
        f"lockfile format\n{proc.stdout}{proc.stderr}"
    )


def test_stub_nothing_scannable_exits_4(tmp_path: Path):
    """rc=4 is documented, referenced in validate.sh and /precheck, and was untested."""
    repo = tmp_path / "bare"
    repo.mkdir()
    proc = _run_env(repo, _stub_trivy(tmp_path, CLEAN_JSON))
    assert proc.returncode == 4, proc.stdout + proc.stderr


def test_validate_survives_a_non_zero_scan_rc(tmp_path: Path):
    """REGRESSION for the `set -e` bug (review finding 1).

    `dep_out=$(...)` followed by `dep_rc=$?` under `set -euo pipefail` aborts the
    whole script on any non-zero rc — the case statement was dead code, and CI
    (which has no trivy, so rc=3) would have gone red on every PR with no summary
    printed. The wiring test greps validate.sh for the filename and passed over
    the broken wiring: config exists is not config works.

    Asserts the SUMMARY still prints, because that is what disappears.
    """
    fake_scan = tmp_path / "dependency-scan.sh"
    fake_scan.write_text("#!/usr/bin/env bash\necho 'dependency-scan: SKIP'\nexit 3\n")
    fake_scan.chmod(0o755)

    snippet = (REPO_ROOT / "scripts" / "ci" / "validate.sh").read_text()
    # Anchor to LINE START. A bare `.index("dep_rc=0")` matched inside the comment
    # that explains this very fix ("`dep_rc=0` then `|| dep_rc=$?`"), so the slice
    # began mid-sentence and the harness died on unbalanced backticks — a test
    # defeated by the prose documenting what it tests.
    start = snippet.index("\ndep_rc=0\n") + 1
    end = snippet.index("\nesac", start) + len("\nesac")
    body = snippet[start:end].replace(
        '"$REPO_DIR/scripts/ci/dependency-scan.sh" "$REPO_DIR"', f'"{fake_scan}" .'
    )
    harness = (
        "set -euo pipefail\n"
        "PASS=0; FAIL=0\n"
        "info() { echo \"  [+] $*\"; }\n"
        "err() { echo \"  [!] $*\"; }\n"
        f"{body}\n"
        'echo "Results: $PASS passed, $FAIL failed"\n'
    )
    proc = subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True, timeout=60
    )
    assert "Results:" in proc.stdout, (
        "validate.sh aborted before its summary — the non-zero rc killed it via "
        f"errexit\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "[SKIPPED]" in proc.stdout, "rc=3 must reach the skip branch"
