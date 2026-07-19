"""Tests for scripts/skill-gc — byte-preserving skill-body eviction (epic #906, D4 #907).

Loads the no-extension script via SourceFileLoader (repo convention, cf.
tests/test_discord_status.py), builds synthetic transcripts containing a real
Skill tool_use -> tool_result -> isMeta body chain, and asserts the eviction is
lossless, byte-preserving, structurally intact, and fail-closed on live sessions.
"""

from __future__ import annotations

import gzip
import importlib.machinery
import importlib.util
import json
import os
import time

import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "skill-gc")
_loader = importlib.machinery.SourceFileLoader("skill_gc", _SCRIPT)
_spec = importlib.util.spec_from_file_location("skill_gc", _SCRIPT, loader=_loader)
sg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sg)


# --------------------------------------------------------------------------- #
# fixture builders
# --------------------------------------------------------------------------- #
def _body(skill: str, extra: str = "") -> str:
    return f"SKILL BODY START [{skill}]{extra} — " + ("procedure line. " * 200) + " — SKILL BODY END"


def _invocation(skill: str, suffix: str, parent: str) -> list[dict]:
    """A Skill tool_use -> tool_result -> isMeta body triple, uniquely id'd by suffix."""
    return [
        {"type": "assistant", "uuid": f"A{suffix}", "parentUuid": parent,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": f"toolu_{suffix}", "name": "Skill", "input": {"skill": skill}}]}},
        {"type": "user", "uuid": f"R{suffix}", "parentUuid": f"A{suffix}",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": f"toolu_{suffix}", "content": f"Launching skill: {skill}"}]}},
        {"type": "user", "uuid": f"B{suffix}", "parentUuid": f"R{suffix}", "isMeta": True,
         "message": {"role": "user", "content": [{"type": "text", "text": _body(skill)}]}},
    ]


def _events() -> list[dict]:
    return [
        {"type": "user", "uuid": "U0", "parentUuid": None,
         "message": {"role": "user", "content": [{"type": "text", "text": "please run precheck"}]}},
        *_invocation("precheck", "A", "U0"),
        {"type": "assistant", "uuid": "W4", "parentUuid": "BA",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Running precheck step 1."}]}},
        # a NON-skill tool pair — must remain paired and untouched
        {"type": "assistant", "uuid": "W5", "parentUuid": "W4",
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "toolu_B", "name": "Bash", "input": {"command": "ls"}}]}},
        {"type": "user", "uuid": "W6", "parentUuid": "W5",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "toolu_B", "content": "file.txt"}]}},
    ]


def _write(events, path, ensure_ascii=True, blank_after=None):
    lines = []
    for idx, e in enumerate(events):
        lines.append(json.dumps(e, separators=(",", ":"), ensure_ascii=ensure_ascii) + "\n")
        if blank_after is not None and idx == blank_after:
            lines.append("\n")  # a blank line to desync event-index vs raw-index
    path.write_text("".join(lines), encoding="utf-8")
    old = time.time() - 3600
    os.utime(path, (old, old))  # look NOT live so --apply is allowed
    return str(path)


@pytest.fixture
def transcript(tmp_path):
    return _write(_events(), tmp_path / "sess.jsonl")


# --------------------------------------------------------------------------- #
def test_identify_chain(transcript):
    targets = sg.find_skill_body_indices(sg.parse_aligned(
        open(transcript, encoding="utf-8").read().splitlines(keepends=True)))
    assert targets == {3: "precheck"}  # raw index of the body line, nothing else


def test_byte_preserving_and_shrinks(transcript):
    orig = open(transcript, encoding="utf-8").read().splitlines(keepends=True)
    out, targets, reclaimed = sg.evict(transcript)
    assert set(targets) == {3}
    assert reclaimed > 0
    for i in range(len(orig)):
        if i not in targets:
            assert out[i] == orig[i], f"non-target line {i} changed"
    assert len("".join(out)) < len("".join(orig))
    assert "SKILL BODY START" not in "".join(out)
    assert "evicted for context GC" in out[3]


def test_ensure_ascii_false_unicode_body(tmp_path):
    """Real CC transcripts store raw UTF-8 (ensure_ascii=False). The swap's
    ensure_ascii=False branch must find + evict a unicode body."""
    evs = _events()
    evs[3]["message"]["content"][0]["text"] = "БODY — em—dash 世界 " + ("x " * 300)
    p = _write(evs, tmp_path / "u.jsonl", ensure_ascii=False)
    orig = open(p, encoding="utf-8").read().splitlines(keepends=True)
    out, targets, reclaimed = sg.evict(p)
    assert set(targets) == {3} and reclaimed > 0
    assert "em—dash 世界" not in "".join(out)
    assert sg.verify(p, out, targets) == []
    for i in range(len(orig)):
        if i not in targets:
            assert out[i] == orig[i]


def test_blank_line_before_target_stays_aligned(tmp_path):
    """A blank line before the body desyncs event-index vs raw-index unless
    parsing is raw-aligned. Body must still be found at its RAW index (finding #1)."""
    p = _write(_events(), tmp_path / "blank.jsonl", blank_after=1)  # blank after line 1
    out, targets, reclaimed = sg.evict(p)
    assert list(targets.values()) == ["precheck"]
    (idx,) = targets
    assert out[idx].strip() != "" and "evicted for context GC" in out[idx]
    assert reclaimed > 0
    assert sg.verify(p, out, targets) == []


def test_duplicate_skill_invocations(tmp_path):
    evs = [
        {"type": "user", "uuid": "U0", "parentUuid": None,
         "message": {"role": "user", "content": [{"type": "text", "text": "go"}]}},
        *_invocation("precheck", "A", "U0"),
        *_invocation("precheck", "C", "BA"),  # same skill again
    ]
    p = _write(evs, tmp_path / "dup.jsonl")
    out, targets, _ = sg.evict(p)
    assert sorted(targets.values()) == ["precheck", "precheck"]  # both bodies evicted
    assert "SKILL BODY START" not in "".join(out)
    assert sg.verify(p, out, targets) == []


def test_structural_integrity(transcript):
    out, targets, _ = sg.evict(transcript)
    assert sg.verify(transcript, out, targets) == []
    raw = open(transcript, encoding="utf-8").read().splitlines(keepends=True)
    assert sg._pairs(sg.parse_aligned(raw)) == sg._pairs(sg.parse_aligned(out))


def test_verify_catches_drift(transcript):
    """Mutation-test: a non-target line drift MUST be flagged."""
    out, targets, _ = sg.evict(transcript)
    assert sg.verify(transcript, out, targets) == []
    tampered = list(out)
    tampered[0] = tampered[0].rstrip("\n") + " \n"
    assert any("non-target" in f for f in sg.verify(transcript, tampered, targets))


def test_verify_catches_malformed_output(transcript):
    """Mutation-test: a target line corrupted to invalid JSON MUST be flagged."""
    out, targets, _ = sg.evict(transcript)
    tampered = list(out)
    (idx,) = targets
    tampered[idx] = "{not json\n"
    fails = sg.verify(transcript, tampered, targets)
    assert any("malformed JSON" in f for f in fails), fails


def test_none_uuid_does_not_false_evict(tmp_path):
    """A tool_result lacking a uuid must not make a root isMeta message (parentUuid None)
    a false target."""
    evs = [
        {"type": "user", "uuid": None, "parentUuid": None, "isMeta": True,
         "message": {"role": "user", "content": [{"type": "text", "text": "some meta " + "z" * 400}]}},
        {"type": "assistant", "uuid": "A1", "parentUuid": None,
         "message": {"role": "assistant", "content": [
             {"type": "tool_use", "id": "toolu_A", "name": "Skill", "input": {"skill": "engage"}}]}},
        # tool_result WITHOUT a uuid
        {"type": "user", "parentUuid": "A1",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "toolu_A", "content": "Launching skill: engage"}]}},
    ]
    p = _write(evs, tmp_path / "none.jsonl")
    _, targets, _ = sg.evict(p)
    assert targets == {}  # nothing evicted; the root isMeta message is NOT a false target


def test_only_skills_subset(transcript):
    _, targets, _ = sg.evict(transcript, only_skills={"nonexistent"})
    assert targets == {}


def test_backup_roundtrips(transcript, tmp_path):
    data = open(transcript, "rb").read()
    bak = sg.backup(transcript, str(tmp_path / "bk"))
    assert bak.endswith(".jsonl.gz")
    assert gzip.open(bak, "rb").read() == data


def test_apply_writes_and_backs_up(transcript, tmp_path):
    bdir = str(tmp_path / "bk")
    assert sg.main([transcript, "--apply", "--backup-dir", bdir]) == 0
    assert "SKILL BODY START" not in open(transcript, encoding="utf-8").read()
    assert any(f.endswith(".jsonl.gz") for f in os.listdir(bdir))


def test_dry_run_does_not_write(transcript):
    before = open(transcript, "rb").read()
    assert sg.main([transcript]) == 0
    assert open(transcript, "rb").read() == before


def test_refuses_live_session_by_mtime(transcript):
    now = time.time()
    os.utime(transcript, (now, now))  # fresh mtime => live
    before = open(transcript, "rb").read()
    assert sg.main([transcript, "--apply"]) == 3
    assert open(transcript, "rb").read() == before
    assert sg.main([transcript, "--apply", "--force"]) == 0  # --force overrides


# NOTE: `test_detects_open_fd_as_live` lived here and passed for every release —
# by opening the fd itself. Claude Code never holds a transcript fd open (0 of 277
# held across 10,613 fds on the live fleet), so it asserted a branch production
# never reached while the real detector was blind. Liveness now lives in
# tests/test_liveness.py, driven by /proc trees built from observed cmdlines. (#919)
