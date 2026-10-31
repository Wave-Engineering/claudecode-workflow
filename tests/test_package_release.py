"""The release tarball ships what ./install deploys (#1360, triage #24).

Before #1360 package-release.sh copied only top-level scripts/ files. A release install
then had no hooks/ (every template hook pointed at a missing file), no lib/ and no
logrotate asset. These run the real packager into tmp_path and read the tarball.
"""

from __future__ import annotations

import json
import re
import shutil
import tarfile
from pathlib import Path

import pytest

from tests.release_fixture import REPO_DIR, build_tarball, deployed_scripts, tarball_members

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="bash required")

_TEMPLATE = REPO_DIR / "config" / "settings.template.json"
_KIT_PATH = re.compile(r"~/\.claude/scripts/(\S+)")


@pytest.fixture(scope="module")
def tarball(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_tarball(tmp_path_factory.mktemp("release"))


def test_tarball_ships_every_cellar_file(tarball: Path) -> None:
    shipped = {m.removeprefix("scripts/") for m in tarball_members(tarball) if m.startswith("scripts/")}
    want = deployed_scripts()
    assert shipped == want, (
        f"missing from tarball: {sorted(want - shipped)}; unexpected: {sorted(shipped - want)}"
    )


def test_tarball_ships_every_template_hook(tarball: Path) -> None:
    members = tarball_members(tarball)
    template = json.loads(_TEMPLATE.read_text())
    commands = [h.get("command", "") for groups in template["hooks"].values() if isinstance(groups, list)
                for g in groups for h in g.get("hooks", [])]
    paths = sorted({m.group(1) for c in commands for m in _KIT_PATH.finditer(c)})
    assert paths, "the template names no ~/.claude/scripts/ hook; the test reads nothing"
    missing = [p for p in paths if f"scripts/{p}" not in members]
    assert not missing, f"template hooks missing from the tarball: {missing}"


def test_tarball_ships_the_merge_lib_and_logrotate_asset(tarball: Path) -> None:
    members = tarball_members(tarball)
    for want in ("scripts/lib/settings-merge.sh", "scripts/lib/assert-no-duplicate-hooks.sh",
                 "assets/logrotate/cc-mcp-logs"):
        assert want in members, f"{want} missing from the tarball"
    assert not [m for m in members if m.startswith("scripts/ci/")], "scripts/ci/ must not ship"


def test_tarball_preserves_helper_modes(tarball: Path) -> None:
    with tarfile.open(tarball) as tf:
        mode = {m.name.removeprefix("./"): m.mode for m in tf.getmembers() if m.isfile()}
    for exe in ("skills/view/file-opener", "skills/jfail/job-fetch"):
        assert mode[exe] & 0o111, f"{exe} lost its executable bit in the tarball"
    assert not mode["skills/nextwave/bundle.mjs"] & 0o111, "bundle.mjs became executable"
