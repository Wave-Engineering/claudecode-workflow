"""Oracle for the auto-soak accrual bridge (#1008) — surgeon --live → soak_ledger.accrue.

Prior waves proved the soak WRITER (``soak_ledger.py``, #975) and the health PROBE
(``surgeon.py``, #970) in isolation, but nothing in a live path connected them, so a
real dogfood cutover accrued **zero** soak and the promotion gate's ``SOAK_HOURS``
never filled (R-07/R-08 unit-proven, not live-wired). ``scripts/ci/soak_accrual_bridge.py``
is that connective tissue. These tests prove the mapping + accrual **hermetically** —
the surgeon ``--live`` and ``aoe list --json`` gather steps are injected as fixture
output, so NO live aoe/docker is required.

What is intentionally NOT proved here (rides an operator field-run, MV-04/MV-06,
Dev Spec §6.3 E2E-02): the live end-to-end cycle — real ``:edge`` aoe sessions, the
surgeon resolving their real transcripts, and the gate's soak filling over wall-clock.
The bridge's contract with the two live seams is exercised via injection; the seams
themselves (aoe's sandbox mount/label layout) are the operator-cutover's proof.

Coverage:

* mapping — a running dogfood session becomes the correct observation shape; a
  non-running session is skipped; ``active_since`` is the aoe ``created_at`` (transcript
  fallback) **clamped to a bounded per-pass look-back**, so a point-in-time verdict
  credits at most LOOK_BACK — never a session's full age nor a broken→recovered gap;
* accrual — the full ``run`` accrues dogfood, EXCLUDES dev-mode (R-22) and broken
  (§4.3), bounds the first pass to LOOK_BACK, does not back-credit a broken flap, and is
  watermark-idempotent across passes;
* plumbing — the gather seams parse JSON and fail loud on a broken gather; the CLI
  wrapper is executable; the surgeon is run ``--live`` and NOT ``--fail-on-quarantine``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CI_DIR = REPO_ROOT / "scripts" / "ci"
BRIDGE_WRAPPER = CI_DIR / "soak-accrual-bridge.sh"

# Path-style import (no PYTHONPATH dependency), mirroring test_promotion_cycle.py.
sys.path.insert(0, str(CI_DIR))
import soak_accrual_bridge as bridge  # noqa: E402

NOW = datetime(2026, 7, 23, 12, 0, 0, tzinfo=timezone.utc)


def _assessment(session, profile, status, *, broken=False, last_activity=None):
    """One ``surgeon.py --live`` assessment (the ``Assessment.as_dict()`` shape)."""
    return {
        "container_id": session,
        "title": session,
        "profile": profile,
        "quarantine_eligible": profile != "dev-mode",
        "should_quarantine": broken and profile != "dev-mode",
        "health": {
            "status": status,
            "state": "healthy" if not broken else "stalled",
            "broken": broken,
            "stalled": broken,
            "looping": False,
            "idle_seconds": None,
            "last_activity": (last_activity or NOW).isoformat(),
            "reasons": [],
        },
        "reasons": [],
    }


def _session(session, *, hours_ago=30, path=None, created_at="__default__"):
    """One ``aoe list --json`` session record. ``created_at`` defaults to
    ``NOW - hours_ago``; pass ``None`` to simulate a missing/absent stamp."""
    if created_at == "__default__":
        created_at = (NOW - timedelta(hours=hours_ago)).isoformat()
    return {
        "id": session,
        "title": session,
        "path": path or f"/work/{session}",
        "group": "oaw",
        "tool": "claude",
        "profile": "default",  # aoe workspace profile — NOT the oaw.profile label
        "created_at": created_at,
        "workspace_repos": [],
    }


def _runner(payload):
    """A gather runner that returns ``payload`` (a JSON-serialisable list) regardless
    of the command — the injection seam that removes the live aoe/docker dependency."""
    return lambda cmd: json.dumps(payload)


# --- the pure mapping core (build_observations) -------------------------------


def test_running_dogfood_maps_to_correct_observation():
    """A running dogfood session becomes exactly the soak_ledger observation shape:
    session, profile, active_since=created_at, active_until=now, broken=False. A wide
    look-back keeps created_at (20h ago) inside the window, so it flows through as-is."""
    start = (NOW - timedelta(hours=20)).isoformat()
    obs, skipped = bridge.build_observations(
        [_assessment("a", "dogfood", "running")],
        [_session("a", created_at=start)],
        now=NOW,
        lookback_hours=100,
    )
    assert skipped == []
    assert obs == [
        {
            "session": "a",
            "profile": "dogfood",
            "active_since": start,
            "active_until": NOW.isoformat(),
            "broken": False,
        }
    ]


def test_observation_shape_is_exactly_the_ledger_contract():
    """The emitted observation carries exactly the keys soak_ledger.accrue reads —
    no more, no less (guards against a silently-dropped or spurious field)."""
    (obs,), _ = bridge.build_observations(
        [_assessment("a", "dogfood", "running")], [_session("a")], now=NOW
    )
    assert set(obs) == {"session", "profile", "active_since", "active_until", "broken"}


def test_non_running_session_is_skipped_with_reason():
    """Only a running session has an open span ending at now; idle/stopped/waiting are
    skipped (never silently — a reason is recorded) so idle time is never soak."""
    for status in ("idle", "stopped", "waiting", "unknown"):
        obs, skipped = bridge.build_observations(
            [_assessment("a", "dogfood", status)], [_session("a")], now=NOW
        )
        assert obs == [], f"{status} must not produce an observation"
        assert len(skipped) == 1 and skipped[0][0] == "a"
        assert "not running" in skipped[0][1]


def test_dev_mode_and_broken_are_passed_through_to_accrue():
    """The bridge does NOT re-implement the R-22 / §4.3 exclusions: a running dev-mode
    and a running broken session are both mapped to observations (profile/broken passed
    straight through) — soak_ledger.accrue is the single enforcement point that drops
    them WITH a reason. Pre-filtering here would make them a silent drop."""
    obs, skipped = bridge.build_observations(
        [
            _assessment("dev", "dev-mode", "running"),
            _assessment("brk", "dogfood", "running", broken=True),
        ],
        [_session("dev"), _session("brk")],
        now=NOW,
    )
    assert skipped == []
    by_session = {o["session"]: o for o in obs}
    assert by_session["dev"]["profile"] == "dev-mode"
    assert by_session["brk"]["broken"] is True


# --- active_since: created_at primary, transcript-earliest fallback -----------


def test_active_since_is_the_aoe_created_at():
    """active_since is the session's aoe created_at (the session-start time) when it
    lies within the look-back window."""
    created = (NOW - timedelta(hours=7)).isoformat()
    (obs,), _ = bridge.build_observations(
        [_assessment("a", "dogfood", "running")],
        [_session("a", created_at=created)],
        now=NOW,
        lookback_hours=100,
    )
    assert obs["active_since"] == created


def test_active_since_falls_back_to_transcript_earliest(tmp_path):
    """When created_at is absent, active_since falls back to the transcript's earliest
    entry timestamp (≈ session start), resolved with the surgeon's own transcript
    resolver under --transcripts-root."""
    # surgeon's _newest_transcript_for matches a .jsonl whose path contains the slug
    # of the session path ("/work/agent-x" -> "work-agent-x").
    root = tmp_path / "projects"
    root.mkdir()
    earliest = (NOW - timedelta(hours=12)).replace(microsecond=0)
    later = (NOW - timedelta(hours=1)).replace(microsecond=0)
    transcript = root / "work-agent-x.jsonl"
    transcript.write_text(
        json.dumps({"timestamp": later.isoformat()})
        + "\n"
        + json.dumps({"timestamp": earliest.isoformat()})
        + "\n"
    )

    (obs,), _ = bridge.build_observations(
        [_assessment("z", "dogfood", "running")],
        [_session("z", path="/work/agent-x", created_at=None)],
        now=NOW,
        transcripts_root=root,
        lookback_hours=100,
    )
    assert obs["active_since"] == earliest.isoformat()


def test_missing_start_signal_credits_at_most_lookback(tmp_path):
    """No created_at AND no resolvable transcript ⇒ active_since falls to the look-back
    floor (now − lookback), so a running-and-clean-now session still credits, but only
    the bounded look-back — never an unbounded span nor a silent zero."""
    (obs,), _ = bridge.build_observations(
        [_assessment("z", "dogfood", "running")],
        [_session("z", created_at=None)],
        now=NOW,
        transcripts_root=tmp_path / "empty",
        lookback_hours=3,
    )
    assert obs["active_since"] == (NOW - timedelta(hours=3)).isoformat()
    results = bridge.sl.accrue(observations=[obs], ledger_path=tmp_path / "l.jsonl", now=NOW)
    assert results[0].accrued and results[0].record["hours"] == pytest.approx(3.0)


# --- the full run: gather -> map -> accrue ------------------------------------


def _fixture_ring():
    """A live-ring fixture: a clean dogfood session, a dev-mode session, a broken
    dogfood session, and an idle dogfood session."""
    assessments = [
        _assessment("clean", "dogfood", "running"),
        _assessment("dev", "dev-mode", "running"),
        _assessment("broken", "dogfood", "running", broken=True),
        _assessment("idle", "dogfood", "idle"),
    ]
    sessions = [_session(a["container_id"]) for a in assessments]
    return assessments, sessions


def test_run_accrues_dogfood_excludes_dev_mode_and_broken(tmp_path):
    """End-to-end: only the clean dogfood session accrues; dev-mode (R-22) and broken
    (§4.3) are excluded WITH reasons, and the idle session is skipped by the bridge."""
    assessments, sessions = _fixture_ring()
    ledger = tmp_path / "ledger.jsonl"

    obs, skipped, results = bridge.run(
        ledger_path=ledger,
        now=NOW,
        lookback_hours=2.0,
        surgeon_runner=_runner(assessments),
        aoe_runner=_runner(sessions),
    )

    # the idle session never became an observation (bridge running-gate).
    assert [s for s, _ in skipped] == ["idle"]
    accrued = {r.session for r in results if r.accrued}
    assert accrued == {"clean"}, "only the clean dogfood session accrues"

    reasons = {r.session: r.reason for r in results}
    assert "dev-mode is non-candidate" in reasons["dev"]
    assert "broken/quarantined" in reasons["broken"]

    ledger_records = bridge.sl.read_ledger(ledger)
    assert [r["session"] for r in ledger_records] == ["clean"]
    assert ledger_records[0]["profile"] == "dogfood"
    # created_at is NOW-30h, but the pass credits only the 2h look-back it sampled —
    # NOT the session's full age (that would be an un-health-checked back-credit).
    assert ledger_records[0]["hours"] == pytest.approx(2.0)


def test_first_pass_credits_at_most_lookback_not_full_age(tmp_path):
    """A session alive 30h, observed for the first time, credits only LOOK_BACK — the
    point-in-time verdict certifies it clean *now*, not across 30h of history (R-07
    'soak is measured, never asserted')."""
    ledger = tmp_path / "ledger.jsonl"
    _, _, results = bridge.run(
        ledger_path=ledger,
        now=NOW,
        lookback_hours=2.0,
        surgeon_runner=_runner([_assessment("old", "dogfood", "running")]),
        aoe_runner=_runner([_session("old", hours_ago=30)]),
    )
    assert results[0].accrued
    assert results[0].record["hours"] == pytest.approx(2.0), "first pass bounded to LOOK_BACK"


def _flap_pass(ledger, *, now, broken, created_at, lookback):
    """One accrual pass over a single 'flapper' session at a given wall-clock ``now``."""
    return bridge.run(
        ledger_path=ledger,
        now=now,
        lookback_hours=lookback,
        surgeon_runner=_runner(
            [_assessment("flapper", "dogfood", "running", broken=broken, last_activity=now)]
        ),
        aoe_runner=_runner([_session("flapper", created_at=created_at)]),
    )


def test_broken_flap_does_not_back_credit(tmp_path):
    """A broken pass writes no record, so the watermark does not advance — but the
    look-back clamp still stops the recovery pass from crediting the broken gap. With an
    hourly cadence (LOOK_BACK=1h): clean, then broken for 3 hourly passes, then
    recovered — the recovery credits only the final look-back hour, NOT the 3h dirty gap
    (§4.3). Un-clamped, the recovery would back-credit the whole gap (total 5h)."""
    ledger = tmp_path / "ledger.jsonl"
    created = (NOW - timedelta(hours=10)).isoformat()  # old enough to never bound
    lb = 1.0

    _flap_pass(ledger, now=NOW, broken=False, created_at=created, lookback=lb)
    assert bridge.sl.aggregate_or_zero(ledger) == pytest.approx(1.0)

    for h in (1, 2, 3):
        _, _, res = _flap_pass(
            ledger, now=NOW + timedelta(hours=h), broken=True, created_at=created, lookback=lb
        )
        assert not res[0].accrued, "a broken pass accrues nothing (§4.3)"
    assert bridge.sl.aggregate_or_zero(ledger) == pytest.approx(1.0), "broken gap credits nothing"

    _, _, res = _flap_pass(
        ledger, now=NOW + timedelta(hours=4), broken=False, created_at=created, lookback=lb
    )
    assert res[0].accrued
    assert res[0].record["hours"] == pytest.approx(1.0), "recovery credits only LOOK_BACK"
    assert bridge.sl.aggregate_or_zero(ledger) == pytest.approx(2.0), (
        "the 3h broken interval must NOT be back-credited on recovery "
        "(the un-clamped bug would total 5.0h)"
    )


def test_run_is_watermark_idempotent_across_passes(tmp_path):
    """Re-running the bridge over the same live window accrues nothing new; a later
    pass accrues only the delta — soak_ledger's per-session watermark makes the bridge
    safe to run on a cron without double-counting."""
    assessment = _assessment("a", "dogfood", "running")
    session = _session("a", hours_ago=10)  # created_at = NOW-10h
    ledger = tmp_path / "ledger.jsonl"
    # A wide look-back isolates the watermark behaviour from the per-pass clamp.
    wide = 100.0

    _, _, first = bridge.run(
        ledger_path=ledger, now=NOW, lookback_hours=wide,
        surgeon_runner=_runner([assessment]), aoe_runner=_runner([session]),
    )
    assert first[0].accrued and bridge.sl.aggregate_or_zero(ledger) == 10.0

    # Same window, run again at the same now → the watermark suppresses a duplicate.
    _, _, again = bridge.run(
        ledger_path=ledger, now=NOW, lookback_hours=wide,
        surgeon_runner=_runner([assessment]), aoe_runner=_runner([session]),
    )
    assert not again[0].accrued
    assert bridge.sl.aggregate_or_zero(ledger) == 10.0, "re-running must not double-count"

    # 5h later → only the new 5h beyond the watermark accrues.
    later_now = NOW + timedelta(hours=5)
    _, _, grew = bridge.run(
        ledger_path=ledger,
        now=later_now,
        lookback_hours=wide,
        surgeon_runner=_runner([assessment]),
        aoe_runner=_runner([session]),
    )
    assert grew[0].accrued and grew[0].record["hours"] == pytest.approx(5.0)
    assert bridge.sl.aggregate_or_zero(ledger) == pytest.approx(15.0)


def test_dry_run_writes_nothing(tmp_path):
    """--dry-run builds the observations but accrues nothing — a safe operator preview."""
    assessments, sessions = _fixture_ring()
    ledger = tmp_path / "ledger.jsonl"

    obs, skipped, results = bridge.run(
        ledger_path=ledger,
        now=NOW,
        dry_run=True,
        surgeon_runner=_runner(assessments),
        aoe_runner=_runner(sessions),
    )
    assert results == []
    assert not ledger.exists(), "dry-run must not create the ledger"
    assert {o["session"] for o in obs} == {"clean", "dev", "broken"}


# --- gather plumbing ----------------------------------------------------------


def test_gather_parses_json_and_tolerates_empty():
    """The gather seams parse a JSON array and treat empty output as an empty ring."""
    assert bridge.gather_aoe_sessions(runner=lambda cmd: "") == []
    assert bridge.gather_surgeon_assessments("~", runner=lambda cmd: "[]") == []
    got = bridge.gather_aoe_sessions(runner=_runner([_session("a")]))
    assert got[0]["id"] == "a"


def test_gather_fails_loud_on_broken_command():
    """A gather subprocess that exits non-zero raises BridgeError — a broken gather is
    visible, never a silent empty ring that masquerades as 'nothing to accrue'."""
    import subprocess

    def broken_runner(cmd, **kw):
        raise subprocess.SubprocessError("boom")

    with pytest.raises(bridge.BridgeError):
        bridge._run(["false"])  # real non-zero exit
    with pytest.raises(bridge.BridgeError):
        bridge._run(["definitely-not-a-real-command-xyz"])


def test_surgeon_is_run_live_and_not_fail_on_quarantine():
    """The bridge drives the surgeon with --live and captures its JSON — it must NOT
    pass --fail-on-quarantine (that would turn a broken container into a non-zero exit
    the gather treats as a failure)."""
    captured = {}

    def spy(cmd):
        captured["cmd"] = cmd
        return "[]"

    bridge.gather_surgeon_assessments("~/.claude/projects", runner=spy)
    assert "--live" in captured["cmd"]
    assert "--fail-on-quarantine" not in captured["cmd"]
    assert str(bridge.SURGEON_PY) in captured["cmd"]


# --- CLI / wrapper ------------------------------------------------------------


def test_lookback_env_default_is_robust(monkeypatch):
    """OAW_SOAK_LOOKBACK_HOURS sets the look-back; a malformed/non-positive/absent value
    falls back to the default — an operator misconfig never crashes or zeroes soak."""
    monkeypatch.setenv("OAW_SOAK_LOOKBACK_HOURS", "6")
    assert bridge._default_lookback() == 6.0
    for bad in ("garbage", "-5", "0"):
        monkeypatch.setenv("OAW_SOAK_LOOKBACK_HOURS", bad)
        assert bridge._default_lookback() == bridge.DEFAULT_LOOKBACK_HOURS
    monkeypatch.delenv("OAW_SOAK_LOOKBACK_HOURS", raising=False)
    assert bridge._default_lookback() == bridge.DEFAULT_LOOKBACK_HOURS


def test_cli_main_accrues_via_injected_gather(tmp_path, monkeypatch):
    """main() wires the CLI end-to-end: monkeypatch the gather seams (so no live aoe),
    run against a tmp ledger, and confirm the clean dogfood soak lands."""
    assessments, sessions = _fixture_ring()
    monkeypatch.setattr(bridge, "gather_surgeon_assessments", lambda root, **kw: assessments)
    monkeypatch.setattr(bridge, "gather_aoe_sessions", lambda **kw: sessions)
    ledger = tmp_path / "ledger.jsonl"

    rc = bridge.main(["--ledger", str(ledger), "--transcripts-root", str(tmp_path)])
    assert rc == 0
    records = bridge.sl.read_ledger(ledger)
    assert [r["session"] for r in records] == ["clean"]


def test_bridge_wrapper_is_executable():
    """The wrapper is invoked directly (scripts/ci/soak-accrual-bridge.sh), so +x
    (repo convention, cf. #948/#953)."""
    assert BRIDGE_WRAPPER.exists(), f"wrapper missing: {BRIDGE_WRAPPER}"
    assert os.access(BRIDGE_WRAPPER, os.X_OK), "soak-accrual-bridge.sh must be executable"
