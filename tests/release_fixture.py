"""A release tarball built by the real scripts/ci/package-release.sh, and stubs that let
scripts/install-remote.sh install it into a sandbox HOME with no network (#1360).

The curl stub serves the fixture tarball for any URL ending in ``cc-workflow.tar.gz`` and
exits 22 (curl's HTTP-error code) for anything else. The claude stub exists only to pass
the prerequisite check; every run passes ``--no-mcps``, so nothing asks it to register.
"""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path

from tests.sandbox_env import sandbox_env

REPO_DIR = Path(__file__).resolve().parent.parent
PACKAGE = REPO_DIR / "scripts" / "ci" / "package-release.sh"
INSTALL_REMOTE = REPO_DIR / "scripts" / "install-remote.sh"

# ./install's SCRIPTS_EXCLUDE_NAMES: a path with any of these as a directory is not deployed.
SCRIPTS_EXCLUDE_NAMES = {"tests", "fixtures", "__pycache__", ".pytest_cache"}

_CURL_STUB = """#!/usr/bin/env bash
out="" url=""
while (($#)); do
	case "$1" in
	-o) out="$2"; shift ;;
	-*) ;;
	*) url="$1" ;;
	esac
	shift
done
[[ "$url" == *cc-workflow.tar.gz ]] || exit 22
cp "$FAKE_TARBALL" "$out"
"""

_CLAUDE_STUB = "#!/usr/bin/env bash\nexit 0\n"


def build_tarball(out_dir: Path) -> Path:
    """Run package-release.sh in out_dir; return the tarball it wrote."""
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["bash", str(PACKAGE), "v0.0.0-test"], cwd=out_dir, check=True,
                   capture_output=True, text=True, timeout=300)
    return out_dir / "cc-workflow.tar.gz"


def tarball_members(tarball: Path) -> set[str]:
    """File paths in the tarball, without the leading './'."""
    with tarfile.open(tarball) as tf:
        return {m.name.removeprefix("./") for m in tf.getmembers() if m.isfile()}


def without_lib(tarball: Path, out_dir: Path) -> Path:
    """A copy of tarball with scripts/lib/ removed: what a pre-#1360 release looks like."""
    stage = out_dir / "stage"
    stage.mkdir(parents=True)
    with tarfile.open(tarball) as tf:
        tf.extractall(stage, filter="tar")
    for f in sorted((stage / "scripts" / "lib").rglob("*"), reverse=True):
        f.unlink() if f.is_file() else f.rmdir()
    (stage / "scripts" / "lib").rmdir()
    old = out_dir / "cc-workflow.tar.gz"
    subprocess.run(["tar", "-czf", str(old), "-C", str(stage), "."], check=True)
    return old


def deployed_scripts() -> set[str]:
    """What ./install's enumerate_scripts deploys to the Cellar, less ci/: the set the
    tarball's scripts/ must hold."""
    root = REPO_DIR / "scripts"
    out = set()
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if rel.parts[0] == "ci" or SCRIPTS_EXCLUDE_NAMES & set(rel.parts[:-1]):
            continue
        out.add(rel.as_posix())
    return out


def stub_bin(dir_: Path) -> Path:
    """Write the curl and claude stubs into dir_ and return it."""
    dir_.mkdir(parents=True, exist_ok=True)
    for name, body in (("curl", _CURL_STUB), ("claude", _CLAUDE_STUB)):
        (dir_ / name).write_text(body)
        os.chmod(dir_ / name, 0o755)
    return dir_


def sandbox_home(root: Path) -> Path:
    home = root / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    return home


def run_install_remote(home: Path, stubs: Path, tarball: Path, *args: str) -> subprocess.CompletedProcess:
    """install-remote.sh into home, from tarball, with no MCPs and no logrotate."""
    env = sandbox_env(home)
    env["PATH"] = f"{stubs}{os.pathsep}{env['PATH']}"
    env["FAKE_TARBALL"] = str(tarball)
    return subprocess.run(
        ["bash", str(INSTALL_REMOTE), "--no-mcps", "--without-logrotate", *args],
        capture_output=True, text=True, env=env, timeout=300,
    )
