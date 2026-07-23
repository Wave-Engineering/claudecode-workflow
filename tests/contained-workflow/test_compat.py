"""Canonical oracle for Story 3.3 (#972) — the SemVer compatibility contract and
the major-partitioned state namespace (Dev Spec §5.8, R-18 / R-20).

The contract (Dev Spec §5.8) is a *policy*, and its runtime representation is the
major-partitioned durable-state namespace ``~/.oaw/state/<major>/`` — the same
seam the coexistence classifier (``containers/oakandwave-workflow/adoption.py``)
reasons over and the mount resolver (``mount_resolver.py``) fences at. Both of
this story's acceptance criteria are proved here as *pure*, filesystem-level
oracles (no docker, no registry) so they run for real in the stock
``pytest tests/`` lane:

* **AC1 [R-18]** — *same-major agents interoperate; within-major changes are
  additive/forward-tolerant.* Two same-major minors classify ``shared-compatible``
  and resolve the SAME ``~/.oaw/state/<major>/`` namespace, so they read and write
  ONE shared-state tree. :func:`test_within_major_change_is_additive_and_forward_tolerant`
  makes the "additive + forward-tolerant" half concrete: an updated minor adds a
  field without dropping the old ones (additive), and a not-yet-updated reader
  ignores the unknown field and still resolves every field it knows
  (forward-tolerant) — in both directions, within the one major namespace.

* **AC2 [R-20]** — *mixing majors is isolated, not corrupting.* The canonical
  :func:`test_namespace_partition` proves v-N and v-M resolve to disjoint,
  non-overlapping directories while same-major minors collapse onto one;
  :func:`test_mixing_majors_is_isolated_not_corrupting` shows a major-M write can
  never touch a major-N reader's file — the partition IS the isolation, so there
  is no shared-state migration engine to build (§1.5 non-goal).

A drift guard (:func:`test_compat_namespace_matches_mount_resolver_seam`) pins the
contract's namespace to the exact path the resolver's R-03/R-20 guard enforces —
one source of truth, so the coexistence namespace and the mount fence can never
diverge.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"

# Path import (no PYTHONPATH dependency), mirroring test_adoption.py / test_mounts.py.
sys.path.insert(0, str(CONTAINER_DIR))
import adoption as ad  # noqa: E402
import mount_resolver as mr  # noqa: E402


# --- A tiny within-major shared-state model -----------------------------------
#
# The compat contract is about how agents SHARE the durable-state tree, so the
# oracle needs something written to and read from it. This models one logical
# state record persisted as JSON at ``<namespace>/agent-state.json``. Two knobs
# make the R-18 property executable:
#   * an ADDITIVE writer adds a key without removing existing keys;
#   * a FORWARD-TOLERANT reader projects onto the keys IT knows and defaults any
#     it is missing, silently ignoring keys it does not recognise.


def _state_file(major: int | str, home: Path) -> Path:
    """The shared-state record path inside the major-partitioned namespace."""
    return Path(ad.state_namespace(major, home=home)) / "agent-state.json"


def _write_state(major: int | str, home: Path, record: dict) -> Path:
    path = _state_file(major, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record))
    return path


def _read_state(major: int | str, home: Path, known_keys: tuple[str, ...], defaults: dict) -> dict:
    """Forward-tolerant read: project the on-disk record onto ``known_keys``,
    defaulting any absent key and ignoring any key the reader does not know."""
    raw = json.loads(_state_file(major, home).read_text())
    return {k: raw.get(k, defaults[k]) for k in known_keys}


# --- AC2 [R-20] — the canonical namespace-partition oracle ---------------------


def test_namespace_partition():
    """CANONICAL (Dev Spec §8, Story 3.3): v-N and v-M states are isolated.

    Different majors resolve to disjoint, non-overlapping directories (mixing
    majors is isolated, not corrupting — R-20); same-major minors collapse onto
    the ONE namespace (so same-major agents share state — the R-18 sharing
    half). The major, and only the major, is what partitions the namespace."""
    home = "/home/ubuntu"

    ns8 = ad.state_namespace(8, home=home)
    ns9 = ad.state_namespace(9, home=home)

    # Isolation: two different majors are different, non-overlapping trees.
    assert ns8 != ns9
    assert ns8.endswith("/.oaw/state/8")
    assert ns9.endswith("/.oaw/state/9")
    # Neither namespace is nested inside the other — a write under one can never
    # land inside the other's subtree.
    p8, p9 = PurePosixPath(ns8), PurePosixPath(ns9)
    assert p9 not in p8.parents and p8 not in p9.parents

    # Sharing: every minor/patch within a major maps to the SAME namespace.
    for minor_patch in ("8.0.0", "8.2.0", "8.9.14", "8.3.0-rc.1"):
        assert ad.state_namespace(minor_patch, home=home) == ns8

    # A semver, a bare major int, and a "major.x" string all partition identically.
    assert ad.state_namespace("8.7.3", home=home) == ad.state_namespace(8, home=home)


# --- AC1 [R-18] — same-major agents interoperate over shared state -------------


def test_same_major_agents_interoperate():
    """Two same-major minors classify ``shared-compatible`` and resolve one
    namespace — the precondition for interoperating over shared state (R-18).
    A cross-major pair classifies ``isolated``."""
    updated, not_updated = "8.3.0", "8.2.0"
    assert ad.classify_coexistence(updated, not_updated) == ad.SHARED_COMPATIBLE
    assert ad.state_namespace(updated) == ad.state_namespace(not_updated)

    assert ad.classify_coexistence("8.9.9", "9.0.0") == ad.ISOLATED
    assert ad.state_namespace("8.9.9") != ad.state_namespace("9.0.0")


def test_within_major_change_is_additive_and_forward_tolerant(tmp_path):
    """Within a major, shared-state changes are additive + forward-tolerant (R-18).

    Scenario: a not-yet-updated agent (minor N, knows {task, cursor}) and an
    updated agent (minor N+1, adds {retries}) share the one major-8 namespace.

    * ADDITIVE: the updated writer adds ``retries`` WITHOUT dropping ``task`` or
      ``cursor`` — the old fields survive the write.
    * FORWARD-TOLERANT (old reads new): the not-yet-updated reader projects onto
      the two keys it knows and silently ignores ``retries`` — it does not choke
      on the unknown field.
    * FORWARD-TOLERANT (new reads old): the updated reader reads a record the old
      writer left (no ``retries``) and defaults the additive field — no crash,
      no corruption.

    Both agents transact against ONE file in ONE namespace throughout — that is
    what "interoperate over shared state" means."""
    home = tmp_path

    old_known = ("task", "cursor")
    old_defaults = {"task": None, "cursor": 0}
    new_known = ("task", "cursor", "retries")
    new_defaults = {"task": None, "cursor": 0, "retries": 0}

    # Old writer lays down the original record.
    _write_state(8, home, {"task": "build", "cursor": 5})

    # New reader reads the OLD record: the additive field defaults, everything
    # else round-trips. (new reads old → forward-tolerant, additive default.)
    seen_by_new = _read_state(8, home, new_known, new_defaults)
    assert seen_by_new == {"task": "build", "cursor": 5, "retries": 0}

    # Updated writer performs an ADDITIVE write: adds retries, keeps task+cursor.
    _write_state(8, home, {"task": "build", "cursor": 7, "retries": 2})

    # Old reader reads the NEW record: it still resolves every field it knows and
    # ignores the field it doesn't. (old reads new → forward-tolerant.)
    seen_by_old = _read_state(8, home, old_known, old_defaults)
    assert seen_by_old == {"task": "build", "cursor": 7}
    assert "retries" not in seen_by_old  # unknown key silently ignored, not fatal

    # And both agents were reading/writing the SAME file — one shared-state tree.
    assert _state_file(8, home) == _state_file("8.99.0", home)


# --- AC2 [R-20] — mixing majors is isolated, not corrupting --------------------


def test_mixing_majors_is_isolated_not_corrupting(tmp_path):
    """A major-8 and a major-9 agent under the SAME home write conflicting values
    for the same logical key; each lands in its OWN namespace, so a major-9 write
    can never touch the major-8 reader's file (R-20). The partition IS the
    isolation — there is no cross-major corruption path to migrate away."""
    home = tmp_path

    _write_state(8, home, {"task": "eight", "cursor": 8})
    _write_state(9, home, {"task": "nine", "cursor": 9})

    # Separate files on disk — the write did not clobber across majors.
    f8, f9 = _state_file(8, home), _state_file(9, home)
    assert f8 != f9
    assert f8.exists() and f9.exists()

    # Each major reads back exactly what IT wrote, uncorrupted by the other.
    assert json.loads(f8.read_text()) == {"task": "eight", "cursor": 8}
    assert json.loads(f9.read_text()) == {"task": "nine", "cursor": 9}

    # Re-writing major 9 leaves major 8 byte-for-byte untouched.
    before = f8.read_bytes()
    _write_state(9, home, {"task": "nine-prime", "cursor": 99, "retries": 3})
    assert f8.read_bytes() == before


# --- Drift guard — the contract namespace IS the mount-fence path --------------


def test_compat_namespace_matches_mount_resolver_seam():
    """The compat contract's namespace and the mount resolver's R-03/R-20 guard
    must fence the SAME path — one source of truth, so the coexistence namespace
    and the enforced mount can never drift apart."""
    # The seam constant is shared, not duplicated.
    assert ad.STATE_ROOT_PARTS == mr.STATE_ROOT_PARTS

    # The concrete path the contract advertises is exactly the state root the
    # resolver's R-03 guard requires the rw memory mount to live under.
    home = PurePosixPath("/home/ubuntu")
    contract_ns = ad.state_namespace(8, home=home)
    guard_root = home.joinpath(*mr.STATE_ROOT_PARTS, "8")
    assert contract_ns == str(guard_root)

    # A source directly under that root satisfies the resolver guard; a sibling
    # under a DIFFERENT major does not (the partition the contract promises is the
    # partition the guard enforces).
    mr.check_sandbox_scoped_memory(f"{contract_ns}/projects/x/memory", 8, home)
    with pytest.raises(mr.ManifestError):
        mr.check_sandbox_scoped_memory(f"{contract_ns}/projects/x/memory", 9, home)
