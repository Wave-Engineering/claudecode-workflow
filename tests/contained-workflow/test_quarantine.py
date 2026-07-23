"""Oracle for Story 3.2 (#971) — quarantine + lossless rollback (E2E-03, R-02/R-17).

The remediation half of the flight surgeon: Story 3.1 (test_surgeon.py) proves the
probe DETECTS a broken ``:edge`` container and emits ``should_quarantine``; this
module proves the ACTION on that verdict — stop → ``docker rm`` → recreate on
``:stable`` — is **lossless**.

The authoritative end-to-end proof is E2E-03 itself: plant a broken ``:edge``,
confirm the surgeon detects it and the quarantine rolls back to ``:stable`` with
durable state intact. The full lifecycle needs a real ``:edge`` + ``:stable`` image
pair (mirrors test_throwaway_ci_ring.py / test_ownership.py), so it cannot run in
the stock pytest lane. This module proves, **hermetically**, the properties that
make the quarantine correct — and a docker-gated branch runs the real
stop/rm/recreate and asserts on-disk durable state survives:

* **AC1 [R-02, R-17]** — a planted broken ``:edge`` is quarantined and recreated on
  ``:stable`` with **zero work lost**. The named story oracle
  :func:`test_lossless_rollback_preserves_host_backed_work` proves the plan
  re-attaches every host-backed mount verbatim and swaps only the image; the
  docker-gated :func:`test_e2e03_real_rollback_preserves_on_disk_work` proves a real
  ``docker rm`` + recreate leaves the host file intact.
* The **lossless invariant is mechanical, not a hope**:
  :func:`test_refuses_non_host_backed_durable_state` shows the planner **refuse** a
  lossy ``rm`` red-first when durable RW state is not host-backed.
* The **surgeon verdict is the only trigger**:
  :func:`test_consumes_surgeon_should_quarantine_verdict` drives the real surgeon →
  quarantine seam, and :func:`test_dev_mode_breakage_is_never_quarantined` proves a
  dev-mode breakage (R-22) is refused.

MV-05 (the manual zero-loss run on a real container + host) is documented in
``docs/contained-workflow/manual-verification.md``.
"""

from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
QUAR_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"
QUAR_PY = QUAR_DIR / "quarantine.py"
SURGEON_DIR = REPO_ROOT / "scripts" / "flight-surgeon"
WRAPPER = REPO_ROOT / "scripts" / "ci" / "quarantine-container.sh"

# Path-style import (no PYTHONPATH dependency), mirroring test_surgeon.py.
sys.path.insert(0, str(QUAR_DIR))
sys.path.insert(0, str(SURGEON_DIR))
import quarantine as q  # noqa: E402
import surgeon as fs  # noqa: E402


# --- fixtures -----------------------------------------------------------------


def make_inspect(
    *,
    cid: str = "edge123",
    name: str = "dogbox",
    image: str = "ghcr.io/wave-engineering/oakandwave-workflow:edge",
    profile: str = "dogfood",
    mounts: list[dict] | None = None,
) -> list[dict]:
    """A ``docker inspect <cid>`` dump (list form) for a dogfood ``:edge`` container.

    Default mounts model the real state taxonomy (§5.3): a host-backed rw memory
    bind (durable work), a host-backed rw workspace bind, and a ro secrets bind.
    All host-backed — so a ``docker rm`` loses nothing."""
    if mounts is None:
        mounts = [
            {
                "Type": "bind",
                "Source": "/home/bakerb/.oaw/state/8/memory",
                "Destination": "/home/ubuntu/.oaw/state/8/memory",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/home/bakerb/work/dogbox",
                "Destination": "/workspace",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": "/home/bakerb/.secrets",
                "Destination": "/home/ubuntu/.secrets",
                "RW": False,
            },
        ]
    return [
        {
            "Id": cid,
            "Name": f"/{name}",
            "Config": {"Image": image, "Labels": {"oaw.profile": profile}},
            "Mounts": mounts,
        }
    ]


STABLE = "ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "a" * 64


def looping_transcript(n: int = 6) -> list[dict]:
    """A transcript whose tail is the SAME tool action repeated ``n`` times — a
    'no forward progress' loop the surgeon classifies broken while running."""
    block = {"type": "tool_use", "name": "Bash", "input": {"command": "ls"}}
    return [{"message": {"content": [dict(block)]}} for _ in range(n)]


# --- AC1: lossless rollback (the named story oracle) --------------------------


def test_lossless_rollback_preserves_host_backed_work() -> None:
    """E2E-03 / AC1 [R-02, R-17]: a broken :edge is quarantined and recreated on
    :stable with zero work lost.

    The 'zero work lost' proof, mechanically: the plan re-attaches EVERY host-backed
    mount (memory, workspace, secrets) verbatim — same source→target, same mode —
    and swaps ONLY the image :edge → :stable. Since all durable state is host-backed
    (R-01), the docker rm between stop and recreate cannot touch it."""
    container = q.parse_container(make_inspect())
    plan = q.plan_quarantine(container=container, stable_ref=STABLE, should_quarantine=True)

    # Recreated on :stable — the rollback target, not the broken :edge.
    assert plan.recreate_image == STABLE
    assert plan.broken_image.endswith(":edge")

    # Every host-backed mount is preserved verbatim (source:target[:ro]).
    reattached = set(plan.recreate_volume_args)
    assert "/home/bakerb/.oaw/state/8/memory:/home/ubuntu/.oaw/state/8/memory" in reattached
    assert "/home/bakerb/work/dogbox:/workspace" in reattached
    assert "/home/bakerb/.secrets:/home/ubuntu/.secrets:ro" in reattached
    assert len(plan.preserved_mounts) == 3

    # The bad :edge digest is held from promotion (feeds the gate's R-07 condition).
    rec = plan.quarantine_record()
    assert rec["event"] == "quarantine"
    assert rec["held_digest"] == plan.broken_image
    assert rec["recreated_on"] == STABLE
    assert rec["durable_mounts_preserved"] == 3


def test_rm_step_is_without_dash_v() -> None:
    """The destructive step is ``docker rm`` WITHOUT ``-v``: it removes only the
    disposable writable layer. ``-v`` would destroy anonymous volumes — belt-and-
    suspenders even though the lossless guard already refuses durable volumes."""
    container = q.parse_container(make_inspect())
    plan = q.plan_quarantine(container=container, stable_ref=STABLE, should_quarantine=True)
    rm_step = next(s for s in plan.steps if s.startswith("rm:"))
    assert "docker rm " in rm_step
    assert "docker rm -v" not in rm_step
    assert "rm --volumes" not in rm_step


def test_profile_label_preserved_on_recreate() -> None:
    """The container's ring label is carried onto the recreate so the rebooted
    session keeps its dogfood/dev-mode identity (feeds the surgeon's R-22 filter)."""
    container = q.parse_container(make_inspect(profile="dogfood"))
    plan = q.plan_quarantine(container=container, stable_ref=STABLE, should_quarantine=True)
    assert plan.profile == "dogfood"
    recreate_step = next(s for s in plan.steps if s.startswith("recreate:"))
    assert "oaw.profile=dogfood" in recreate_step


# --- the lossless invariant is mechanical (red-first refusals) ----------------


def test_refuses_non_host_backed_durable_state() -> None:
    """RED-FIRST [R-02/R-01]: durable RW state on a docker-managed volume (NOT
    host-backed) means a ``docker rm`` would strand it — the planner REFUSES the
    lossy rm rather than lose work. This is the guard that makes 'lossless' a
    proof, not a hope."""
    mounts = [
        {"Type": "bind", "Source": "/home/bakerb/work", "Destination": "/workspace", "RW": True},
        # A named docker volume holding RW state — durable but NOT host-backed.
        {"Type": "volume", "Source": "/var/lib/docker/volumes/scratch/_data",
         "Destination": "/data", "RW": True},
    ]
    container = q.parse_container(make_inspect(mounts=mounts))
    with pytest.raises(q.QuarantineError, match="R-02/R-01 VIOLATION"):
        q.plan_quarantine(container=container, stable_ref=STABLE, should_quarantine=True)


def test_tmpfs_and_readonly_volume_are_not_a_loss_risk() -> None:
    """Only durable RW state that isn't host-backed is a risk. A tmpfs (ephemeral by
    design) and a RO volume (carries no work) are NOT — the quarantine proceeds."""
    mounts = [
        {"Type": "bind", "Source": "/home/bakerb/work", "Destination": "/workspace", "RW": True},
        {"Type": "tmpfs", "Source": "", "Destination": "/tmp", "RW": True},
        {"Type": "volume", "Source": "/var/lib/docker/volumes/ro/_data",
         "Destination": "/ro", "RW": False},
    ]
    container = q.parse_container(make_inspect(mounts=mounts))
    plan = q.plan_quarantine(container=container, stable_ref=STABLE, should_quarantine=True)
    # Only the host-backed bind is re-attached; tmpfs/volume are dropped.
    assert plan.recreate_volume_args == ("/home/bakerb/work:/workspace",)


def test_refuses_unflagged_container() -> None:
    """The surgeon's verdict is the ONLY trigger: a container the surgeon did not
    flag (should_quarantine=False) is never quarantined."""
    container = q.parse_container(make_inspect())
    with pytest.raises(q.QuarantineError, match="did not flag"):
        q.plan_quarantine(container=container, stable_ref=STABLE, should_quarantine=False)


def test_refuses_recreate_on_the_same_broken_digest() -> None:
    """A rollback recreates on :stable, never on the same broken :edge digest —
    that would re-break immediately. Refused fail-loud."""
    same = "ghcr.io/wave-engineering/oakandwave-workflow@sha256:" + "b" * 64
    container = q.parse_container(make_inspect(image=same))
    with pytest.raises(q.QuarantineError, match="equals the broken image"):
        q.plan_quarantine(container=container, stable_ref=same, should_quarantine=True)


def test_missing_stable_ref_is_loud() -> None:
    container = q.parse_container(make_inspect())
    with pytest.raises(q.QuarantineError, match="stable_ref is required"):
        q.plan_quarantine(container=container, stable_ref="  ", should_quarantine=True)


# --- parsing robustness -------------------------------------------------------


def test_parses_docker_inspect_list_and_single_forms() -> None:
    """Accepts both the raw ``docker inspect`` list and a single container object,
    reading Id/Name/Config.Image/Labels/Mounts; the leading '/' on Name is stripped."""
    as_list = q.parse_container(make_inspect(cid="c1", name="dogbox"))
    as_single = q.parse_container(make_inspect(cid="c1", name="dogbox")[0])
    assert as_list == as_single
    assert as_list.id == "c1"
    assert as_list.name == "dogbox"  # '/' stripped
    assert as_list.profile == "dogfood"


def test_empty_inspect_is_loud() -> None:
    """An empty inspect (no such container) is a loud error, never a silent no-op —
    the surgeon's fail-on-quarantine signal expects an action to have occurred."""
    with pytest.raises(q.QuarantineError, match="no such container"):
        q.parse_container([])


def test_rw_defaults_true_when_docker_omits_it() -> None:
    """docker omits ``RW`` for a rw mount; a bind with no RW key is rw (host-backed,
    preserved), not misread as ro."""
    m = q.parse_mount({"Type": "bind", "Source": "/h/x", "Destination": "/x"})
    assert m.rw is True and m.host_backed is True


def test_module_is_kit_independent() -> None:
    """Like the surgeon (R-15), the planner runs host-side and imports ONLY the
    standard library — a broken container's kit can never shape the rollback plan."""
    tree = ast.parse(QUAR_PY.read_text())
    stdlib = {
        "argparse", "json", "sys", "dataclasses", "__future__",
        "os", "pathlib", "typing", "collections", "re",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert imported <= stdlib, f"non-stdlib imports: {imported - stdlib}"


# --- the surgeon -> quarantine seam (real integration) ------------------------


def test_consumes_surgeon_should_quarantine_verdict() -> None:
    """The seam end-to-end: the REAL surgeon classifies a running+looping dogfood
    container broken → should_quarantine=True → the quarantine plans the rollback.
    Detection (3.1) and action (3.2) are wired through the same verdict."""
    verdict = fs.assess(
        container_id="edge123",
        title="dogbox",
        status="running",
        profile="dogfood",
        entries=looping_transcript(),
    )
    assert verdict.should_quarantine is True

    container = q.parse_container(make_inspect(cid="edge123"))
    plan = q.plan_quarantine(
        container=container, stable_ref=STABLE, should_quarantine=verdict.should_quarantine
    )
    assert plan.recreate_image == STABLE
    assert plan.container_id == "edge123"


def test_dev_mode_breakage_is_never_quarantined() -> None:
    """[R-22] via the real surgeon: a dev-mode container that is BROKEN (running +
    looping) is classified broken but should_quarantine=False — and the quarantine
    then REFUSES it. A dev-mode breakage never trips the destructive rollback."""
    verdict = fs.assess(
        container_id="dev1",
        title="devbox",
        status="running",
        profile="dev-mode",
        entries=looping_transcript(),
    )
    assert verdict.health.broken is True
    assert verdict.should_quarantine is False

    container = q.parse_container(make_inspect(cid="dev1", profile="dev-mode"))
    with pytest.raises(q.QuarantineError, match="did not flag"):
        q.plan_quarantine(
            container=container, stable_ref=STABLE, should_quarantine=verdict.should_quarantine
        )


# --- the shell wrapper's plumbing (hermetic, via dry-run + injected seams) ----


def test_wrapper_dry_run_emits_the_plan_without_docker() -> None:
    """The wrapper wires to the planner: with QUARANTINE_DRY_RUN + the injected
    inspect/stable seams it resolves the full plan and would stop/rm/recreate — with
    NO docker call. Proves the shell plumbing hermetically (the real stop/rm/recreate
    is the docker-gated test below)."""
    if not os.access(WRAPPER, os.X_OK):
        pytest.skip("wrapper not executable")
    inspect_file = QUAR_DIR / ".pytest-inspect.json"  # written+removed in-test
    try:
        inspect_file.write_text(json.dumps(make_inspect()))
        env = dict(os.environ)
        env.update(
            CONTAINER_ID="edge123",
            SHOULD_QUARANTINE="true",
            QUARANTINE_DRY_RUN="true",
            OAW_CONTAINER_INSPECT=str(inspect_file),
            OAW_STABLE_RESOLVED_REF=STABLE,
        )
        proc = subprocess.run(
            ["bash", str(WRAPPER)], capture_output=True, text=True, env=env, timeout=60
        )
    finally:
        inspect_file.unlink(missing_ok=True)
    assert proc.returncode == 0, proc.stderr
    assert "[dry-run]" in proc.stdout
    plan = json.loads(proc.stdout[proc.stdout.index("{"):])
    assert plan["recreate_image"] == STABLE
    assert "/home/bakerb/work/dogbox:/workspace" in plan["recreate_volume_args"]


def test_wrapper_refuses_without_surgeon_verdict() -> None:
    """The wrapper mirrors the planner's refusal up front: no SHOULD_QUARANTINE=true
    ⇒ abort, never quarantine a container the surgeon did not flag."""
    if not os.access(WRAPPER, os.X_OK):
        pytest.skip("wrapper not executable")
    env = dict(os.environ)
    env.update(CONTAINER_ID="edge123", QUARANTINE_DRY_RUN="true", OAW_STABLE_RESOLVED_REF=STABLE)
    env.pop("SHOULD_QUARANTINE", None)
    proc = subprocess.run(
        ["bash", str(WRAPPER)], capture_output=True, text=True, env=env, timeout=60
    )
    assert proc.returncode != 0
    assert "SHOULD_QUARANTINE" in proc.stderr


# --- E2E-03 docker-gated: the REAL zero-loss mechanic (self-skips) ------------


def _skip_or_fail(msg: str, require: bool) -> None:
    if require:
        pytest.fail(msg + " (OAKANDWAVE_REQUIRE_IMAGE set)")
    pytest.skip(msg)


def _pick_local_image(docker: str) -> str | None:
    """The smallest already-present local image to stand in for :edge/:stable — we
    never PULL (mirrors test_ownership.py: absence self-skips, not a network fetch).
    ``sleep`` (used to keep the container up) is universal across these bases."""
    for ref in (
        os.environ.get("OAKANDWAVE_IMAGE", ""),
        "oakandwave-workflow:edge",
        "busybox:latest",
        "busybox",
        "alpine:latest",
        "alpine",
    ):
        if ref and subprocess.run(
            [docker, "image", "inspect", ref], capture_output=True
        ).returncode == 0:
            return ref
    return None


def test_e2e03_real_rollback_preserves_on_disk_work(tmp_path: Path) -> None:
    """E2E-03 [R-02, R-17]: a REAL container with a host-backed bind holding work is
    quarantined (stop → docker rm → recreate on a distinct :stable image) and the
    on-disk work SURVIVES — the concrete zero-loss proof. Self-skips without docker
    or a local image; OAKANDWAVE_REQUIRE_IMAGE makes absence a hard failure (CI)."""
    docker = shutil.which("docker")
    require = bool(os.environ.get("OAKANDWAVE_REQUIRE_IMAGE"))
    if docker is None:
        _skip_or_fail("docker binary not found on PATH", require)
    base = _pick_local_image(docker)
    if base is None:
        _skip_or_fail("no local image to stand in for :edge/:stable", require)

    # Distinct :edge / :stable tags off the base so broken_image != recreate target.
    tag = f"oaw-quarantine-test-{uuid.uuid4().hex[:8]}"
    edge_ref, stable_ref = f"{tag}:edge", f"{tag}:stable"
    work = tmp_path / "memory"
    work.mkdir()
    (work / "durable-work.txt").write_text("zero-work-lost")
    os.chmod(tmp_path, 0o777)
    os.chmod(work, 0o777)

    name = f"quar-{uuid.uuid4().hex[:8]}"
    created: list[str] = []
    try:
        for ref in (edge_ref, stable_ref):
            assert subprocess.run(
                [docker, "tag", base, ref], capture_output=True
            ).returncode == 0, f"could not tag {base} -> {ref}"

        # Plant the "broken :edge": a container with the work bind-mounted host-backed.
        run = subprocess.run(
            [docker, "run", "-d", "--name", name, "--label", "oaw.profile=dogfood",
             "-v", f"{work}:/work", edge_ref, "sleep", "300"],
            capture_output=True, text=True, timeout=120,
        )
        assert run.returncode == 0, run.stderr
        created.append(name)
        edge_cid = run.stdout.strip()

        # Inspect → plan (the lossless proof runs here, before any rm).
        insp = subprocess.run(
            [docker, "inspect", edge_cid], capture_output=True, text=True, timeout=60
        )
        assert insp.returncode == 0, insp.stderr
        container = q.parse_container(json.loads(insp.stdout))
        plan = q.plan_quarantine(
            container=container, stable_ref=stable_ref, should_quarantine=True
        )
        assert f"{work}:/work" in plan.recreate_volume_args

        # Apply the quarantine: stop → rm (NO -v) → recreate on :stable.
        subprocess.run([docker, "stop", edge_cid], capture_output=True, timeout=60)
        subprocess.run([docker, "rm", edge_cid], capture_output=True, timeout=60, check=True)
        recreate = [docker, "run", "-d", "--name", name, "--label", f"oaw.profile={plan.profile}"]
        for v in plan.recreate_volume_args:
            recreate += ["-v", v]
        recreate += [stable_ref, "sleep", "300"]
        rerun = subprocess.run(recreate, capture_output=True, text=True, timeout=120)
        assert rerun.returncode == 0, rerun.stderr
        new_cid = rerun.stdout.strip()

        # Zero work lost: the host-backed file survived the rm + recreate untouched.
        assert (work / "durable-work.txt").read_text() == "zero-work-lost"
        # The new container runs on :stable and re-attached the same host source.
        img = subprocess.run(
            [docker, "inspect", "--format", "{{.Config.Image}}", new_cid],
            capture_output=True, text=True, timeout=60,
        ).stdout.strip()
        assert img == stable_ref
    finally:
        for cid in (name,):
            subprocess.run([docker, "rm", "-f", cid], capture_output=True)
        for ref in (edge_ref, stable_ref):
            subprocess.run([docker, "rmi", ref], capture_output=True)
