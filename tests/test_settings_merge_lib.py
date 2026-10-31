"""scripts/lib/settings-merge.sh is the one settings merge, and it stands alone (#1360).

The remote installer used to carry its own copy of the merge, forked before #734. These
pin that there is one definition, that both installers source it, and that it merges with
only its documented contract in place (no REPO_DIR, no LOCAL_MODE).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_LIB = _REPO / "scripts" / "lib" / "settings-merge.sh"
_DEF = re.compile(r"^merge_settings\(\)", re.MULTILINE)


@pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="bash and jq required")
def test_lib_merges_standalone(tmp_path: Path) -> None:
    kit = ["~/.local/bin/kit-a.sh", "~/.claude/scripts/hooks/workflow/kit-b.sh"]
    user = "~/mine.sh"
    tpl = tmp_path / "tpl.json"
    tpl.write_text(json.dumps({"hooks": {"Stop": [
        {"matcher": "*", "hooks": [{"type": "command", "command": c}]} for c in kit]}}))
    local = tmp_path / "local.json"
    local.write_text(json.dumps({"hooks": {"Stop": [
        {"matcher": "*", "hooks": [{"type": "command", "command": user}]}]}, "permissions": {"allow": []}}))
    script = (
        'info(){ :; }; ok(){ :; }; warn(){ :; }; skip(){ :; }; drift(){ :; }; '
        f'CELLAR_DIR="{tmp_path}/cellar"; SCRIPTS_DIR="{tmp_path}/bin"; CLAUDE_DIR="{tmp_path}"; '
        f'source "{_LIB}"; merge_settings "{tpl}" "{local}"'
    )
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", "-euo", "pipefail", "-c", script], capture_output=True, text=True,
                       env=env, timeout=60)
    assert r.returncode == 0, r.stderr
    stop = [h["command"] for g in json.loads(local.read_text())["hooks"]["Stop"] for h in g["hooks"]]
    assert user in stop and all(c in stop for c in kit), stop


def test_one_merge_implementation() -> None:
    install = (_REPO / "install").read_text()
    remote = (_REPO / "scripts" / "install-remote.sh").read_text()
    assert not _DEF.search(install), "install still defines its own merge_settings()"
    assert not _DEF.search(remote), "install-remote.sh still defines its own merge_settings()"
    assert len(_DEF.findall(_LIB.read_text())) == 1
    assert 'source "$REPO_DIR/scripts/lib/settings-merge.sh"' in install
    assert 'source "$release_dir/scripts/lib/settings-merge.sh"' in remote
    others = [p for p in (_REPO / "scripts").rglob("*") if p.is_file() and p != _LIB
              and p.suffix in ("", ".sh") and _DEF.search(p.read_text(errors="ignore"))]
    assert not others, f"another merge_settings() definition: {others}"
