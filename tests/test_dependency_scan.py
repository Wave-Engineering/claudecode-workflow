"""The post-scan denominator: what did the scanner actually ingest? (#1137)

`check-scannable.sh` answers "is there anything to scan?" — PRE-scan. This script
answers "what did the scanner cover?" — POST-scan. They sit on opposite sides of
the same stage, and two green checks either side of a stage prove nothing about
the stage between them.

flightdeck lives in that gap: manifests present and countable, trivy parsing none
of them (bun.lock unsupported, flightdeck#8) — though flightdeck#8's own "unsupported"
diagnosis may be the same flag artifact described below, worth re-measuring before
#1141 commits to it as fact. cc-workflow was a partial instance — 2 scannable, 1
ingested — before this script's own --include-dev-deps fix (cc-workflow#1169): not
a bun.lock parsing limitation, but trivy suppressing this repo's entirely-devDependencies
bun.lock manifests by default, which nothing stated out loud until the coverage line
existed.

The other half closed here: the kit never ran the scan at all. It lived only as
prose in /precheck's Job C asking a sub-agent to report the denominator. An
instruction can be forgotten; a tool that emits the number cannot.
"""

from __future__ import annotations

import re
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


def test_precheck_fallback_scans_siblings_like_the_script():
    """#1247: the raw-trivy fallback, which runs in every repo but this one, must
    agree with dependency-scan.sh: an unpinned sibling stays out of the
    denominator, and a sibling scan's findings count toward the verdict.

    The pin regex is taken FROM check-scannable.sh, so the two cannot drift; a
    literal copied here would only pin SKILL.md to itself.
    """
    script = (REPO_ROOT / "scripts" / "ci" / "check-scannable.sh").read_text()
    m = re.search(r"pinned=\"\$\(grep -cE '([^']+)' \"\$req\"", script)
    assert m, "check-scannable.sh pin test not found; update this extraction with it"
    body = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    assert f"grep -cE '{m.group(1)}' '<sibling>'" in body, (
        "the fallback must test sibling pins with check-scannable.sh's own regex"
    )
    flat = " ".join(body.split())
    assert "leave it out of the denominator and name it as unpinned" in flat
    assert "findings count toward the verdict exactly like the main scan's" in flat
    assert "<same flags>" not in body, "a placeholder for flags is not runnable"


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
    """The coverage line must render on every run, full or partial.

    Zero-ingested is only the extreme case; partial coverage is the same defect
    wearing a pass, and it is the common one. cc-workflow itself used to
    demonstrate the partial case for free (1 of 2 manifests, before the
    --include-dev-deps fix above) — it is now 2 of 2 (3 of 3 in a checkout
    carrying the gitignored .claude/ copy), so this only pins the line's
    presence on a full-coverage run; the partial-coverage path itself is
    exercised by test_stub_partial_coverage_warns_but_still_passes below.
    """
    proc = run(REPO_ROOT)
    assert "coverage:" in proc.stdout, "no coverage ratio emitted"


@trivy_required
def test_present_but_uningested_FAILS_with_its_own_exit_code(tmp_path: Path):
    """The gap: input exists, scanner covered none of it.

    Distinct exit code and distinct wording from "nothing scannable" — they are
    opposite conditions that previously both surfaced as an unremarkable green.
    """
    # A hand-written file check-scannable.sh recognizes by name but that is
    # not valid bun.lock format, so trivy genuinely fails to parse it — a
    # real parse failure, not "bun.lock is unsupported" (trivy parses real
    # bun.lock fine; see --include-dev-deps above). No manifest trivy can.
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


def test_trivy_invoked_with_include_dev_deps_and_list_all_pkgs(tmp_path: Path):
    """cc-workflow#1169, ported into this script rather than left in the old
    prose-based Job C prompt it replaced: --include-dev-deps and
    --list-all-pkgs are REQUIRED, not optional.

    Without --include-dev-deps, a dev-only-deps manifest (a bun-based tools
    repo is the measured case) doesn't just scan zero packages — it drops
    out of Results entirely. Verified live against this repo's own two
    bun.lock files: `manifests ingested` reads 1 (pip only) without the
    flag and 3 (both bun.lock files too) with it, even though
    check-scannable.sh correctly counts all three as scannable either way.
    Without --list-all-pkgs (a trivy default only since v0.67.0, and this
    fleet pins no minimum version), an older install leaves every
    manifest's Packages array empty regardless of dev-deps.

    Asserts the actual argv trivy receives, not just that the flags appear
    somewhere in the script's source — a stub that ignores its arguments
    would pass a substring-only test while the real regression shipped."""
    repo = _scannable_repo(tmp_path)
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    argv_log = tmp_path / "argv.log"
    stub = bindir / "trivy"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "Version: 9.9.9-stub"; exit 0; fi\n'
        f'echo "$@" > {argv_log}\n'
        f"cat <<'JSON'\n{CLEAN_JSON}\nJSON\n"
        "exit 0\n"
    )
    stub.chmod(0o755)
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path)}
    proc = _run_env(repo, env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    argv = argv_log.read_text().split()
    assert "--include-dev-deps" in argv, f"trivy invoked without --include-dev-deps: {argv}"
    assert "--list-all-pkgs" in argv, f"trivy invoked without --list-all-pkgs: {argv}"


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


def test_stub_partial_coverage_warns_but_still_passes(tmp_path: Path):
    """SOME manifests ingested, not all — the common case, distinct from the
    zero-ingested extreme above.

    cc-workflow's own bun.lock manifests used to demonstrate this for free
    (1 of 2 ingested) until the --include-dev-deps fix closed that gap —
    which means the live-repo test above no longer exercises this path at
    all. Stubbed here so it stays covered."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "sub").mkdir()
    (repo / "sub" / "requirements.txt").write_text("django==5.0.0\n")
    # check-scannable.sh finds both (2 scannable); the stub trivy "ingests"
    # only one of them, mirroring a scanner that silently skips one manifest.
    payload = '{"Results":[{"Target":"requirements.txt","Type":"pip","Packages":[{"Name":"flask"}]}]}'
    proc = _run_env(repo, _stub_trivy(tmp_path, payload))
    assert proc.returncode == 0, (
        f"partial coverage must still PASS (it is not zero-ingested) — "
        f"the warning carries the shortfall, not a failing exit code\n"
        f"{proc.stdout}{proc.stderr}"
    )
    assert "coverage: 1 of 2" in proc.stdout, proc.stdout
    assert "WARNING" in proc.stdout + proc.stderr, "shortfall must not be silent"
    assert "COVERS 1/2" in proc.stdout, "the verdict itself must carry the shortfall"


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


def test_stub_malformed_json_exits_5_NOT_2(tmp_path: Path):
    """cc-workflow#1169 code review: malformed JSON is a scanner error too,
    not a lockfile-format problem — same distinction as the timeout/no-output
    cases above, previously exited 2 (present-but-uningested) instead."""
    repo = _scannable_repo(tmp_path)
    proc = _run_env(repo, _stub_trivy(tmp_path, "{not valid json"))
    assert proc.returncode == 5, (
        f"expected 5 (scanner error), got {proc.returncode} — 2 would blame the "
        f"lockfile format\n{proc.stdout}{proc.stderr}"
    )
    assert "could not parse trivy output" in proc.stdout + proc.stderr


def test_stub_nothing_scannable_exits_4(tmp_path: Path):
    """rc=4 is documented, referenced in validate.sh and /precheck, and was untested."""
    repo = tmp_path / "bare"
    repo.mkdir()
    proc = _run_env(repo, _stub_trivy(tmp_path, CLEAN_JSON))
    assert proc.returncode == 4, proc.stdout + proc.stderr


def test_missing_sibling_check_scannable_exits_5_not_4(tmp_path: Path):
    """cc-workflow#1169 code review: a partial install (this script present,
    check-scannable.sh not) must not misreport as "nothing scannable".

    `install` excludes ci/* from distribution today, so this is a real
    reachable shape, not a hypothetical — and without the explicit guard,
    bash's rc=127 for a missing file falls into the SAME branch as a
    genuinely empty repo, sending the operator after a dependency-pinning
    problem that does not exist."""
    isolated = tmp_path / "isolated-ci"
    isolated.mkdir()
    lone_script = isolated / "dependency-scan.sh"
    lone_script.write_text(SCRIPT.read_text())
    lone_script.chmod(0o755)
    # Deliberately NOT copying check-scannable.sh alongside it.

    proc = subprocess.run(
        ["bash", str(lone_script), str(_scannable_repo(tmp_path))],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 5, (
        f"expected 5 (scanner-infrastructure error), got {proc.returncode} — "
        f"4 would falsely claim nothing is scannable\n{proc.stdout}{proc.stderr}"
    )
    assert "check-scannable.sh missing" in proc.stdout + proc.stderr


# --- pip locks not named exactly requirements.txt (#1247) ------------------------
#
# trivy's pip analyzer reads ONLY a file named exactly `requirements.txt`. A
# sibling lock (requirements-dev.txt, requirements-build.txt) was skipped with no
# warning, though check-scannable.sh counts it. Measured on a real 4-lock tree:
# 2 ingested, the 209-package dev lock never examined, and the scan exited 0.
# dependency-scan.sh now scans each sibling alone, under the one name trivy reads.


def _routing_stub(tmp_path: Path, main_payload: str, sibling_payload: str, *, sibling_rc: int = 0) -> dict[str, str]:
    """A trivy stub that answers the repo scan with `main_payload` and a sibling
    scan with `sibling_payload`. It tells them apart by behaviour, not by the
    script's temp-dir names: a sibling scan targets a directory holding exactly
    one file, `requirements.txt`. A lock whose first line is `nothing==` yields no
    Results, like a lock trivy cannot read. Every call goes to calls.log: a
    `MAIN` line, or `SIBLING` followed by the requirements.txt it was handed."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir(exist_ok=True)
    log = tmp_path / "calls.log"
    stub = bindir / "trivy"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "--version" ]; then echo "Version: 9.9.9-stub"; exit 0; fi\n'
        'for a in "$@"; do last="$a"; done\n'
        'if [ "$(ls -A "$last")" = "requirements.txt" ]; then\n'
        f'  {{ echo SIBLING; cat "$last/requirements.txt"; }} >> {log}\n'
        '  if head -1 "$last/requirements.txt" | grep -q "^nothing=="; then echo \'{"Results":[]}\'; exit 0; fi\n'
        f"  cat <<'JSON'\n{sibling_payload}\nJSON\n"
        f"  exit {sibling_rc}\n"
        "fi\n"
        f"echo MAIN >> {log}\n"
        f"cat <<'JSON'\n{main_payload}\nJSON\n"
    )
    stub.chmod(0o755)
    return {"PATH": f"{bindir}:/usr/bin:/bin", "HOME": str(tmp_path)}


def _pip(target: str, *names: str, vulns: str = "") -> str:
    pkgs = ",".join(f'{{"Name":"{n}"}}' for n in names)
    v = f',"Vulnerabilities":[{vulns}]' if vulns else ""
    return f'{{"Target":"{target}","Type":"pip","Packages":[{pkgs}]{v}}}'


def _four_lock_repo(tmp_path: Path) -> Path:
    """The issue's shape: an app lock, a dev lock and a build lock, plus a nested app lock."""
    repo = tmp_path / "repo"
    (repo / "sub").mkdir(parents=True)
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "requirements-dev.txt").write_text("flask==3.0.0\npytest==8.0.0\n")
    (repo / "sub" / "requirements.txt").write_text("django==5.0.0\n")
    (repo / "sub" / "requirements-build.txt").write_text("pip==24.0\nwheel==0.43.0\n")
    return repo


# What trivy 0.74.0 reads of that tree in place: the two exact-name files only.
FOUR_LOCK_MAIN = f'{{"Results":[{_pip("requirements.txt", "flask")},{_pip("sub/requirements.txt", "django")}]}}'
SIBLING_TWO = f'{{"Results":[{_pip("requirements.txt", "a", "b")}]}}'


def test_sibling_pip_locks_are_scanned_alone_and_counted(tmp_path: Path):
    """The 2-of-4 case: every pinned lock is now ingested, under its real path.
    Against the pre-#1247 script this reads `coverage: 2 of 4`."""
    repo = _four_lock_repo(tmp_path)
    proc = _run_env(repo, _routing_stub(tmp_path, FOUR_LOCK_MAIN, SIBLING_TWO))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "coverage: 4 of 4 scannable manifest(s) ingested" in proc.stdout, out
    assert "manifests ingested: 4" in proc.stdout, out
    assert "packages scanned: 6" in proc.stdout, out
    assert "requirements-dev.txt  (pip, 2 packages, 0 finding(s); scanned alone as requirements.txt)" in proc.stdout, out
    assert "sub/requirements-build.txt  (pip, 2 packages, 0 finding(s); scanned alone as requirements.txt)" in proc.stdout, out
    assert "WARNING" not in out and "UNSCANNED" not in out and "COVERS" not in out, out
    # Each sibling was handed to trivy whole, under the name it reads.
    calls = (tmp_path / "calls.log").read_text()
    assert calls.count("MAIN") == 1 and calls.count("SIBLING") == 2, calls
    assert "SIBLING\nflask==3.0.0\npytest==8.0.0\n" in calls, calls
    assert "SIBLING\npip==24.0\nwheel==0.43.0\n" in calls, calls


def test_a_finding_in_a_sibling_lock_fails_the_scan(tmp_path: Path):
    repo = _four_lock_repo(tmp_path)
    vuln = '{"PkgName":"pytest","VulnerabilityID":"CVE-9999-7","Severity":"HIGH","FixedVersion":"8.0.1"}'
    sibling = f'{{"Results":[{_pip("requirements.txt", "pytest", vulns=vuln)}]}}'
    proc = _run_env(repo, _routing_stub(tmp_path, FOUR_LOCK_MAIN, sibling))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "FINDINGS — 2 HIGH,CRITICAL across 4 manifest(s)" in proc.stderr, proc.stderr
    assert "pytest | CVE-9999-7 | HIGH | 8.0.1" in proc.stderr, proc.stderr


def test_a_pinned_lock_trivy_ingests_nothing_from_is_named_unscanned(tmp_path: Path):
    """The honest denominator: the shortfall names the file, and the verdict says so."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "requirements-odd.txt").write_text("nothing==1.0\n")
    main = f'{{"Results":[{_pip("requirements.txt", "flask")}]}}'
    proc = _run_env(repo, _routing_stub(tmp_path, main, SIBLING_TWO))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "coverage: 1 of 2" in proc.stdout, out
    assert "UNSCANNED — 1 pinned pip lock(s) trivy ingested nothing from:\n  - requirements-odd.txt" in proc.stderr, out
    assert "(1 pip lock(s) UNSCANNED — see above)" in proc.stdout, out


def test_a_sibling_trivy_reads_in_place_is_not_counted_twice(tmp_path: Path):
    """A future trivy that reads requirements-dev.txt itself must not double it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "requirements-dev.txt").write_text("flask==3.0.0\npytest==8.0.0\n")
    main = f'{{"Results":[{_pip("requirements.txt", "flask")},{_pip("requirements-dev.txt", "flask", "pytest")}]}}'
    proc = _run_env(repo, _routing_stub(tmp_path, main, SIBLING_TWO))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "manifests ingested: 2" in proc.stdout, out
    assert "packages scanned: 3" in proc.stdout, out
    assert "scanned alone" not in proc.stdout, out


def test_a_sibling_scan_with_no_output_exits_5_naming_the_lock(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "requirements-dev.txt").write_text("pytest==8.0.0\n")
    main = f'{{"Results":[{_pip("requirements.txt", "flask")}]}}'
    proc = _run_env(repo, _routing_stub(tmp_path, main, "", sibling_rc=1))
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "trivy produced no output scanning requirements-dev.txt" in proc.stderr, proc.stderr


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


def test_ci_trivy_version_matches_the_container_image_pin() -> None:
    """cc-workflow#1169 code review: .github/workflows/validate.yml and
    containers/oakandwave-workflow/Dockerfile each pin their own
    TRIVY_VERSION, with nothing enforcing they agree. A split scanner
    version between CI and the fleet's runtime image is exactly the
    "coverage shortfall could be an ecosystem limit OR a stale binary"
    ambiguity dependency-scan.sh's own version-in-output line exists to
    resolve — a mismatch here would reintroduce it one level up."""
    workflow_text = (REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text()
    dockerfile_text = (
        REPO_ROOT / "containers" / "oakandwave-workflow" / "Dockerfile"
    ).read_text()

    workflow_match = re.search(r'TRIVY_VERSION:\s*"([\d.]+)"', workflow_text)
    dockerfile_match = re.search(r"ARG TRIVY_VERSION=([\d.]+)", dockerfile_text)
    assert workflow_match, "TRIVY_VERSION pin not found in validate.yml"
    assert dockerfile_match, "TRIVY_VERSION pin not found in the Dockerfile"
    assert workflow_match.group(1) == dockerfile_match.group(1), (
        f"CI pins trivy {workflow_match.group(1)!r} but the container image pins "
        f"{dockerfile_match.group(1)!r} — these must move together"
    )


def _install_trivy_step_script() -> str:
    """Pull the "Install trivy" step's `run:` block scalar out of the real
    workflow YAML (not a hand-copied excerpt), so this test tracks the
    actual file rather than a snapshot of it.

    Plain indentation-based extraction, not a YAML parser: PyYAML is not a
    dependency of this repo's test suite anywhere else (CI's "Install test
    dependencies" step installs only pytest/pytest-cov), and this step's
    `run: |` block is a known, fixed shape — a general parser would be a new
    dependency to buy nothing this doesn't already do. (This test itself
    shipped broken to CI once already by importing yaml and passing only
    because it happened to be installed on the machine that wrote it —
    exactly the gap this file exists to catch elsewhere.)"""
    lines = (REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip() == "- name: Install trivy")
    run_idx = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    block_indent = len(lines[run_idx]) - len(lines[run_idx].lstrip(" "))
    body = []
    for ln in lines[run_idx + 1 :]:
        if ln.strip() and (len(ln) - len(ln.lstrip(" "))) <= block_indent:
            break
        body.append(ln)
    assert body, "Install trivy step's run block appears empty — extraction is broken"
    return "\n".join(body)


def test_ci_trivy_checksum_check_targets_the_actual_downloaded_filename() -> None:
    """cc-workflow#1169 code review, critical finding: `sha256sum -c`
    resolves the file to verify from the CHECKSUM LINE's filename, not from
    the path curl wrote the download to. A mismatch (curl -o trivy.tar.gz,
    checksum line naming trivy_<version>_Linux-64bit.tar.gz) makes every CI
    run fail deterministically — sha256sum looks for a file that was never
    created. A standalone manual test of the bare shell command passed only
    because it happened to copy the file under the checksum line's name
    first, which the actual workflow step never does; this test reads the
    real step script instead of trusting that command in isolation.

    Structural, not an execution test (the step also runs `sudo install` to
    /usr/local/bin, which a test must not do to the real machine): asserts
    the download target and the checksum-check target are driven by the
    SAME variable, and that the old hardcoded mismatched name is gone."""
    script = _install_trivy_step_script()
    # Executable lines only — the fix's own explanatory comment names the
    # pre-fix literal filename as history, which must not trip this check.
    code_lines = [
        ln for ln in script.splitlines() if ln.strip() and not ln.strip().startswith("#")
    ]
    code = "\n".join(code_lines)
    assert "trivy.tar.gz" not in code, (
        "found the literal pre-fix filename 'trivy.tar.gz' in executable code — "
        "the download target must be named identically to what the checksums "
        "file names, not a shorter alias"
    )
    curl_download_line = next(
        ln for ln in code_lines if "-o " in ln and "checksums.txt" not in ln
    )
    checksum_line = next(ln for ln in code_lines if "sha256sum -c" in ln)
    assert "${asset}" in curl_download_line, (
        f"download line does not reference ${{asset}}: {curl_download_line!r}"
    )
    assert "${asset}" in checksum_line, (
        f"checksum-check line does not reference ${{asset}}: {checksum_line!r}"
    )
