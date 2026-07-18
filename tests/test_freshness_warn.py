"""Tests for D1 (#908) — the context-freshness install stamp + SessionStart warn hook.

Covers scripts/write-install-stamp (imported via SourceFileLoader) and
scripts/hooks/workflow/context-freshness-warn.sh (driven via subprocess with a
sandboxed $HOME). Epic #906.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import subprocess

import pytest

_HERE = os.path.dirname(__file__)
_STAMP_SCRIPT = os.path.join(_HERE, "..", "scripts", "write-install-stamp")
_HOOK = os.path.join(_HERE, "..", "scripts", "hooks", "workflow", "context-freshness-warn.sh")

_loader = importlib.machinery.SourceFileLoader("write_install_stamp", _STAMP_SCRIPT)
_spec = importlib.util.spec_from_file_location("write_install_stamp", _STAMP_SCRIPT, loader=_loader)
wis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wis)


# --------------------------------------------------------------------------- #
# stamp writer
# --------------------------------------------------------------------------- #
def _make_repo(tmp_path, skills: dict[str, str]):
    for name, body in skills.items():
        d = tmp_path / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(body)
    return str(tmp_path)


def test_skill_hashes_reads_skill_md(tmp_path):
    repo = _make_repo(tmp_path, {"engage": "one", "precheck": "two"})
    h = wis.skill_hashes(repo)
    assert set(h) == {"engage", "precheck"}
    assert h["engage"] != h["precheck"]


def test_first_install_marks_all_changed(tmp_path):
    repo = _make_repo(tmp_path, {"engage": "one", "precheck": "two"})
    stamp = wis.build_stamp(repo, prior_skills={})
    assert stamp["first_install"] is True
    assert sorted(stamp["changed_skills"]) == ["engage", "precheck"]
    assert stamp["skill_count"] == 2
    assert "installed_at_epoch" in stamp and isinstance(stamp["installed_at_epoch"], int)


def test_changed_skills_is_the_diff(tmp_path):
    repo = _make_repo(tmp_path, {"engage": "NEW", "precheck": "same", "nextwave": "brand-new"})
    prior = wis.skill_hashes(repo).copy()
    # simulate the prior install: precheck unchanged, engage different, nextwave absent
    prior["engage"] = "OLD-hash-differs"
    del prior["nextwave"]
    stamp = wis.build_stamp(repo, prior_skills=prior)
    assert stamp["first_install"] is False
    assert sorted(stamp["changed_skills"]) == ["engage", "nextwave"]  # precheck NOT listed


def test_write_stamp_atomic_and_valid(tmp_path):
    repo = _make_repo(tmp_path, {"engage": "one"})
    cdir = tmp_path / "claude"
    path, stamp = wis.write_stamp(repo, str(cdir))
    assert os.path.isfile(path)
    on_disk = json.load(open(path))
    assert on_disk["skill_count"] == 1
    assert not os.path.exists(path + ".tmp")  # temp cleaned up by rename


# --------------------------------------------------------------------------- #
# hook
# --------------------------------------------------------------------------- #
def _run_hook(stdin_obj, home):
    return subprocess.run(
        ["bash", _HOOK],
        input=json.dumps(stdin_obj),
        capture_output=True, text=True,
        env={**os.environ, "HOME": str(home)},
    )


def _write_transcript(path, session_ts):
    """A FAITHFUL transcript: CC-style preamble records with NO top-level timestamp,
    then the first genuinely-timestamped event (regression guard for the head -n1 bug)."""
    with open(path, "w") as f:
        f.write(json.dumps({"type": "custom-title", "title": "x"}) + "\n")
        f.write(json.dumps({"type": "mode", "mode": "normal"}) + "\n")
        f.write(json.dumps({"type": "user", "timestamp": session_ts,
                            "message": {"role": "user", "content": "hi"}}) + "\n")


def _setup(home, *, install_epoch, session_ts, sid="sid123",
           changed=("nextwave", "precheck"), stamp_dir=None):
    home = str(home)
    proj = os.path.join(home, ".claude", "projects", "encoded-proj")
    os.makedirs(proj, exist_ok=True)
    sdir = stamp_dir or os.path.join(home, ".claude")
    os.makedirs(sdir, exist_ok=True)
    json.dump(
        {"installed_at": "2026-07-18T00:00:00Z", "installed_at_epoch": install_epoch,
         "repo_sha": "abcdef1234567890", "changed_skills": list(changed)},
        open(os.path.join(sdir, ".last-kit-install"), "w"),
    )
    trans = os.path.join(proj, f"{sid}.jsonl")
    if session_ts is not None:
        _write_transcript(trans, session_ts)
    # transcript_path is provided by CC on stdin — the hook never reconstructs it.
    return {"session_id": sid, "cwd": "/x/proj", "source": "resume", "transcript_path": trans}


def test_hook_warns_on_stale_resume(tmp_path):
    """Faithful transcript (timestamp on line 3, not line 1) must still warn — the
    hook scans for the first genuinely-timestamped record."""
    stdin = _setup(tmp_path, install_epoch=1_700_000_000, session_ts="2020-01-01T00:00:00.000Z")
    p = _run_hook(stdin, tmp_path)
    assert p.returncode == 0
    assert "CONTEXT FRESHNESS WARNING" in p.stdout
    assert "nextwave, precheck" in p.stdout  # names the changed skills


def test_hook_silent_on_fresh_session(tmp_path):
    stdin = _setup(tmp_path, install_epoch=1_700_000_000, session_ts="2099-01-01T00:00:00.000Z")
    p = _run_hook(stdin, tmp_path)
    assert p.returncode == 0 and p.stdout.strip() == ""


def test_hook_prefers_project_local_stamp(tmp_path):
    """A --local install stamps <cwd>/.claude; the hook must read that (not just $HOME)."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)  # HOME exists but has NO stamp
    proj = tmp_path / "proj"
    (proj / ".claude").mkdir(parents=True)
    json.dump({"installed_at": "2026-07-18T00:00:00Z", "installed_at_epoch": 1_700_000_000,
               "repo_sha": "abc", "changed_skills": ["only-local"]},
              open(proj / ".claude" / ".last-kit-install", "w"))
    trans = proj / "t.jsonl"
    _write_transcript(str(trans), "2020-01-01T00:00:00.000Z")
    stdin = {"session_id": "s", "cwd": str(proj), "source": "resume", "transcript_path": str(trans)}
    p = _run_hook(stdin, home)
    assert p.returncode == 0
    assert "CONTEXT FRESHNESS WARNING" in p.stdout and "only-local" in p.stdout


def test_hook_silent_without_stamp(tmp_path):
    trans = tmp_path / "t.jsonl"
    _write_transcript(str(trans), "2020-01-01T00:00:00Z")
    p = _run_hook({"session_id": "s", "cwd": "/x/proj", "source": "resume",
                   "transcript_path": str(trans)}, tmp_path)
    assert p.returncode == 0 and p.stdout.strip() == ""


def test_hook_skips_clear_and_compact(tmp_path):
    stdin = _setup(tmp_path, install_epoch=1_700_000_000, session_ts="2020-01-01T00:00:00.000Z")
    for src in ("clear", "compact"):
        p = _run_hook({**stdin, "source": src}, tmp_path)
        assert p.returncode == 0 and p.stdout.strip() == "", f"should skip source={src}"


def test_hook_always_exits_zero_on_garbage(tmp_path):
    p = subprocess.run(["bash", _HOOK], input="not json at all", capture_output=True,
                       text=True, env={**os.environ, "HOME": str(tmp_path)})
    assert p.returncode == 0
