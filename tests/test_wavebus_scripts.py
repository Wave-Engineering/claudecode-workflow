"""Tests for scripts/wavebus/ — filesystem message bus primitives.

Exercises the real bash scripts via subprocess.run().  No mocking of the
scripts under test.  The ``tmp_path`` fixture isolates each test so no
cross-test pollution of /tmp/wavemachine can happen; the scripts accept
arbitrary roots indirectly — tests that need the canonical /tmp/wavemachine/…
path build it under tmp_path via a bind-style approach (see below) where
possible, otherwise they create real subtrees under /tmp/wavemachine and
clean them up themselves.

Since wave-init and wave-cleanup hard-code /tmp/wavemachine as the namespace
root, tests that exercise them use unique slug/wave-id values derived from
``tmp_path`` to avoid collision with any concurrent test runner, and they
register a finalizer to rm -rf the created tree.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
WAVEBUS_DIR = REPO_ROOT / "scripts" / "wavebus"
WAVE_INIT = WAVEBUS_DIR / "wave-init"
FLIGHT_FINALIZE = WAVEBUS_DIR / "flight-finalize"
WAVE_CLEANUP = WAVEBUS_DIR / "wave-cleanup"

CANONICAL_RE = re.compile(r"^(/tmp/wavemachine/[^\s]+/results\.md) (PASS|FAIL)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _unique_slug() -> str:
    """Per-test slug so parallel runs / leftover state don't collide."""
    return f"test-{uuid.uuid4().hex[:12]}"


@pytest.fixture()
def wave_slug(request: pytest.FixtureRequest) -> str:
    """Provide a unique repo-slug for the test and guarantee teardown."""
    slug = _unique_slug()

    def _cleanup() -> None:
        path = Path("/tmp/wavemachine") / slug
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    request.addfinalizer(_cleanup)
    return slug


def _seed_partial(
    slug: str,
    wave_id: str = "1",
    flight_id: str = "1",
    issue_id: str = "42",
    content: str = "results content\n",
) -> Path:
    """Create the canonical issue dir + results.md.partial for flight-finalize tests."""
    issue_dir = (
        Path("/tmp/wavemachine")
        / slug
        / f"wave-{wave_id}"
        / f"flight-{flight_id}"
        / f"issue-{issue_id}"
    )
    issue_dir.mkdir(parents=True, exist_ok=True)
    partial = issue_dir / "results.md.partial"
    partial.write_text(content)
    return partial


# ---------------------------------------------------------------------------
# wave-init
# ---------------------------------------------------------------------------


def test_wave_init_creates_tree(wave_slug: str) -> None:
    result = _run([str(WAVE_INIT), wave_slug, "1", "3"])
    assert result.returncode == 0, result.stderr
    wave_root = Path(f"/tmp/wavemachine/{wave_slug}/wave-1")
    assert wave_root.is_dir()
    for i in (1, 2, 3):
        assert (wave_root / f"flight-{i}").is_dir()
    # Prints the wave root on success
    assert result.stdout.strip() == str(wave_root)


def test_wave_init_idempotent(wave_slug: str) -> None:
    first = _run([str(WAVE_INIT), wave_slug, "2", "2"])
    assert first.returncode == 0, first.stderr
    # Seed a marker file — second call must NOT blow it away.
    marker = Path(f"/tmp/wavemachine/{wave_slug}/wave-2/flight-1/marker.txt")
    marker.write_text("persist")
    second = _run([str(WAVE_INIT), wave_slug, "2", "2"])
    assert second.returncode == 0, second.stderr
    assert marker.read_text() == "persist"
    assert Path(f"/tmp/wavemachine/{wave_slug}/wave-2/flight-2").is_dir()


# ---------------------------------------------------------------------------
# flight-finalize
# ---------------------------------------------------------------------------


def test_flight_finalize_atomic_rename(wave_slug: str) -> None:
    partial = _seed_partial(wave_slug)
    result = _run([str(FLIGHT_FINALIZE), str(partial), "PASS"])
    assert result.returncode == 0, result.stderr
    assert not partial.exists()
    assert (partial.parent / "results.md").is_file()


def test_flight_finalize_done_sentinel_pass(wave_slug: str) -> None:
    partial = _seed_partial(wave_slug)
    result = _run([str(FLIGHT_FINALIZE), str(partial), "PASS"])
    assert result.returncode == 0, result.stderr
    done = partial.parent / "DONE"
    assert done.is_file()
    # Exactly "PASS" — no trailing whitespace / newline
    assert done.read_bytes() == b"PASS"


def test_flight_finalize_done_sentinel_fail(wave_slug: str) -> None:
    partial = _seed_partial(wave_slug)
    result = _run([str(FLIGHT_FINALIZE), str(partial), "FAIL"])
    assert result.returncode == 0, result.stderr
    done = partial.parent / "DONE"
    assert done.is_file()
    assert done.read_bytes() == b"FAIL"


def test_flight_finalize_canonical_return(wave_slug: str) -> None:
    partial = _seed_partial(wave_slug)
    result = _run([str(FLIGHT_FINALIZE), str(partial), "PASS"])
    assert result.returncode == 0, result.stderr
    line = result.stdout.rstrip("\n")
    m = CANONICAL_RE.match(line)
    assert m is not None, f"stdout did not match canonical regex: {line!r}"
    results_path = m.group(1)
    assert results_path == str(partial.parent / "results.md")
    assert m.group(2) == "PASS"


def test_flight_finalize_rejects_missing_partial(wave_slug: str) -> None:
    # Build a well-shaped path that doesn't exist on disk.
    issue_dir = (
        Path("/tmp/wavemachine") / wave_slug / "wave-1" / "flight-1" / "issue-7"
    )
    issue_dir.mkdir(parents=True, exist_ok=True)
    missing = issue_dir / "results.md.partial"
    assert not missing.exists()
    result = _run([str(FLIGHT_FINALIZE), str(missing), "PASS"])
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr={result.stderr}"
    )


def test_flight_finalize_rejects_empty_partial(wave_slug: str) -> None:
    partial = _seed_partial(wave_slug, content="")
    assert partial.exists() and partial.stat().st_size == 0
    result = _run([str(FLIGHT_FINALIZE), str(partial), "PASS"])
    assert result.returncode == 2, (
        f"expected exit 2, got {result.returncode}; stderr={result.stderr}"
    )


def test_flight_finalize_rejects_wrong_path(tmp_path: Path) -> None:
    # A path that exists and is non-empty but not under the canonical shape.
    bogus = tmp_path / "results.md.partial"
    bogus.write_text("data")
    result = _run([str(FLIGHT_FINALIZE), str(bogus), "PASS"])
    assert result.returncode == 3, (
        f"expected exit 3, got {result.returncode}; stderr={result.stderr}"
    )


# ---------------------------------------------------------------------------
# wave-cleanup
# ---------------------------------------------------------------------------


def test_wave_cleanup_removes_tree(wave_slug: str) -> None:
    # Seed a real tree.
    init = _run([str(WAVE_INIT), wave_slug, "1", "2"])
    assert init.returncode == 0, init.stderr
    wave_root = Path(f"/tmp/wavemachine/{wave_slug}/wave-1")
    assert wave_root.is_dir()
    result = _run([str(WAVE_CLEANUP), str(wave_root)])
    assert result.returncode == 0, result.stderr
    assert not wave_root.exists()
    assert f"cleaned {wave_root}" in result.stdout


def test_wave_cleanup_refuses_outside_namespace(tmp_path: Path) -> None:
    # /tmp/foo/wave-1 is under /tmp but not /tmp/wavemachine
    unsafe = "/tmp/foo/wave-1"
    result = _run([str(WAVE_CLEANUP), unsafe])
    assert result.returncode == 4, (
        f"expected exit 4, got {result.returncode}; stderr={result.stderr}"
    )


def test_wave_cleanup_refuses_traversal() -> None:
    unsafe = "/tmp/wavemachine/../etc"
    # Pre-condition: don't accidentally succeed because the path doesn't exist.
    # The script MUST refuse on shape alone — exit 4, not 0.
    result = _run([str(WAVE_CLEANUP), unsafe])
    assert result.returncode == 4, (
        f"expected exit 4, got {result.returncode}; stderr={result.stderr}"
    )
    # And /etc must still exist (defensive; the script should never touch it).
    assert os.path.isdir("/etc")


def test_wave_cleanup_idempotent(wave_slug: str) -> None:
    # Never created — cleanup should be a no-op, exit 0.
    wave_root = Path(f"/tmp/wavemachine/{wave_slug}/wave-99")
    assert not wave_root.exists()
    result = _run([str(WAVE_CLEANUP), str(wave_root)])
    assert result.returncode == 0, result.stderr
    assert f"cleaned {wave_root}" in result.stdout
