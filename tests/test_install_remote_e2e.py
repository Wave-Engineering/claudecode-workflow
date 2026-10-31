"""scripts/install-remote.sh, end to end, from a real release tarball (#1360).

A tarball built by the real package-release.sh is installed into a sandbox HOME
(tests/sandbox_env.py) through stub curl and claude. Nothing reaches the network,
runs a real claude, or touches the real ~/.claude.

Covers triage #24 (the tarball ships the hooks; the remote merge is the shared
one, with the kit-owned union, the old-path migration and the duplicate collapse;
--dry-run writes no settings; a tarball older than the shared merge is refused)
and triage #26 through the remote path (only executable helpers get a PATH link).
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest

from tests.release_fixture import (
    INSTALL_REMOTE,
    REPO_DIR,
    build_tarball,
    run_install_remote,
    sandbox_home,
    stub_bin,
    without_lib,
)

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("jq") and shutil.which("python3")),
    reason="bash, jq and python3 required",
)

_TEMPLATE = json.loads((REPO_DIR / "config" / "settings.template.json").read_text())
_STALL_GUARD = "~/.claude/scripts/hooks/workflow/wavemachine-stall-guard.sh"
_PUSH_GATE = "~/.claude/scripts/hooks/workflow/pre-push-test-gate.sh"


@pytest.fixture(scope="module")
def tarball(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_tarball(tmp_path_factory.mktemp("release"))


@pytest.fixture()
def env(tmp_path: Path) -> tuple[Path, Path]:
    return sandbox_home(tmp_path), stub_bin(tmp_path / "stubs")


def _commands(settings: dict, event: str) -> list[str]:
    return [h.get("command", "") for g in settings.get("hooks", {}).get(event, []) for h in g.get("hooks", [])]


def _template_kit_paths() -> list[str]:
    cmds = [c for ev, groups in _TEMPLATE["hooks"].items() if isinstance(groups, list) for c in _commands(_TEMPLATE, ev)]
    return sorted({m.group(1) for c in cmds for m in re.finditer(r"~/\.claude/scripts/(\S+)", c)})


def _install(env: tuple[Path, Path], tarball: Path, *args: str):
    home, stubs = env
    r = run_install_remote(home, stubs, tarball, *args)
    assert r.returncode == 0, f"install-remote.sh failed (rc={r.returncode}):\n{r.stdout}\n{r.stderr}"
    return r


def _seed(home: Path, settings: dict) -> Path:
    path = home / ".claude" / "settings.json"
    path.write_text(json.dumps(settings, indent=2))
    return path


def test_remote_install_deploys_hooks(env: tuple[Path, Path], tarball: Path) -> None:
    home, _ = env
    _install(env, tarball)
    paths = _template_kit_paths()
    assert paths
    for rel in paths:
        f = home / ".claude" / "scripts" / rel
        assert f.is_file(), f"template hook {rel} missing after a release install"
        assert os.access(f, os.X_OK), f"template hook {rel} is not executable"


def test_remote_merge_unions_kit_star_hooks(env: tuple[Path, Path], tarball: Path) -> None:
    home, _ = env
    user = "~/my-own-stop-hook.sh"
    path = _seed(home, {"hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": user}]}]}})
    _install(env, tarball)
    stop = _commands(json.loads(path.read_text()), "Stop")
    assert user in stop, "the user's own Stop hook was dropped"
    kit = [c for g in _TEMPLATE["hooks"]["Stop"] if g.get("matcher") == "*" for c in [h["command"] for h in g["hooks"]]]
    assert len(kit) > 1
    missing = [c for c in kit if c not in stop]
    assert not missing, f"kit '*' Stop hooks not unioned in: {missing}"


def test_remote_merge_migrates_old_hook_paths(env: tuple[Path, Path], tarball: Path) -> None:
    home, _ = env
    old = _PUSH_GATE.replace("~/.claude/scripts/hooks/", "~/.local/bin/hooks/")
    path = _seed(home, {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": old}]}]}})
    _install(env, tarball)
    merged = json.loads(path.read_text())
    every = [c for ev in merged["hooks"] for c in _commands(merged, ev)]
    assert not [c for c in every if c.startswith("~/.local/bin/hooks/")], "an old hook path survived"
    assert _PUSH_GATE in _commands(merged, "PreToolUse")


def test_remote_merge_collapses_duplicates(env: tuple[Path, Path], tarball: Path) -> None:
    home, _ = env
    twice = [{"type": "command", "command": _STALL_GUARD}] * 2
    path = _seed(home, {"hooks": {"Stop": [{"matcher": "*", "hooks": twice}]}})
    _install(env, tarball)
    assert _commands(json.loads(path.read_text()), "Stop").count(_STALL_GUARD) == 1


def test_remote_dry_run_writes_no_settings(env: tuple[Path, Path], tarball: Path) -> None:
    home, _ = env
    path = _seed(home, {"hooks": {}, "permissions": {"allow": ["Read"]}})
    before = path.read_bytes()
    r = _install(env, tarball, "--dry-run")
    assert path.read_bytes() == before, "--dry-run changed settings.json"
    assert not (home / ".claude" / "settings.json.bak").exists(), "--dry-run wrote a backup"
    assert "(dry-run) Would merge settings.template.json" in r.stdout


def test_remote_refuses_a_tarball_without_the_lib(env: tuple[Path, Path], tarball: Path, tmp_path: Path) -> None:
    home, stubs = env
    floor = re.search(r'^SETTINGS_MERGE_FLOOR="([^"]+)"', INSTALL_REMOTE.read_text(), re.MULTILINE)
    assert floor, "SETTINGS_MERGE_FLOOR is not defined in install-remote.sh"
    r = run_install_remote(home, stubs, without_lib(tarball, tmp_path / "old"))
    out = r.stdout + r.stderr
    assert r.returncode != 0, f"a lib-less tarball was installed:\n{out}"
    assert "predates the shared settings merge" in out, out
    assert f"v{floor.group(1)}" in out, f"the refusal does not name v{floor.group(1)}:\n{out}"
    assert "<tag>/scripts/install-remote.sh" in out, f"the refusal does not say how to install an older tag:\n{out}"
    assert not (home / ".claude" / "scripts").exists(), "the refused install wrote the Cellar"


def test_remote_non_executable_helpers_get_no_path_link(env: tuple[Path, Path], tarball: Path) -> None:
    home, _ = env
    _install(env, tarball)
    for skill in ("nextwave", "lazyriver"):
        got = home / ".claude" / "scripts" / "skills" / skill / "bundle.mjs"
        assert got.read_bytes() == (REPO_DIR / "skills" / skill / "bundle.mjs").read_bytes(), f"{skill}'s bundle.mjs"
    farm = home / ".local" / "bin"
    assert not (farm / "bundle.mjs").exists() and not (farm / "bundle.mjs").is_symlink()
    for exe in ("file-opener", "job-fetch"):
        assert (farm / exe).is_symlink(), f"{exe} has no PATH link"
