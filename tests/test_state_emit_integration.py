"""S1.2 / #855 — every state.py mutator emits one typed, scoped event (IT-01).

Drives each instrumented mutator in-process and asserts it appends EXACTLY one
FlightDeck event of the expected kind, correctly scoped. Also proves the
instrumentation is purely additive: a raising emitter never breaks a mutation
(the mutation still persists state.json), and no mutator changes its return /
persistence behavior.

The autouse ``_isolate_flightdeck_buffer`` fixture (conftest) points the emit
buffer at a per-test tmp file and clears the ingest env, so these run offline.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from wave_status import state


# ---------------------------------------------------------------------------
# Buffer helpers (reads the tmp buffer the autouse fixture configured)
# ---------------------------------------------------------------------------

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
    off = Path(str(p) + ".offset")
    if off.exists():
        off.unlink()


@pytest.fixture()
def inited(temp_git_repo, sample_plan) -> Path:
    """A git repo with an initialized plan; buffer cleared post-init."""
    state.init_state(sample_plan, temp_git_repo)
    _clear()
    return temp_git_repo


def _one(kind: str) -> dict:
    evs = _events()
    assert len(evs) == 1, f"expected exactly one event, got {len(evs)}: {evs}"
    assert evs[0]["kind"] == kind, f"expected kind {kind}, got {evs[0]['kind']}"
    assert evs[0]["activityId"]
    assert evs[0]["ts"]
    assert evs[0]["schemaVersion"] == 1
    return evs[0]


# ---------------------------------------------------------------------------
# One event per mutation, correctly typed + scoped
# ---------------------------------------------------------------------------

class TestOneEventPerMutation:
    def test_init_state_activity_start(self, temp_git_repo, sample_plan):
        state.init_state(sample_plan, temp_git_repo)
        ev = _one("activity_start")
        assert ev["wave"] == "wave-1"
        # #1026: init emits a BARE activity_start — the FlightDeck campaign vitals
        # (dev-name title, planTotal denominator, campaign type) are emitted by the
        # wavemachine DRIVER keyed on <plan_id>, not here (see skills/wavemachine).
        assert "activityType" not in ev
        assert "detail" not in ev

    def test_planning_phase(self, inited):
        state.planning(inited)
        ev = _one("phase")
        assert ev["wave"] == "wave-1"
        assert ev["action"] == "planning"

    def test_preflight_phase_via_set_action(self, inited):
        state.preflight(inited)
        ev = _one("phase")
        assert ev["action"] == "pre-flight"

    def test_review_phase_via_set_action(self, inited):
        state.review(inited)
        ev = _one("phase")
        assert ev["action"] == "post-wave-review"

    def test_waiting_blocked_on_human(self, inited):
        state.waiting(inited, "need a human")
        ev = _one("blocked_on_human")
        assert ev["action"] == "waiting-on-meatbag"

    def test_hold_blocked_on_human(self, inited):
        state.hold(inited, "adjudicating")
        ev = _one("blocked_on_human")
        assert ev["action"] == "hold"

    def test_waiting_ci(self, inited):
        state.waiting_ci(inited, "run 123")
        ev = _one("ci_wait")
        assert ev["action"] == "waiting-ci"

    def test_promoting_step(self, inited):
        state.promoting(inited, "wave-1")
        ev = _one("step")
        assert ev["action"] == "promoting"

    def test_launching_step(self, inited):
        state.launching(inited, "wave-1")
        ev = _one("step")
        assert ev["action"] == "launching"

    def test_awaiting_verdict_step(self, inited):
        state.awaiting_verdict(inited, "wave-1")
        ev = _one("step")
        assert ev["action"] == "awaiting-verdict"

    def test_flight_step(self, inited, sample_flights):
        state.store_flight_plan(sample_flights, inited)
        _clear()  # store_flight_plan is not instrumented; isolate the flight event
        state.flight(1, inited)
        ev = _one("step")
        assert ev["wave"] == "wave-1"
        assert ev["flight"] == 1
        assert ev["action"] == "in-flight"

    def test_flight_done_step(self, inited, sample_flights):
        state.store_flight_plan(sample_flights, inited)
        state.flight(1, inited)
        _clear()
        state.flight_done(1, inited)
        ev = _one("step")
        assert ev["flight"] == 1
        assert ev["action"] == "merging"

    def test_complete_step(self, inited):
        state.complete(inited)
        ev = _one("step")
        assert ev["wave"] == "wave-1"
        assert ev["action"] == "complete"
        assert ev["label"] == "promoted"

    def test_close_issue_step(self, inited):
        state.close_issue(13, inited)
        ev = _one("step")
        assert ev["action"] == "close-issue"

    def test_record_mr_step(self, inited):
        state.record_mr(13, "#99", inited)
        ev = _one("step")
        assert ev["wave"] == "wave-1"
        assert ev["action"] == "record-mr"
        assert ev["detail"] == "#99"

    def test_append_trajectory_step(self, inited):
        state.append_trajectory(inited, "wave-1", {"verdict": "PASS"})
        ev = _one("step")
        assert ev["wave"] == "wave-1"
        assert ev["action"] == "trajectory"

    def test_set_current_wave_phase(self, inited):
        state.set_current_wave("wave-2", inited)
        ev = _one("phase")
        assert ev["wave"] == "wave-2"
        assert ev["action"] == "set-current-wave"

    def test_wavemachine_start_step(self, inited):
        state.wavemachine_start(inited, launcher="agent-x")
        ev = _one("step")
        assert ev["action"] == "wavemachine-start"

    def test_wavemachine_stop_activity_end(self, inited):
        state.wavemachine_start(inited)
        _clear()
        state.wavemachine_stop(inited)
        ev = _one("activity_end")
        assert ev["action"] == "wavemachine-stop"


# ---------------------------------------------------------------------------
# Additive safety: instrumentation never alters the mutation
# ---------------------------------------------------------------------------

class TestAdditiveSafety:
    def test_activity_id_stable_across_campaign(self, inited):
        state.planning(inited)
        state.close_issue(13, inited)
        state.complete(inited)
        ids = {e["activityId"] for e in _events()}
        assert len(ids) == 1  # one campaign → one stable activityId

    def test_raising_emitter_does_not_break_mutation(self, inited, monkeypatch):
        # Force the underlying emit() to raise; emit_state_event must swallow it
        # (R-03) and the mutation must still persist state.json unchanged.
        import wave_status.events.emit as emit_mod

        def _boom(*a, **k):
            raise RuntimeError("ingest exploded")

        monkeypatch.setattr(emit_mod, "emit", _boom)

        result = state.planning(inited)  # must not raise
        assert result["current_action"]["action"] == "planning"
        # state.json persisted the planning transition despite the emit blowing up
        d = state.status_dir(inited)
        persisted = state.load_json(d / "state.json")
        assert persisted["waves"]["wave-1"]["status"] == "in_progress"

    def test_no_extra_stdout_from_mutation(self, inited, capsys):
        state.planning(inited)
        out = capsys.readouterr()
        assert out.out == "" and out.err == ""
