"""Orphan-prune tests for the ``install`` skill path (issue #714).

``./install --skills`` adds/updates skill files but historically did NOT
remove files that no longer exist in the source skill dir (the scripts
farm prunes via its Cellar wipe; the skill install did not). The #691
cutover deleted ``skills/{wavemachine,nextwave}/introduction.md`` yet the
stale installed copies persisted. This file pins the prune.

Self-contained — like ``tests/test_install_cellar.py`` it writes synthetic
fixtures, invokes ``./install --skills`` with ``HOME`` overridden, and
asserts the post-install on-disk shape. It does NOT depend on the
known-stale ``test_install.py``.

Acceptance criteria (#714):
- AC1 — orphaned installed skill files are pruned: ``test_orphaned_skill_file_pruned``,
  ``test_orphaned_subdir_file_pruned``, ``test_orphaned_cellar_helper_and_symlink_pruned``
- AC2 — ``.bak`` rollback artifacts preserved: ``test_bak_preserved``
- No-op re-install leaves the tree unchanged: ``test_reinstall_is_stable``
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO_DIR = Path(__file__).resolve().parent.parent
_INSTALL_SCRIPT = str(_REPO_DIR / "install")

_HAS_BASH = shutil.which("bash") is not None
_HAS_JQ = shutil.which("jq") is not None
_SKIP = pytest.mark.skipif(
    not (_HAS_BASH and _HAS_JQ), reason="bash and jq required"
)


def _make_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env


def _build_synthetic_repo(tmp_path: Path) -> Path:
    """A minimal repo whose ``skills/demo/`` ships SKILL.md, a content
    subdir file, and a non-.md helper (Cellar-bound) — but NOT the orphan
    files we plant in the sandbox HOME below."""
    repo = tmp_path / "repo"
    skills = repo / "skills" / "demo"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("# Demo skill\n")
    (skills / "helper.sh").write_text("#!/usr/bin/env bash\necho helper\n")
    os.chmod(skills / "helper.sh", 0o755)
    tours = skills / "tours"
    tours.mkdir()
    (tours / "intro.md").write_text("# Intro tour\n")

    # Stub ci/check-deps.sh so the post-install dep gate is a no-op.
    ci_dir = repo / "scripts" / "ci"
    ci_dir.mkdir(parents=True)
    (ci_dir / "check-deps.sh").write_text(
        "#!/usr/bin/env bash\ncheck_deps() { return 0; }\n"
    )
    (ci_dir / "check-deps.sh").chmod(0o755)

    shutil.copy(_INSTALL_SCRIPT, repo / "install")
    os.chmod(repo / "install", 0o755)
    return repo


def _build_sandbox_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills" / "demo" / "tours").mkdir(parents=True)
    (home / ".claude" / "scripts" / "skills" / "demo").mkdir(parents=True)
    return home


def _run_install(repo: Path, home: Path, args: list[str] | None = None):
    result = subprocess.run(
        ["bash", str(repo / "install")] + (args or ["--skills"]),
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _plant_orphans(home: Path) -> dict[str, Path]:
    """Simulate a prior install whose source has since dropped some files."""
    skill = home / ".claude" / "skills" / "demo"
    orphan_md = skill / "introduction.md"  # the canonical #714 case
    orphan_md.write_text("# stale legacy intro\n")
    bak = skill / "SKILL.md.bak"  # rollback artifact — must be preserved
    bak.write_text("# old SKILL backup\n")
    orphan_sub = skill / "tours" / "old-tour.md"
    orphan_sub.write_text("# removed tour\n")

    cellar_helper = home / ".claude" / "scripts" / "skills" / "demo" / "old-helper.sh"
    cellar_helper.write_text("#!/usr/bin/env bash\necho old\n")
    link = home / ".local" / "bin" / "old-helper.sh"
    link.symlink_to(cellar_helper)
    return {
        "orphan_md": orphan_md,
        "bak": bak,
        "orphan_sub": orphan_sub,
        "cellar_helper": cellar_helper,
        "link": link,
    }


@_SKIP
def test_orphaned_skill_file_pruned(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    p = _plant_orphans(home)
    rc, out, err = _run_install(repo, home)
    assert rc == 0, f"install failed: {out}\n{err}"
    assert not p["orphan_md"].exists(), "orphaned introduction.md was not pruned"
    # Real source file is present.
    assert (home / ".claude" / "skills" / "demo" / "SKILL.md").exists()


@_SKIP
def test_orphaned_subdir_file_pruned(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    p = _plant_orphans(home)
    rc, out, err = _run_install(repo, home)
    assert rc == 0, f"install failed: {out}\n{err}"
    assert not p["orphan_sub"].exists(), "orphaned subdir file was not pruned"
    # The real subdir content survives.
    assert (home / ".claude" / "skills" / "demo" / "tours" / "intro.md").exists()


@_SKIP
def test_orphaned_cellar_helper_and_symlink_pruned(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    p = _plant_orphans(home)
    rc, out, err = _run_install(repo, home)
    assert rc == 0, f"install failed: {out}\n{err}"
    assert not p["cellar_helper"].exists(), "orphaned Cellar helper not pruned"
    assert not p["link"].exists(), "orphaned farm symlink not pruned"
    # The real helper IS installed to the Cellar.
    assert (home / ".claude" / "scripts" / "skills" / "demo" / "helper.sh").exists()


@_SKIP
def test_bak_preserved(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    p = _plant_orphans(home)
    rc, out, err = _run_install(repo, home)
    assert rc == 0, f"install failed: {out}\n{err}"
    assert p["bak"].exists(), ".bak rollback artifact must be preserved by prune"


@_SKIP
def test_foreign_symlink_not_removed(tmp_path: Path) -> None:
    """A same-named symlink in the farm that points somewhere OTHER than the
    orphaned Cellar target must NOT be removed (the catastrophic-deletion
    negative case for concern #3)."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    _plant_orphans(home)
    # A foreign file + a farm symlink (same bare name as the orphan helper)
    # pointing at it, NOT at the orphaned Cellar target.
    foreign_target = home / "foreign-tool.sh"
    foreign_target.write_text("#!/usr/bin/env bash\necho foreign\n")
    foreign_link = home / ".local" / "bin" / "old-helper.sh"
    foreign_link.unlink()  # drop the one _plant_orphans made
    foreign_link.symlink_to(foreign_target)

    rc, out, err = _run_install(repo, home)
    assert rc == 0, f"install failed: {out}\n{err}"
    assert foreign_link.is_symlink(), "foreign symlink was wrongly removed"
    assert foreign_link.resolve() == foreign_target.resolve()


@_SKIP
def test_dry_run_preserves_orphans(tmp_path: Path) -> None:
    """`--dry-run --skills` must NOT delete planted orphans (DRY_RUN gate)."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    p = _plant_orphans(home)
    rc, out, err = _run_install(repo, home, args=["--skills", "--dry-run"])
    assert rc == 0, f"dry-run install failed: {out}\n{err}"
    assert p["orphan_md"].exists(), "dry-run pruned an orphan (must only preview)"
    assert p["cellar_helper"].exists(), "dry-run pruned a Cellar helper"
    assert p["link"].exists(), "dry-run pruned a farm symlink"


@_SKIP
def test_reinstall_is_stable(tmp_path: Path) -> None:
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)
    _plant_orphans(home)
    rc1, _, _ = _run_install(repo, home)
    assert rc1 == 0
    skill = home / ".claude" / "skills" / "demo"
    before = sorted(str(p.relative_to(home)) for p in skill.rglob("*") if p.is_file())
    rc2, out, err = _run_install(repo, home)
    assert rc2 == 0, f"second install failed: {out}\n{err}"
    after = sorted(str(p.relative_to(home)) for p in skill.rglob("*") if p.is_file())
    assert before == after, f"no-op re-install changed the tree: {before} != {after}"
