"""S1.3 / #861 — coded-concern emit at coded escape hatches (IT-02, R-05).

The ONE coded escape hatch reachable from state.py is the ENG-1 gate-skip-but-hold
landing: ``hold_wave`` marks a wave ``held`` (non-promoted terminal) when the
promotion gate is SKIPPED/HELD or a PASS did not land. It must emit a
``concern{source:'coded', concernKind:'gate-override'}``.

The remaining coded hatches live OUTSIDE state.py and co-deliver with Story 1.5
(deferred here — sdlc/nextwave repo work):
  - ENG-2 forced chore-default  → skills/nextwave/resume.js deriveBranchType
    (a bundled Workflow helper; TC-2 forbids in-script fs, so it must emit from
    an agent() prompt / post-node hook).
  - ENG-6 self-approved MR       → skills/precheck + sdlc pr_merge
    ([AUTO-APPROVED: kahuna sandbox] sentinel path).
  - ENG-8 kahuna pre-sync        → sdlc/nextwave (no state.py landing).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from wave_status import state


def _buf() -> Path:
    return Path(os.environ["FLIGHTDECK_EVENTS_PATH"])


def _events() -> list[dict]:
    p = _buf()
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _clear() -> None:
    p = _buf()
    if p.exists():
        p.write_text("", encoding="utf-8")


@pytest.fixture()
def inited(temp_git_repo, sample_plan) -> Path:
    state.init_state(sample_plan, temp_git_repo)
    _clear()
    return temp_git_repo


class TestEng1HoldWaveConcern:
    def test_hold_wave_emits_coded_gate_override_concern(self, inited):
        state.hold_wave("wave-1", inited, detail="gate SKIPPED: loop did not converge")
        evs = _events()
        assert len(evs) == 1
        ev = evs[0]
        assert ev["kind"] == "concern"
        assert ev["concernKind"] == "gate-override"
        assert ev["source"] == "coded"
        assert ev["wave"] == "wave-1"
        assert "SKIPPED" in ev["detail"]

    def test_hold_wave_concern_without_detail(self, inited):
        state.hold_wave("wave-1", inited)
        ev = _events()[0]
        assert ev["kind"] == "concern"
        assert ev["concernKind"] == "gate-override"
        assert ev["source"] == "coded"
        # detail absent (None dropped), never null
        assert "detail" not in ev

    def test_hold_wave_still_holds_and_does_not_advance(self, inited):
        # Additive: the concern emit must not change the hold semantics — wave
        # goes 'held', current_wave does NOT advance (ENG-1 contract).
        before = state.load_json(state.status_dir(inited) / "state.json")
        assert before["current_wave"] == "wave-1"
        state.hold_wave("wave-1", inited, detail="reconcile-blocked")
        after = state.load_json(state.status_dir(inited) / "state.json")
        assert after["waves"]["wave-1"]["status"] == "held"
        assert after["current_wave"] == "wave-1"  # unchanged

    def test_raising_emitter_does_not_break_hold(self, inited, monkeypatch):
        import wave_status.events.emit as emit_mod

        monkeypatch.setattr(emit_mod, "emit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        # hold_wave must still succeed and persist despite a raising emitter.
        result = state.hold_wave("wave-1", inited, detail="x")
        assert result["waves"]["wave-1"]["status"] == "held"
