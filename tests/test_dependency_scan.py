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

import json
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "ci" / "dependency-scan.sh"
PREDICATE = REPO_ROOT / "scripts" / "ci" / "lock-predicate.sh"


def predicate(expr: str) -> str:
    """Evaluate `expr` with lock-predicate.sh sourced: the one lock predicate (#1358)."""
    return subprocess.run(
        ["bash", "-c", f'source "$1"; {expr}', "pred", str(PREDICATE)],
        capture_output=True, text=True, timeout=30, check=True,
    ).stdout.rstrip("\n")

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

    The pin regex is taken FROM lock-predicate.sh (#1358), so the two cannot
    drift; a literal copied here would only pin SKILL.md to itself.
    """
    pin_re = predicate('printf %s "$PIN_RE"')
    assert pin_re, "lock-predicate.sh PIN_RE is empty"
    body = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    assert f"grep -cE '{pin_re}' '<that file>'" in body, (
        "the fallback must test pins with lock-predicate.sh's PIN_RE"
    )
    flat = " ".join(body.split())
    assert "leave it out of the denominator and name it as unpinned" in flat
    assert "findings count toward the verdict exactly like the main scan's" in flat
    assert "<same flags>" not in body, "a placeholder for flags is not runnable"
    # The main fallback scan names its target: `trivy fs` with no path errors when run as written.
    # Its flags and skip-dirs are lock-predicate.sh's, generated into the prose (#1358).
    flags = predicate('printf %s "$TRIVY_PROSE_FLAGS"')
    assert f"trivy fs {flags} {predicate('skip_dirs_args')} <repo_root> > " in body, "the fallback main scan must be lock-predicate.sh's, with a target"
    # The FULL denominator (babelfish's #1269 review): the fallback runs the trust
    # gate's own find, byte for byte, so a lone bun.lockb or a pinned lock trivy
    # read nothing from enters it and can be named UNSCANNED. The gate's find is
    # taken from gate.js's source and un-escaped, so the two cannot drift. The gate
    # roots it at its detached kahuna worktree, <w>/tree (#1206); precheck at <repo_root>.
    gate = (REPO_ROOT / "skills" / "nextwave" / "gate.js").read_text()
    g = re.search(r"^    `  (find <w>/tree .+ -print)`,$", gate, re.M)
    assert g, "gate.js trivy find not found; update this extraction with it"
    gate_find = g.group(1).replace("<w>/tree", "<repo_root>").replace("\\\\", "\\")
    assert f"  {gate_find}\n" in body, "the fallback must run the trust gate's own find"
    # Both are lock-predicate.sh's lock_find_expr, so all three paths agree (#1358).
    expr = predicate("lock_find_expr")
    assert gate_find == f"find <repo_root> {expr}", "gate.js's find must be lock-predicate.sh's lock_find_expr"
    for layout in ("'*requirements*.txt'", "'*/requirements/*.txt'"):
        assert layout in expr, f"the predicate lost {layout}"
    assert "Any UNSCANNED lock -> the checklist item FAILS" in flat
    assert "A declaration applies only when no lock is found; any found-but-unscanned lock FAILS." in flat
    assert "a bun.lockb with a bun.lock in the same directory" in flat
    assert re.search(r"^\s+6\s+PARTIAL COVERAGE .*-> checklist$", body, re.M), "exit 6 must be in Job C's table"


def test_precheck_fallback_fails_a_declared_lone_bun_lockb(tmp_path: Path):
    """#1247, babelfish's ruling, on the fallback path: the fallback's own find,
    run over a lone bun.lockb with a declaration beside it, puts the bun.lockb
    in the denominator, and SKILL.md's rule fails a found-but-unscanned lock
    whether or not a declaration exists (the script exits 2; the gate HOLDs)."""
    body = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    m = re.search(r"^\s+(find <repo_root> .+ -print)$", body, re.M)
    assert m, "the fallback find is missing from SKILL.md"
    (tmp_path / "package.json").write_text('{"name":"p","dependencies":{"left-pad":"1.3.0"}}\n')
    (tmp_path / "bun.lockb").write_bytes(b"\x00binary\x00")
    (tmp_path / ".no-scannable-dependencies").write_text("bun.lockb only; trivy cannot read it.\n")
    cmd = m.group(1).replace("<repo_root>", shlex.quote(str(tmp_path)))
    proc = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.splitlines() == [str(tmp_path / "bun.lockb")], proc.stdout
    flat = " ".join(body.split())
    assert "A bun.lockb with NO bun.lock beside it stays in; trivy cannot parse it, so it is UNSCANNED" in flat
    assert "any found-but-unscanned lock FAILS" in flat


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
    exercised by test_stub_partial_coverage_exits_6 below.
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
    # #1358: a repo's .trivyignore or trivy.yaml must not hide a finding or a lock, and the
    # vendored trees the find prunes are skipped by trivy too (.git it never walks).
    joined = " ".join(argv)
    assert "--ignorefile /dev/null" in joined, argv
    assert "--config /dev/null" in joined, argv
    prune = predicate('printf "%s\\n" "${LOCK_PRUNE[@]}"').split()
    skips = [argv[i + 1] for i, a in enumerate(argv) if a == "--skip-dirs"]
    assert skips == [f"**/{d}" for d in prune if d != ".git"], skips


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
    # A pinned requirements file is never an empty lock (check-scannable.sh counts
    # one only with an `==` pin), so it gets its own remedy, not the delete advice.
    assert "A pinned requirements file trivy read no package from is malformed" in proc.stderr, proc.stderr
    assert "delete the empty lockfile" not in proc.stderr, proc.stderr


# A lock trivy reads but check-scannable.sh does not count. This was a poetry.lock
# until #1289 counted the Python locks; a Gemfile.lock keeps these tests about a
# Result OUTSIDE the denominator, which is what they pin.
def _gemfile_result(target: str = "Gemfile.lock") -> str:
    return f'{{"Target":"{target}","Type":"bundler","Packages":[{{"Name":"rack"}}]}}'


def _web_bun_lockb(repo: Path) -> None:
    (repo / "web").mkdir(parents=True, exist_ok=True)
    (repo / "web" / "package.json").write_text('{"name":"w","dependencies":{"left-pad":"1.3.0"}}\n')
    (repo / "web" / "bun.lockb").write_bytes(b"\x00binary\x00")


def test_a_result_outside_the_denominator_covers_no_counted_lock(tmp_path: Path):
    """babelfish's #1269 finding, its tree: a root lock check-scannable.sh does
    not count (a poetry.lock then, a Gemfile.lock since #1289 counts poetry.lock)
    and web/bun.lockb (which it does). The count-based check read trivy's 1
    Result as "1 of 1" and PASSED with the bun.lockb never scanned. By name,
    nothing counted was ingested: exit 2, the bun.lockb named, the uncounted
    lock listed but marked outside the denominator."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Gemfile.lock").write_text("GEM\n")
    _web_bun_lockb(repo)
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{_gemfile_result()}]}}'))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "coverage: 0 of 1 scannable manifest(s) ingested" in proc.stdout, proc.stdout
    assert "UNSCANNED — 1 lock(s) no scan ingested a package from:\n  - web/bun.lockb" in proc.stderr, proc.stderr
    assert "Gemfile.lock  (bundler, 1 packages, 0 finding(s); NOT in the denominator, so it covers no counted lock)" in proc.stdout, proc.stdout
    assert "1 trivy Result(s) outside the denominator: listed, never counted toward coverage" in proc.stdout, proc.stdout
    assert "bun's text lockfile, bun.lock" in proc.stderr, proc.stderr
    assert "PASS" not in proc.stdout


def test_a_result_outside_the_denominator_with_a_counted_lock_ingested_exits_6(tmp_path: Path):
    """The same tree with a pinned requirements.txt that trivy does ingest: some
    counted locks ingested, one UNSCANNED, so PARTIAL COVERAGE (6)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Gemfile.lock").write_text("GEM\n")
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    _web_bun_lockb(repo)
    flask = '{"Target":"requirements.txt","Type":"pip","Packages":[{"Name":"flask"}]}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{_gemfile_result()},{flask}]}}'))
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "coverage: 1 of 2 scannable manifest(s) ingested" in proc.stdout, proc.stdout
    assert "FAIL — PARTIAL COVERAGE: 1 of 2 scannable manifest(s) ingested, 1 lock(s) UNSCANNED" in proc.stderr, proc.stderr
    assert "  - web/bun.lockb" in proc.stderr, proc.stderr


def test_a_finding_outside_the_denominator_still_fails_first(tmp_path: Path):
    """A Result outside the denominator covers no counted lock, but its CVEs are
    real: findings count from every Result, and exit 1 comes before the
    zero-ingested exit 2, so the CVE is reported rather than hidden behind it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "Gemfile.lock").write_text("GEM\n")
    _web_bun_lockb(repo)
    vuln = '"Vulnerabilities":[{"PkgName":"rack","VulnerabilityID":"CVE-9999-3","Severity":"CRITICAL","FixedVersion":"2.2.8"}]'
    gemfile = f'{{"Target":"Gemfile.lock","Type":"bundler","Packages":[{{"Name":"rack"}}],{vuln}}}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{gemfile}]}}'))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "rack | CVE-9999-3 | CRITICAL | 2.2.8" in proc.stderr, proc.stderr
    assert "  - web/bun.lockb" in proc.stderr, "the UNSCANNED lock is still named before the verdict"


def test_a_result_with_no_packages_does_not_ingest_its_lock(tmp_path: Path):
    """A lock is INGESTED only when a Result names it AND carries a package, the
    rule the gate and the fallback already state. An empty Packages list is a
    lock read as nothing, so it is UNSCANNED."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "web").mkdir()
    (repo / "web" / "package.json").write_text('{"name":"w","dependencies":{"left-pad":"1.3.0"}}\n')
    (repo / "web" / "bun.lock").write_text('{"lockfileVersion":1,"packages":{}}\n')
    flask = '{"Target":"requirements.txt","Type":"pip","Packages":[{"Name":"flask"}]}'
    empty = '{"Target":"web/bun.lock","Type":"bun","Packages":[]}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{flask},{empty}]}}'))
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "UNSCANNED — 1 lock(s) no scan ingested a package from:\n  - web/bun.lock" in proc.stderr, proc.stderr


def test_a_go_module_is_ingested_under_its_go_mod(tmp_path: Path):
    """check-scannable.sh counts the go.sum, and trivy names the module by the
    go.mod beside it (measured, trivy 0.74.0: the Target is the go.mod path,
    never the go.sum). Either name covers the lock."""
    repo = tmp_path / "repo"
    (repo / "svc").mkdir(parents=True)
    (repo / "svc" / "go.mod").write_text("module example.com/m\n\ngo 1.21\n")
    (repo / "svc" / "go.sum").write_text("golang.org/x/text v0.3.7 h1:x=\n")
    gomod = '{"Target":"svc/go.mod","Type":"gomod","Packages":[{"Name":"golang.org/x/text"}]}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{gomod}]}}'))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "coverage: 1 of 1 scannable manifest(s) ingested" in proc.stdout, proc.stdout
    assert "NOT in the denominator" not in proc.stdout, proc.stdout


# --- #1289: the Python locks ----------------------------------------------------
# A repo whose only lock was a uv.lock read "0 scannable": no count, no scan. Each
# lock below is one trivy 0.74.0 was measured to ingest (Type per lock), so each
# alone must be counted, scanned and passed when clean.
PY_LOCKS = {"uv.lock": "uv", "poetry.lock": "poetry", "Pipfile.lock": "pipenv"}


@pytest.mark.parametrize("rel", [*PY_LOCKS, "py/uv.lock", "svc/poetry.lock", "app/Pipfile.lock"])
def test_a_lone_python_lock_is_counted_and_ingested(tmp_path: Path, rel: str):
    repo = tmp_path / "repo"
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text("version = 1\n")
    rtype = PY_LOCKS[Path(rel).name]
    result = f'{{"Target":"{rel}","Type":"{rtype}","Packages":[{{"Name":"six"}}]}}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{result}]}}'))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"  [scannable] ./{rel}\n" in proc.stdout, "check-scannable.sh must count it"
    assert "coverage: 1 of 1 scannable manifest(s) ingested" in proc.stdout, proc.stdout
    assert "NOT in the denominator" not in proc.stdout, proc.stdout
    assert "dependency-scan: PASS" in proc.stdout, proc.stdout


def test_a_python_lock_trivy_reads_nothing_from_is_unscanned(tmp_path: Path):
    """Counting the lock makes it a lock the scan must cover: a Result with no
    packages leaves it UNSCANNED (exit 2), never a pass over nothing."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text("version = 1\n")
    empty = '{"Target":"uv.lock","Type":"uv","Packages":[]}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{empty}]}}'))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "UNSCANNED — 1 lock(s) no scan ingested a package from:\n  - uv.lock" in proc.stderr, proc.stderr


# Minimal real locks, one clean package each (six 1.16.0: no advisories). The real
# trivy test below proves the pinned scanner ingests every lock check-scannable.sh
# counts by this rule, so a trivy that stops reading one fails here, not in the
# field as an UNSCANNED lock with no way to clear it.
_SIX_SDIST = (
    "https://files.pythonhosted.org/packages/source/s/six/six-1.16.0.tar.gz",
    "sha256:1e61c37477a1626458e36f7b1d82aa5c9b094fa4802892072e49de9c60c4c926",
)
REAL_PY_LOCKS = {
    "uv.lock": (
        'version = 1\nrequires-python = ">=3.8"\n\n'
        '[[package]]\nname = "demo"\nversion = "0.1.0"\nsource = { virtual = "." }\n'
        'dependencies = [\n    { name = "six" },\n]\n\n'
        '[package.metadata]\nrequires-dist = [{ name = "six", specifier = "==1.16.0" }]\n\n'
        '[[package]]\nname = "six"\nversion = "1.16.0"\nsource = { registry = "https://pypi.org/simple" }\n'
        f'sdist = {{ url = "{_SIX_SDIST[0]}", hash = "{_SIX_SDIST[1]}" }}\n'
    ),
    "poetry.lock": (
        "[[package]]\n"
        'name = "six"\nversion = "1.16.0"\ndescription = "Python 2 and 3 compatibility utilities"\n'
        'optional = false\npython-versions = ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*"\n'
        f'files = [\n    {{file = "six-1.16.0.tar.gz", hash = "{_SIX_SDIST[1]}"}},\n]\n\n'
        '[metadata]\nlock-version = "2.0"\npython-versions = "^3.8"\n'
        'content-hash = "0000000000000000000000000000000000000000000000000000000000000000"\n'
    ),
    "Pipfile.lock": json.dumps({
        "_meta": {"hash": {"sha256": "0" * 64}, "pipfile-spec": 6, "requires": {"python_version": "3.8"},
                  "sources": [{"name": "pypi", "url": "https://pypi.org/simple", "verify_ssl": True}]},
        "default": {"six": {"hashes": [_SIX_SDIST[1]], "version": "==1.16.0"}},
        "develop": {},
    }, indent=4) + "\n",
}


@trivy_required
@pytest.mark.parametrize("name", sorted(REAL_PY_LOCKS))
def test_the_pinned_trivy_ingests_each_counted_python_lock(tmp_path: Path, name: str):
    """No stub: the installed trivy (CI pins 0.74.0) reads a real lock of each
    counted Python type, alone, and the scan passes 1 of 1."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / name).write_text(REAL_PY_LOCKS[name])
    proc = run(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "coverage: 1 of 1 scannable manifest(s) ingested" in proc.stdout, proc.stdout
    assert re.search(rf"^  - {re.escape(name)}  \({PY_LOCKS[name]}, [1-9]\d* packages", proc.stdout, re.M), proc.stdout


def test_lock_lists_agree():
    """#1289, #1358: the lock names live in lock-predicate.sh, which the scripts
    source. The Workflow bundle is one self-contained file, and the /precheck
    fallback runs in repos that carry no scripts/ci, so their finds are
    generated copies (gen-lock-find.sh). This holds the copies to LOCK_NAMES.
    dependency-scan.sh has no list: its denominator is check-scannable.sh's
    `[scannable]` lines, by name."""
    counted = set(predicate('printf "%s\\n" "${LOCK_NAMES[@]}"').split())
    assert {"uv.lock", "poetry.lock", "Pipfile.lock"} <= counted, counted
    assert "pdm.lock" not in counted, "trivy 0.74.0 cannot read pdm.lock (#1289); re-measure before adding it"

    def find_names(find: str) -> set[str]:
        # Quoted -name operands are lock names; the prune list is unquoted, and
        # the requirements patterns are globs.
        return {n for n in re.findall(r"-name '([^']+)'", find) if "*" not in n}

    gate = (REPO_ROOT / "skills" / "nextwave" / "gate.js").read_text()
    g = re.search(r"^    `  (find <w>/tree .+ -print)`,$", gate, re.M)
    assert g, "gate.js trivy find not found; update this extraction with it"
    body = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    s = re.search(r"^\s+(find <repo_root> .+ -print)$", body, re.M)
    assert s, "the fallback find is missing from SKILL.md"
    assert find_names(g.group(1)) == counted, f"gate.js find {sorted(find_names(g.group(1)))} != LOCK_NAMES {sorted(counted)}"
    assert find_names(s.group(1)) == counted, f"SKILL.md find {sorted(find_names(s.group(1)))} != LOCK_NAMES {sorted(counted)}"


def test_a_package_lock_beside_a_bun_lockb_fails_on_all_three_paths(tmp_path: Path):
    """One rule for a bun.lockb with no bun.lock beside it, on every path: it is
    in the denominator and UNSCANNED, even beside a lock trivy reads. Only bun.lock
    is the same packages in another format; a package-lock.json is another tool's
    resolution, so it is no stand-in.

    - script: check-scannable.sh counts both locks in web/ (lock-centric, #1358),
      trivy reads only the package-lock.json, so by name the bun.lockb is
      UNSCANNED (6), 2 of 3;
    - gate: its own find puts both in the denominator, exclusion (2) leaves the
      bun.lockb in, and trivyCoverage() HOLDs the counts that follow;
    - fallback: the same find, and any UNSCANNED lock FAILS."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    _web_bun_lockb(repo)
    (repo / "web" / "package-lock.json").write_text('{"name":"w","lockfileVersion":3,"packages":{}}\n')
    flask = '{"Target":"requirements.txt","Type":"pip","Packages":[{"Name":"flask"}]}'
    npm = '{"Target":"web/package-lock.json","Type":"npm","Packages":[{"Name":"left-pad"}]}'
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{flask},{npm}]}}'))
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "  - web/bun.lockb" in proc.stderr, proc.stderr
    assert "  - web/package-lock.json  (npm, 1 packages, 0 finding(s))\n" in proc.stdout, proc.stdout
    assert "coverage: 2 of 3 scannable manifest(s) ingested" in proc.stdout, proc.stdout

    body = (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()
    m = re.search(r"^\s+(find <repo_root> .+ -print)$", body, re.M)
    assert m, "the fallback find is missing from SKILL.md"
    cmd = m.group(1).replace("<repo_root>", shlex.quote(str(repo)))
    found = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30).stdout.split()
    rel = sorted(str(Path(p).relative_to(repo)) for p in found)
    assert rel == ["requirements.txt", "web/bun.lockb", "web/package-lock.json"], rel
    flat = " ".join(body.split())
    assert "(2) a bun.lockb with a bun.lock in the same directory" in flat, "only a bun.lock beside it excludes a bun.lockb"
    assert "Any UNSCANNED lock -> the checklist item FAILS" in flat

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the gate leg needs it")
    gate = (REPO_ROOT / "skills" / "nextwave" / "gate.js").as_uri()
    sig = '{"signal":"trivy","passed":true,"detail":"0 HIGH/CRITICAL","found":3,"ingested":2,"unscanned":["web/bun.lockb"],"declared":false}'
    js = f"import({json.dumps(gate)}).then(m => console.log(JSON.stringify(m.trivyCoverage({sig}))))"
    verdict = json.loads(subprocess.run([node, "--input-type=module", "-e", js], capture_output=True, text=True, timeout=30, check=True).stdout)
    assert verdict["passed"] is False, verdict
    assert "UNSCANNED: web/bun.lockb" in verdict["detail"], verdict


def test_a_denominator_that_cannot_be_read_by_name_exits_5(tmp_path: Path):
    """Coverage by name needs check-scannable.sh's lock lines to be the set it
    counted. If the two disagree, the names are not the denominator: a tooling
    error (5), never a verdict."""
    ci = tmp_path / "ci"
    ci.mkdir()
    shutil.copy(SCRIPT, ci / "dependency-scan.sh")
    shutil.copy(PREDICATE, ci / "lock-predicate.sh")
    (ci / "check-scannable.sh").write_text(
        "#!/usr/bin/env bash\n"
        'echo "check-scannable: 2 scannable manifest(s) in $1"\n'
        'echo "  [scannable] ./requirements.txt — 1 pinned entry"\n'
    )
    repo = _scannable_repo(tmp_path)
    proc = subprocess.run(
        ["bash", str(ci / "dependency-scan.sh"), str(repo)],
        capture_output=True, text=True, timeout=120, env=_stub_trivy(tmp_path, CLEAN_JSON),
    )
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "could not read check-scannable.sh's 2 scannable lock(s) by name" in proc.stderr, proc.stderr


def test_an_unreadable_scannable_count_exits_5_not_pass(tmp_path: Path):
    """The name check above compares two numbers, so it cannot see both sides
    vanish. If check-scannable.sh's summary line AND its lock lines are both
    reshaped, a count defaulted to 0 agrees with 0 names, the denominator is
    empty, and a clean trivy run PASSes over locks nobody matched. A missing
    count is unmeasured, not zero: a tooling error (5)."""
    ci = tmp_path / "ci"
    ci.mkdir()
    shutil.copy(SCRIPT, ci / "dependency-scan.sh")
    shutil.copy(PREDICATE, ci / "lock-predicate.sh")
    (ci / "check-scannable.sh").write_text(
        "#!/usr/bin/env bash\n"
        'echo "check-scannable v2: found 1 lock in $1"\n'
        'echo "  * requirements.txt (1 pinned)"\n'
    )
    repo = _scannable_repo(tmp_path)
    proc = subprocess.run(
        ["bash", str(ci / "dependency-scan.sh"), str(repo)],
        capture_output=True, text=True, timeout=120, env=_stub_trivy(tmp_path, CLEAN_JSON),
    )
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "could not read check-scannable.sh's scannable count" in proc.stderr, proc.stderr
    assert "PASS" not in proc.stdout, proc.stdout


def test_a_declaration_does_not_rescue_a_lone_bun_lockb(tmp_path: Path):
    """#1247, babelfish's ruling: a declaration applies only when no lock is
    found, on all three paths. A lone bun.lockb is a found lock trivy cannot
    parse, so a .no-scannable-dependencies beside it is a contradiction, not a
    rescue: the script exits 2, as the trust gate HOLDs and the fallback FAILS.
    The message must not send the operator to the declaration that cannot help."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"name":"p","dependencies":{"left-pad":"1.3.0"}}\n')
    (repo / "bun.lockb").write_bytes(b"\x00binary\x00")
    (repo / ".no-scannable-dependencies").write_text("bun.lockb only; trivy cannot read it.\n")
    proc = _run_env(repo, _stub_trivy(tmp_path, '{"Results":[]}'))
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 2, combined
    assert "ingested ZERO" in combined
    assert "bun's text lockfile, bun.lock" in proc.stderr, proc.stderr
    assert "delete the empty lockfile" not in proc.stderr, "a bun.lockb is not an empty lock"
    assert "declaration does not rescue a lock that is still\n  here: it covers only a repo where no lock is found" in proc.stderr, proc.stderr
    assert "PASS" not in proc.stdout


def test_a_dependency_free_lock_names_the_real_escape(tmp_path: Path):
    """#1247 (babelfish: 2a). trivy 0.74.0 emits no Result at all for a
    dependency-free package-lock.json (measured), so it exits 2 like an
    unparseable lock. The old advice, "use bun.lock, not bun.lockb", sent the
    operator nowhere. The escape is deleting the empty lockfile, and the next
    test proves that escape passes."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"name":"y","version":"1.0.0"}\n')
    (repo / "package-lock.json").write_text(
        '{"name":"y","version":"1.0.0","lockfileVersion":3,"requires":true,'
        '"packages":{"":{"name":"y","version":"1.0.0"}}}\n'
    )
    proc = _run_env(repo, _stub_trivy(tmp_path, '{"Results":[]}'))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "If the package has no dependencies,\n  delete the empty lockfile: there is nothing to lock." in proc.stderr, proc.stderr
    assert "bun.lockb is bun's old binary format" not in proc.stderr, "no bun.lockb here"


def test_a_mixed_zero_ingested_repo_names_both_escapes(tmp_path: Path):
    """A lone bun.lockb in one package and a dependency-free package-lock.json
    in another: each lock gets its own remedy, so both blocks print."""
    repo = tmp_path / "repo"
    (repo / "a").mkdir(parents=True)
    (repo / "b").mkdir()
    (repo / "a" / "package.json").write_text('{"name":"a","dependencies":{"left-pad":"1.3.0"}}\n')
    (repo / "a" / "bun.lockb").write_bytes(b"\x00binary\x00")
    (repo / "b" / "package.json").write_text('{"name":"b","version":"1.0.0"}\n')
    (repo / "b" / "package-lock.json").write_text(
        '{"name":"b","version":"1.0.0","lockfileVersion":3,"requires":true,'
        '"packages":{"":{"name":"b","version":"1.0.0"}}}\n'
    )
    proc = _run_env(repo, _stub_trivy(tmp_path, '{"Results":[]}'))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "bun's text lockfile, bun.lock" in proc.stderr, proc.stderr
    assert "delete the empty lockfile: there is nothing to lock." in proc.stderr, proc.stderr


def test_the_named_escape_passes(tmp_path: Path):
    """The escape the exit-2 message names works: with the empty lockfile
    deleted, check-scannable finds no lock, so a declaration applies and the
    run passes. Advice that leads to another failure is not an escape."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "package.json").write_text('{"name":"y","version":"1.0.0"}\n')
    (repo / ".no-scannable-dependencies").write_text("No dependencies; package.json carries metadata only.\n")
    proc = _run_env(repo, _stub_trivy(tmp_path, '{"Results":[]}'))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "absence is DECLARED" in proc.stdout, proc.stdout
    assert "dependency-scan: PASS" in proc.stdout, proc.stdout


def test_stub_partial_coverage_exits_6(tmp_path: Path):
    """SOME manifests ingested, not all — the common case, distinct from the
    zero-ingested extreme above.

    #1247: this used to exit 0 with a COVERS note, but Job C and the autochain
    gate both read exit 0 as PASS, so /precheck passed the very shape the trust
    gate's trivyCoverage() HOLDs. A partial run now exits 6, which fails.

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
    assert proc.returncode == 6, (
        f"partial coverage must FAIL with its own code, not pass with a note\n"
        f"{proc.stdout}{proc.stderr}"
    )
    assert "coverage: 1 of 2" in proc.stdout, proc.stdout
    assert "WARNING" in proc.stdout + proc.stderr, "shortfall must not be silent"
    assert "UNSCANNED — 1 lock(s) no scan ingested a package from:\n  - sub/requirements.txt" in proc.stderr, proc.stderr
    assert "FAIL — PARTIAL COVERAGE: 1 of 2 scannable manifest(s) ingested, 1 lock(s) UNSCANNED" in proc.stderr, proc.stderr
    assert "PASS" not in proc.stdout, "a partial run must print no PASS verdict"


def test_a_lone_bun_lockb_beside_a_pip_lock_exits_6(tmp_path: Path):
    """babelfish's #1269 review case: trivy cannot parse bun.lockb, so a pinned
    requirements.txt beside one used to read `PASS … (COVERS 1/2)` with rc 0.
    Coverage is by name, so the bun.lockb itself is named UNSCANNED."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "package.json").write_text('{"name":"p","dependencies":{"left-pad":"1.3.0"}}\n')
    (repo / "bun.lockb").write_bytes(b"\x00binary\x00")
    proc = _run_env(repo, _stub_trivy(tmp_path, CLEAN_JSON))
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "UNSCANNED — 1 lock(s) no scan ingested a package from:\n  - bun.lockb" in proc.stderr, proc.stderr
    assert "FAIL — PARTIAL COVERAGE: 1 of 2 scannable manifest(s) ingested, 1 lock(s) UNSCANNED (named above). An unscanned lock is not a clean one." in proc.stderr, proc.stderr


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
    """The honest denominator: the shortfall names the file, and the run fails."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    (repo / "requirements-odd.txt").write_text("nothing==1.0\n")
    main = f'{{"Results":[{_pip("requirements.txt", "flask")}]}}'
    proc = _run_env(repo, _routing_stub(tmp_path, main, SIBLING_TWO))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 6, out
    assert "coverage: 1 of 2" in proc.stdout, out
    assert "UNSCANNED — 1 lock(s) no scan ingested a package from:\n  - requirements-odd.txt" in proc.stderr, out
    assert "1 lock(s) UNSCANNED (named above)" in proc.stderr, out


@pytest.mark.parametrize(
    "layout",
    ["dev-requirements.txt", "requirements/base.txt", "app/requirements/test.txt"],
)
def test_other_pip_lock_layouts_are_counted_and_scanned_alone(tmp_path: Path, layout: str):
    """#1247: the prefix form and the pip-tools requirements/<name>.txt layout
    were invisible on every path (no count, no scan, no report) because the
    match was the basename glob `requirements*.txt`. check-scannable.sh's
    REQ_FIND now matches them, so each is counted and scanned alone like any
    other pip lock trivy will not read under its own name."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("flask==3.0.0\n")
    lock = repo / layout
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text("pytest==8.0.0\nwheel==0.43.0\n")
    main = f'{{"Results":[{_pip("requirements.txt", "flask")}]}}'
    proc = _run_env(repo, _routing_stub(tmp_path, main, SIBLING_TWO))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "coverage: 2 of 2 scannable manifest(s) ingested" in proc.stdout, out
    assert f"{layout}  (pip, 2 packages, 0 finding(s); scanned alone as requirements.txt)" in proc.stdout, out
    calls = (tmp_path / "calls.log").read_text()
    assert "SIBLING\npytest==8.0.0\nwheel==0.43.0\n" in calls, calls


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


# ── #1358: one lock predicate, on all three paths ───────────────────────────────


def _skill_body() -> str:
    return (REPO_ROOT / "skills" / "precheck" / "SKILL.md").read_text()


def _skill_find(root: Path) -> list[str]:
    """Run the SKILL.md fallback's find line on `root`; paths relative to it."""
    m = re.search(r"^\s+(find <repo_root> .+ -print)$", _skill_body(), re.M)
    assert m, "the fallback find is missing from SKILL.md"
    cmd = m.group(1).replace("<repo_root>", shlex.quote(str(root)))
    out = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30).stdout.split("\n")
    return sorted(str(Path(p).relative_to(root)) for p in out if p)


def _three_path_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    for d in ("web", "b", "g", "c", "bb", "node_modules/x"):
        (repo / d).mkdir(parents=True)
    (repo / "web" / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}\n')
    (repo / "web" / "yarn.lock").write_text("# yarn lockfile v1\n")
    (repo / "b" / "bun.lock").write_text("{}\n")
    (repo / "g" / "go.sum").write_text("example.com/m v1.0.0 h1:x=\n")
    (repo / "c" / "Cargo.lock").write_text("version = 3\n")
    (repo / "bb" / "bun.lock").write_text("{}\n")
    (repo / "bb" / "bun.lockb").write_bytes(b"\x00bun\x00")
    (repo / "requirements.lock").write_text("flask==3.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n")
    (repo / "dev-requirements.lock").write_text("flask>=3\n")
    (repo / "constraints.txt").write_text("six==1.16.0\n")
    (repo / "node_modules" / "x" / "yarn.lock").write_text("# vendored\n")
    return repo


def test_three_paths_count_the_same_locks(tmp_path: Path):
    """check-scannable.sh's [scannable] set equals the SKILL.md find, less its two
    exclusions (an unpinned requirements file; a bun.lockb with a bun.lock beside
    it), and the gate's find prints exactly what SKILL.md's does."""
    repo = _three_path_fixture(tmp_path)
    cs = subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "ci" / "check-scannable.sh"), str(repo)],
        capture_output=True, text=True, timeout=60,
    )
    assert cs.returncode == 0, cs.stdout + cs.stderr
    script_set = sorted(re.findall(r"^  \[scannable\] \./(\S+)", cs.stdout, re.M))

    found = _skill_find(repo)
    pin_re = predicate('printf %s "$PIN_RE"')
    names = set(predicate('printf "%s\\n" "${LOCK_NAMES[@]}"').split())

    def excluded(rel: str) -> bool:
        p = repo / rel
        if p.name not in names:  # a requirements file: out when nothing is pinned
            return subprocess.run(["grep", "-cE", pin_re, str(p)], capture_output=True, text=True).stdout.strip() == "0"
        return p.name == "bun.lockb" and (p.parent / "bun.lock").exists()

    prose_set = sorted(r for r in found if not excluded(r))
    assert prose_set == script_set, f"SKILL.md {prose_set} != check-scannable.sh {script_set}"
    assert script_set == [
        "b/bun.lock", "bb/bun.lock", "c/Cargo.lock", "constraints.txt", "g/go.sum",
        "requirements.lock", "web/package-lock.json", "web/yarn.lock",
    ], script_set
    assert not any(r.startswith("node_modules/") for r in found), "a vendored lock leaked in"

    gate = (REPO_ROOT / "skills" / "nextwave" / "gate.js").read_text()
    g = re.search(r"^    `  (find <w>/tree .+ -print)`,$", gate, re.M)
    assert g, "gate.js trivy find not found"
    cmd = g.group(1).replace("\\\\", "\\").replace("<w>/tree", shlex.quote(str(repo)))
    gate_found = sorted(str(Path(p).relative_to(repo)) for p in subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=30).stdout.split("\n") if p)
    assert gate_found == found, "the gate's find and the fallback's find must print the same locks"


def test_lock_names_cover_every_manifest_lock():
    names = set(predicate('printf "%s\\n" "${LOCK_NAMES[@]}"').split())
    for entry in predicate('printf "%s\\n" "${MANIFEST_LOCKS[@]}"').split():
        for lock in entry.split(":", 1)[1].split(","):
            assert lock in names, f"MANIFEST_LOCKS names {lock}, which LOCK_NAMES does not count"


def _npm(target: str) -> str:
    return f'{{"Target":"{target}","Type":"npm","Packages":[{{"Name":"left-pad"}}]}}'


def test_a_second_js_lock_is_counted(tmp_path: Path):
    """A yarn.lock beside a package-lock.json is counted, not paired away (#1358):
    trivy reading only the package-lock.json leaves the yarn.lock UNSCANNED (6)."""
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    (repo / "web" / "package-lock.json").write_text('{"lockfileVersion":3,"packages":{}}\n')
    (repo / "web" / "yarn.lock").write_text("# yarn lockfile v1\n")
    proc = _run_env(repo, _stub_trivy(tmp_path, f'{{"Results":[{_npm("web/package-lock.json")}]}}'))
    assert proc.returncode == 6, proc.stdout + proc.stderr
    assert "  - web/yarn.lock" in proc.stderr, proc.stderr
    assert "coverage: 1 of 2 scannable manifest(s) ingested" in proc.stdout, proc.stdout


def test_a_hash_locked_requirements_lock_is_scanned_alone(tmp_path: Path):
    """requirements.lock (pins + --hash lines) and constraints.txt are pip locks
    trivy reads only as requirements.txt, so each is scanned alone: 2 of 2."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.lock").write_text("flask==3.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n")
    (repo / "constraints.txt").write_text("six==1.16.0\n")
    proc = _run_env(repo, _routing_stub(tmp_path, '{"Results":[]}', f'{{"Results":[{_pip("requirements.txt", "x")}]}}'))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    assert "coverage: 2 of 2 scannable manifest(s) ingested" in proc.stdout, out
    for name in ("requirements.lock", "constraints.txt"):
        assert f"{name}  (pip, 1 packages, 0 finding(s); scanned alone as requirements.txt)" in proc.stdout, out
    assert (tmp_path / "calls.log").read_text().count("SIBLING") == 2


@trivy_required
def test_the_pinned_trivy_ingests_a_hash_locked_requirements_lock(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.lock").write_text(
        "flask==3.0.0 \\\n    --hash=sha256:" + "a" * 64 + "\n"
        "click==8.1.7 \\\n    --hash=sha256:" + "b" * 64 + "\n"
    )
    proc = run(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "coverage: 1 of 1 scannable manifest(s) ingested" in proc.stdout, proc.stdout
    assert re.search(r"^  - requirements\.lock  \(pip, 2 packages", proc.stdout, re.M), proc.stdout


@trivy_required
def test_a_committed_trivyignore_or_trivy_yaml_suppresses_nothing(tmp_path: Path):
    """trivy reads .trivyignore and trivy.yaml from the CURRENT DIRECTORY. Run
    from inside a repo carrying them, the scan must still find what is there."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "requirements.txt").write_text("django==2.2.0\n")
    raw = subprocess.run(
        ["trivy", "fs", "--scanners", "vuln", "--severity", "HIGH,CRITICAL", "--format", "json", "--quiet", str(repo)],
        capture_output=True, text=True, timeout=300, cwd=tmp_path,
    )
    ids = sorted({v["VulnerabilityID"] for r in json.loads(raw.stdout).get("Results", []) for v in r.get("Vulnerabilities") or []})
    assert ids, "django 2.2.0 should carry HIGH/CRITICAL advisories; the fixture proves nothing without them"

    (repo / ".trivyignore").write_text("\n".join(ids) + "\n")
    proc = subprocess.run(["bash", str(SCRIPT), str(repo)], capture_output=True, text=True, timeout=300, cwd=repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    (repo / ".trivyignore").unlink()

    (repo / "trivy.yaml").write_text("scan:\n  skip-files:\n    - requirements.txt\n")
    proc = subprocess.run(["bash", str(SCRIPT), str(repo)], capture_output=True, text=True, timeout=300, cwd=repo)
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_prose_exclusion_names_exactly_the_lock_names():
    """Exclusion (1) tells a requirements file from a lock by name, as is_req_file
    does. The prose names the locks outright, because "not one of the find's -name
    files" reads `requirements.lock`, itself a -name match, as a lock (#1358 review)."""
    names = predicate('printf "%s\\n" "${LOCK_NAMES[@]}"').split()
    line = ", ".join(names) + ";"
    gate = (REPO_ROOT / "skills" / "nextwave" / "gate.js").read_text()
    for where, text in (("gate.js", gate), ("SKILL.md", _skill_body())):
        # The list opens its own line in both files. Anchoring there is what fails a list whose
        # leading names drifted out of LOCK_NAMES; a bare substring would still match.
        assert re.search(r"(?m)^[ \t`]*" + re.escape(line), text), f"{where} exclusion (1) must name exactly LOCK_NAMES: {line}"
        assert "requirements.lock" in " ".join(text.split()).split(line, 1)[1][:120], f"{where} must say requirements.lock is a requirements file"


def test_every_prose_trivy_run_disables_ignore_and_config():
    runs = [ln for ln in _skill_body().splitlines() if "trivy fs " in ln and ln.lstrip().startswith(("trivy fs ", "d=$(mktemp"))]
    assert len(runs) >= 2, f"expected the main and the per-file fallback scans, found {runs}"
    for ln in runs:
        assert "--ignorefile /dev/null --config /dev/null" in ln, ln


def test_a_summary_over_the_pipe_buffer_does_not_false_fail(tmp_path: Path):
    """A summary bigger than the 64 KiB pipe buffer: piped into `grep -q` under
    pipefail it read as "no COUNTS line" and exited 5 every run (#1358)."""
    repo = _scannable_repo(tmp_path)
    many = ",".join(_npm(f"pkg{i:04d}/very/long/path/to/a/vendored/package/lock/package-lock.json") for i in range(1500))
    payload = f'{{"Results":[{_pip("requirements.txt", "flask")},{many}]}}'
    proc = _run_env(repo, _stub_trivy(tmp_path, payload))
    assert len(proc.stdout) > 65536, f"the summary is only {len(proc.stdout)} bytes; it proves nothing under the pipe buffer"
    assert proc.returncode == 0, proc.stderr
    assert "coverage: 1 of 1 scannable manifest(s) ingested" in proc.stdout


def test_an_exit_5_keeps_the_raw_output(tmp_path: Path):
    repo = _scannable_repo(tmp_path)
    keep = tmp_path / "keep"
    keep.mkdir()
    env = {**_stub_trivy(tmp_path, "{not json"), "DEP_SCAN_KEEP_DIR": str(keep)}
    proc = _run_env(repo, env)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    m = re.search(r"raw scanner output kept at (\S+)", proc.stderr)
    assert m, proc.stderr
    kept = Path(m.group(1))
    assert kept.parent == keep, kept
    for f in ("main.json", "trivy.err", "summary.txt"):
        assert (kept / f).is_file(), f"{f} not kept: {sorted(p.name for p in kept.iterdir())}"


def test_no_tested_pipeline_reads_the_summary():
    assert "printf '%s' \"$summary\" |" not in SCRIPT.read_text(), "never pipe the summary (#1358)"


def test_measured_trivy_version_is_the_pinned_one():
    """Every trivy version a comment says was measured is the one CI pins."""
    pin = re.search(r'TRIVY_VERSION:\s*"([\d.]+)"', (REPO_ROOT / ".github" / "workflows" / "validate.yml").read_text())
    assert pin
    seen = 0
    for name in ("check-scannable.sh", "lock-predicate.sh", "dependency-scan.sh"):
        for v in re.findall(r"trivy (\d+\.\d+\.\d+)", (REPO_ROOT / "scripts" / "ci" / name).read_text()):
            seen += 1
            assert v == pin.group(1), f"{name} names trivy {v}; CI pins {pin.group(1)}"
    assert seen, "no measured trivy version found; the test is vacuous"
