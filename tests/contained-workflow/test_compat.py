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
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"

# Path import (no PYTHONPATH dependency), mirroring test_adoption.py / test_mounts.py.
sys.path.insert(0, str(CONTAINER_DIR))
import adoption as ad  # noqa: E402
import compat_guard as cg  # noqa: E402
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


# =============================================================================
# Story 3.4 (#973) — the mechanical compat-break guard (Dev Spec §5.8, R-19).
#
# Story 3.3 (above) proved the *policy*: same-major agents share one namespace,
# within-major changes are additive + forward-tolerant. Story 3.4 is the
# ENFORCEMENT: a mechanical guard that versions the shared-state schema and blocks
# a same-major minor from silently breaking that shared state. The two ACs are:
#   AC1 — a deliberate within-major schema break trips the guard (red-first).
#   AC2 — the guard blocks a silent minor ship of a breaking change.
# Both are proved here as pure oracles over compat_guard.py, and end-to-end
# through the git-sourced wrapper scripts/ci/compat-guard.sh.
# =============================================================================


def _schema(version: str, fields: dict) -> "cg.StateSchema":
    """Build a StateSchema from a compact mapping, e.g.
    ``_schema("0.1.0", {"task": ("string", False), "cursor": ("integer", False)})``.
    A field value is a ``(type, required)`` pair (or a bare type string ⇒ optional).
    """
    field_map = {}
    for name, spec in fields.items():
        if isinstance(spec, tuple):
            ftype, required = spec
        else:
            ftype, required = spec, False
        field_map[name] = {"type": ftype, "required": required}
    return cg.StateSchema.from_mapping({"schema_version": version, "fields": field_map})


BASELINE_FIELDS = {"task": "string", "cursor": "integer"}


# --- AC1 [R-19] — a within-major schema break trips the guard, RED-FIRST -------


@pytest.mark.parametrize(
    "candidate_fields, label",
    [
        ({"task": "string"}, "removed a field"),
        ({"task": "string", "cursor": "string"}, "changed a field's type"),
        ({"task": "string", "cursor": ("integer", True)}, "tightened optional -> required"),
        ({"task": "string", "cursor": "integer", "owner": ("string", True)}, "added a NEW required field"),
    ],
)
def test_within_major_break_trips_the_guard_red_first(candidate_fields, label):
    """AC1: a DELIBERATE within-major shared-state schema break trips the guard.

    Shown red-first by CONTRAST — the identical structural break is proved to be
    the thing tripping the guard, not a blanket refusal: the SAME change, when it
    crosses a major, is permitted. So the guard reacts to the *break*, and only a
    same-major break is red. Every parametrized case is one of the four mutations
    R-18 forbids within a major (remove / retype / tighten / new-required)."""
    baseline = _schema("0.1.0", BASELINE_FIELDS)

    # RED: the break shipped as a same-major (minor) bump → the guard raises.
    same_major_break = _schema("0.2.0", candidate_fields)
    with pytest.raises(cg.CompatBreakError) as exc:
        cg.assert_shippable(baseline, same_major_break)
    assert "major bump" in str(exc.value)  # the guard forces a major bump (R-19)

    # GREEN by contrast: the SAME break, crossing a major, is permitted — proving
    # the guard tripped on the same-major-ness of the break, not on the break alone.
    major_crossed_break = _schema("1.0.0", candidate_fields)
    report = cg.assert_shippable(baseline, major_crossed_break)  # does NOT raise
    assert report.diff.breaking, f"{label} should still classify as a breaking change"
    assert report.major_bumped


# --- AC2 [R-19] — the guard blocks a silent minor ship of a breaking change ----


def test_guard_blocks_silent_minor_ship_of_breaking_change():
    """AC2: a breaking change shipped under a same-major MINOR bump is blocked —
    the "silent minor ship" R-19 forbids. The guard is the mechanical detector."""
    baseline = _schema("0.1.0", BASELINE_FIELDS)
    # Drop `cursor` but only bump the minor — the silent minor ship.
    silent_minor = _schema("0.2.0", {"task": "string"})

    report = cg.evaluate_compat(baseline, silent_minor)
    assert report.diff.change == cg.BREAKING
    assert report.blocked is True
    assert report.requires_major_bump is True
    assert report.major_bumped is False
    # The block reason names the offending field and the forced major bump.
    reason = report.block_reason()
    assert "cursor" in reason
    assert "WITHOUT a major bump" in reason

    # And a same-major PATCH bump of the same break is equally blocked.
    silent_patch = _schema("0.1.1", {"task": "string"})
    assert cg.evaluate_compat(baseline, silent_patch).blocked is True


def test_additive_change_ships_within_major():
    """The compatible counterpart: adding an OPTIONAL field is additive and ships
    within-major without a major bump — the guard does NOT block it (else it would
    be a gate that blocks everything, as broken as one that blocks nothing)."""
    baseline = _schema("0.1.0", BASELINE_FIELDS)
    additive = _schema("0.2.0", {"task": "string", "cursor": "integer", "retries": "integer"})

    report = cg.assert_shippable(baseline, additive)  # does NOT raise
    assert report.diff.change == cg.ADDITIVE
    assert report.diff.added == ("retries",)
    assert report.blocked is False
    assert report.requires_major_bump is False


def test_identical_schema_is_a_noop():
    """No structural change ⇒ identical ⇒ shippable, regardless of a version bump."""
    baseline = _schema("0.1.0", BASELINE_FIELDS)
    same = _schema("0.1.1", BASELINE_FIELDS)
    report = cg.assert_shippable(baseline, same)
    assert report.diff.change == cg.IDENTICAL
    assert report.blocked is False


def test_loosening_required_to_optional_is_not_a_break():
    """A field going required -> optional LOOSENS the contract (still
    forward-tolerant), so it is not a break and ships within-major."""
    baseline = _schema("0.1.0", {"task": ("string", True), "cursor": "integer"})
    loosened = _schema("0.2.0", {"task": ("string", False), "cursor": "integer"})
    report = cg.assert_shippable(baseline, loosened)
    assert report.diff.change == cg.IDENTICAL  # required-ness loosened, no field/type change
    assert report.blocked is False


def test_major_bump_permits_the_break():
    """A breaking change that DID bump the major is permitted — the break is
    properly signalled by the major, so mixing is isolated not corrupting (R-20),
    and the guard passes."""
    baseline = _schema("0.1.0", BASELINE_FIELDS)
    crossed = _schema("1.0.0", {"task": "string"})  # dropped cursor, but bumped major
    report = cg.assert_shippable(baseline, crossed)
    assert report.diff.breaking is True
    assert report.major_bumped is True
    assert report.blocked is False


def test_version_regression_is_blocked():
    """A schema version only ever moves forward; a candidate that regresses is a
    fail-loud sanity violation, blocked independent of the field diff."""
    baseline = _schema("0.2.0", BASELINE_FIELDS)
    regressed = _schema("0.1.0", BASELINE_FIELDS)  # identical fields, LOWER version
    report = cg.evaluate_compat(baseline, regressed)
    assert report.version_regressed is True
    assert report.blocked is True
    with pytest.raises(cg.CompatBreakError):
        cg.assert_shippable(baseline, regressed)


# --- Fail-loud: a malformed schema is never assumed compatible -----------------


@pytest.mark.parametrize(
    "bad",
    [
        {"fields": {"task": {"type": "string"}}},  # missing schema_version
        {"schema_version": "not-a-semver", "fields": {}},  # unparseable version
        {"schema_version": "0.1.0"},  # missing fields
        {"schema_version": "0.1.0", "fields": {"task": {"type": "widget"}}},  # invalid type
        {"schema_version": "0.1.0", "fields": {"task": {"type": "string", "required": "yes"}}},  # required not bool
        {"schema_version": "0.1.0", "fields": {"task": "string"}},  # field spec not an object
    ],
)
def test_malformed_schema_is_fail_loud(bad):
    with pytest.raises(cg.CompatBreakError):
        cg.StateSchema.from_mapping(bad)


# --- Drift guard — the committed live schema is well-formed and self-consistent -


def test_live_schema_self_validates_and_partitions_its_namespace():
    """The checked-in state-schema.json parses, and its declared major is the same
    seam that partitions the durable-state namespace (R-20) — one source of truth,
    so the versioned schema and the coexistence namespace can never diverge."""
    live = cg.StateSchema.load(CONTAINER_DIR / cg.SCHEMA_FILENAME)
    assert live.fields, "the live schema must declare at least one field"

    # The schema's major partitions ~/.oaw/state/<major>/ — the exact namespace the
    # coexistence classifier (Story 3.3) and the mount resolver fence at.
    ns = ad.state_namespace(live.version.major, home="/home/ubuntu")
    assert ns.endswith(f"/.oaw/state/{live.version.major}")

    # Guarding the live schema against ITSELF is trivially shippable (identical).
    assert cg.assert_shippable(live, live).diff.change == cg.IDENTICAL


# --- End-to-end — the git-sourced wrapper trips red-first, then greens ----------

COMPAT_GUARD_SH = REPO_ROOT / "scripts" / "ci" / "compat-guard.sh"
SCHEMA_REL = "containers/oakandwave-workflow/state-schema.json"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo_with_schema(repo: Path, schema: dict) -> None:
    """A throwaway git repo carrying a committed baseline schema at the real path."""
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "compat guard test")
    dest = repo / SCHEMA_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(schema, indent=2))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "baseline schema")


def _run_guard(repo: Path, base_ref: str = "HEAD") -> subprocess.CompletedProcess:
    env = {**os.environ, "COMPAT_GUARD_REPO": str(repo), "COMPAT_GUARD_BASE_REF": base_ref}
    return subprocess.run(
        ["bash", str(COMPAT_GUARD_SH)],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_compat_guard_sh_blocks_breaking_minor_via_git_baseline(tmp_path):
    """IT-05 end-to-end (red-first): the wrapper sources the committed baseline
    from git, diffs the working-tree candidate, and BLOCKS a breaking change that
    only bumped the minor — then GREENS the identical break once it bumps the
    major. Proves the whole mechanism on real files through git, not just the
    pure function."""
    repo = tmp_path / "repo"
    repo.mkdir()
    baseline = {
        "schema_version": "0.1.0",
        "fields": {"task": {"type": "string"}, "cursor": {"type": "integer"}},
    }
    _init_repo_with_schema(repo, baseline)
    candidate_path = repo / SCHEMA_REL

    # RED: working tree drops `cursor` but bumps only the minor → guard trips (exit 2).
    candidate_path.write_text(
        json.dumps({"schema_version": "0.2.0", "fields": {"task": {"type": "string"}}})
    )
    red = _run_guard(repo)
    assert red.returncode == 2, red.stderr
    assert "BLOCKED" in red.stderr
    assert "major bump" in red.stderr

    # GREEN: the SAME break, now bumping the major → guard passes (exit 0).
    candidate_path.write_text(
        json.dumps({"schema_version": "1.0.0", "fields": {"task": {"type": "string"}}})
    )
    green = _run_guard(repo)
    assert green.returncode == 0, green.stderr
    assert green.stdout.strip() == "breaking"


@pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)
def test_compat_guard_sh_self_validates_when_no_baseline(tmp_path):
    """When the base ref has no schema (a first-ever add), the wrapper cannot diff;
    it self-validates the candidate only and passes — a new schema cannot break
    anything that never existed."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "compat guard test")
    # First commit does NOT contain the schema.
    (repo / "README.md").write_text("seed\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")
    first_commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()

    # Now add the schema in the working tree; diff against the schema-less commit.
    dest = repo / SCHEMA_REL
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps({"schema_version": "0.1.0", "fields": {"task": {"type": "string"}}})
    )
    result = _run_guard(repo, base_ref=first_commit)
    assert result.returncode == 0, result.stderr
    assert "self-validating" in result.stderr
