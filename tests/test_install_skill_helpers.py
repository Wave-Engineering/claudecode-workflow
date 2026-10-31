"""Skill helpers: only executable ones get a PATH link, and a collision is fatal (#1360, triage #26).

Both installers put every non-.md skill helper in a per-skill Cellar dir, and used to farm
a bare-name $SCRIPTS_DIR link for each one too, warning and overwriting on a clash. The two
bundle.mjs files (nextwave's and lazyriver's) differ, so the last skill won a PATH link to a
JS module nothing runs that way. Now a link is made only for an executable helper, the old
links are reaped, and two skills claiming one name in a run fail the install.

Each test installs a synthetic repo with ``./install --skills`` into a sandbox HOME.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.sandbox_env import sandbox_env

_REPO = Path(__file__).resolve().parent.parent
pytestmark = pytest.mark.skipif(not (shutil.which("bash") and shutil.which("jq")), reason="bash and jq required")


def _repo(tmp_path: Path, skills: dict[str, Path | dict[str, tuple[str, int]]]) -> Path:
    """A repo whose skills/ holds copies of real skills (a Path) or synthetic ones
    ({file: (body, mode)})."""
    repo = tmp_path / "repo"
    for name, src in skills.items():
        dest = repo / "skills" / name
        if isinstance(src, Path):
            shutil.copytree(src, dest)
        else:
            dest.mkdir(parents=True)
            (dest / "SKILL.md").write_text(f"# {name}\n")
            for f, (body, mode) in src.items():
                (dest / f).write_text(body)
                os.chmod(dest / f, mode)
    ci = repo / "scripts" / "ci"
    ci.mkdir(parents=True)
    (ci / "check-deps.sh").write_text("#!/usr/bin/env bash\ncheck_deps() { return 0; }\n")
    (repo / "scripts" / "lib").mkdir()
    shutil.copy(_REPO / "scripts" / "lib" / "settings-merge.sh", repo / "scripts" / "lib")
    shutil.copy(_REPO / "install", repo / "install")
    return repo


def _home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


def _install(repo: Path, home: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(repo / "install"), "--skills"], capture_output=True, text=True,
                          env=sandbox_env(home), timeout=120)


def test_non_executable_helpers_get_no_path_link(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {s: _REPO / "skills" / s for s in ("nextwave", "lazyriver", "jfail", "view")})
    home = _home(tmp_path)
    r = _install(repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    for skill in ("nextwave", "lazyriver"):
        got = home / ".claude" / "scripts" / "skills" / skill / "bundle.mjs"
        assert got.read_bytes() == (_REPO / "skills" / skill / "bundle.mjs").read_bytes()
        assert not os.access(got, os.X_OK), f"{skill}'s bundle.mjs was made executable in the Cellar"
    farm = home / ".local" / "bin"
    assert not (farm / "bundle.mjs").is_symlink() and not (farm / "bundle.mjs").exists()
    for exe in ("file-opener", "job-fetch"):
        assert (farm / exe).is_symlink() and os.access(farm / exe, os.X_OK), f"{exe} has no working PATH link"


def test_stale_non_executable_links_are_reaped(tmp_path: Path) -> None:
    repo = _repo(tmp_path, {"nextwave": _REPO / "skills" / "nextwave"})
    home = _home(tmp_path)
    farm = home / ".local" / "bin"
    stale = farm / "gate.js"
    stale.symlink_to(home / ".claude" / "scripts" / "skills" / "nextwave" / "gate.js")
    (tmp_path / "elsewhere.js").write_text("// not the kit's\n")
    foreign = farm / "foreign.js"
    foreign.symlink_to(tmp_path / "elsewhere.js")
    r = _install(repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert not stale.is_symlink(), "the old gate.js PATH link survived"
    assert "Reaped non-executable helper link" in r.stdout
    assert foreign.is_symlink() and foreign.resolve() == (tmp_path / "elsewhere.js").resolve()


def test_upgrade_drops_an_old_exec_bit_and_reaps_its_link(tmp_path: Path) -> None:
    """An older install made every Cellar helper +x. `--skills` skips the Cellar wipe, so
    the copy must not keep that mode, or the reap would skip the stale link."""
    repo = _repo(tmp_path, {"nextwave": _REPO / "skills" / "nextwave"})
    home = _home(tmp_path)
    old = home / ".claude" / "scripts" / "skills" / "nextwave" / "gate.js"
    old.parent.mkdir(parents=True)
    old.write_text("// an older gate.js\n")
    os.chmod(old, 0o755)
    link = home / ".local" / "bin" / "gate.js"
    link.symlink_to(old)
    r = _install(repo, home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert old.read_bytes() == (_REPO / "skills" / "nextwave" / "gate.js").read_bytes()
    assert not os.access(old, os.X_OK), "the Cellar gate.js kept the old install's exec bit"
    assert not link.is_symlink(), "the old gate.js PATH link survived an upgrade"


def test_executable_helper_collision_is_fatal(tmp_path: Path) -> None:
    exe = ("#!/usr/bin/env bash\necho {}\n", 0o755)
    repo = _repo(tmp_path, {"aaa": {"dup.sh": (exe[0].format("a"), exe[1])},
                            "bbb": {"dup.sh": (exe[0].format("b"), exe[1])}})
    home = _home(tmp_path)
    r = _install(repo, home)
    assert r.returncode != 0, f"a helper name collision installed:\n{r.stdout}"
    assert "Helper name collision for 'dup.sh'" in r.stderr, r.stderr
    link = home / ".local" / "bin" / "dup.sh"
    assert os.readlink(link) == str(home / ".claude" / "scripts" / "skills" / "aaa" / "dup.sh")


def test_repo_has_no_executable_helper_collisions() -> None:
    seen: dict[str, str] = {}
    clashes = []
    for helper in sorted((_REPO / "skills").glob("*/*")):
        if not helper.is_file() or helper.suffix == ".md" or not os.access(helper, os.X_OK):
            continue
        skill = helper.parent.name
        if helper.name in seen and seen[helper.name] != skill:
            clashes.append(f"{helper.name}: {seen[helper.name]} and {skill}")
        seen.setdefault(helper.name, skill)
    top = {p.name for p in (_REPO / "scripts").iterdir() if p.is_file()}
    clashes += [f"{n}: a skill helper and scripts/{n}" for n in sorted(top & seen.keys())]
    assert not clashes, clashes
