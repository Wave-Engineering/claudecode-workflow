"""Tests for scripts/testing/wave-fixture-gen.py — synthetic fixture generator.

Exercises real git operations against temp repos.  No mocking of git or the
filesystem — the script-under-test manipulates git branches directly, so
the tests do too.  This follows the Flight Agent rule that tests should
exercise real code paths with mocks only for true external boundaries.

Covers:
    * Every scenario produces the expected branches + epic payload JSON
    * Every scenario is deterministic (same inputs → same commit SHAs)
    * cleanup removes all fixture branches and the artifact dir
    * cleanup is idempotent (no error when there's nothing to clean)
    * CLI surface — help text, subcommand dispatch, error on missing repo
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_GEN_PATH = REPO_ROOT / "scripts" / "testing" / "wave-fixture-gen.py"


# ---------------------------------------------------------------------------
# Module loader — import the script as a module despite its hyphenated name
# ---------------------------------------------------------------------------


def _import_fixture_gen():
    """Import wave-fixture-gen.py as a module (it has a hyphen in the name).

    Registers the module in sys.modules before exec_module so that the
    @dataclass decorator inside can resolve its own module via
    sys.modules[cls.__module__] — otherwise dataclass raises AttributeError
    in Python 3.12's _is_type helper.
    """
    spec = importlib.util.spec_from_file_location(
        "wave_fixture_gen", FIXTURE_GEN_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["wave_fixture_gen"] = module
    spec.loader.exec_module(module)
    return module


wfg = _import_fixture_gen()


# ---------------------------------------------------------------------------
# Git repo fixture
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(cwd), *args],
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Initialize a fresh git repo at tmp_path with main as the default branch."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "--initial-branch=main")
    # Minimum local identity so any fallback commits (not through fixture-gen)
    # still work.  The script itself overrides these for its own commits.
    _git(repo, "config", "user.name", "Test Runner")
    _git(repo, "config", "user.email", "test@example.invalid")
    # Seed an initial commit on main so we can branch from it.
    (repo / "README.md").write_text("# test repo\n")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "initial")
    return repo


@pytest.fixture()
def all_scenarios() -> list[str]:
    return [
        "conflicting-functions",
        "trivy-dep-vuln",
        "critical-code-smell",
        "rebase-conflict-setup",
    ]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def test_scenarios_registry_matches_expected(all_scenarios: list[str]) -> None:
    """The SCENARIOS dict must cover exactly the four documented scenarios."""
    assert set(wfg.SCENARIOS.keys()) == set(all_scenarios)
    # Every registry value must be callable
    for name, fn in wfg.SCENARIOS.items():
        assert callable(fn), f"scenario {name} is not callable"


def test_epoch_seconds_for_monotonic() -> None:
    """_epoch_seconds_for(step) must be strictly increasing in step."""
    prev = wfg._epoch_seconds_for(0)
    for i in range(1, 5):
        cur = wfg._epoch_seconds_for(i)
        assert cur > prev, f"step {i} not monotonic"
        prev = cur


def test_repo_arg_to_path_rejects_nonexistent(tmp_path: Path) -> None:
    """--repo must fail fast on a missing path."""
    with pytest.raises(SystemExit) as exc_info:
        wfg._repo_arg_to_path(str(tmp_path / "does-not-exist"))
    assert "does not exist" in str(exc_info.value)


def test_repo_arg_to_path_rejects_non_git_dir(tmp_path: Path) -> None:
    """--repo must fail fast if the path isn't a git repo."""
    plain = tmp_path / "plain"
    plain.mkdir()
    with pytest.raises(SystemExit) as exc_info:
        wfg._repo_arg_to_path(str(plain))
    assert "not a git repository" in str(exc_info.value)


def test_repo_arg_to_path_accepts_git_repo(git_repo: Path) -> None:
    """Happy path — an initialized repo resolves to an absolute path."""
    result = wfg._repo_arg_to_path(str(git_repo))
    assert result == git_repo.resolve()


# ---------------------------------------------------------------------------
# Per-scenario generation
# ---------------------------------------------------------------------------


def _branch_shas(repo: Path, branches: list[str]) -> dict[str, str]:
    """Resolve each branch to its HEAD SHA."""
    out = {}
    for b in branches:
        r = _git(repo, "rev-parse", b)
        out[b] = r.stdout.strip()
    return out


def test_conflicting_functions_creates_two_branches(git_repo: Path) -> None:
    repo = wfg.GitRepo(path=git_repo)
    result = wfg.scenario_conflicting_functions(repo)

    assert result.name == "conflicting-functions"
    assert len(result.created_branches) == 2
    for branch in result.created_branches:
        assert branch.startswith("wave-fixture/conflicting-functions/")
        # Each branch must exist in git
        assert repo.ref_exists(branch)

    # The shared file must exist on both branches with different bodies
    a, b = result.created_branches
    a_body = _git(git_repo, "show", f"{a}:src/fixture_target.py").stdout
    b_body = _git(git_repo, "show", f"{b}:src/fixture_target.py").stdout
    assert a_body != b_body
    assert "multiply" in a_body or "* 2" in a_body
    assert "add" in b_body or "+ 10" in b_body

    # Epic payload exists and parses
    payload_path = git_repo / result.epic_payload_path
    payload = json.loads(payload_path.read_text())
    assert payload["scenario"] == "conflicting-functions"
    assert payload["expected_signals"]["commutativity_verify"] == "WEAK"
    assert len(payload["stories"]) == 2


def test_trivy_dep_vuln_creates_one_branch_with_requirements(git_repo: Path) -> None:
    repo = wfg.GitRepo(path=git_repo)
    result = wfg.scenario_trivy_dep_vuln(repo)

    assert len(result.created_branches) == 1
    branch = result.created_branches[0]
    content = _git(git_repo, "show", f"{branch}:requirements.txt").stdout
    # Django 1.11.0 — a stable vuln pin over time
    assert "django==1.11.0" in content.lower()

    payload = json.loads((git_repo / result.epic_payload_path).read_text())
    assert payload["expected_signals"]["trivy_fs"] == "HIGH_OR_CRITICAL"


def test_critical_code_smell_creates_module_with_both_smells(git_repo: Path) -> None:
    repo = wfg.GitRepo(path=git_repo)
    result = wfg.scenario_critical_code_smell(repo)

    assert len(result.created_branches) == 1
    branch = result.created_branches[0]
    content = _git(git_repo, "show", f"{branch}:src/fixture_smell.py").stdout
    # Must contain both code-review red flags
    assert "API_KEY" in content
    assert "sk-live" in content, "hardcoded-credential smell missing"
    assert 'f"SELECT' in content, "SQL injection smell missing"

    payload = json.loads((git_repo / result.epic_payload_path).read_text())
    assert payload["expected_signals"]["code_reviewer"] == "CRITICAL"


def test_rebase_conflict_setup_branches_diverge_from_base(git_repo: Path) -> None:
    repo = wfg.GitRepo(path=git_repo)
    result = wfg.scenario_rebase_conflict_setup(repo)

    assert len(result.created_branches) == 2
    integration = next(b for b in result.created_branches if "integration" in b)
    flight_2 = next(b for b in result.created_branches if "flight-2" in b)

    # The scenario is valid iff a rebase of flight-2 onto integration would
    # actually conflict.  We verify that directly by running merge-tree, which
    # reports conflicts without mutating working tree state.
    # merge-tree <base> <branch1> <branch2> outputs conflict markers on conflict.
    merge_base = _git(
        git_repo, "merge-base", integration, flight_2
    ).stdout.strip()
    mt = subprocess.run(
        ["git", "-C", str(git_repo), "merge-tree", merge_base, integration, flight_2],
        capture_output=True,
        text=True,
    )
    # git merge-tree prints conflict hunks on stdout when there's a conflict.
    # The exact format varies by git version, but conflict markers are stable.
    assert "<<<<<<<" in mt.stdout or "changed in both" in mt.stdout, (
        f"expected conflict in merge-tree output; got: stdout={mt.stdout!r} "
        f"stderr={mt.stderr!r}"
    )

    payload = json.loads((git_repo / result.epic_payload_path).read_text())
    assert payload["expected_signals"]["rebase"] == "CONFLICT"


def test_every_scenario_leaves_base_branch_checked_out(
    tmp_path: Path, all_scenarios: list[str]
) -> None:
    """Caller's starting branch must still be checked out after generation."""
    for scenario in all_scenarios:
        repo_path = tmp_path / f"repo-{scenario}"
        repo_path.mkdir()
        _git(repo_path, "init", "-q", "--initial-branch=main")
        _git(repo_path, "config", "user.name", "Test Runner")
        _git(repo_path, "config", "user.email", "test@example.invalid")
        (repo_path / "README.md").write_text("# test\n")
        _git(repo_path, "add", "README.md")
        _git(repo_path, "commit", "-q", "-m", "initial")

        repo = wfg.GitRepo(path=repo_path)
        starting_branch = repo.current_branch()
        wfg.SCENARIOS[scenario](repo)
        assert repo.current_branch() == starting_branch, (
            f"{scenario} left us on {repo.current_branch()} "
            f"instead of {starting_branch}"
        )


# ---------------------------------------------------------------------------
# Determinism — the core property
# ---------------------------------------------------------------------------


def _run_scenario_in_fresh_repo(
    tmp_path: Path, scenario: str, suffix: str
) -> dict[str, str]:
    """Create a fresh repo, run the scenario, return {branch: sha} mapping."""
    repo_path = tmp_path / f"det-{scenario}-{suffix}"
    repo_path.mkdir()
    _git(repo_path, "init", "-q", "--initial-branch=main")
    _git(repo_path, "config", "user.name", "Test Runner")
    _git(repo_path, "config", "user.email", "test@example.invalid")
    # Use a *fixed* initial commit so branch SHAs derived from it are stable.
    (repo_path / "README.md").write_text("# det\n")
    _git(repo_path, "add", "README.md")
    # Override date/author for the initial commit too — otherwise the seed
    # commit's SHA drifts between runs and all downstream SHAs with it.
    env = {
        "GIT_AUTHOR_NAME": "Test Runner",
        "GIT_AUTHOR_EMAIL": "test@example.invalid",
        "GIT_COMMITTER_NAME": "Test Runner",
        "GIT_COMMITTER_EMAIL": "test@example.invalid",
        "GIT_AUTHOR_DATE": "@1767225500 +0000",  # before FIXTURE_EPOCH
        "GIT_COMMITTER_DATE": "@1767225500 +0000",
        "PATH": __import__("os").environ.get("PATH", ""),
    }
    subprocess.run(
        ["git", "-C", str(repo_path), "commit", "-q", "-m", "initial"],
        env=env,
        check=True,
    )

    repo = wfg.GitRepo(path=repo_path)
    result = wfg.SCENARIOS[scenario](repo)
    return _branch_shas(repo_path, result.created_branches)


@pytest.mark.parametrize(
    "scenario",
    [
        "conflicting-functions",
        "trivy-dep-vuln",
        "critical-code-smell",
        "rebase-conflict-setup",
    ],
)
def test_scenario_is_deterministic(tmp_path: Path, scenario: str) -> None:
    """Same inputs → same commit SHAs, across two independent repos."""
    first = _run_scenario_in_fresh_repo(tmp_path, scenario, "a")
    second = _run_scenario_in_fresh_repo(tmp_path, scenario, "b")
    assert first == second, (
        f"scenario {scenario} produced different SHAs across runs:\n"
        f"  run 1: {first}\n  run 2: {second}"
    )


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def test_cleanup_removes_all_generated_artifacts(
    git_repo: Path, all_scenarios: list[str]
) -> None:
    repo = wfg.GitRepo(path=git_repo)
    # Generate every scenario, then cleanup
    for scenario in all_scenarios:
        wfg.SCENARIOS[scenario](repo)

    # Pre-cleanup: branches and artifact dir exist
    pre = repo.list_branches_with_prefix(f"{wfg.BRANCH_PREFIX}/")
    assert len(pre) > 0
    assert (git_repo / wfg.ARTIFACT_DIR).is_dir()

    result = wfg.run_cleanup(repo)

    assert set(result.removed_branches) == set(pre)
    assert result.removed_artifact_dir is True
    assert repo.list_branches_with_prefix(f"{wfg.BRANCH_PREFIX}/") == []
    assert not (git_repo / wfg.ARTIFACT_DIR).exists()


def test_cleanup_is_idempotent(git_repo: Path) -> None:
    """Running cleanup twice must not error, even with nothing to remove."""
    repo = wfg.GitRepo(path=git_repo)
    # Never generate anything; cleanup should no-op cleanly.
    result = wfg.run_cleanup(repo)
    assert result.removed_branches == []
    assert result.removed_artifact_dir is False

    # After a real generation + cleanup, a second cleanup must also no-op.
    wfg.scenario_trivy_dep_vuln(repo)
    wfg.run_cleanup(repo)
    second = wfg.run_cleanup(repo)
    assert second.removed_branches == []
    assert second.removed_artifact_dir is False


def test_cleanup_handles_being_on_fixture_branch(git_repo: Path) -> None:
    """If the caller is checked out on a fixture branch, cleanup must still succeed."""
    repo = wfg.GitRepo(path=git_repo)
    result = wfg.scenario_conflicting_functions(repo)
    # Switch onto one of the fixture branches so deleting it is interesting
    _git(git_repo, "checkout", result.created_branches[0])

    cleanup = wfg.run_cleanup(repo)
    assert set(cleanup.removed_branches) == set(result.created_branches)
    # We should end up back on a safe branch, not on a (now-deleted) fixture.
    assert not repo.current_branch().startswith(wfg.BRANCH_PREFIX)


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


def _run_cli(argv: list[str]) -> subprocess.CompletedProcess:
    """Invoke the CLI via python3 on the actual script file."""
    return subprocess.run(
        [sys.executable, str(FIXTURE_GEN_PATH), *argv],
        capture_output=True,
        text=True,
    )


def test_cli_top_level_help_lists_every_scenario(all_scenarios: list[str]) -> None:
    """`wave-fixture-gen --help` must mention every scenario subcommand."""
    result = _run_cli(["--help"])
    assert result.returncode == 0, result.stderr
    for scenario in all_scenarios:
        assert scenario in result.stdout, f"missing {scenario} in top-level help"
    assert "cleanup" in result.stdout


def test_cli_subcommand_help_is_nonempty(all_scenarios: list[str]) -> None:
    """Each scenario subcommand must have its own --help text."""
    for scenario in [*all_scenarios, "cleanup"]:
        result = _run_cli([scenario, "--help"])
        assert result.returncode == 0, f"{scenario} --help failed: {result.stderr}"
        assert "--repo" in result.stdout, f"{scenario} help missing --repo"
        # Description should be present (more than the one-line help)
        assert len(result.stdout.splitlines()) >= 5


def test_cli_missing_repo_errors() -> None:
    """Invoking without --repo must fail (argparse requires it)."""
    result = _run_cli(["conflicting-functions"])
    assert result.returncode != 0
    assert "repo" in result.stderr.lower()


def test_cli_nonexistent_repo_errors(tmp_path: Path) -> None:
    """--repo pointing to a missing path must exit non-zero with a clear message."""
    result = _run_cli(
        ["conflicting-functions", "--repo", str(tmp_path / "nope")]
    )
    assert result.returncode != 0
    assert "does not exist" in result.stderr


def test_cli_generates_scenario_end_to_end(git_repo: Path) -> None:
    """End-to-end CLI test: subcommand + --repo produces expected artifacts."""
    result = _run_cli(["trivy-dep-vuln", "--repo", str(git_repo)])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["scenario"] == "trivy-dep-vuln"
    assert len(payload["created_branches"]) == 1
    # The real artifact file must be on disk
    assert (git_repo / payload["epic_payload_path"]).exists()


def test_cli_cleanup_end_to_end(git_repo: Path) -> None:
    """End-to-end CLI test: cleanup after generation removes artifacts."""
    _run_cli(["conflicting-functions", "--repo", str(git_repo)])
    _run_cli(["trivy-dep-vuln", "--repo", str(git_repo)])
    result = _run_cli(["cleanup", "--repo", str(git_repo)])
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["removed_artifact_dir"] is True
    assert len(payload["removed_branches"]) >= 3


def test_cli_subcommand_required() -> None:
    """No subcommand → argparse error."""
    result = _run_cli([])
    assert result.returncode != 0
