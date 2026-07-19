"""Tests for scripts/find-projects (epic #906, D3 #910) — POSIX-find-like selection
over session stores + optional -exec. Uses --projects-dir pointed at a fake tree so
no real session store is touched.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import io
import json
import os
import time

import pytest

_HERE = os.path.dirname(__file__)
_SCRIPT = os.path.join(_HERE, "..", "scripts", "find-projects")
_loader = importlib.machinery.SourceFileLoader("find_projects", _SCRIPT)
_spec = importlib.util.spec_from_file_location("find_projects", _SCRIPT, loader=_loader)
fp = importlib.util.module_from_spec(_spec)
_loader.exec_module(fp)


def _store(projects_dir, name, *, first_ts="2020-01-01T00:00:00.000Z", cwd="/home/x/proj", old=True):
    store = os.path.join(projects_dir, name)
    os.makedirs(store, exist_ok=True)
    t = os.path.join(store, "s.jsonl")
    with open(t, "w") as f:
        f.write(json.dumps({"type": "mode"}) + "\n")               # no ts/cwd
        f.write(json.dumps({"type": "attachment", "cwd": cwd}) + "\n")  # cwd, no ts
        f.write(json.dumps({"type": "user", "timestamp": first_ts, "cwd": cwd}) + "\n")
    if old:
        o = time.time() - 3600
        os.utime(t, (o, o))
    return store


def _stamp(tmp_path, install_epoch):
    p = tmp_path / "last-kit-install"
    p.write_text(json.dumps({"installed_at_epoch": install_epoch, "changed_skills": ["precheck"]}))
    return str(p)


# --------------------------------------------------------------------------- #
def test_list_default_no_side_effects(tmp_path, capsys, monkeypatch):
    pdir = tmp_path / "projects"
    a = _store(str(pdir), "a", cwd="/home/x/alpha")
    _store(str(pdir), "b", cwd="/home/x/beta")
    calls = []
    monkeypatch.setattr(fp.subprocess, "run", lambda *a, **k: calls.append(a))
    rc = fp.main(["--path", "*/alpha", "--projects-dir", str(pdir)])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out == [a]                 # only the matching store, printed
    assert calls == []                # and NO command was run (proves list-only)


def test_predicate_context_predates_install(tmp_path, monkeypatch, capsys):
    pdir = tmp_path / "projects"
    old = _store(str(pdir), "old", first_ts="2020-01-01T00:00:00.000Z")
    _store(str(pdir), "new", first_ts="2099-01-01T00:00:00.000Z")
    monkeypatch.setattr(fp, "STAMP", _stamp(tmp_path, 1_700_000_000))
    rc = fp.main(["--context-predates-install", "--projects-dir", str(pdir)])
    assert rc == 0
    assert capsys.readouterr().out.strip().splitlines() == [old]


def test_print_cwd_token(tmp_path, capsys):
    pdir = tmp_path / "projects"
    _store(str(pdir), "a", cwd="/home/x/alpha")
    fp.main(["--path", "*/alpha", "--print", "cwd", "--projects-dir", str(pdir)])
    assert capsys.readouterr().out.strip() == "/home/x/alpha"


def test_stopped_vs_running(tmp_path, capsys, monkeypatch):
    pdir = tmp_path / "projects"
    stopped = _store(str(pdir), "stopped")
    _store(str(pdir), "running")
    # deterministic + portable: don't depend on /proc or wall-clock mtime.
    # match on the STORE dir name (the tmp path itself contains "stopped").
    monkeypatch.setattr(fp, "_liveness",
                        lambda s, scan=None: "idle" if os.path.basename(os.path.dirname(s)) == "stopped" else "live")
    assert fp.main(["--stopped", "--projects-dir", str(pdir)]) == 0
    assert capsys.readouterr().out.strip().splitlines() == [stopped]


def test_missing_terminator_is_an_error(tmp_path, capsys):
    pdir = tmp_path / "projects"
    _store(str(pdir), "a")
    # forgot the '\;' — must error, never sweep
    rc = fp.main(["--stopped", "--projects-dir", str(pdir), "-exec", "reorient", "{}"])
    assert rc == 2
    assert "terminator" in capsys.readouterr().err


def test_predicate_after_terminator_is_honored(tmp_path, monkeypatch):
    """A predicate placed AFTER the terminator must reach argparse, not be dropped."""
    pdir = tmp_path / "projects"
    _store(str(pdir), "a", cwd="/home/x/alpha")
    calls = []
    monkeypatch.setattr(fp.subprocess, "run", lambda cmd, *a, **k: calls.append(cmd) or type("R", (), {"returncode": 0})())
    # --path after the terminator should still filter (here: match nothing)
    rc = fp.main(["--projects-dir", str(pdir), "-exec", "echo", "{}", ";", "--path", "*/nomatch"])
    assert rc == 0 and calls == []  # predicate honored -> no match -> no exec


def test_no_predicate_exec_is_refused_unless_force(tmp_path, monkeypatch, capsys):
    pdir = tmp_path / "projects"
    _store(str(pdir), "a")
    ran = []
    monkeypatch.setattr(fp.subprocess, "run", lambda cmd, *a, **k: ran.append(cmd) or type("R", (), {"returncode": 0})())
    assert fp.main(["--projects-dir", str(pdir), "-exec", "echo", "{}", ";"]) == 2  # refused
    assert ran == [] and "refusing" in capsys.readouterr().err
    assert fp.main(["--force", "--projects-dir", str(pdir), "-exec", "echo", "{}", ";"]) == 0  # allowed
    assert len(ran) == 1


def test_bad_last_active_before_errors(tmp_path, capsys):
    pdir = tmp_path / "projects"
    _store(str(pdir), "a")
    assert fp.main(["--last-active-before", "not-a-date", "--projects-dir", str(pdir)]) == 2
    assert "unparseable" in capsys.readouterr().err


def test_exec_substitutes_and_isolates(tmp_path, capsys):
    pdir = tmp_path / "projects"
    a = _store(str(pdir), "a", cwd="/home/x/a")
    b = _store(str(pdir), "b", cwd="/home/x/b")
    open(os.path.join(a, "ok"), "w").close()  # 'a' will pass; 'b' has no ok -> fails
    # touch a 'ran' marker in every store it executes on, then test -e ok (fails for b)
    rc = fp.main(["--path", "*", "--projects-dir", str(pdir),
                  "-exec", "sh", "-c", 'touch "$1/ran"; test -e "$1/ok"', "_", "{}", ";"])
    assert rc == 1  # one exec failed
    assert os.path.exists(os.path.join(a, "ran")) and os.path.exists(os.path.join(b, "ran"))  # both ran (isolation)


def test_exec_requires_placeholder(tmp_path):
    pdir = tmp_path / "projects"
    _store(str(pdir), "a")
    assert fp.main(["--projects-dir", str(pdir), "-exec", "echo", "hi", ";"]) == 2


def test_dry_run_prints_plan_runs_nothing(tmp_path, capsys):
    pdir = tmp_path / "projects"
    a = _store(str(pdir), "a")
    rc = fp.main(["--dry-run", "--path", "*", "--projects-dir", str(pdir),
                  "-exec", "touch", "{}/SHOULD_NOT_EXIST", ";"])
    assert rc == 0
    assert not os.path.exists(os.path.join(a, "SHOULD_NOT_EXIST"))
    assert "would exec:" in capsys.readouterr().out


def test_ok_prompt_yes_and_no(tmp_path, monkeypatch):
    pdir = tmp_path / "projects"
    a = _store(str(pdir), "a")
    # decline
    monkeypatch.setattr("sys.stdin", io.StringIO("n\n"))
    fp.main(["--path", "*", "--projects-dir", str(pdir), "-ok", "touch", "{}/MARK", ";"])
    assert not os.path.exists(os.path.join(a, "MARK"))
    # accept
    monkeypatch.setattr("sys.stdin", io.StringIO("y\n"))
    fp.main(["--path", "*", "--projects-dir", str(pdir), "-ok", "touch", "{}/MARK", ";"])
    assert os.path.exists(os.path.join(a, "MARK"))
    # --yes bypasses the prompt
    fp.main(["--yes", "--path", "*", "--projects-dir", str(pdir), "-ok", "touch", "{}/MARK2", ";"])
    assert os.path.exists(os.path.join(a, "MARK2"))
