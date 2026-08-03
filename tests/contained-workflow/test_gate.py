"""Oracle for Story 2.3 (#968) — the mechanical promotion gate (R-07/R-23).

The gate (``containers/oakandwave-workflow/promotion_gate.py``) decides whether a
candidate ``:edge`` digest may be promoted to ``:stable``. Two acceptance
criteria, both proved here as *pure* unit oracles (no docker, no registry, no
FlightDeck) so they run for real in the stock ``pytest tests/`` lane:

* **AC1 [R-07]** — *no code path promotes without all conditions green.* The
  named story oracle, :func:`test_gate_conjunction`, drives every single-red
  combination of the four mechanical conditions and asserts :func:`promote`
  refuses each one; the all-green case promotes only with the ACK. Fail-closed:
  a missing / unknown / malformed signal is RED, never assumed green.
* **AC2 [R-07, R-23]** — *the promoted digest equals the digest E2E-01 tested.*
  A green CI result for a *different* digest cannot carry this one, and
  :func:`promote` returns exactly the tested digest — never a re-resolved tag.

Plus guards on the ACK semantics (confirm-only, never a substitute) and on the
wrapper/CLI wiring that the promotion mechanism rides.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
GATE_PY = CONTAINER_DIR / "promotion_gate.py"
PROMOTE_SCRIPT = REPO_ROOT / "scripts" / "ci" / "promote-oakandwave-image.sh"

# The resolver-style path import (no PYTHONPATH dependency), mirroring
# test_mounts.py — the gate module is colocated with the container assets.
sys.path.insert(0, str(CONTAINER_DIR))
import promotion_gate as pg  # noqa: E402

# Two distinct, well-formed immutable digest pins.
DIGEST_A = "ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "a" * 64
DIGEST_B = "ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "b" * 64
MOVING_TAG = "ghcr.io/wave-engineering/oakandwave-workflow:edge"

# A fully-green signal set for DIGEST_A. Individual tests knock ONE condition red.
GREEN_SIGNALS = dict(
    target_digest=DIGEST_A,
    ci_passed=True,
    ci_digest=DIGEST_A,
    quarantine_count=0,
    open_sev1_count=0,
)

# For each condition, the signal override(s) that turn JUST that condition red —
# including the fail-closed "unavailable" (None) shape.
RED_OVERRIDES: dict[str, list[dict]] = {
    "throwaway_ci": [
        {"ci_passed": False},  # E2E-01 red
        {"ci_passed": None},  # no CI result at all (fail-closed)
        {"ci_digest": DIGEST_B},  # green, but for a DIFFERENT digest (R-23)
        {"ci_digest": None},  # green, but no digest attested (fail-closed)
        {"ci_digest": MOVING_TAG},  # green, but attested a moving tag (R-23)
    ],
    "quarantines": [
        {"quarantine_count": 1},  # a quarantine tripped
        {"quarantine_count": None},  # quarantine telemetry unavailable
    ],
    "sev1": [
        {"open_sev1_count": 3},  # open Sev-1
        {"open_sev1_count": None},  # Sev-1 telemetry unavailable
    ],
}


def _report(**overrides) -> pg.GateReport:
    signals = {**GREEN_SIGNALS, **overrides}
    return pg.evaluate_gate(**signals)


# --- AC1 [R-07]: the named story oracle — no promotion unless ALL green -------


def test_gate_conjunction() -> None:
    """No code path promotes without all four mechanical conditions green (R-07).

    Drive every single-condition-red shape (including the fail-closed "signal
    unavailable" shapes) and assert the gate reads red AND :func:`promote`
    refuses. Then the all-green case: it promotes — but only once the ACK
    confirms it.
    """
    for condition, overrides_list in RED_OVERRIDES.items():
        for override in overrides_list:
            report = _report(**override)
            assert not report.green, (
                f"{condition} red via {override} must leave the gate RED, "
                f"got green:\n{report.summary()}"
            )
            # Even WITH the operator ACK, a red condition must never promote —
            # the ACK cannot substitute for a red condition.
            with pytest.raises(pg.GateError):
                pg.promote(report, operator_ack=True)
            assert any(c.name == condition for c in report.red()), (
                f"the RED condition should be {condition}; report:\n{report.summary()}"
            )

    # All-green: the gate is green and promotes the tested digest — with the ACK.
    green = _report()
    assert green.green, f"the fully-green signal set must be green:\n{green.summary()}"
    assert pg.promote(green, operator_ack=True) == DIGEST_A


def test_multiple_red_conditions_still_refused() -> None:
    """Every non-all-green combination refuses, ACK or not (exhaustive over the
    2^3 truth table of the three conditions)."""
    knobs = {
        "throwaway_ci": {"ci_passed": False},
        "quarantines": {"quarantine_count": 2},
        "sev1": {"open_sev1_count": 1},
    }
    names = list(knobs)
    for greens in itertools.product([True, False], repeat=len(names)):
        overrides: dict = {}
        for name, keep_green in zip(names, greens):
            if not keep_green:
                overrides.update(knobs[name])
        report = _report(**overrides)
        all_green = all(greens)
        assert report.green is all_green, (
            f"gate green={report.green} but expected {all_green} for {greens}"
        )
        if not all_green:
            with pytest.raises(pg.GateError):
                pg.promote(report, operator_ack=True)


# --- AC2 [R-07, R-23]: the promoted digest is the digest E2E-01 tested --------


def test_promoted_digest_equals_tested_digest() -> None:
    """A green E2E-01 for a DIFFERENT digest cannot promote this one (R-23)."""
    # CI passed, but against DIGEST_B while we target DIGEST_A.
    report = pg.evaluate_gate(
        **{**GREEN_SIGNALS, "target_digest": DIGEST_A, "ci_digest": DIGEST_B}
    )
    assert not report.green
    ci = next(c for c in report.conditions if c.name == "throwaway_ci")
    assert not ci.green and "R-23" in ci.detail
    with pytest.raises(pg.GateError):
        pg.promote(report, operator_ack=True)

    # The matched case returns EXACTLY the tested digest, not a moving tag.
    matched = pg.evaluate_gate(**GREEN_SIGNALS)
    promoted = pg.promote(matched, operator_ack=True)
    assert promoted == DIGEST_A == GREEN_SIGNALS["ci_digest"]
    assert "@sha256:" in promoted, "the promoted ref must be the immutable digest"


def test_gate_refuses_a_moving_tag_target() -> None:
    """The promotion target must be an immutable digest, never a moving tag (R-23)."""
    with pytest.raises(pg.GateError):
        pg.evaluate_gate(**{**GREEN_SIGNALS, "target_digest": MOVING_TAG})


# --- ACK semantics: confirm-only, never a substitute (R-07) -------------------


def test_ack_cannot_promote_a_red_gate() -> None:
    """The ACK confirms a green gate; it can never rescue a red one (R-07)."""
    report = _report(ci_passed=False)
    assert not report.green
    with pytest.raises(pg.GateError):
        pg.promote(report, operator_ack=True)


def test_green_gate_still_needs_the_ack() -> None:
    """A green gate does NOT auto-promote — the operator ACK is required, and it
    is consulted only after the query is green."""
    report = _report()
    assert report.green
    with pytest.raises(pg.GateError):
        pg.promote(report, operator_ack=False)
    assert pg.promote(report, operator_ack=True) == DIGEST_A


# --- CLI: the wrapper's decision surface (fail-closed) ------------------------


def _run_gate_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE_PY), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_cli_promotes_only_on_green_plus_ack() -> None:
    """The CLI prints the digest and exits 0 only on a green gate WITH --ack."""
    base = [
        "--target-digest", DIGEST_A,
        "--ci-passed", "true", "--ci-digest", DIGEST_A,
        "--quarantines", "0", "--open-sev1", "0",
    ]
    # Green but no ACK → refuse (non-zero), print nothing promotable on stdout.
    no_ack = _run_gate_cli(*base)
    assert no_ack.returncode != 0
    assert DIGEST_A not in no_ack.stdout

    # Green + ACK → promote: stdout is exactly the tested digest.
    acked = _run_gate_cli(*base, "--ack")
    assert acked.returncode == 0, acked.stderr
    assert acked.stdout.strip() == DIGEST_A


def test_cli_is_fail_closed_on_missing_signals() -> None:
    """Omitting a signal (unknown telemetry) leaves the gate RED, even with --ack."""
    # No soak / quarantine / sev1 signals at all → every one reads red.
    proc = _run_gate_cli(
        "--target-digest", DIGEST_A,
        "--ci-passed", "true", "--ci-digest", DIGEST_A,
        "--ack",
    )
    assert proc.returncode != 0, "missing telemetry must fail-closed, not promote"
    assert DIGEST_A not in proc.stdout


def test_cli_refuses_ci_green_for_a_different_digest() -> None:
    """CLI: E2E-01 green for another digest cannot promote the target (R-23)."""
    proc = _run_gate_cli(
        "--target-digest", DIGEST_A,
        "--ci-passed", "true", "--ci-digest", DIGEST_B,
        "--quarantines", "0", "--open-sev1", "0",
        "--ack",
    )
    assert proc.returncode != 0
    assert DIGEST_A not in proc.stdout


# --- Wrapper wiring: the promote script rides the tested gate + retags exactly -


def test_promote_script_is_executable() -> None:
    """The workflow / operator invokes the wrapper directly, so it must be +x."""
    assert PROMOTE_SCRIPT.exists(), f"promote script missing: {PROMOTE_SCRIPT}"
    assert os.access(PROMOTE_SCRIPT, os.X_OK), "promote script must be executable"


def test_promote_script_delegates_the_decision_to_the_gate() -> None:
    """The wrapper must NOT reimplement the conjunction — it calls the gate CLI
    and only retags on a green+ACK'd verdict (the decision is unit-tested)."""
    text = PROMOTE_SCRIPT.read_text()
    assert "promotion_gate.py" in text, "wrapper must call the gate module"
    # It retags by the EXACT digest with imagetools create — never a rebuild.
    assert "docker buildx imagetools create" in text, "wrapper must retag by digest"
    # No real build: `docker build`/`buildx build` (but `docker buildx imagetools`
    # is the retag, not a build — so match `docker build` NOT followed by `x`).
    assert re.search(r"docker build(?!x)", text) is None, "wrapper must NOT build (R-23)"
    assert "buildx build" not in text, "wrapper must NOT build (R-23)"


def test_promote_script_dry_run_requires_green_and_ack(tmp_path) -> None:
    """End-to-end through the wrapper (dry-run, no docker): a red or un-ACK'd
    gate retags nothing; green + ACK prints the exact-digest retag."""
    env = dict(os.environ)
    env.update(
        DIGEST_REF=DIGEST_A,
        THROWAWAY_CI_PASSED="true",
        THROWAWAY_CI_DIGEST=DIGEST_A,
        SOAK_HOURS="48",
        SOAK_REQUIRED_HOURS="24",
        QUARANTINE_COUNT="0",
        OPEN_SEV1_COUNT="0",
        PROMOTE_DRY_RUN="true",
    )
    # Clear any ambient signal that would leak in.
    env.pop("OPERATOR_ACK", None)

    def _run(e):
        return subprocess.run(
            ["bash", str(PROMOTE_SCRIPT)],
            capture_output=True, text=True, env=e, timeout=60,
        )

    # Green gate, but no ACK → wrapper exits non-zero, retags nothing.
    no_ack = _run(env)
    assert no_ack.returncode != 0, "a green gate must not promote without the ACK"
    assert "would retag" not in no_ack.stdout

    # Green + ACK → dry-run announces the exact-digest retag to :stable.
    env_ack = {**env, "OPERATOR_ACK": "true"}
    acked = _run(env_ack)
    assert acked.returncode == 0, acked.stderr
    assert "would retag" in acked.stdout
    assert DIGEST_A in acked.stdout
    assert ":stable" in acked.stdout

    # A red condition (a quarantine) never promotes, ACK or not.
    env_red = {**env_ack, "QUARANTINE_COUNT": "1"}
    red = _run(env_red)
    assert red.returncode != 0, "a quarantine must block promotion despite the ACK"
    assert "would retag" not in red.stdout
