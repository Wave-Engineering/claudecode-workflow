"""Cellar + symlink-farm tests for the ``install`` script (issue #560).

Covers the layout migration where kit-managed scripts move from direct
deployment in ``~/.local/bin/`` to a wipe-and-recreate Cellar at
``~/.claude/scripts/``, with ``~/.local/bin/`` becoming a symlink farm
pointing into the Cellar (Homebrew/Nix pattern).

This file is intentionally self-contained — like
``tests/test_install_merge_hooks_union.py`` it does NOT depend on
``tests/test_install.py`` or ``tests/test_install_merge.py`` (which have
known pre-existing failures from the ``install.sh`` -> ``install`` rename).
It writes synthetic fixtures, invokes ``./install`` with ``HOME``
overridden, and asserts the post-install on-disk shape.

Acceptance criteria from #560 are mapped 1:1 to test functions:

- AC1 — Cellar wipe + redeploy: ``test_cellar_wipe_and_redeploy``
- AC2 — Symlink farm granularity B: ``test_symlink_farm_granularity_b``
- AC3 — Removed-from-repo orphan-free re-deploy:
  ``test_removed_from_repo_no_orphan``
- AC4 — Hook path migration in settings.json:
  ``test_settings_hook_path_migration``
- AC5 — Matcher union-merge (re-confirms #556 still holds after #560):
  ``test_matcher_union_merge_still_works``
- AC6 — User-customized plain file backup:
  ``test_user_customized_plain_file_backup``
- AC7 — ``--check`` reports stale symlinks AND old-path hooks:
  ``test_check_reports_stale_symlinks``,
  ``test_check_reports_old_path_hooks``
- Bonus — Foreign symlinks (target outside Cellar) NOT touched:
  ``test_foreign_symlinks_untouched``
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent
_INSTALL_SCRIPT = str(_REPO_DIR / "install")


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_HAS_BASH = shutil.which("bash") is not None
_HAS_JQ = shutil.which("jq") is not None
_HAS_PYTHON3 = shutil.which("python3") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_JQ = pytest.mark.skipif(not _HAS_JQ, reason="jq not available")
_SKIP_NO_PYTHON3 = pytest.mark.skipif(
    not _HAS_PYTHON3, reason="python3 not available (zipapp build)"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _build_synthetic_repo(tmp_path: Path) -> Path:
    """Materialize a minimal repo at ``tmp_path/repo`` exercising
    the Cellar + symlink-farm code path without dragging in skills,
    crystallizer, MCPs, or built packages.

    Layout::

        repo/
        ├── install                         (real script)
        ├── config/
        │   └── settings.template.json      (with new ~/.claude/scripts/ paths)
        └── scripts/
            ├── foo                         (top-level — gets a symlink)
            ├── bar                         (top-level — gets a symlink)
            ├── ci/
            │   └── check-deps.sh           (stub: no deps)
            └── hooks/nerf/
                └── pre-compact.sh          (subtree — Cellar only, no symlink)
    """
    repo = tmp_path / "repo"
    scripts = repo / "scripts"
    scripts.mkdir(parents=True)

    # Top-level scripts (these get symlinks).
    (scripts / "foo").write_text("#!/bin/bash\necho foo\n")
    os.chmod(scripts / "foo", 0o755)
    (scripts / "bar").write_text("#!/bin/bash\necho bar\n")
    os.chmod(scripts / "bar", 0o755)

    # Subtree (Cellar-only, no symlink under recommendation B).
    nerf = scripts / "hooks" / "nerf"
    nerf.mkdir(parents=True)
    (nerf / "pre-compact.sh").write_text("#!/bin/bash\necho pre-compact\n")
    os.chmod(nerf / "pre-compact.sh", 0o755)

    # Stub ci/check-deps.sh so the post-install dep gate is a no-op.
    ci_dir = scripts / "ci"
    ci_dir.mkdir()
    (ci_dir / "check-deps.sh").write_text(
        "#!/usr/bin/env bash\ncheck_deps() { return 0; }\n"
    )
    (ci_dir / "check-deps.sh").chmod(0o755)

    # Minimal settings template using the NEW Cellar hook path.
    config_dir = repo / "config"
    config_dir.mkdir()
    template = {
        "hooks": {
            "PreCompact": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "~/.claude/scripts/hooks/nerf/pre-compact.sh",
                        }
                    ],
                }
            ],
        },
    }
    (config_dir / "settings.template.json").write_text(json.dumps(template, indent=2))

    # Drop the real install script in.
    shutil.copy(_INSTALL_SCRIPT, repo / "install")
    os.chmod(repo / "install", 0o755)
    return repo


def _build_sandbox_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


def _run_install(repo: Path, args: list[str], home: Path) -> tuple[int, str, str]:
    result = subprocess.run(
        ["bash", str(repo / "install")] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# AC1 — Cellar wipe + redeploy
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
def test_cellar_wipe_and_redeploy(tmp_path: Path) -> None:
    """``~/.claude/scripts/`` is the canonical install location and the
    entire tree is wiped and recreated on every ``./install``."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # Plant a stale file in the Cellar BEFORE install — verify it disappears.
    cellar = home / ".claude" / "scripts"
    cellar.mkdir(parents=True, exist_ok=True)
    stale = cellar / "leftover-from-old-install"
    stale.write_text("#!/bin/bash\necho stale\n")

    rc, out, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"install --scripts failed: stdout={out}\nstderr={err}"

    # Cellar exists and contains current sources.
    assert (cellar / "foo").exists(), "Cellar missing top-level: foo"
    assert (cellar / "bar").exists(), "Cellar missing top-level: bar"
    assert (cellar / "hooks" / "nerf" / "pre-compact.sh").exists(), (
        "Cellar missing nested hook: hooks/nerf/pre-compact.sh"
    )

    # Stale file from before install was wiped.
    assert not stale.exists(), (
        f"Cellar wipe did not delete stale file: {stale}"
    )

    # Cellar files have exec bits preserved.
    assert os.access(str(cellar / "foo"), os.X_OK), "Cellar foo not executable"
    assert os.access(str(cellar / "hooks" / "nerf" / "pre-compact.sh"), os.X_OK), (
        "Cellar hook script not executable"
    )


# ---------------------------------------------------------------------------
# AC2 — Symlink farm: granularity B (top-level only)
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
def test_symlink_farm_granularity_b(tmp_path: Path) -> None:
    """``~/.local/bin/`` contains symlinks for top-level Cellar entries
    only. Subtrees (hooks/, vox-providers/, etc.) stay Cellar-only."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    rc, _out, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"install failed: {err}"

    bin_dir = home / ".local" / "bin"
    cellar = home / ".claude" / "scripts"

    # Top-level entries are symlinks pointing into the Cellar.
    for name in ("foo", "bar"):
        link = bin_dir / name
        assert link.is_symlink(), f"{name} should be a symlink in {bin_dir}"
        target = os.readlink(str(link))
        # Target may be absolute or relative — resolve via os.path.realpath.
        resolved = Path(os.path.realpath(str(link)))
        assert resolved == cellar / name, (
            f"{name} symlink target: expected {cellar / name}, got {resolved}"
        )

    # Subtree entries are NOT symlinked (granularity B).
    assert not (bin_dir / "hooks").exists(), (
        "hooks/ subtree should NOT be mirrored into ~/.local/bin/ "
        "(recommendation B from #560)"
    )


# ---------------------------------------------------------------------------
# AC3 — Removed-from-repo orphan-free re-deploy
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
def test_removed_from_repo_no_orphan(tmp_path: Path) -> None:
    """Running ``./install`` after a script is removed from the repo
    deletes both the Cellar entry AND the corresponding ``~/.local/bin/``
    symlink — without any ``--prune`` flag."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # First install: foo and bar both present.
    rc, _, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"first install failed: {err}"

    cellar = home / ".claude" / "scripts"
    bin_dir = home / ".local" / "bin"
    assert (cellar / "foo").exists()
    assert (bin_dir / "foo").is_symlink()

    # Remove foo from the repo.
    (repo / "scripts" / "foo").unlink()

    # Second install: foo should be gone from BOTH Cellar and bin/.
    rc, _, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"second install failed: {err}"

    assert not (cellar / "foo").exists(), (
        "removed-from-repo script still in Cellar after re-install"
    )
    assert not (bin_dir / "foo").exists(), (
        "removed-from-repo symlink still in ~/.local/bin/ — orphan rot"
    )
    # bar is unaffected.
    assert (cellar / "bar").exists()
    assert (bin_dir / "bar").is_symlink()


# ---------------------------------------------------------------------------
# AC4 — Settings hook path migration
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_settings_hook_path_migration(tmp_path: Path) -> None:
    """``~/.claude/settings.json`` hook command paths get rewritten from
    ``~/.local/bin/hooks/...`` to ``~/.claude/scripts/hooks/...`` during
    ``merge_settings()``."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # Pre-existing user settings with the OLD path shape.
    settings = home / ".claude" / "settings.json"
    _write_json(settings, {
        "hooks": {
            "PreCompact": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "~/.local/bin/hooks/nerf/pre-compact.sh",
                        }
                    ],
                }
            ],
        },
    })

    rc, _out, err = _run_install(repo, ["--config"], home)
    assert rc == 0, f"install --config failed: {err}"

    merged = _read_json(settings)
    cmd = merged["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    assert cmd == "~/.claude/scripts/hooks/nerf/pre-compact.sh", (
        f"hook path not migrated: got {cmd}"
    )

    # Backup retains the original.
    bak = settings.with_suffix(".json.bak")
    assert bak.exists(), "settings.json.bak not created during migration"
    bak_data = _read_json(bak)
    bak_cmd = bak_data["hooks"]["PreCompact"][0]["hooks"][0]["command"]
    assert bak_cmd == "~/.local/bin/hooks/nerf/pre-compact.sh", (
        "settings.json.bak should preserve the pre-migration path"
    )


# ---------------------------------------------------------------------------
# AC5 — Matcher union-merge still works (re-confirm #556 wave-1 contract)
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_matcher_union_merge_still_works(tmp_path: Path) -> None:
    """``merge_settings()`` continues to union-merge new matcher entries
    into existing event arrays (regression test for #556 logic now sharing
    code path with the #560 path-rewrite)."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # Override the synthetic template to have TWO matchers in a single
    # event. The user has only one — merge must add the second.
    template = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "default-session-start.sh"}
                    ],
                },
                {
                    "matcher": "compact",
                    "hooks": [
                        {"type": "command", "command": "session-start-compact.sh"}
                    ],
                },
            ],
        },
    }
    (repo / "config" / "settings.template.json").write_text(
        json.dumps(template, indent=2)
    )

    settings = home / ".claude" / "settings.json"
    _write_json(settings, {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "user-session-start.sh"}
                    ],
                }
            ],
        },
    })

    rc, _out, err = _run_install(repo, ["--config"], home)
    assert rc == 0, f"install --config failed: {err}"

    merged = _read_json(settings)
    matchers = sorted(e["matcher"] for e in merged["hooks"]["SessionStart"])
    assert matchers == ["*", "compact"], (
        f"matcher union merge failed: got {matchers}"
    )
    # User customization on '*' preserved.
    star = next(e for e in merged["hooks"]["SessionStart"] if e["matcher"] == "*")
    assert any(h["command"] == "user-session-start.sh" for h in star["hooks"]), (
        "user customization on shared matcher was overwritten"
    )


# ---------------------------------------------------------------------------
# AC6 — User-customized plain file gets backed up before symlink replacement
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
def test_user_customized_plain_file_backup(tmp_path: Path) -> None:
    """If ``~/.local/bin/<script>`` is a plain file (not a symlink) with
    hand edits, install backs it up to ``.bak`` before replacing it with
    a symlink."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # Plant a user-customized plain file at the destination.
    bin_dir = home / ".local" / "bin"
    user_foo = bin_dir / "foo"
    user_foo.write_text("#!/bin/bash\necho USER CUSTOMIZED\n")
    os.chmod(user_foo, 0o755)

    rc, _out, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"install failed: {err}"

    # Plain file replaced with symlink into Cellar.
    assert user_foo.is_symlink(), "user plain file not replaced with symlink"
    # Backup retains the user's version.
    bak = bin_dir / "foo.bak"
    assert bak.exists(), "user customization not backed up to .bak"
    assert "USER CUSTOMIZED" in bak.read_text(), (
        "backup does not contain user-customized content"
    )


# ---------------------------------------------------------------------------
# Bonus AC — Foreign symlinks (target outside Cellar) NOT touched
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
def test_foreign_symlinks_untouched(tmp_path: Path) -> None:
    """Symlinks in ``~/.local/bin/`` whose target is outside the Cellar
    (e.g. user-installed binaries from another tool) must NOT be touched
    by the symlink-farm reaper."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # First install establishes the Cellar.
    rc, _, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"first install failed: {err}"

    # Plant a foreign symlink: point ~/.local/bin/myapp at a path OUTSIDE
    # the Cellar. Make the target legitimate (so it isn't itself stale),
    # then verify install leaves it alone.
    foreign_target = tmp_path / "elsewhere" / "myapp"
    foreign_target.parent.mkdir(parents=True, exist_ok=True)
    foreign_target.write_text("#!/bin/bash\necho foreign\n")
    os.chmod(foreign_target, 0o755)

    bin_dir = home / ".local" / "bin"
    foreign_link = bin_dir / "myapp"
    foreign_link.symlink_to(foreign_target)

    # Re-run install.
    rc, _out, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"second install failed: {err}"

    # Foreign symlink and its target both still exist, untouched.
    assert foreign_link.is_symlink(), "foreign symlink was removed"
    assert foreign_link.resolve() == foreign_target.resolve(), (
        "foreign symlink target was changed"
    )

    # Now make the foreign target also dangle (rm the file). Reaper still
    # leaves it — because it points OUTSIDE Cellar, not under it.
    foreign_target.unlink()
    rc, _out, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"third install failed: {err}"
    assert foreign_link.is_symlink(), (
        "foreign symlink with dangling external target was incorrectly "
        "reaped (reaper must only consider Cellar-targeted symlinks)"
    )


# ---------------------------------------------------------------------------
# AC7a — --check reports stale symlinks
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
def test_check_reports_stale_symlinks(tmp_path: Path) -> None:
    """``./install --check`` reports symlinks under ``~/.local/bin/`` that
    point into the Cellar but whose target no longer exists."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # First install populates the farm.
    rc, _, err = _run_install(repo, ["--scripts"], home)
    assert rc == 0, f"install failed: {err}"

    # Manually break a symlink — delete its Cellar target without touching
    # the link itself. Use a name that will NOT be in enumerate_farm_targets
    # on the next check (i.e. simulate a removed-from-repo script).
    cellar = home / ".claude" / "scripts"
    bin_dir = home / ".local" / "bin"

    # Plant a symlink to a fake old script and a Cellar target, then
    # delete the target.
    fake_target = cellar / "ghost-script"
    fake_target.write_text("#!/bin/bash\necho ghost\n")
    fake_link = bin_dir / "ghost-script"
    fake_link.symlink_to(fake_target)
    fake_target.unlink()  # now stale

    rc, out, err = _run_install(repo, ["--check"], home)
    assert rc == 0, f"--check exited non-zero: {err}"

    output = out + err
    # The stale entry must appear in the output as drift.
    assert "ghost-script" in output, (
        f"--check did not report stale symlink 'ghost-script':\n{output}"
    )
    # Either as DANGLING SYMLINK (if it's enumerated as expected) or as
    # 'stale symlink' (the reaper-side detection) — both forms are valid.
    assert ("stale" in output.lower()) or ("dangling" in output.lower()), (
        f"--check did not flag the symlink as stale/dangling:\n{output}"
    )
    assert "out of sync" in output.lower(), (
        f"--check summary did not report drift:\n{output}"
    )


# ---------------------------------------------------------------------------
# AC7b — --check reports old-path hook commands as drift
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_check_reports_old_path_hooks(tmp_path: Path) -> None:
    """``./install --check`` reports hook command paths still using the
    pre-Cellar form ``~/.local/bin/hooks/...`` as drift."""
    repo = _build_synthetic_repo(tmp_path)
    home = _build_sandbox_home(tmp_path)

    # Pre-existing settings with old-shape hook paths.
    settings = home / ".claude" / "settings.json"
    _write_json(settings, {
        "hooks": {
            "PreCompact": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "~/.local/bin/hooks/nerf/pre-compact.sh",
                        }
                    ],
                }
            ],
        },
    })

    rc, out, err = _run_install(repo, ["--check"], home)
    assert rc == 0, f"--check exited non-zero: {err}"
    output = out + err

    # The drift report must name the affected event AND describe the gap.
    assert "PreCompact" in output, (
        f"--check did not name the affected event 'PreCompact':\n{output}"
    )
    assert "old" in output.lower() and "~/.local/bin/hooks" in output, (
        f"--check did not describe the old-path drift:\n{output}"
    )
    assert "out of sync" in output.lower(), (
        f"--check summary did not report drift:\n{output}"
    )
