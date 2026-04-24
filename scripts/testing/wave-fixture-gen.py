#!/usr/bin/env python3
"""wave-fixture-gen — synthetic wave-pattern fixture generator.

Materializes deterministic conflict and failure scenarios against a target
git repo so the KAHUNA wave-pattern pipeline can be exercised repeatedly.

Referenced by integration tests IT-03, IT-04, IT-05, IT-08 in the KAHUNA
Dev Spec (see ``docs/kahuna-devspec.md`` §6.2). Outlives KAHUNA — this is
general-purpose test infrastructure for any wave-pattern work that needs
to reproduce specific conflict/failure shapes.

Usage::

    wave-fixture-gen <scenario> --repo <path> [--waves N] [--flights-per-wave M]
    wave-fixture-gen cleanup    --repo <path>

Scenarios:
    conflicting-functions   Two flights modify the same function differently
                            (commutativity verdict: WEAK).  Exercises IT-03.
    trivy-dep-vuln          Epic introduces a known-vulnerable dependency so
                            ``trivy fs`` reports HIGH/CRITICAL.  IT-04.
    critical-code-smell     Epic includes an obvious SQL-injection / hardcoded
                            -secret shape so code-reviewer flags it.  IT-05.
    rebase-conflict-setup   Flight ordering that produces a deterministic
                            rebase conflict on kahuna.  IT-08.

Properties guaranteed by every scenario:
    * Deterministic — same ``--repo`` + same arguments produce the same
      branch SHAs (fixed commit timestamps + fixed author identity).
    * Isolated — all artifacts live under the branch prefix
      ``wave-fixture/<scenario>/*`` and the directory ``.wave-fixtures/``.
    * Cleanable — ``cleanup`` removes every branch with the ``wave-fixture/``
      prefix and the ``.wave-fixtures/`` directory.

Python 3 stdlib-only (no external deps), matching ``src/wave_status/``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List


# ---------------------------------------------------------------------------
# Constants — the deterministic invariants
# ---------------------------------------------------------------------------

BRANCH_PREFIX = "wave-fixture"
ARTIFACT_DIR = ".wave-fixtures"

# Fixed author/committer identity: any non-determinism here leaks into commit
# SHAs.  These values are only used when constructing fixture commits and do
# not affect the user's git config.
FIXTURE_AUTHOR_NAME = "Wave Fixture Generator"
FIXTURE_AUTHOR_EMAIL = "wave-fixture-gen@example.invalid"

# Fixed commit timestamps (ISO-8601, UTC) — one per "logical step" so that
# the second flight's commits are strictly after the first's.  Using fixed
# values (rather than e.g. time.time()) is what makes the fixture branches
# reproducible bit-for-bit.
FIXTURE_EPOCH = "2026-01-01T00:00:00+00:00"
FIXTURE_STEP_SECONDS = 60


# ---------------------------------------------------------------------------
# Git helper
# ---------------------------------------------------------------------------


@dataclass
class GitRepo:
    """Thin wrapper around ``git -C <path>`` for the fixture generator.

    Sets fixed author/committer identity via environment variables on every
    commit so branch SHAs are deterministic regardless of the user's global
    git config.
    """

    path: Path

    def _env(self, step: int) -> dict:
        """Env for a commit at ``step`` seconds past FIXTURE_EPOCH."""
        # Compute an ISO-8601 offset from the fixed epoch.  We avoid any
        # datetime.now() calls so nothing non-deterministic sneaks in.
        env = os.environ.copy()
        env["GIT_AUTHOR_NAME"] = FIXTURE_AUTHOR_NAME
        env["GIT_AUTHOR_EMAIL"] = FIXTURE_AUTHOR_EMAIL
        env["GIT_COMMITTER_NAME"] = FIXTURE_AUTHOR_NAME
        env["GIT_COMMITTER_EMAIL"] = FIXTURE_AUTHOR_EMAIL
        # Git accepts "YYYY-MM-DDTHH:MM:SS+00:00" + optional " + Nsec" offset
        # via the raw seconds form.  We use the seconds-since-epoch form to
        # stay clear of timezone parsing corner cases.
        seconds = _epoch_seconds_for(step)
        env["GIT_AUTHOR_DATE"] = f"@{seconds} +0000"
        env["GIT_COMMITTER_DATE"] = f"@{seconds} +0000"
        return env

    def run(
        self,
        args: List[str],
        *,
        check: bool = True,
        capture: bool = True,
        env: dict | None = None,
    ) -> subprocess.CompletedProcess:
        """Run ``git <args>`` inside ``self.path``."""
        full = ["git", "-C", str(self.path), *args]
        return subprocess.run(
            full,
            capture_output=capture,
            text=True,
            check=check,
            env=env,
        )

    def current_branch(self) -> str:
        return self.run(["rev-parse", "--abbrev-ref", "HEAD"]).stdout.strip()

    def ref_exists(self, ref: str) -> bool:
        result = self.run(
            ["rev-parse", "--verify", "--quiet", ref],
            check=False,
        )
        return result.returncode == 0

    def list_branches_with_prefix(self, prefix: str) -> List[str]:
        """List local branches whose names start with ``prefix``."""
        result = self.run(["branch", "--list", f"{prefix}*", "--format=%(refname:short)"])
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def commit_file(
        self,
        relative_path: str,
        content: str,
        message: str,
        step: int,
    ) -> str:
        """Write ``content`` to ``relative_path``, git add + commit, return SHA."""
        file_path = self.path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        self.run(["add", "--", relative_path])
        self.run(["commit", "-m", message], env=self._env(step))
        return self.run(["rev-parse", "HEAD"]).stdout.strip()


def _epoch_seconds_for(step: int) -> int:
    """Seconds-since-Unix-epoch for the ``step``-th fixture commit.

    Uses a fixed base (2026-01-01 UTC) so every fixture-produced commit has
    a deterministic commit date and therefore a deterministic SHA.
    """
    # 2026-01-01T00:00:00Z in seconds since epoch (precomputed to avoid
    # datetime parsing at runtime).  1767225600 = calendar.timegm((2026,1,1,0,0,0,0,0,0)).
    base = 1767225600
    return base + (step * FIXTURE_STEP_SECONDS)


# ---------------------------------------------------------------------------
# Scenario result (for programmatic + test use)
# ---------------------------------------------------------------------------


@dataclass
class ScenarioResult:
    """Summary of what a scenario produced — used by tests and the CLI."""

    name: str
    base_branch: str
    created_branches: List[str] = field(default_factory=list)
    epic_payload_path: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario": self.name,
            "base_branch": self.base_branch,
            "created_branches": list(self.created_branches),
            "epic_payload_path": self.epic_payload_path,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Scenario implementations
# ---------------------------------------------------------------------------


def _ensure_base_branch(repo: GitRepo) -> str:
    """Return the name of a sane base branch, creating one if needed.

    We stash the starting branch so that every scenario can branch off the
    same commit and, crucially, so that the generator leaves the repo on the
    branch it found it on (tests assume the caller's checkout is preserved).
    """
    base = repo.current_branch()
    # Fresh repos in tests may have no commits; seed a trivial one so every
    # subsequent fixture branch has a parent to fork from.
    if not repo.ref_exists("HEAD"):
        repo.commit_file(
            "README.md",
            "# fixture base\n",
            "chore: fixture base commit",
            step=0,
        )
        base = repo.current_branch()
    return base


def _write_epic_payload(
    repo: GitRepo,
    scenario: str,
    payload: dict,
) -> str:
    """Write the epic payload JSON under ``.wave-fixtures/`` and return its path."""
    out_dir = repo.path / ARTIFACT_DIR
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / f"{scenario}-epic.json"
    # Deterministic JSON: sorted keys + fixed indent + trailing newline.
    out_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return str(out_path.relative_to(repo.path))


def scenario_conflicting_functions(repo: GitRepo) -> ScenarioResult:
    """Two flights modify the same function differently → commutativity WEAK.

    Creates ``wave-fixture/conflicting-functions/flight-a`` and
    ``wave-fixture/conflicting-functions/flight-b``.  Both branches edit
    ``src/fixture_target.py`` in overlapping lines but in incompatible ways.
    """
    scenario = "conflicting-functions"
    base = _ensure_base_branch(repo)
    result = ScenarioResult(name=scenario, base_branch=base)

    # Seed the shared file on the base branch so both flights can diverge from
    # a common ancestor.  Use a stable step so the seed commit is reproducible
    # but distinct from flight commits.
    shared = "src/fixture_target.py"
    seed_body = (
        '"""Fixture target: a function modified by two conflicting flights."""\n'
        "\n"
        "def compute(value: int) -> int:\n"
        "    # TODO: implementation pending\n"
        "    return value\n"
    )
    repo.commit_file(shared, seed_body, f"chore({scenario}): seed shared target", step=1)

    flight_a = f"{BRANCH_PREFIX}/{scenario}/flight-a"
    flight_b = f"{BRANCH_PREFIX}/{scenario}/flight-b"

    # Flight A — multiplies
    repo.run(["checkout", "-B", flight_a])
    a_body = (
        '"""Fixture target: a function modified by two conflicting flights."""\n'
        "\n"
        "def compute(value: int) -> int:\n"
        "    # flight-a: multiply\n"
        "    return value * 2\n"
    )
    repo.commit_file(shared, a_body, f"feat({scenario}): flight-a multiplies", step=2)

    # Flight B — branches off the seed commit (not off flight-a) and adds.
    repo.run(["checkout", base])
    repo.run(["checkout", "-B", flight_b])
    b_body = (
        '"""Fixture target: a function modified by two conflicting flights."""\n'
        "\n"
        "def compute(value: int) -> int:\n"
        "    # flight-b: add\n"
        "    return value + 10\n"
    )
    repo.commit_file(shared, b_body, f"feat({scenario}): flight-b adds", step=3)

    # Back to the base branch so the repo state is caller-preserving.
    repo.run(["checkout", base])

    result.created_branches = [flight_a, flight_b]
    result.notes.append(
        "Both flights touch the same line in src/fixture_target.py with "
        "incompatible replacements; commutativity_verify should emit WEAK."
    )

    payload = {
        "scenario": scenario,
        "title": "test-epic: conflicting-functions (IT-03)",
        "labels": ["type::epic", "test::fixture"],
        "stories": [
            {
                "branch": flight_a,
                "title": "test-story: flight-a (multiplies compute())",
            },
            {
                "branch": flight_b,
                "title": "test-story: flight-b (adds to compute())",
            },
        ],
        "expected_signals": {"commutativity_verify": "WEAK"},
    }
    result.epic_payload_path = _write_epic_payload(repo, scenario, payload)
    return result


def scenario_trivy_dep_vuln(repo: GitRepo) -> ScenarioResult:
    """Epic introduces a known-vulnerable dependency.

    Creates a single branch that adds a ``requirements.txt`` pinning an
    unambiguously-old Django release (Django 1.11.0, released 2017, with
    known HIGH/CRITICAL CVEs).  ``trivy fs`` should flag this.
    """
    scenario = "trivy-dep-vuln"
    base = _ensure_base_branch(repo)
    result = ScenarioResult(name=scenario, base_branch=base)

    branch = f"{BRANCH_PREFIX}/{scenario}/dep-vuln"
    repo.run(["checkout", "-B", branch])

    # Django 1.11.0 — April 2017 — has multiple published HIGH/CRITICAL CVEs
    # in trivy's DB.  Chosen because its vuln history is stable over time
    # (the CVEs were published years ago and won't "age out").
    requirements = (
        "# Fixture: deliberately pins a vulnerable dep for trivy-dep-vuln\n"
        "# scenario.  DO NOT ADOPT IN PRODUCTION CODE.\n"
        "django==1.11.0\n"
    )
    repo.commit_file(
        "requirements.txt",
        requirements,
        f"feat({scenario}): pin known-vulnerable dep",
        step=1,
    )
    repo.run(["checkout", base])

    result.created_branches = [branch]
    result.notes.append(
        "Branch pins django==1.11.0 (April 2017).  Trivy fs should report "
        "multiple HIGH/CRITICAL CVEs against the resolved package."
    )

    payload = {
        "scenario": scenario,
        "title": "test-epic: trivy-dep-vuln (IT-04)",
        "labels": ["type::epic", "test::fixture"],
        "stories": [
            {
                "branch": branch,
                "title": "test-story: introduce vulnerable dependency",
            },
        ],
        "expected_signals": {"trivy_fs": "HIGH_OR_CRITICAL"},
    }
    result.epic_payload_path = _write_epic_payload(repo, scenario, payload)
    return result


def scenario_critical_code_smell(repo: GitRepo) -> ScenarioResult:
    """Epic includes an obvious SQL-injection / hardcoded-secret shape.

    Creates a single branch that adds a Python file containing both a
    hardcoded API key and a classic format-string SQL injection.  Any
    competent code-reviewer (human or LLM) flags these instantly.
    """
    scenario = "critical-code-smell"
    base = _ensure_base_branch(repo)
    result = ScenarioResult(name=scenario, base_branch=base)

    branch = f"{BRANCH_PREFIX}/{scenario}/code-smell"
    repo.run(["checkout", "-B", branch])

    # Two classic code-review red flags in one module:
    #   1. Hardcoded credential that looks like a real API key
    #   2. SQL injection via f-string interpolation of user input
    # These are deliberately ugly — the point is that code-reviewer should
    # say "critical" without ambiguity.
    smelly = (
        '"""Fixture: deliberately smelly module for critical-code-smell.\n'
        "\n"
        "DO NOT ADOPT PATTERNS BELOW IN REAL CODE.\n"
        '"""\n'
        "\n"
        '# Hardcoded credential — critical finding (example key, not real)\n'
        'API_KEY = "sk-live-ABCD1234EXAMPLEFIXTUREKEYDONOTUSE"\n'
        "\n"
        "\n"
        "def lookup_user(cursor, username: str):\n"
        "    # SQL injection via f-string — critical finding\n"
        '    query = f"SELECT * FROM users WHERE name = \'{username}\'"\n'
        "    cursor.execute(query)\n"
        "    return cursor.fetchone()\n"
    )
    repo.commit_file(
        "src/fixture_smell.py",
        smelly,
        f"feat({scenario}): add module with critical code smells",
        step=1,
    )
    repo.run(["checkout", base])

    result.created_branches = [branch]
    result.notes.append(
        "Branch introduces src/fixture_smell.py with a hardcoded credential "
        "and a classic f-string SQL injection.  code-reviewer should emit "
        "at least one 'critical' finding."
    )

    payload = {
        "scenario": scenario,
        "title": "test-epic: critical-code-smell (IT-05)",
        "labels": ["type::epic", "test::fixture"],
        "stories": [
            {
                "branch": branch,
                "title": "test-story: introduce module with critical smells",
            },
        ],
        "expected_signals": {"code_reviewer": "CRITICAL"},
    }
    result.epic_payload_path = _write_epic_payload(repo, scenario, payload)
    return result


def scenario_rebase_conflict_setup(repo: GitRepo) -> ScenarioResult:
    """Flight ordering that produces a deterministic rebase conflict on kahuna.

    Flight-1 lands on the integration branch first.  Flight-2 was branched
    off the *pre*-integration base and edits overlapping lines.  When
    flight-2 tries to rebase onto the integration branch, the merge
    resolves to a conflict every time.
    """
    scenario = "rebase-conflict-setup"
    base = _ensure_base_branch(repo)
    result = ScenarioResult(name=scenario, base_branch=base)

    shared = "src/fixture_rebase_target.py"
    seed_body = (
        '"""Fixture: rebase-conflict target module."""\n'
        "\n"
        "STATUS = \"initial\"\n"
    )
    repo.commit_file(shared, seed_body, f"chore({scenario}): seed rebase target", step=1)

    # Simulated integration branch (the scenario's stand-in for kahuna) with
    # flight-1 already merged onto it.
    integration = f"{BRANCH_PREFIX}/{scenario}/integration"
    repo.run(["checkout", "-B", integration])
    integration_body = (
        '"""Fixture: rebase-conflict target module."""\n'
        "\n"
        "STATUS = \"flight-1\"  # committed to integration branch\n"
    )
    repo.commit_file(
        shared,
        integration_body,
        f"feat({scenario}): flight-1 changes STATUS on integration",
        step=2,
    )

    # Flight-2 branches from the seed commit — NOT from integration — and
    # edits the same line differently.  A subsequent rebase onto integration
    # will conflict.
    repo.run(["checkout", base])
    flight_2 = f"{BRANCH_PREFIX}/{scenario}/flight-2"
    repo.run(["checkout", "-B", flight_2])
    flight_2_body = (
        '"""Fixture: rebase-conflict target module."""\n'
        "\n"
        "STATUS = \"flight-2\"  # conflicts with integration\n"
    )
    repo.commit_file(
        shared,
        flight_2_body,
        f"feat({scenario}): flight-2 changes STATUS on branch",
        step=3,
    )
    repo.run(["checkout", base])

    result.created_branches = [integration, flight_2]
    result.notes.append(
        f"Rebase {flight_2} onto {integration} to reproduce the conflict; "
        "flight-2 should return FAIL per Procedure B (R-21)."
    )

    payload = {
        "scenario": scenario,
        "title": "test-epic: rebase-conflict-setup (IT-08)",
        "labels": ["type::epic", "test::fixture"],
        "stories": [
            {
                "branch": integration,
                "title": "test-story: flight-1 (lands first on integration)",
            },
            {
                "branch": flight_2,
                "title": "test-story: flight-2 (rebase conflicts with integration)",
            },
        ],
        "expected_signals": {"rebase": "CONFLICT"},
    }
    result.epic_payload_path = _write_epic_payload(repo, scenario, payload)
    return result


# Registry — keeps the CLI's scenario list in exact sync with the implementations.
SCENARIOS: dict[str, Callable[[GitRepo], ScenarioResult]] = {
    "conflicting-functions": scenario_conflicting_functions,
    "trivy-dep-vuln": scenario_trivy_dep_vuln,
    "critical-code-smell": scenario_critical_code_smell,
    "rebase-conflict-setup": scenario_rebase_conflict_setup,
}


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


@dataclass
class CleanupResult:
    """Summary of what ``cleanup`` removed — used by tests and the CLI."""

    removed_branches: List[str] = field(default_factory=list)
    removed_artifact_dir: bool = False


def run_cleanup(repo: GitRepo) -> CleanupResult:
    """Remove every ``wave-fixture/*`` branch and the artifact dir.

    Leaves the caller's current branch alone unless the caller is *on* a
    wave-fixture branch, in which case we switch to a safe branch first so
    the delete can proceed.
    """
    res = CleanupResult()
    current = repo.current_branch() if repo.ref_exists("HEAD") else ""
    branches = repo.list_branches_with_prefix(f"{BRANCH_PREFIX}/")
    if branches:
        # If we're currently on one of the doomed branches, step off it onto
        # a safe branch.  Prefer ``main`` if it exists; otherwise use the
        # repo's initial branch derived from HEAD detached state.
        if current in branches:
            safe = "main" if repo.ref_exists("main") else None
            if safe is None:
                # Try to find any non-fixture branch as a fallback
                all_branches = repo.run(
                    ["branch", "--format=%(refname:short)"]
                ).stdout.splitlines()
                candidates = [
                    b.strip() for b in all_branches
                    if b.strip() and not b.strip().startswith(f"{BRANCH_PREFIX}/")
                ]
                safe = candidates[0] if candidates else None
            if safe is not None:
                repo.run(["checkout", safe])
        for branch in branches:
            repo.run(["branch", "-D", branch])
            res.removed_branches.append(branch)

    artifact_dir = repo.path / ARTIFACT_DIR
    if artifact_dir.exists():
        # Recursively remove the artifact directory.  We avoid git rm because
        # cleanup shouldn't require a commit — the artifact dir should not
        # have been committed in the first place.
        for child in sorted(artifact_dir.rglob("*"), reverse=True):
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        artifact_dir.rmdir()
        res.removed_artifact_dir = True

    return res


# ---------------------------------------------------------------------------
# CLI dispatch
# ---------------------------------------------------------------------------


def _repo_arg_to_path(raw: str) -> Path:
    """Resolve ``--repo`` to an absolute path that exists and is a git repo."""
    path = Path(raw).expanduser().resolve()
    if not path.exists():
        raise SystemExit(f"error: --repo path does not exist: {path}")
    if not (path / ".git").exists():
        raise SystemExit(f"error: --repo is not a git repository: {path}")
    return path


def _cmd_scenario(args: argparse.Namespace) -> None:
    """Dispatch to a scenario implementation and print the summary."""
    scenario_fn = SCENARIOS[args.scenario]
    repo = GitRepo(path=_repo_arg_to_path(args.repo))
    result = scenario_fn(repo)
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))


def _cmd_cleanup(args: argparse.Namespace) -> None:
    """Remove every fixture artifact from the target repo."""
    repo = GitRepo(path=_repo_arg_to_path(args.repo))
    result = run_cleanup(repo)
    print(
        json.dumps(
            {
                "removed_branches": result.removed_branches,
                "removed_artifact_dir": result.removed_artifact_dir,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser with scenario + cleanup subcommands."""
    parser = argparse.ArgumentParser(
        prog="wave-fixture-gen",
        description=(
            "Materialize deterministic conflict/failure scenarios for wave-"
            "pattern pipeline testing.  See docs/kahuna-devspec.md §6.2."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def _add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--repo",
            required=True,
            help="Absolute or relative path to the target git repository.",
        )
        p.add_argument(
            "--waves",
            type=int,
            default=1,
            help=(
                "Number of waves the synthesized epic will span "
                "(currently informational; fixtures are shape-specific)."
            ),
        )
        p.add_argument(
            "--flights-per-wave",
            type=int,
            default=2,
            help=(
                "Number of flights per wave in the synthesized epic "
                "(currently informational; fixtures are shape-specific)."
            ),
        )

    # conflicting-functions
    p_cf = sub.add_parser(
        "conflicting-functions",
        help="Two flights modify the same function differently (IT-03).",
        description=(
            "Create two branches that edit the same lines of "
            "src/fixture_target.py in incompatible ways, so "
            "commutativity_verify returns WEAK.  Exercises IT-03 and R-12."
        ),
    )
    _add_common(p_cf)
    p_cf.set_defaults(func=_cmd_scenario, scenario="conflicting-functions")

    # trivy-dep-vuln
    p_tv = sub.add_parser(
        "trivy-dep-vuln",
        help="Epic introduces a known-vulnerable dependency (IT-04).",
        description=(
            "Create a branch that adds requirements.txt pinning django "
            "1.11.0 (known HIGH/CRITICAL CVEs).  Exercises IT-04 and R-15."
        ),
    )
    _add_common(p_tv)
    p_tv.set_defaults(func=_cmd_scenario, scenario="trivy-dep-vuln")

    # critical-code-smell
    p_cs = sub.add_parser(
        "critical-code-smell",
        help="Epic includes an obvious SQL-injection / hardcoded-secret shape (IT-05).",
        description=(
            "Create a branch that adds a Python module with a hardcoded "
            "credential and an f-string SQL injection.  code-reviewer "
            "should emit critical findings.  Exercises IT-05 and R-14."
        ),
    )
    _add_common(p_cs)
    p_cs.set_defaults(func=_cmd_scenario, scenario="critical-code-smell")

    # rebase-conflict-setup
    p_rc = sub.add_parser(
        "rebase-conflict-setup",
        help="Flight ordering that produces a deterministic rebase conflict (IT-08).",
        description=(
            "Create an integration branch with flight-1 merged plus a "
            "flight-2 branched off the pre-integration base that edits "
            "the same lines.  Rebasing flight-2 onto the integration "
            "branch produces a conflict every run.  Exercises IT-08 and R-21."
        ),
    )
    _add_common(p_rc)
    p_rc.set_defaults(func=_cmd_scenario, scenario="rebase-conflict-setup")

    # cleanup
    p_cl = sub.add_parser(
        "cleanup",
        help="Remove every wave-fixture branch and the .wave-fixtures directory.",
        description=(
            "Delete all local branches under the wave-fixture/* prefix and "
            "remove the .wave-fixtures directory.  Idempotent: safe to run "
            "repeatedly; no-op if nothing is present."
        ),
    )
    p_cl.add_argument(
        "--repo",
        required=True,
        help="Absolute or relative path to the target git repository.",
    )
    p_cl.set_defaults(func=_cmd_cleanup)

    return parser


def main(argv: List[str] | None = None) -> int:
    """CLI entry point.  Returns an exit code (0 on success)."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or "").strip() or str(exc)
        print(f"error: git subprocess failed: {msg}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        # SystemExit with a string payload carries a user-facing error message
        # (e.g. from _repo_arg_to_path).  argparse uses int payloads, so pass
        # those through without printing.
        if isinstance(exc.code, str):
            print(exc.code, file=sys.stderr)
            return 1
        return int(exc.code) if isinstance(exc.code, int) else 1
    except Exception as exc:  # noqa: BLE001 — CLI error boundary
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
