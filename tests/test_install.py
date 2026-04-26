"""Install/uninstall lifecycle tests in a sandboxed HOME.

Tests the full install -> check -> uninstall lifecycle by running
``install.sh`` and ``uninstall.sh`` as subprocesses with ``HOME``
overridden to a temporary directory.  The real ``$HOME`` is never
touched.

Acceptance criteria from issue #41:
- All tests use a sandboxed $HOME
- Install lifecycle: install -> check (clean) -> modify -> check (drift) -> reinstall
- Uninstall removes all artifacts including wave-status binary
- Dry-run mode verified for both install and uninstall
- Tests skip gracefully if required tools are unavailable
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Tuple

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent

_INSTALL_SCRIPT = str(_REPO_DIR / "install.sh")
_UNINSTALL_SCRIPT = str(_REPO_DIR / "uninstall.sh")


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_HAS_BASH = shutil.which("bash") is not None
_HAS_PYTHON3 = shutil.which("python3") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_PYTHON3 = pytest.mark.skipif(
    not _HAS_PYTHON3, reason="python3 not available (needed for zipapp build)"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox_home(tmp_path: Path) -> Path:
    """Create a sandboxed HOME directory mimicking the real structure.

    Layout::

        tmp/
          home/
            .local/bin/
            .claude/
              skills/
              config/

    Returns the ``home/`` path to be used as ``HOME``.
    """
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


def _make_env(home: Path) -> dict[str, str]:
    """Build a subprocess environment with HOME overridden."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_install(
    args: list[str],
    home: Path,
) -> Tuple[int, str, str]:
    """Run ``install.sh <args>`` with HOME overridden.

    Returns ``(returncode, stdout, stderr)``.
    """
    result = subprocess.run(
        ["bash", _INSTALL_SCRIPT] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def run_uninstall(
    args: list[str],
    home: Path,
) -> Tuple[int, str, str]:
    """Run ``uninstall.sh <args>`` with HOME overridden.

    Returns ``(returncode, stdout, stderr)``.
    """
    result = subprocess.run(
        ["bash", _UNINSTALL_SCRIPT] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Inventory helpers — derive the expected artifacts from the repo layout
# ---------------------------------------------------------------------------

def _expected_skill_dirs() -> list[str]:
    """Return skill directory names (e.g. ['ccfold', 'cryo', ...])."""
    return sorted(
        d.name
        for d in (_REPO_DIR / "skills").iterdir()
        if d.is_dir() and (d / "SKILL.md").exists()
    )


def _expected_helper_scripts() -> list[str]:
    """Return helper script basenames installed to ~/.local/bin/ from skills.

    Only non-.md files qualify — .md files are installed into the skill
    directory, not the scripts directory.
    """
    helpers = []
    for skill_dir in (_REPO_DIR / "skills").iterdir():
        if not skill_dir.is_dir():
            continue
        for f in skill_dir.iterdir():
            if f.is_file() and f.name != "SKILL.md" and not f.name.endswith(".md"):
                helpers.append(f.name)
    return sorted(helpers)


def _expected_skill_content_md() -> dict[str, list[str]]:
    """Return a mapping of skill_name -> list of .md filenames (excluding SKILL.md).

    These files are installed into ~/.claude/skills/<skill_name>/ rather than
    ~/.local/bin/.
    """
    result: dict[str, list[str]] = {}
    for skill_dir in (_REPO_DIR / "skills").iterdir():
        if not skill_dir.is_dir():
            continue
        md_files = []
        for f in skill_dir.iterdir():
            if f.is_file() and f.name.endswith(".md") and f.name != "SKILL.md":
                md_files.append(f.name)
        if md_files:
            result[skill_dir.name] = sorted(md_files)
    return result


def _expected_standalone_scripts() -> list[str]:
    """Return standalone script basenames from scripts/ (excluding ci/ dir)."""
    scripts = []
    for f in (_REPO_DIR / "scripts").iterdir():
        if f.is_file():
            scripts.append(f.name)
    return sorted(scripts)


def _expected_package_artifacts() -> list[str]:
    """Return package artifact names (e.g. ['wave-status'])."""
    artifacts = []
    src_dir = _REPO_DIR / "src"
    if src_dir.is_dir():
        for pkg_dir in src_dir.iterdir():
            if pkg_dir.is_dir() and (pkg_dir / "__main__.py").exists():
                artifacts.append(pkg_dir.name.replace("_", "-"))
    return sorted(artifacts)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstallCreatesArtifacts:
    """install.sh copies skills, scripts, config, AND builds + installs
    wave-status to $HOME/.local/bin/."""

    def test_install_creates_artifacts(self, sandbox_home: Path) -> None:
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"install.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        # --- Skills: SKILL.md installed for each skill ---
        skills_dir = sandbox_home / ".claude" / "skills"
        for skill_name in _expected_skill_dirs():
            skill_md = skills_dir / skill_name / "SKILL.md"
            assert skill_md.exists(), f"Missing skill: {skill_md}"

        # --- Helper scripts from skills (e.g. job-fetch, slackbot-send) ---
        bin_dir = sandbox_home / ".local" / "bin"
        for helper in _expected_helper_scripts():
            assert (bin_dir / helper).exists(), f"Missing helper script: {helper}"

        # --- Skill content .md files (e.g. introduction.md) ---
        for skill_name, md_files in _expected_skill_content_md().items():
            for md_file in md_files:
                md_path = skills_dir / skill_name / md_file
                assert md_path.exists(), (
                    f"Missing skill content file: {skill_name}/{md_file}"
                )
                # .md files must NOT be executable
                assert not os.access(str(md_path), os.X_OK), (
                    f"Skill content file should not be executable: {md_path}"
                )

        # --- Standalone scripts ---
        for script_name in _expected_standalone_scripts():
            assert (bin_dir / script_name).exists(), (
                f"Missing standalone script: {script_name}"
            )

        # --- Config: statusline-command.sh ---
        statusline = sandbox_home / ".claude" / "statusline-command.sh"
        assert statusline.exists(), "Missing config: statusline-command.sh"

        # --- Package artifacts (wave-status zipapp) ---
        for artifact in _expected_package_artifacts():
            assert (bin_dir / artifact).exists(), (
                f"Missing package artifact: {artifact}"
            )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstalledBinaryRuns:
    """After install, $HOME/.local/bin/wave-status --help exits 0."""

    def test_installed_binary_runs(self, sandbox_home: Path) -> None:
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed"

        result = subprocess.run(
            [str(wave_status), "--help"],
            capture_output=True,
            text=True,
            env=_make_env(sandbox_home),
            timeout=30,
        )
        assert result.returncode == 0, (
            f"wave-status --help failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstallCheckClean:
    """Immediately after install, install.sh --check reports no drift."""

    def test_install_check_clean(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        # Check — should report everything in sync
        rc, out, err = run_install(["--check"], sandbox_home)
        assert rc == 0, f"--check failed: {err}"
        assert "in sync" in out.lower(), (
            f"Expected 'in sync' in check output, got:\n{out}"
        )
        assert "out of sync" not in out.lower(), (
            f"Unexpected drift detected after clean install:\n{out}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestInstallCheckDetectsDrift:
    """After modifying an installed artifact, install.sh --check reports drift."""

    def test_install_check_detects_drift(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        # Modify an installed artifact to create drift
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed"
        wave_status.write_text("#!/bin/bash\necho tampered\n")

        # Check — should report drift
        rc, out, err = run_install(["--check"], sandbox_home)
        # Note: install.sh --check always exits 0, drift is reported textually
        assert rc == 0, f"--check failed: {err}"
        assert "out of sync" in out.lower(), (
            f"Expected drift report in check output, got:\n{out}"
        )


@_SKIP_NO_BASH
class TestInstallDryRun:
    """install.sh --dry-run creates nothing in $HOME."""

    def test_install_dry_run(self, sandbox_home: Path) -> None:
        rc, out, err = run_install(["--dry-run"], sandbox_home)
        assert rc == 0, f"--dry-run failed: {err}"

        # The dry-run output should mention "dry-run" or "Dry run"
        assert "dry run" in out.lower() or "dry-run" in out.lower(), (
            f"Expected dry-run indicator in output:\n{out}"
        )

        # Nothing should have been installed
        bin_dir = sandbox_home / ".local" / "bin"
        installed_files = list(bin_dir.iterdir())
        assert len(installed_files) == 0, (
            f"Dry run created files in bin: {installed_files}"
        )

        skills_dir = sandbox_home / ".claude" / "skills"
        skill_contents = list(skills_dir.iterdir())
        assert len(skill_contents) == 0, (
            f"Dry run created files in skills: {skill_contents}"
        )

        statusline = sandbox_home / ".claude" / "statusline-command.sh"
        assert not statusline.exists(), (
            "Dry run created statusline-command.sh"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestUninstallRemovesArtifacts:
    """After install, uninstall.sh removes skills, scripts, config,
    AND wave-status from $HOME/.local/bin/."""

    def test_uninstall_removes_artifacts(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        # Verify things were installed (sanity check)
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed before uninstall test"

        # Uninstall
        rc, out, err = run_uninstall([], sandbox_home)
        assert rc == 0, (
            f"uninstall.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"
        )

        # --- Skills removed ---
        skills_dir = sandbox_home / ".claude" / "skills"
        for skill_name in _expected_skill_dirs():
            skill_path = skills_dir / skill_name
            assert not skill_path.exists(), (
                f"Skill not removed: {skill_path}"
            )

        # --- Helper scripts removed ---
        bin_dir = sandbox_home / ".local" / "bin"
        for helper in _expected_helper_scripts():
            assert not (bin_dir / helper).exists(), (
                f"Helper script not removed: {helper}"
            )

        # --- Standalone scripts removed ---
        for script_name in _expected_standalone_scripts():
            assert not (bin_dir / script_name).exists(), (
                f"Standalone script not removed: {script_name}"
            )

        # --- Package artifacts removed (wave-status) ---
        for artifact in _expected_package_artifacts():
            assert not (bin_dir / artifact).exists(), (
                f"Package artifact not removed: {artifact}"
            )

        # --- Config removed ---
        statusline = sandbox_home / ".claude" / "statusline-command.sh"
        assert not statusline.exists(), "statusline-command.sh not removed"


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestUninstallDryRun:
    """uninstall.sh --dry-run removes nothing from $HOME."""

    def test_uninstall_dry_run(self, sandbox_home: Path) -> None:
        # Install first
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        # Collect pre-uninstall state
        bin_dir = sandbox_home / ".local" / "bin"
        pre_files = set(f.name for f in bin_dir.iterdir())
        assert len(pre_files) > 0, "Nothing installed — can't test dry-run"

        # Dry-run uninstall
        rc, out, err = run_uninstall(["--dry-run"], sandbox_home)
        assert rc == 0, f"--dry-run uninstall failed: {err}"

        # Output should mention dry-run
        assert "dry run" in out.lower() or "dry-run" in out.lower(), (
            f"Expected dry-run indicator in output:\n{out}"
        )

        # Nothing should have been removed
        post_files = set(f.name for f in bin_dir.iterdir())
        assert pre_files == post_files, (
            f"Dry-run removed files: {pre_files - post_files}"
        )

        # Skills should still exist
        skills_dir = sandbox_home / ".claude" / "skills"
        for skill_name in _expected_skill_dirs():
            assert (skills_dir / skill_name).exists(), (
                f"Dry-run removed skill: {skill_name}"
            )


@_SKIP_NO_BASH
class TestInstallSyntheticTree:
    """End-to-end install behavior on a synthetic ``scripts/`` layout.

    Builds a throwaway "repo" containing a stub install + scripts/ tree,
    then exercises recursion, executable preservation, and exclusion of
    noise subtrees (tests/, fixtures/, __pycache__, .pytest_cache).
    """

    def _build_synthetic_repo(self, tmp_path: Path) -> Path:
        """Materialize a minimal repo at ``tmp_path/repo`` with just scripts/.

        Strips the install script down to the script-copy block alone so the
        test stays fast and doesn't pull in skills/config/MCP machinery.
        """
        repo = tmp_path / "repo"
        scripts = repo / "scripts"
        scripts.mkdir(parents=True)

        # Top-level (flat) script.
        (scripts / "foo").write_text("#!/bin/bash\necho foo\n")
        os.chmod(scripts / "foo", 0o755)

        # Nested executable.
        sub = scripts / "sub"
        sub.mkdir()
        (sub / "bar").write_text("#!/bin/bash\necho bar\n")
        os.chmod(sub / "bar", 0o755)

        # Doubly-nested executable.
        baz = sub / "baz"
        baz.mkdir()
        (baz / "qux").write_text("#!/bin/bash\necho qux\n")
        os.chmod(baz / "qux", 0o755)

        # Non-executable doc.
        (sub / "README.md").write_text("# sub\n")

        # Excluded noise subtree.
        excluded = scripts / "excluded" / "__pycache__"
        excluded.mkdir(parents=True)
        (excluded / "y").write_text("compiled\n")

        # The real install script sources scripts/ci/check-deps.sh at the end
        # for the post-install dep gate. Stub it so the synthetic repo doesn't
        # need the full ci/ tree.
        ci_dir = scripts / "ci"
        ci_dir.mkdir()
        (ci_dir / "check-deps.sh").write_text("check_deps() { return 0; }\n")

        # Drop in a copy of the real install script so we run the actual code.
        shutil.copy(_REPO_DIR / "install", repo / "install")
        os.chmod(repo / "install", 0o755)
        return repo

    def test_recursive_install_with_exclusions(self, tmp_path: Path) -> None:
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = os.environ.copy()
        env["HOME"] = str(home)
        # --scripts skips skills/config/mcps/crystallizer; depcheck still
        # runs but is harmless on an empty repo.
        result = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"install failed (rc={result.returncode}):\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

        bin_dir = home / ".local" / "bin"
        # Flat + nested + doubly-nested all landed.
        assert (bin_dir / "foo").exists(), "flat top-level script missing"
        assert (bin_dir / "sub" / "bar").exists(), "single-nested script missing"
        assert (bin_dir / "sub" / "baz" / "qux").exists(), (
            "double-nested script missing"
        )
        # Executable bits preserved.
        assert os.access(str(bin_dir / "foo"), os.X_OK)
        assert os.access(str(bin_dir / "sub" / "bar"), os.X_OK)
        assert os.access(str(bin_dir / "sub" / "baz" / "qux"), os.X_OK)
        # Non-executable doc copied, NOT marked executable.
        readme = bin_dir / "sub" / "README.md"
        assert readme.exists(), "non-executable doc not copied"
        assert not os.access(str(readme), os.X_OK), (
            "non-executable doc was incorrectly chmod'd +x"
        )
        # Excluded subtree not copied.
        assert not (bin_dir / "excluded" / "__pycache__" / "y").exists(), (
            "excluded __pycache__ subtree was copied"
        )

    def test_prune_removes_orphan(self, tmp_path: Path) -> None:
        """--prune removes installed files whose source no longer exists."""
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = os.environ.copy()
        env["HOME"] = str(home)

        # Install once.
        rc = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        ).returncode
        assert rc == 0, "first install failed"

        # Plant an orphan (the manifest will pick it up since we'll add it).
        bin_dir = home / ".local" / "bin"
        orphan = bin_dir / "ghost"
        orphan.write_text("#!/bin/bash\necho gone\n")
        os.chmod(orphan, 0o755)
        manifest = bin_dir / ".cc-workflow-manifest"
        with manifest.open("a") as fh:
            fh.write("ghost\n")

        # Prune (non-interactive).
        result = subprocess.run(
            ["bash", str(repo / "install"), "--prune", "--yes"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, (
            f"prune failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert not orphan.exists(), "orphan was not pruned"
        # Backup retained.
        assert (bin_dir / "ghost.bak").exists(), "orphan backup missing"
        # Real files still present.
        assert (bin_dir / "foo").exists(), "prune removed live top-level script"
        assert (bin_dir / "sub" / "bar").exists(), (
            "prune removed live nested script"
        )

    def test_check_reports_nested_drift(self, tmp_path: Path) -> None:
        """--check reports drift for missing nested files (not just top-level)."""
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = os.environ.copy()
        env["HOME"] = str(home)

        rc = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        ).returncode
        assert rc == 0, "install failed"

        # Delete a nested file; --check should flag the drift.
        target = home / ".local" / "bin" / "sub" / "bar"
        assert target.exists()
        target.unlink()

        result = subprocess.run(
            ["bash", str(repo / "install"), "--check"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        assert result.returncode == 0, "check exited non-zero"
        assert "sub/bar" in result.stdout, (
            f"--check did not report missing nested file:\n{result.stdout}"
        )
        assert "out of sync" in result.stdout.lower(), (
            f"--check did not flag drift:\n{result.stdout}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestReinstallOverwrites:
    """Installing twice succeeds without errors (second install overwrites)."""

    def test_reinstall_overwrites(self, sandbox_home: Path) -> None:
        # First install
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, f"first install failed: {err}"

        # Second install (should succeed — no errors)
        rc, out, err = run_install([], sandbox_home)
        assert rc == 0, (
            f"second install failed (rc={rc}):\nstdout: {out}\nstderr: {err}"
        )

        # Artifacts should still be present
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status missing after reinstall"

        for skill_name in _expected_skill_dirs():
            skill_md = (
                sandbox_home / ".claude" / "skills" / skill_name / "SKILL.md"
            )
            assert skill_md.exists(), (
                f"Skill missing after reinstall: {skill_name}"
            )
