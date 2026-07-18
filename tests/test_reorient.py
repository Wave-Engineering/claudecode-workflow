"""Tests for scripts/reorient (epic #906, D2 #909) — proactive re-orientation of a
stopped agent. Drives the real skill-gc via subprocess, so it exercises the full
evict + backup + fail-closed-on-live chain end to end.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import time

import pytest

_HERE = os.path.dirname(__file__)
_SCRIPT = os.path.join(_HERE, "..", "scripts", "reorient")
_loader = importlib.machinery.SourceFileLoader("reorient", _SCRIPT)
_spec = importlib.util.spec_from_file_location("reorient", _SCRIPT, loader=_loader)
ro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ro)

BODY = "SKILL BODY START — " + ("line. " * 200) + " — SKILL BODY END"


def _make_transcript(path, *, first_ts="2020-01-01T00:00:00.000Z", stale_mtime=True):
    events = [
        {"type": "user", "uuid": "U0", "parentUuid": None, "timestamp": first_ts,
         "message": {"role": "user", "content": [{"type": "text", "text": "run precheck"}]}},
        {"type": "assistant", "uuid": "U1", "parentUuid": "U0", "timestamp": first_ts,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "toolu_A", "name": "Skill", "input": {"skill": "precheck"}}]}},
        {"type": "user", "uuid": "U2", "parentUuid": "U1", "timestamp": first_ts,
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "toolu_A", "content": "Launching skill: precheck"}]}},
        {"type": "user", "uuid": "U3", "parentUuid": "U2", "isMeta": True, "timestamp": first_ts,
         "message": {"role": "user", "content": [{"type": "text", "text": BODY}]}},
    ]
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    if stale_mtime:
        old = time.time() - 3600
        os.utime(path, (old, old))
    return str(path)


def _stamp(claude_dir, *, install_epoch, changed=("precheck", "nextwave")):
    os.makedirs(claude_dir, exist_ok=True)
    json.dump({"installed_at": "2026-07-18T00:00:00Z", "installed_at_epoch": install_epoch,
               "repo_sha": "abcdef1234567890", "changed_skills": list(changed)},
              open(os.path.join(claude_dir, ".last-kit-install"), "w"))


# --------------------------------------------------------------------------- #
def test_pick_transcript_file_and_dir(tmp_path):
    t = _make_transcript(str(tmp_path / "a.jsonl"))
    assert ro.pick_transcript(t) == t
    # dir: newest of two
    d = tmp_path / "proj"; d.mkdir()
    old = _make_transcript(str(d / "old.jsonl"))
    time.sleep(0.01)
    new = _make_transcript(str(d / "new.jsonl"), stale_mtime=False)
    assert ro.pick_transcript(str(d)) == new
    assert ro.pick_transcript(str(tmp_path / "nope")) is None


def test_find_skill_gc_prefers_sibling():
    """reorient must resolve its co-located skill-gc (the repo sibling here), not a
    PATH-installed copy — otherwise the tests validate the wrong skill-gc."""
    resolved = ro.find_skill_gc()
    assert resolved is not None
    assert os.path.basename(resolved) == "skill-gc"
    assert os.path.realpath(resolved) == os.path.realpath(
        os.path.join(_HERE, "..", "scripts", "skill-gc"))


def test_first_timestamp_epoch(tmp_path):
    t = _make_transcript(str(tmp_path / "a.jsonl"), first_ts="2020-01-01T00:00:00.000Z")
    assert ro.first_timestamp_epoch(t) == 1_577_836_800  # 2020-01-01 UTC


def test_first_timestamp_skips_malformed_lines(tmp_path):
    """A partial/garbage line before the first timestamped record must not abort the scan."""
    p = tmp_path / "m.jsonl"
    with open(p, "w") as f:
        f.write("{ this is not valid json\n")
        f.write(json.dumps({"type": "mode", "mode": "normal"}) + "\n")  # no timestamp
        f.write(json.dumps({"type": "user", "timestamp": "2020-01-01T00:00:00.000Z"}) + "\n")
    assert ro.first_timestamp_epoch(str(p)) == 1_577_836_800


def test_delta_brief_predates_install(tmp_path):
    t = _make_transcript(str(tmp_path / "a.jsonl"), first_ts="2020-01-01T00:00:00.000Z")
    cdir = tmp_path / "claude"; _stamp(str(cdir), install_epoch=1_700_000_000)
    b = ro.delta_brief(t, str(cdir))
    assert b["predates_install"] is True
    assert b["changed_skills"] == ["precheck", "nextwave"]


def test_delta_brief_current_session(tmp_path):
    t = _make_transcript(str(tmp_path / "a.jsonl"), first_ts="2099-01-01T00:00:00.000Z")
    cdir = tmp_path / "claude"; _stamp(str(cdir), install_epoch=1_700_000_000)
    b = ro.delta_brief(t, str(cdir))
    assert b["predates_install"] is False and b["changed_skills"] == []


def test_reorient_evicts_stopped_session(tmp_path, monkeypatch):
    home = tmp_path / "home"; _stamp(str(home / ".claude"), install_epoch=1_700_000_000)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "proj").mkdir()
    t = _make_transcript(str(tmp_path / "proj" / "s.jsonl"))
    rc = ro.main([t, "--json"])  # dry-run first
    assert rc == 0
    assert "SKILL BODY START" in open(t).read()  # dry-run did not write
    rc = ro.main([t, "--apply", "--json"])
    assert rc == 0
    assert "SKILL BODY START" not in open(t).read()  # body evicted
    assert os.path.isdir(os.path.join(os.path.dirname(t), "transcript-backups"))


def test_reorient_refuses_live_session(tmp_path):
    t = _make_transcript(str(tmp_path / "live.jsonl"), stale_mtime=False)  # fresh mtime => live
    now = time.time(); os.utime(t, (now, now))
    before = open(t).read()
    rc = ro.main([t, "--apply"])
    assert rc == 3  # skill-gc's fail-closed refusal propagates
    assert open(t).read() == before  # nothing written


def test_reorient_missing_target(tmp_path):
    assert ro.main([str(tmp_path / "nothing")]) == 2
