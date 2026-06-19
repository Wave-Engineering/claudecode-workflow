"""Tests for scripts/wavebus-changelog-aggregate.

Exercises the real bash script via subprocess.run() against a tmp-dir wave
root and a tmp-dir target repo. No mocking of the script under test.

Pattern mirrors tests/test_wavebus_scripts.py — keep the same shape so the
two test files read consistently.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "wavebus-changelog-aggregate"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True)


def _seed_fragment(
    wave_root: Path,
    flight: int,
    issue: int,
    body: str,
) -> Path:
    issue_dir = wave_root / f"flight-{flight}" / f"issue-{issue}"
    issue_dir.mkdir(parents=True, exist_ok=True)
    frag = issue_dir / "CHANGELOG.fragment.md"
    frag.write_text(body)
    return frag


@pytest.fixture()
def wave_root(tmp_path: Path) -> Path:
    root = tmp_path / "wave-1"
    root.mkdir()
    return root


@pytest.fixture()
def target_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


def test_usage_error_no_args() -> None:
    result = _run([str(SCRIPT)])
    assert result.returncode == 1, result.stderr
    assert "usage:" in result.stderr


def test_usage_error_too_many_args(tmp_path: Path) -> None:
    result = _run([str(SCRIPT), str(tmp_path), str(tmp_path), "wave-1", "extra"])
    assert result.returncode == 1, result.stderr


def test_rejects_missing_wave_root(target_repo: Path, tmp_path: Path) -> None:
    bogus = tmp_path / "does-not-exist"
    result = _run([str(SCRIPT), str(bogus), str(target_repo)])
    assert result.returncode == 2, result.stderr


def test_rejects_missing_target_repo(wave_root: Path, tmp_path: Path) -> None:
    bogus = tmp_path / "no-such-repo"
    result = _run([str(SCRIPT), str(wave_root), str(bogus)])
    assert result.returncode == 3, result.stderr


# ---------------------------------------------------------------------------
# Empty / no-op cases
# ---------------------------------------------------------------------------


def test_empty_wave_root_is_noop(wave_root: Path, target_repo: Path) -> None:
    """No fragments anywhere -> exit 0, no CHANGELOG.md created."""
    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr
    assert not (target_repo / "CHANGELOG.md").exists()
    assert "no fragments" in result.stdout.lower()


def test_fragments_with_no_recognized_categories_is_noop(
    wave_root: Path, target_repo: Path
) -> None:
    """Fragments exist but contain no recognized H3 category bullets -> no-op."""
    _seed_fragment(
        wave_root,
        1,
        100,
        "## Just an H2\n\nSome prose, no category headings.\n",
    )
    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr
    assert not (target_repo / "CHANGELOG.md").exists()


# ---------------------------------------------------------------------------
# Basic merge: 3 fragments, 2 categories, deterministic order
# ---------------------------------------------------------------------------


def test_basic_merge_three_fragments_two_categories(
    wave_root: Path, target_repo: Path
) -> None:
    _seed_fragment(
        wave_root,
        1,
        101,
        "### Features\n- Added A (#101)\n\n### Fixes\n- Fixed X (#101)\n",
    )
    _seed_fragment(
        wave_root,
        1,
        102,
        "### Features\n- Added B (#102)\n",
    )
    _seed_fragment(
        wave_root,
        2,
        103,
        "### Fixes\n- Fixed Y (#103)\n",
    )

    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr

    content = (target_repo / "CHANGELOG.md").read_text()
    # Heading present
    assert "## Unreleased" in content
    # Both categories present in canonical order
    feat_idx = content.index("### Features")
    fix_idx = content.index("### Fixes")
    assert feat_idx < fix_idx, "Features should come before Fixes"
    # Numeric flight / issue ordering preserved within Features:
    # flight-1/issue-101 (Added A) before flight-1/issue-102 (Added B)
    a_idx = content.index("Added A (#101)")
    b_idx = content.index("Added B (#102)")
    assert a_idx < b_idx
    # And X (flight 1) before Y (flight 2) within Fixes
    x_idx = content.index("Fixed X (#101)")
    y_idx = content.index("Fixed Y (#103)")
    assert x_idx < y_idx


# ---------------------------------------------------------------------------
# Dedup: identical bullet across fragments collapses to one line
# ---------------------------------------------------------------------------


def test_duplicate_bullet_collapses_to_one_line(
    wave_root: Path, target_repo: Path
) -> None:
    _seed_fragment(wave_root, 1, 200, "### Features\n- Same bullet\n")
    _seed_fragment(wave_root, 1, 201, "### Features\n- Same bullet\n")
    _seed_fragment(wave_root, 2, 202, "### Features\n- Same bullet\n")

    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr

    content = (target_repo / "CHANGELOG.md").read_text()
    occurrences = content.count("- Same bullet")
    assert occurrences == 1, f"expected one occurrence, got {occurrences}"


# ---------------------------------------------------------------------------
# Splice into an existing CHANGELOG.md
# ---------------------------------------------------------------------------


def test_splice_replaces_existing_unreleased_block(
    wave_root: Path, target_repo: Path
) -> None:
    _seed_fragment(wave_root, 1, 300, "### Features\n- New entry\n")

    (target_repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n"
        "## Unreleased\n\n"
        "### Fixes\n\n"
        "- Stale entry that should disappear\n\n"
        "## v1.0.0\n\n"
        "- Initial release\n"
    )

    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr

    content = (target_repo / "CHANGELOG.md").read_text()
    assert "Stale entry that should disappear" not in content
    assert "New entry" in content
    # Earlier release section preserved
    assert "## v1.0.0" in content
    assert "Initial release" in content
    # Unreleased still appears exactly once
    assert content.count("## Unreleased") == 1


def test_splice_inserts_when_unreleased_absent(
    wave_root: Path, target_repo: Path
) -> None:
    _seed_fragment(wave_root, 1, 400, "### Features\n- Brand new entry\n")

    (target_repo / "CHANGELOG.md").write_text(
        "# Changelog\n\n## v1.0.0\n\n- Initial release\n"
    )

    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr

    content = (target_repo / "CHANGELOG.md").read_text()
    assert "## Unreleased" in content
    assert "Brand new entry" in content
    # Unreleased should land before the prior release
    assert content.index("## Unreleased") < content.index("## v1.0.0")
    # H1 still at the top
    assert content.startswith("# Changelog")


# ---------------------------------------------------------------------------
# Numeric flight ordering: flight-2 before flight-10
# ---------------------------------------------------------------------------


def test_flight_ordering_is_numeric_not_lexical(
    wave_root: Path, target_repo: Path
) -> None:
    _seed_fragment(wave_root, 2, 500, "### Features\n- From flight 2\n")
    _seed_fragment(wave_root, 10, 501, "### Features\n- From flight 10\n")

    result = _run([str(SCRIPT), str(wave_root), str(target_repo)])
    assert result.returncode == 0, result.stderr

    content = (target_repo / "CHANGELOG.md").read_text()
    # flight 2 must precede flight 10 even though "10" sorts before "2" lexically
    assert content.index("From flight 2") < content.index("From flight 10")


# ---------------------------------------------------------------------------
# Wave-id arg accepted (forward-compat) but ignored
# ---------------------------------------------------------------------------


def test_wave_id_arg_accepted(wave_root: Path, target_repo: Path) -> None:
    _seed_fragment(wave_root, 1, 600, "### Features\n- With wave id\n")
    result = _run([str(SCRIPT), str(wave_root), str(target_repo), "wave-1"])
    assert result.returncode == 0, result.stderr
    assert "With wave id" in (target_repo / "CHANGELOG.md").read_text()
