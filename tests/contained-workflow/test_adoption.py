"""Oracle for Story 2.4 (#969) — rolling per-agent :stable adoption (R-08/R-18).

The adoption decision (``containers/oakandwave-workflow/adoption.py``) decides how
a fleet agent adopts a promoted :stable at *its* container-recreate. Two
acceptance criteria, both proved here as *pure* unit oracles (no docker, no
registry) so they run for real in the stock ``pytest tests/`` lane:

* **AC1 [R-08]** — *a minor/patch :stable is adopted at the next
  container-recreate, not by synchronized flip.* The named oracle
  :func:`test_minor_patch_adopted_at_recreate_not_flipped` proves a same-major
  minor/patch bump verdicts ``adopt``; that the adoption takes effect only via a
  recreate *plan* (the next launch ref), never by mutating a running/current ref;
  and that the decision is a per-agent function of *this* agent's current version
  — two agents on different currents each decide independently (rolling), so
  there is no stop-the-world flip.

* **AC2 [R-08, R-18]** — *updated and not-yet-updated agents coexist.*
  :func:`test_updated_and_not_yet_updated_coexist` proves two same-major minors
  classify ``shared-compatible`` and map to the SAME ``~/.oaw/state/<major>/``
  namespace (coexist, additive/forward-tolerant), while a major bump classifies
  ``isolated`` (separate namespaces) and is NOT auto-adopted at recreate — a major
  cross is opt-in (§5.8).

Plus fail-loud guards (a malformed / digest-only version raises) and the
CLI/wrapper wiring the adoption mechanism rides.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
ADOPTION_PY = CONTAINER_DIR / "adoption.py"
ADOPT_SCRIPT = REPO_ROOT / "scripts" / "ci" / "adopt-stable.sh"

# Path import (no PYTHONPATH dependency), mirroring test_gate.py / test_mounts.py.
sys.path.insert(0, str(CONTAINER_DIR))
import adoption as ad  # noqa: E402
import mount_resolver as mr  # noqa: E402

# Two distinct, well-formed immutable digest pins for the same repo.
REPO = "ghcr.io/wave-engineering/oakandwave-workflow"
DIGEST_A = f"{REPO}@sha256:" + "a" * 64
DIGEST_B = f"{REPO}@sha256:" + "b" * 64


# --- AC1 [R-08] — adopt a minor/patch at recreate, not by synchronized flip ----


def test_minor_patch_adopted_at_recreate_not_flipped():
    """The named story oracle. A minor and a patch bump within the same major
    both verdict ``adopt``; adoption manifests only as the *next* launch ref (a
    recreate), never by mutating the running ref; and the decision is per-agent."""
    # A minor bump and a patch bump are both adopted.
    minor = ad.decide_adoption("8.2.0", "8.3.0")
    patch = ad.decide_adoption("8.2.0", "8.2.1")
    assert minor.action == ad.ADOPT and minor.adopt
    assert patch.action == ad.ADOPT and patch.adopt

    # "Not by synchronized flip": adoption takes effect ONLY through a recreate
    # plan that changes the NEXT launch ref — the running/current ref is retained
    # untouched (for rollback), never mutated in place. There is no push into a
    # running container; only the recreate consumes the new digest.
    plan = ad.plan_recreate(
        current_ref=DIGEST_A,
        current_version="8.2.0",
        target_ref=DIGEST_B,
        target_version="8.3.0",
    )
    assert plan.action == ad.ADOPT
    assert plan.launch_ref == DIGEST_B  # the recreate launches the new digest
    assert plan.prior_ref == DIGEST_A  # the old digest is preserved, not flipped

    # Per-agent / rolling: the verdict is a function of THIS agent's current, so
    # agents on different currents adopt independently at their own recreate —
    # there is no fleet-wide, all-at-once flip.
    ahead = ad.decide_adoption("8.3.0", "8.3.0")  # already updated → noop
    behind = ad.decide_adoption("8.1.0", "8.3.0")  # not yet updated → adopts on recreate
    assert ahead.action == ad.NOOP
    assert behind.action == ad.ADOPT


def test_already_on_stable_is_noop_no_recreate_churn():
    """An agent already on the current :stable does not re-adopt — a NOOP, so a
    published :stable never forces a redundant recreate on an up-to-date agent."""
    d = ad.decide_adoption("8.3.0", "8.3.0")
    assert d.action == ad.NOOP and not d.adopt
    plan = ad.plan_recreate(
        current_ref=DIGEST_A, current_version="8.3.0",
        target_ref=DIGEST_A, target_version="8.3.0",
    )
    assert plan.action == ad.NOOP
    assert plan.launch_ref == DIGEST_A  # stays on the same digest


def test_same_major_rollback_is_followed_at_recreate():
    """Rollback (§5.6) publishes a prior digest to :stable; a same-major agent
    follows :stable in the DOWN direction too, at its next recreate."""
    d = ad.decide_adoption("8.3.0", "8.2.0")
    assert d.action == ad.ADOPT  # follows :stable downward within the major
    assert "rollback" in d.reason


# --- AC2 [R-08, R-18] — updated and not-yet-updated agents coexist -------------


def test_updated_and_not_yet_updated_coexist():
    """Two same-major minors are ``shared-compatible`` and resolve the SAME
    major-partitioned namespace, so an updated (8.3.0) and a not-yet-updated
    (8.2.0) agent coexist over one shared-state tree (R-18). A major bump is
    ``isolated`` (separate namespaces) — mixing majors is isolated, not
    corrupting, so it is never auto-adopted at recreate."""
    updated, not_updated = "8.3.0", "8.2.0"
    assert ad.classify_coexistence(updated, not_updated) == ad.SHARED_COMPATIBLE
    assert ad.state_namespace(updated) == ad.state_namespace(not_updated)
    assert ad.state_namespace(updated).endswith("/.oaw/state/8")

    # A major bump: isolated namespaces, and not auto-adopted (opt-in, §5.8).
    assert ad.classify_coexistence("8.9.9", "9.0.0") == ad.ISOLATED
    assert ad.state_namespace("8.9.9") != ad.state_namespace("9.0.0")
    hold = ad.decide_adoption("8.9.9", "9.0.0")
    assert hold.action == ad.HOLD and not hold.adopt
    assert hold.coexistence == ad.ISOLATED


def test_major_cross_requires_explicit_opt_in():
    """A major cross HOLDs by default and only adopts with an explicit opt-in
    (§5.8: the developer decides when to cross a major)."""
    default = ad.decide_adoption("8.5.0", "9.0.0")
    opted = ad.decide_adoption("8.5.0", "9.0.0", allow_major_cross=True)
    assert default.action == ad.HOLD
    assert opted.action == ad.ADOPT
    # The plan stays on the current major when held; a HELD agent never launches
    # the cross-major digest at recreate.
    held_plan = ad.plan_recreate(
        current_ref=DIGEST_A, current_version="8.5.0",
        target_ref=DIGEST_B, target_version="9.0.0",
    )
    assert held_plan.action == ad.HOLD
    assert held_plan.launch_ref == DIGEST_A  # holds on current, not the cross digest


def test_state_namespace_matches_mount_resolver_seam():
    """The coexistence namespace and the mount resolver's R-03 guard must fence
    the SAME path — one source of truth, so they can never drift apart."""
    assert ad.STATE_ROOT_PARTS == mr.STATE_ROOT_PARTS
    # And the concrete path agrees with the resolver's constant.
    assert ad.state_namespace(8, home="/home/ubuntu") == "/home/ubuntu/.oaw/state/8"


# --- Fail-loud parsing guards -------------------------------------------------


@pytest.mark.parametrize("bad", ["", "not-a-version", "8.2", "8", "v8.x.0", None, 8])
def test_malformed_version_raises(bad):
    with pytest.raises(ad.AdoptionError):
        ad.parse_semver(bad)


def test_digest_ref_carries_no_semver():
    """A digest ref has no version — parsing one must fail-loud, forcing the
    caller to read the OCI version label instead of guessing."""
    with pytest.raises(ad.AdoptionError):
        ad.parse_semver(DIGEST_A)


def test_tagged_ref_and_v_prefix_parse():
    assert ad.parse_semver(f"{REPO}:8.3.1").triple == (8, 3, 1)
    assert ad.parse_semver("v8.3.1").triple == (8, 3, 1)
    assert ad.parse_semver("0.0.0-dev").triple == (0, 0, 0)
    assert ad.parse_semver("0.0.0-dev").prerelease == "dev"


# --- CLI wiring ---------------------------------------------------------------


def _run_cli(*args):
    return subprocess.run(
        [sys.executable, str(ADOPTION_PY), *args],
        capture_output=True, text=True,
    )


def test_cli_action_and_json():
    r = _run_cli("--current-version", "8.2.0", "--target-version", "8.3.0")
    assert r.returncode == 0
    assert r.stdout.strip() == "adopt"

    r = _run_cli(
        "--current-version", "8.2.0", "--target-version", "8.3.0", "--format", "json"
    )
    payload = json.loads(r.stdout)
    assert payload["action"] == "adopt"
    assert payload["coexistence"] == ad.SHARED_COMPATIBLE


def test_cli_plan_emits_launch_ref():
    """With both refs, stdout is the digest the recreate should launch (adopt →
    the target; hold → the current)."""
    r = _run_cli(
        "--current-ref", DIGEST_A, "--current-version", "8.2.0",
        "--target-ref", DIGEST_B, "--target-version", "8.3.0",
    )
    assert r.returncode == 0
    assert r.stdout.strip() == DIGEST_B

    r = _run_cli(
        "--current-ref", DIGEST_A, "--current-version", "8.2.0",
        "--target-ref", DIGEST_B, "--target-version", "9.0.0",
    )
    assert r.stdout.strip() == DIGEST_A  # major cross held → stays on current


def test_cli_malformed_version_exits_2():
    r = _run_cli("--current-version", "nope", "--target-version", "8.3.0")
    assert r.returncode == 2
    assert "adoption error" in r.stderr.lower()


# --- Wrapper (adopt-stable.sh) dry-run wiring ---------------------------------


def _run_wrapper(env_extra, tmp_path):
    env = dict(os.environ)
    env.update(
        ADOPT_DRY_RUN="true",
        OAW_STATE_DIR=str(tmp_path / "adoption"),
    )
    env.update(env_extra)
    return subprocess.run(
        ["bash", str(ADOPT_SCRIPT)], capture_output=True, text=True, env=env
    )


def test_wrapper_dry_run_adopts_minor(tmp_path):
    """The recreate wrapper, at a dry-run recreate, resolves the injected :stable
    and emits the new digest to launch for a same-major minor bump — without
    docker, and without touching a running container."""
    r = _run_wrapper(
        {
            "OAW_STABLE_RESOLVED_REF": DIGEST_B,
            "OAW_STABLE_VERSION": "8.3.0",
            "OAW_CURRENT_REF": DIGEST_A,
            "OAW_CURRENT_VERSION": "8.2.0",
        },
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == DIGEST_B
    # Dry-run pins nothing.
    assert not (tmp_path / "adoption" / "current").exists()


def test_wrapper_dry_run_holds_major(tmp_path):
    """A cross-major :stable is HELD by default — the wrapper emits the current
    digest, keeping the agent on its major (coexistence preserved)."""
    r = _run_wrapper(
        {
            "OAW_STABLE_RESOLVED_REF": DIGEST_B,
            "OAW_STABLE_VERSION": "9.0.0",
            "OAW_CURRENT_REF": DIGEST_A,
            "OAW_CURRENT_VERSION": "8.2.0",
        },
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == DIGEST_A


def test_wrapper_dry_run_bootstrap_adopts_when_no_current(tmp_path):
    """A first-ever adoption (no recorded current) bootstraps onto :stable."""
    r = _run_wrapper(
        {
            "OAW_STABLE_RESOLVED_REF": DIGEST_B,
            "OAW_STABLE_VERSION": "8.3.0",
        },
        tmp_path,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip().splitlines()[-1] == DIGEST_B


def test_wrapper_apply_pins_current_and_rollback(tmp_path):
    """Non-dry-run apply (still docker-free — refs injected) records the adopted
    digest and keeps the PRIOR digest for a §5.6 rollback repoint."""
    env = dict(os.environ)
    state_dir = tmp_path / "adoption"
    env.update(
        ADOPT_DRY_RUN="false",
        OAW_STATE_DIR=str(state_dir),
        OAW_STABLE_RESOLVED_REF=DIGEST_B,
        OAW_STABLE_VERSION="8.3.0",
        OAW_CURRENT_REF=DIGEST_A,
        OAW_CURRENT_VERSION="8.2.0",
    )
    r = subprocess.run(
        ["bash", str(ADOPT_SCRIPT)], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, r.stderr
    assert (state_dir / "current").read_text().strip() == DIGEST_B
    assert (state_dir / "current-version").read_text().strip() == "8.3.0"
    assert (state_dir / "rollback").read_text().strip() == DIGEST_A
