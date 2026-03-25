"""Shared fixtures for subprocess-based integration tests.

Provides:
- ``temp_git_repo`` — a tmp_path with ``git init`` so get_project_root() works
- ``sample_plan``   — multi-phase, multi-wave, multi-issue plan dict
- ``sample_flights`` — single-flight list for wave-1
- ``sample_flights_multi`` — multi-flight list for wave-1
- ``run_cli``       — fixture returning a helper that invokes
                      ``python3 -m wave_status`` via subprocess

All fixtures support the subprocess test strategy: real CLI invocations
in a temporary git repository with PYTHONPATH set to ``src/``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest


# ---------------------------------------------------------------------------
# Path to project src/ for PYTHONPATH injection
# ---------------------------------------------------------------------------

_SRC_DIR = str(Path(__file__).resolve().parent.parent / "src")


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

SAMPLE_PLAN: dict = {
    "project": "test-project",
    "base_branch": "main",
    "master_issue": 100,
    "phases": [
        {
            "name": "Foundation",
            "waves": [
                {
                    "id": "wave-1",
                    "name": "Wave 1",
                    "issues": [
                        {"number": 13, "title": "Issue 13", "deps": []},
                        {"number": 1, "title": "Issue 1", "deps": []},
                    ],
                },
                {
                    "id": "wave-2",
                    "name": "Wave 2",
                    "issues": [
                        {"number": 2, "title": "Issue 2", "deps": [13]},
                        {"number": 3, "title": "Issue 3", "deps": [1]},
                    ],
                },
            ],
        },
        {
            "name": "Enhancement",
            "waves": [
                {
                    "id": "wave-3",
                    "name": "Wave 3",
                    "issues": [
                        {"number": 5, "title": "Issue 5", "deps": [2, 3]},
                    ],
                },
            ],
        },
    ],
}

SAMPLE_FLIGHTS: list = [
    {"issues": [13, 1], "status": "pending"},
]

SAMPLE_FLIGHTS_MULTI: list = [
    {"issues": [13], "status": "pending"},
    {"issues": [1], "status": "pending"},
]


# ---------------------------------------------------------------------------
# Subprocess helper (module-level function)
# ---------------------------------------------------------------------------

def _run_cli_impl(
    args: list[str],
    cwd: str | Path,
    input_text: str | None = None,
) -> tuple[int, str, str]:
    """Run ``python3 -m wave_status <args>`` as a subprocess.

    Parameters
    ----------
    args:
        CLI arguments (e.g. ``["init", "plan.json"]``).
    cwd:
        Working directory for the subprocess (should be a git repo).
    input_text:
        Optional text piped to stdin.

    Returns
    -------
    tuple[int, str, str]
        ``(returncode, stdout, stderr)``
    """
    env = os.environ.copy()
    # Ensure wave_status is importable from src/
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = _SRC_DIR + (os.pathsep + existing if existing else "")

    result = subprocess.run(
        [sys.executable, "-m", "wave_status"] + args,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        input=input_text,
        env=env,
    )
    return (result.returncode, result.stdout, result.stderr)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def temp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary directory with ``git init`` so that
    ``get_project_root()`` resolves correctly in subprocess context.
    """
    subprocess.run(
        ["git", "init"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    # Configure git user so commits work if needed
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path),
        capture_output=True,
        check=True,
    )
    return tmp_path


@pytest.fixture()
def sample_plan() -> dict:
    """Return a copy of the sample plan data."""
    return json.loads(json.dumps(SAMPLE_PLAN))


@pytest.fixture()
def sample_flights() -> list:
    """Return a copy of the sample flights data."""
    return json.loads(json.dumps(SAMPLE_FLIGHTS))


@pytest.fixture()
def sample_flights_multi() -> list:
    """Return a copy of the multi-flight data."""
    return json.loads(json.dumps(SAMPLE_FLIGHTS_MULTI))


RunCli = Callable[[list[str], str | Path, str | None], tuple[int, str, str]]


@pytest.fixture()
def run_cli() -> RunCli:
    """Return the ``run_cli(args, cwd, input_text=None)`` helper function.

    Usage in tests::

        def test_something(self, temp_git_repo, run_cli):
            rc, out, err = run_cli(["init", "plan.json"], temp_git_repo)
    """
    return _run_cli_impl
