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

_INSTALL_SCRIPT = str(_REPO_DIR / "install")  # renamed from install.sh in #281
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


def _install_ok(rc: int, out: str, err: str) -> bool:
    """install exits with the COUNT of missing dependencies — a late-stage audit
    unrelated to the install/merge work. In a sandbox HOME those deps are
    legitimately absent, so a non-zero exit is expected; accept it as long as it's
    the dep audit (not a real crash). See #753.
    """
    if rc == 0:
        return True
    combined = (out or "") + (err or "")
    return "dependenc" in combined and "missing" in combined


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
        assert _install_ok(rc, out, err), f"install.sh failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

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
        assert _install_ok(rc, out, err), f"install failed: {err}"

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
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Check — should report everything in sync
        rc, out, err = run_install(["--check"], sandbox_home)
        assert _install_ok(rc, out, err), f"--check failed: {err}"
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
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Modify an installed artifact to create drift
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed"
        wave_status.write_text("#!/bin/bash\necho tampered\n")

        # Check — should report drift
        rc, out, err = run_install(["--check"], sandbox_home)
        # Note: install.sh --check always exits 0, drift is reported textually
        assert _install_ok(rc, out, err), f"--check failed: {err}"
        assert "out of sync" in out.lower(), (
            f"Expected drift report in check output, got:\n{out}"
        )


@_SKIP_NO_BASH
class TestInstallDryRun:
    """install.sh --dry-run creates nothing in $HOME."""

    def test_install_dry_run(self, sandbox_home: Path) -> None:
        rc, out, err = run_install(["--dry-run"], sandbox_home)
        assert _install_ok(rc, out, err), f"--dry-run failed: {err}"

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
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Verify things were installed (sanity check)
        wave_status = sandbox_home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not installed before uninstall test"

        # Uninstall
        rc, out, err = run_uninstall([], sandbox_home)
        assert _install_ok(rc, out, err), (
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
        assert _install_ok(rc, out, err), f"install failed: {err}"

        # Collect pre-uninstall state
        bin_dir = sandbox_home / ".local" / "bin"
        pre_files = set(f.name for f in bin_dir.iterdir())
        assert len(pre_files) > 0, "Nothing installed — can't test dry-run"

        # Dry-run uninstall
        rc, out, err = run_uninstall(["--dry-run"], sandbox_home)
        assert _install_ok(rc, out, err), f"--dry-run uninstall failed: {err}"

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

        # Cellar + symlink-farm contract (#560, recommendation B):
        # - Cellar at ~/.claude/scripts/ holds the full recursive tree
        #   (top-level + nested), preserving exec bits and structure.
        # - ~/.local/bin/ holds symlinks ONLY for top-level Cellar entries.
        cellar = home / ".claude" / "scripts"
        bin_dir = home / ".local" / "bin"

        # Cellar mirrors the source tree end-to-end (top-level + nested).
        assert (cellar / "foo").exists(), "flat top-level script missing in Cellar"
        assert (cellar / "sub" / "bar").exists(), (
            "single-nested script missing in Cellar"
        )
        assert (cellar / "sub" / "baz" / "qux").exists(), (
            "double-nested script missing in Cellar"
        )
        # Executable bits preserved end-to-end in the Cellar.
        assert os.access(str(cellar / "foo"), os.X_OK)
        assert os.access(str(cellar / "sub" / "bar"), os.X_OK)
        assert os.access(str(cellar / "sub" / "baz" / "qux"), os.X_OK)
        # Non-executable doc copied to Cellar, NOT marked executable.
        readme = cellar / "sub" / "README.md"
        assert readme.exists(), "non-executable doc not copied to Cellar"
        assert not os.access(str(readme), os.X_OK), (
            "non-executable doc was incorrectly chmod'd +x in Cellar"
        )
        # Excluded subtree not copied to Cellar either.
        assert not (cellar / "excluded" / "__pycache__" / "y").exists(), (
            "excluded __pycache__ subtree was copied"
        )

        # Symlink farm: only top-level entries are symlinked into ~/.local/bin/.
        # Nested entries (sub/, sub/baz/, etc.) stay Cellar-only per
        # recommendation B from #560.
        assert (bin_dir / "foo").is_symlink(), (
            "top-level script should be a symlink in the farm"
        )
        assert not (bin_dir / "sub").exists(), (
            "subtree directories should NOT be mirrored into ~/.local/bin/ "
            "(granularity B per #560)"
        )

    def test_prune_removes_orphan(self, tmp_path: Path) -> None:
        """--prune (legacy, manifest-based) removes ~/.local/bin/<rel> files
        whose source under scripts/<rel> no longer exists.

        Note: under #560's Cellar layout, structural orphan rot is killed
        by the cellar-wipe at install time, so --prune is effectively a
        backwards-compat code path. We exercise it with a synthetic
        manifest entry to confirm it still functions.
        """
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = os.environ.copy()
        env["HOME"] = str(home)

        # Install once.
        _proc = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        rc, out, err = _proc.returncode, _proc.stdout, _proc.stderr
        assert _install_ok(rc, out, err), "first install failed"

        # Plant an orphan (manifest-tracked plain file under ~/.local/bin/).
        # The legacy --prune walks the manifest and removes plain files
        # whose source under scripts/ no longer exists.
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
        # Cellar live files still present (top-level + nested).
        cellar = home / ".claude" / "scripts"
        assert (cellar / "foo").exists(), "prune removed live top-level Cellar entry"
        assert (cellar / "sub" / "bar").exists(), (
            "prune removed live nested Cellar entry"
        )
        # Symlink farm top-level still present.
        assert (bin_dir / "foo").is_symlink(), (
            "prune removed live top-level symlink-farm entry"
        )

    def test_check_reports_nested_drift(self, tmp_path: Path) -> None:
        """--check reports drift for missing nested files in the Cellar.

        Under #560 the Cellar (~/.claude/scripts/) holds the full recursive
        tree (top-level + nested). Deleting a nested Cellar entry should
        surface as drift — the tree no longer matches the source.
        """
        repo = self._build_synthetic_repo(tmp_path)
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)

        env = os.environ.copy()
        env["HOME"] = str(home)

        _proc = subprocess.run(
            ["bash", str(repo / "install"), "--scripts"],
            capture_output=True,
            text=True,
            env=env,
            timeout=60,
        )
        rc, out, err = _proc.returncode, _proc.stdout, _proc.stderr
        assert _install_ok(rc, out, err), "install failed"

        # Delete a nested Cellar file; --check should flag the drift.
        target = home / ".claude" / "scripts" / "sub" / "bar"
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
            f"--check did not report missing nested Cellar file:\n{result.stdout}"
        )
        assert "out of sync" in result.stdout.lower(), (
            f"--check did not flag drift:\n{result.stdout}"
        )


def run_install_cwd(
    args: list[str],
    home: Path,
    cwd: Path,
) -> Tuple[int, str, str]:
    """Run ``install <args>`` with HOME overridden AND a specific cwd.

    ``--local`` keys its install root off ``$(pwd)``, not ``$HOME``, so the
    subprocess cwd must be set to the project directory under test.
    """
    result = subprocess.run(
        ["bash", _INSTALL_SCRIPT] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        cwd=str(cwd),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestLocalScopeInstall:
    """``./install --local`` installs into ``<cwd>/.claude/`` instead of
    global ``$HOME``, leaving the global fleet install untouched."""

    def test_local_scope_placement(self, tmp_path: Path) -> None:
        """--local from cwd=project lands skills, Cellar, farm, and settings
        all under project/.claude/."""
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()

        rc, out, err = run_install_cwd(["--local"], home, project)
        assert _install_ok(rc, out, err), (
            f"--local install failed (rc={rc}):\nstdout: {out}\nstderr: {err}"
        )

        proj_claude = project / ".claude"
        # Skills land under project/.claude/skills/<name>/SKILL.md.
        for skill_name in _expected_skill_dirs():
            assert (proj_claude / "skills" / skill_name / "SKILL.md").exists(), (
                f"Missing project-local skill: {skill_name}"
            )
        # Cellar at project/.claude/scripts (top-level scripts present).
        assert (proj_claude / "scripts").is_dir(), "project-local Cellar missing"
        # Symlink farm at project/.claude/bin (NOT .claude/scripts).
        assert (proj_claude / "bin").is_dir(), "project-local farm (bin/) missing"
        for script_name in _expected_standalone_scripts():
            assert (proj_claude / "scripts" / script_name).exists(), (
                f"Missing standalone script in project Cellar: {script_name}"
            )
        # Settings merged/installed into project/.claude/settings.json.
        assert (proj_claude / "settings.json").exists(), (
            "project-local settings.json missing"
        )

    def test_local_leaves_global_untouched(self, tmp_path: Path) -> None:
        """After --local, the global $HOME/.claude and $HOME/.local/bin stay
        empty/absent — no fleet contamination."""
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()

        rc, out, err = run_install_cwd(["--local"], home, project)
        assert _install_ok(rc, out, err), f"--local install failed: {err}"

        # Global skills dir empty.
        global_skills = home / ".claude" / "skills"
        assert list(global_skills.iterdir()) == [], (
            f"--local contaminated global skills: {list(global_skills.iterdir())}"
        )
        # Global bin empty.
        global_bin = home / ".local" / "bin"
        assert list(global_bin.iterdir()) == [], (
            f"--local contaminated global bin: {list(global_bin.iterdir())}"
        )
        # No global settings.json created.
        assert not (home / ".claude" / "settings.json").exists(), (
            "--local created a global settings.json"
        )
        # No global Cellar.
        assert not (home / ".claude" / "scripts").exists(), (
            "--local created a global Cellar"
        )

    def test_default_install_unchanged(self, sandbox_home: Path) -> None:
        """No flag → lands in $HOME as today AND a project-local .claude/ is
        NOT created in cwd (proves --local is strictly opt-in)."""
        # Run default install from a project dir; nothing should land there.
        home = sandbox_home
        project = home.parent / "project"
        project.mkdir()

        rc, out, err = run_install_cwd([], home, project)
        assert _install_ok(rc, out, err), f"default install failed: {err}"

        # Global path populated as usual.
        assert (home / ".claude" / "skills").iterdir(), "global skills not installed"
        wave_status = home / ".local" / "bin" / "wave-status"
        assert wave_status.exists(), "wave-status not in global bin"
        # The cwd project dir must NOT have a .claude/ created by a default run.
        assert not (project / ".claude").exists(), (
            "default (no --local) install created a project-local .claude/"
        )

    def test_local_uninstall(self, tmp_path: Path) -> None:
        """uninstall.sh --local removes the project-scoped install while the
        global install is untouched."""
        home = tmp_path / "home"
        (home / ".local" / "bin").mkdir(parents=True)
        (home / ".claude" / "skills").mkdir(parents=True)
        project = tmp_path / "project"
        project.mkdir()

        rc, out, err = run_install_cwd(["--local"], home, project)
        assert _install_ok(rc, out, err), f"--local install failed: {err}"
        # Sanity: project install present.
        assert (project / ".claude" / "skills").is_dir()

        # Uninstall --local from the project dir.
        result = subprocess.run(
            ["bash", _UNINSTALL_SCRIPT, "--local"],
            capture_output=True,
            text=True,
            env=_make_env(home),
            cwd=str(project),
            timeout=120,
        )
        assert _install_ok(result.returncode, result.stdout, result.stderr), (
            f"--local uninstall failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )

        # Project skills removed.
        for skill_name in _expected_skill_dirs():
            assert not (project / ".claude" / "skills" / skill_name).exists(), (
                f"project-local skill not removed: {skill_name}"
            )
        # Project statusline removed.
        assert not (project / ".claude" / "statusline-command.sh").exists(), (
            "project-local statusline not removed"
        )
        # Global install never existed → still clean.
        assert list((home / ".claude" / "skills").iterdir()) == [], (
            "--local uninstall touched global skills"
        )


@_SKIP_NO_BASH
@_SKIP_NO_PYTHON3
class TestReinstallOverwrites:
    """Installing twice succeeds without errors (second install overwrites)."""

    def test_reinstall_overwrites(self, sandbox_home: Path) -> None:
        # First install
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), f"first install failed: {err}"

        # Second install (should succeed — no errors)
        rc, out, err = run_install([], sandbox_home)
        assert _install_ok(rc, out, err), (
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
