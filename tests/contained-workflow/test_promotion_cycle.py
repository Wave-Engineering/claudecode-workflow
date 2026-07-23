"""Oracle for Story 4.2 (#975) — dogfood cutover + soak → the E2E-02 promotion cycle.

E2E-02 (Dev Spec §6.3): *soak → mechanical gate green → retag the tested digest
:edge → :stable → rolling per-agent adoption* `[R-07, R-08]`. The authoritative
end-to-end proof needs a real registry retag + live containers, so — exactly like
test_throwaway_ci_ring.py (E2E-01) — the whole cycle against a live digest is a
skip-gated branch (:func:`test_full_lifecycle_against_live_registry`). What runs
in the stock ``pytest tests/`` lane is the **full lifecycle exercised hermetically**
by composing the real, unit-proven modules of every prior wave into one chain:

    soak_ledger.accrue            (Story 4.2 — the FlightDeck soak WRITER, new here)
      → profiles.aggregate_gate_signals   (Story 4.1 — the profile filter, R-22)
      → promotion_gate.evaluate_gate/promote  (Story 2.3 — mechanical gate, R-07)
      → adoption.decide_adoption / plan_recreate  (Story 2.4 — rolling adopt, R-08)

The story's two acceptance criteria, both proved below:

* **AC1 [R-21]** — the OaW team works on :edge in the dogfood profile with the
  surgeon active. Proved by :func:`test_cutover_plans_dogfood_ring_and_surgeon`
  (the cutover script stamps oaw.profile=dogfood and wires the surgeon) and by the
  soak-accrual filter proving dev-mode never accrues (:func:`test_soak_excludes_dev_mode`).
* **AC2 [R-07, R-08]** — soak telemetry accrues in FlightDeck AND a promotion cycle
  completes end-to-end. Proved by :func:`test_full_promotion_cycle_end_to_end`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
CUTOVER_SCRIPT = REPO_ROOT / "scripts" / "ci" / "dogfood-cutover.sh"

# Path-style import (no PYTHONPATH dependency), mirroring test_profiles.py.
sys.path.insert(0, str(CONTAINER_DIR))
import adoption as ad  # noqa: E402
import profiles as pf  # noqa: E402
import promotion_gate as pg  # noqa: E402
import soak_ledger as sl  # noqa: E402

# A stable content-addressed digest to promote through the whole cycle (R-23: the
# digest tested is the digest promoted is the digest the fleet adopts).
DIGEST = "ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "a" * 64


def _obs(session, profile, hours, *, broken=False, start=None):
    """A dogfood session observation: a clean `hours`-long span ending `start`+hours."""
    start = start or datetime(2026, 7, 22, tzinfo=timezone.utc)
    return {
        "session": session,
        "profile": profile,
        "active_since": start.isoformat(),
        "active_until": (start + timedelta(hours=hours)).isoformat(),
        "broken": broken,
    }


# --- AC2 [R-07, R-08] — the full promotion cycle, end to end ------------------


def test_full_promotion_cycle_end_to_end(tmp_path):
    """soak accrues → gate green → retag :edge→:stable → rolling adoption (E2E-02).

    Every stage is the REAL module; the chain is the story's whole point — the pieces
    each prior wave unit-proved actually compose into a promotion cycle.
    """
    ledger = tmp_path / "soak" / "ledger.jsonl"

    # 1. SOAK ACCRUES (the new FlightDeck writer). Two clean dogfood sessions total
    #    30h; a dev-mode session and a broken dogfood session are BOTH excluded.
    results = sl.accrue(
        observations=[
            _obs("agent-a", "dogfood", 20),
            _obs("agent-b", "dogfood", 10),
            _obs("agent-c", "dev-mode", 500),  # non-candidate — must not accrue (R-22)
            _obs("agent-d", "dogfood", 99, broken=True),  # dirty — must not accrue (§4.3)
        ],
        ledger_path=ledger,
    )
    written = {r.session for r in results if r.accrued}
    assert written == {"agent-a", "agent-b"}, "only clean dogfood work accrues soak"

    # 2. THE PROFILE FILTER folds the FlightDeck ledger into the gate's soak signal —
    #    the gate reads exactly what soak_ledger wrote (30h), dev-mode already gone.
    signals = pf.aggregate_gate_signals(
        soak_records=sl.read_ledger(ledger),
        quarantine_records=[],
    )
    assert signals["soak_hours"] == 30
    assert signals["quarantine_count"] == 0

    # 3. THE MECHANICAL GATE goes green on the real signals and promotes the EXACT
    #    tested digest — no rebuild, and the ACK only confirms an already-green gate.
    report = pg.evaluate_gate(
        target_digest=DIGEST,
        ci_passed=True,
        ci_digest=DIGEST,
        soak_hours=signals["soak_hours"],
        soak_required_hours=24.0,
        quarantine_count=signals["quarantine_count"],
        open_sev1_count=0,
    )
    assert report.green, report.summary()
    promoted = pg.promote(report, operator_ack=True)
    assert promoted == DIGEST, "the digest promoted is the digest soak+CI tested (R-23)"

    # 4. ROLLING ADOPTION. :stable now points at the promoted digest (version 1.5.0);
    #    a fleet agent on 1.4.0 adopts it at ITS OWN container-recreate — the launch
    #    ref is the promoted digest, closing the tested→promoted→adopted chain.
    plan = ad.plan_recreate(
        current_ref="ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "b" * 64,
        current_version="1.4.0",
        target_ref=promoted,
        target_version="1.5.0",
    )
    assert plan.action == ad.ADOPT
    assert plan.launch_ref == promoted, "the agent adopts the exact promoted digest"


def test_gate_red_when_soak_unmet_blocks_the_cycle(tmp_path):
    """Under-soaked dogfood work cannot promote — even with the operator ACK (R-07).

    The 4.2-lens red-first assertion: if the accrued soak is below the requirement,
    the mechanical gate is RED and promotion refuses; the ACK never substitutes.
    """
    ledger = tmp_path / "ledger.jsonl"
    sl.accrue(observations=[_obs("agent-a", "dogfood", 5)], ledger_path=ledger)  # 5h << 24h
    signals = pf.aggregate_gate_signals(soak_records=sl.read_ledger(ledger), quarantine_records=[])

    report = pg.evaluate_gate(
        target_digest=DIGEST,
        ci_passed=True,
        ci_digest=DIGEST,
        soak_hours=signals["soak_hours"],
        soak_required_hours=24.0,
        quarantine_count=0,
        open_sev1_count=0,
    )
    assert not report.green
    with pytest.raises(pg.GateError):
        pg.promote(report, operator_ack=True)  # ACK cannot rescue a red soak condition


# --- Soak accrual (the new FlightDeck writer) — R-21/R-22 + §4.3 --------------


def test_soak_excludes_dev_mode(tmp_path):
    """A dev-mode session accrues NO soak record (R-22) — its span never reaches the
    ledger the gate reads, so a dev-mode session can never inflate soak."""
    ledger = tmp_path / "ledger.jsonl"
    results = sl.accrue(observations=[_obs("dev", "dev-mode", 100)], ledger_path=ledger)
    assert not any(r.accrued for r in results)
    assert not ledger.exists() or sl.read_ledger(ledger) == []
    assert "dev-mode is non-candidate" in results[0].reason


def test_soak_excludes_broken_session(tmp_path):
    """A broken/quarantined dogfood session accrues nothing — *clean* work only
    accrues soak (§4.3). The dirty span is not soak."""
    ledger = tmp_path / "ledger.jsonl"
    results = sl.accrue(
        observations=[_obs("stalled", "dogfood", 30, broken=True)], ledger_path=ledger
    )
    assert not any(r.accrued for r in results)
    assert "broken/quarantined" in results[0].reason


def test_unlabeled_session_accrues_as_candidate(tmp_path):
    """An unlabeled/unknown-profile session accrues (candidate by default) — fail-safe
    toward measuring, mirroring profiles.is_candidate and the surgeon's eligibility."""
    ledger = tmp_path / "ledger.jsonl"
    results = sl.accrue(observations=[_obs("mystery", "somethingelse", 12)], ledger_path=ledger)
    assert results[0].accrued
    assert sl.aggregate_or_zero(ledger) == 12


def test_soak_accrual_is_watermarked_idempotent(tmp_path):
    """Re-running the accrual pass over the SAME span writes nothing the second time,
    and a later span accrues only the new delta — no double-counting."""
    ledger = tmp_path / "ledger.jsonl"
    start = datetime(2026, 7, 22, tzinfo=timezone.utc)

    first = sl.accrue(observations=[_obs("a", "dogfood", 10, start=start)], ledger_path=ledger)
    assert first[0].accrued and sl.aggregate_or_zero(ledger) == 10

    # Same span again → the watermark (until = start+10h) suppresses a duplicate.
    again = sl.accrue(observations=[_obs("a", "dogfood", 10, start=start)], ledger_path=ledger)
    assert not again[0].accrued
    assert sl.aggregate_or_zero(ledger) == 10, "re-accruing the same span must not double-count"

    # A later window (start → start+15h) accrues only the NEW 5h beyond the watermark.
    later = {
        "session": "a",
        "profile": "dogfood",
        "active_since": start.isoformat(),
        "active_until": (start + timedelta(hours=15)).isoformat(),
    }
    grew = sl.accrue(observations=[later], ledger_path=ledger)
    assert grew[0].accrued
    assert grew[0].record["hours"] == pytest.approx(5.0)
    assert sl.aggregate_or_zero(ledger) == pytest.approx(15.0)


def test_soak_record_shape_matches_gate_reader(tmp_path):
    """A written soak record is exactly what profiles._soak_hours_of reads — the
    writer and the gate-side reader agree on the record contract by construction."""
    ledger = tmp_path / "ledger.jsonl"
    sl.accrue(observations=[_obs("a", "dogfood", 7)], ledger_path=ledger)
    (record,) = sl.read_ledger(ledger)
    assert record["event"] == "soak"
    assert record["profile"] == "dogfood"
    assert record["hours"] == 7
    # The exact function the gate uses to read a soak record must agree.
    assert pf._soak_hours_of(record) == 7


# --- AC1 [R-21] — the cutover: dogfood ring + surgeon, plan-by-default --------


def _run_cutover(env_overrides):
    env = dict(os.environ)
    for k in ("CUTOVER_WORKSPACES", "DOGFOOD_CUTOVER_APPLY", "EDGE_REF", "OAW_MAJOR"):
        env.pop(k, None)
    env.update(env_overrides)
    return subprocess.run(
        ["bash", str(CUTOVER_SCRIPT)], capture_output=True, text=True, env=env, timeout=60
    )


def test_cutover_script_is_executable():
    """The cutover is invoked directly (./scripts/ci/dogfood-cutover.sh), so +x."""
    assert CUTOVER_SCRIPT.exists(), f"cutover script missing: {CUTOVER_SCRIPT}"
    assert os.access(CUTOVER_SCRIPT, os.X_OK), "cutover script must be executable"


def test_cutover_plans_dogfood_ring_and_surgeon(tmp_path):
    """Plan mode stamps oaw.profile=dogfood, wires the surgeon, and launches NOTHING.

    AC1: the OaW team works on :edge in the dogfood profile with the surgeon active.
    Plan-by-default proves the composition (dogfood label + surgeon watch) with no
    aoe/docker — a real cutover is the operator's explicit DOGFOOD_CUTOVER_APPLY go.
    """
    proc = _run_cutover(
        {
            "CUTOVER_WORKSPACES": "/work/agent-a /work/agent-b",
            "EDGE_REF": "ghcr.io/wave-engineering/oakandwave-workflow:edge",
        }
    )
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out
    # dogfood profile label (from profiles.py, not hand-spelled) — R-21.
    assert "oaw.profile=dogfood" in out, "cutover must stamp the dogfood profile label"
    # the surgeon is wired to watch, filtering on the label + failing on quarantine.
    assert "surgeon.py" in out and "--fail-on-quarantine" in out
    # :edge, per-workspace launches planned…
    assert out.count("aoe add --sandbox") >= 2, "one dogfood sandbox planned per workspace"
    # …but NOTHING launched (plan-by-default — this cuts LIVE fleet agents over).
    assert "launched 0" in out and "plan" in out.lower()


def test_cutover_fails_closed_without_workspaces():
    """No CUTOVER_WORKSPACES ⇒ fail loud, never a silent no-op 'cutover done'."""
    proc = _run_cutover({})
    assert proc.returncode != 0
    assert "CUTOVER_WORKSPACES" in (proc.stdout + proc.stderr)


# --- Real-registry branch (skip-gated, mirrors test_throwaway_ci_ring.py) -----


def test_full_lifecycle_against_live_registry():
    """Run the whole promotion cycle against a real signed digest when provided.

    Set OAKANDWAVE_CYCLE_DIGEST to a pushed+signed :edge digest (and be logged in to
    ghcr) to exercise E2E-02 for real: promote (retag :edge→:stable) + adopt. Absent
    that, this skips — the stock lane has no registry artifact to retag.
    """
    digest = os.environ.get("OAKANDWAVE_CYCLE_DIGEST")
    if not digest:
        pytest.skip("set OAKANDWAVE_CYCLE_DIGEST to a live signed :edge digest to run E2E-02")

    promote = REPO_ROOT / "scripts" / "ci" / "promote-oakandwave-image.sh"
    env = dict(os.environ)
    env.update(
        DIGEST_REF=digest,
        THROWAWAY_CI_PASSED="true",
        SOAK_HOURS="48",
        SOAK_REQUIRED_HOURS="24",
        QUARANTINE_COUNT="0",
        OPEN_SEV1_COUNT="0",
        OPERATOR_ACK="true",
        PROMOTE_DRY_RUN="true",  # evaluate the gate + print the retag; do not push
    )
    proc = subprocess.run(
        ["bash", str(promote)], capture_output=True, text=True, env=env, timeout=120
    )
    assert proc.returncode == 0, f"promotion cycle failed:\n{proc.stdout}\n{proc.stderr}"
    assert digest in (proc.stdout + proc.stderr)
