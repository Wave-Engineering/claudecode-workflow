#!/usr/bin/env python3
"""Quarantine + lossless rollback — Story 3.2 (#971), Plan #959, Dev Spec §4.6 / §5.7.

The remediation half of the flight surgeon. Story 3.1 (``scripts/flight-surgeon/
surgeon.py``) **detects and classifies** a broken ``:edge`` container and emits a
``should_quarantine`` verdict; this module **acts on that verdict** — it plans the
quarantine (stop → ``docker rm`` → recreate on ``:stable``) and, crucially, proves
the rollback is **lossless** *before* it authorises the destructive ``docker rm``.

Requirements this module is the guard for:

* **R-17** — WHEN the probe detects a broken container, THEN it shall quarantine it
  (stop + roll back to ``:stable``) **losslessly**. Realised as :func:`plan_quarantine`:
  it consumes the surgeon's ``should_quarantine`` verdict as its **only** trigger
  (refusing any container the surgeon did not flag — the documented §5.7 seam), then
  emits the ordered ``stop → rm → recreate-on-:stable`` plan.
* **R-02** — WHEN a container is removed and recreated, the system shall lose **no
  durable state**. This is not a hope — it is **mechanically asserted**:
  :func:`assert_lossless` proves every piece of durable RW state on the broken
  container lives on a **host-backed bind-mount** (which a ``docker rm`` cannot
  touch), and the recreate re-attaches those exact host sources by target. If the
  container carries durable RW state that is **not** host-backed (a docker-managed
  volume — the shape R-01 forbids), the plan **refuses** rather than proceed with a
  lossy ``rm``. Fail-loud toward *not* losing work (assertion-liveness, D7).

Why "lossless" is provable at all (Dev Spec §1.3 / §5.1 — the stateless-container
invariant, R-01): the container filesystem is a **disposable RTE**; all durable
state resides on host-backed mounts. So ``docker rm`` destroys only the writable
layer — every host-backed bind-mount *source* survives on the host untouched, and
recreation on ``:stable`` re-attaches the identical sources. Quarantine is a
``docker rm``, not an incident. This module's job is to keep that invariant honest
at the moment of the destructive step: it re-attaches the **entire** host-backed
mount set verbatim and swaps **only** the image ``:edge → :stable`` (the §5.6
rollback = repoint at the prior ``:stable`` digest).

Separation of concerns — this module **plans and asserts only**. It performs no
docker call itself (no ``stop`` / ``rm`` / ``run``): that is the wrapper
``scripts/ci/quarantine-container.sh``, which runs ``docker inspect`` to feed this
planner, then executes the plan it returns — keeping the logic in a unit-tested
module, never in the shell (project rule). The live seam (mapping an aoe sandbox
session to its container id, and the host→container stop path) is UNPROVEN against
a real sandbox (Dev Spec TC-7 / §5.N#5, exercised by MV-04); the pure planner below
is the story's canonical oracle (``tests/contained-workflow/test_quarantine.py``),
and the end-to-end zero-loss proof is E2E-03 / MV-05.

CLI::

    # plan a quarantine from a `docker inspect <cid>` dump + the resolved :stable ref
    docker inspect <cid> | python3 quarantine.py \\
        --container-inspect - --stable-ref REPO@sha256:… --should-quarantine

    # inspect just the ordered steps (human), or the full JSON plan for the wrapper
    python3 quarantine.py --container-inspect insp.json --stable-ref … \\
        --should-quarantine --format steps
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field

# The profile label the dogfood/dev-mode ring stamps (Story 4.1 / #974); the
# surgeon reads it to compute should_quarantine, and it is preserved verbatim onto
# the recreated container so the rebooted session keeps its ring identity.
PROFILE_LABEL_KEY = "oaw.profile"

# docker mount kinds (from `docker inspect .Mounts[].Type`).
BIND = "bind"
VOLUME = "volume"
TMPFS = "tmpfs"


class QuarantineError(ValueError):
    """A quarantine contract violation — most importantly, a rollback that could
    NOT be proven lossless. Raised LOUD, never swallowed: the whole point of the
    guard is to refuse a destructive ``rm`` it cannot make safe."""


# --- mount model (the lossless-invariant primitives) --------------------------


@dataclass(frozen=True)
class Mount:
    """One entry of a container's ``docker inspect .Mounts`` list.

    ``kind`` is the docker mount type; the lossless invariant keys off it — a
    ``bind`` is host-backed (its ``source`` is a host path that ``docker rm`` never
    touches), whereas a ``volume`` is docker-managed (a ``/var/lib/docker/volumes``
    path) and a ``tmpfs`` is in-memory. ``source.startswith('/')`` is true for a
    volume too, so host-backedness MUST key off ``kind == 'bind'``, never the path."""

    kind: str
    source: str
    target: str
    rw: bool

    @property
    def host_backed(self) -> bool:
        """A host-backed bind-mount: survives ``docker rm`` and is re-attachable by
        its host source on recreate. The ONLY durable-state shape R-01 permits."""
        return self.kind == BIND and self.source.startswith("/")

    @property
    def durable_risk(self) -> bool:
        """Durable RW state a ``docker rm`` cannot preserve re-attachably: a writable
        docker-managed ``volume`` (named or anonymous). It is NOT host-backed, so it
        breaks R-01 and cannot be re-mounted by host source on recreate — a lossy
        shape the planner must refuse. (A ``tmpfs`` is ephemeral by design; a ``ro``
        mount carries no work; a ``bind`` is host-backed and safe.)"""
        return self.rw and self.kind == VOLUME

    def to_docker_volume(self) -> str:
        """``docker run -v`` spec re-attaching this mount verbatim: ``src:tgt[:ro]``."""
        suffix = "" if self.rw else ":ro"
        return f"{self.source}:{self.target}{suffix}"


def parse_mount(obj: object) -> Mount:
    """Parse one ``docker inspect .Mounts[]`` element into a :class:`Mount`.

    Tolerant of the two spellings docker emits: modern ``.Mounts`` entries carry
    ``Type``/``Source``/``Destination``/``RW``; ``RW`` defaults to True when absent
    (docker omits it for rw). A missing ``Type`` is treated as ``bind`` only when a
    host ``Source`` is present, else ``volume`` (conservative — an unlabeled durable
    mount is assumed non-host-backed so the lossless guard errs toward refusing)."""
    if not isinstance(obj, dict):
        raise QuarantineError(f"mount must be an object, got {type(obj).__name__}")
    source = str(obj.get("Source", obj.get("source", "")) or "")
    target = str(obj.get("Destination", obj.get("Target", obj.get("target", ""))) or "")
    kind = str(obj.get("Type", obj.get("type", "")) or "").strip().lower()
    if not kind:
        kind = BIND if source.startswith("/") else VOLUME
    rw_raw = obj.get("RW", obj.get("rw", True))
    rw = bool(rw_raw) if isinstance(rw_raw, bool) else str(rw_raw).lower() != "false"
    return Mount(kind=kind, source=source, target=target, rw=rw)


@dataclass(frozen=True)
class Container:
    """The broken ``:edge`` container as seen from the host via ``docker inspect``."""

    id: str
    name: str
    image: str
    labels: dict[str, str] = field(default_factory=dict)
    mounts: tuple[Mount, ...] = ()

    @property
    def profile(self) -> str:
        """The container's ``oaw.profile`` ring label, or ``''`` if unlabeled."""
        return str(self.labels.get(PROFILE_LABEL_KEY, "") or "")


def parse_container(obj: object) -> Container:
    """Parse a ``docker inspect <cid>`` dump into a :class:`Container`.

    Accepts either the raw ``docker inspect`` **list** (takes the first element) or
    a single container object. Reads ``.Id`` / ``.Name`` / ``.Config.Image`` /
    ``.Config.Labels`` / ``.Mounts``. A dump with no container is a loud error —
    the wrapper must not have inspected a live container, and quarantining nothing
    would be a silent no-op the surgeon's fail-on-quarantine signal expects to act."""
    if isinstance(obj, list):
        if not obj:
            raise QuarantineError("docker inspect returned an empty list — no such container")
        obj = obj[0]
    if not isinstance(obj, dict):
        raise QuarantineError(f"container inspect must be an object, got {type(obj).__name__}")
    config = obj.get("Config") if isinstance(obj.get("Config"), dict) else {}
    labels = config.get("Labels") if isinstance(config.get("Labels"), dict) else {}
    raw_mounts = obj.get("Mounts") if isinstance(obj.get("Mounts"), list) else []
    name = str(obj.get("Name", "") or "").lstrip("/")
    return Container(
        id=str(obj.get("Id", obj.get("id", "")) or ""),
        name=name,
        image=str(config.get("Image", obj.get("Image", "")) or ""),
        labels={str(k): str(v) for k, v in labels.items()},
        mounts=tuple(parse_mount(m) for m in raw_mounts),
    )


# --- the lossless invariant (R-02 / R-01) -------------------------------------


def assert_lossless(container: Container) -> tuple[Mount, ...]:
    """Prove the quarantine will lose NO durable state, and return the host-backed
    mounts the recreate must re-attach (R-02).

    The proof (Dev Spec §5.1, R-01): every piece of durable RW state lives on a
    host-backed bind-mount, which ``docker rm`` cannot touch. So the check is: does
    the broken container hold any durable RW state that is **not** host-backed? Such
    state is a docker-managed ``volume`` (:attr:`Mount.durable_risk`) — durable, but
    not re-attachable by host source on recreate. If any exists, we **refuse** the
    quarantine (a lossy ``rm``) rather than strand work.

    Returns every host-backed bind-mount (rw *and* ro) — the full mount set the
    recreate re-attaches verbatim, so the session comes back up on ``:stable``
    identical but for the image."""
    risky = [m for m in container.mounts if m.durable_risk]
    if risky:
        targets = ", ".join(m.target or "?" for m in risky)
        raise QuarantineError(
            f"R-02/R-01 VIOLATION: cannot quarantine {container.name or container.id!r} "
            f"losslessly — it holds durable RW state on non-host-backed mount(s): "
            f"[{targets}]. A `docker rm` would strand these (a docker-managed volume "
            f"is not re-attachable by host source on recreate). The stateless-container "
            f"invariant (R-01) requires ALL durable state on host-backed bind-mounts; "
            f"refusing a lossy rm. Fix the container's mount manifest, then re-quarantine."
        )
    preserved = tuple(m for m in container.mounts if m.host_backed)
    return preserved


# --- the quarantine plan ------------------------------------------------------

STEP_STOP = "stop"
STEP_RM = "rm"
STEP_RECREATE = "recreate"


@dataclass(frozen=True)
class QuarantinePlan:
    """The ordered, verified quarantine: stop → rm → recreate-on-:stable, with the
    proof (preserved host-backed mounts) that it is lossless."""

    container_id: str
    name: str
    profile: str
    broken_image: str  # the :edge ref quarantined — held from promotion (feeds R-07)
    recreate_image: str  # the :stable ref recreated on — the §5.6 rollback target
    preserved_mounts: tuple[Mount, ...]
    labels: dict[str, str]

    @property
    def recreate_volume_args(self) -> tuple[str, ...]:
        """``docker run -v`` specs re-attaching every host-backed mount verbatim."""
        return tuple(m.to_docker_volume() for m in self.preserved_mounts)

    @property
    def steps(self) -> tuple[str, ...]:
        """The ordered destructive-then-recreate actions, as human-readable lines.

        The ``rm`` is deliberately WITHOUT ``-v``: even a stray (non-durable) volume
        must not be destroyed by the quarantine, and host binds are never docker's to
        remove — the destructive step touches ONLY the disposable writable layer."""
        cid = self.container_id or self.name
        n = len(self.preserved_mounts)
        return (
            f"{STEP_STOP}: docker stop {cid}  "
            f"(halt the broken :edge session; transcript already host-backed)",
            f"{STEP_RM}: docker rm {cid}  "
            f"(remove the disposable RTE — NO -v; all {n} durable mount(s) are "
            f"host-backed and survive)",
            f"{STEP_RECREATE}: docker run --label {PROFILE_LABEL_KEY}={self.profile or 'unknown'} "
            f"{' '.join('-v ' + v for v in self.recreate_volume_args)} {self.recreate_image}  "
            f"(recreate on :stable, re-attaching the identical host sources — §5.6 rollback)",
        )

    def as_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "name": self.name,
            "profile": self.profile,
            "broken_image": self.broken_image,
            "recreate_image": self.recreate_image,
            "recreate_volume_args": list(self.recreate_volume_args),
            "preserved_mounts": [
                {"source": m.source, "target": m.target, "mode": "rw" if m.rw else "ro"}
                for m in self.preserved_mounts
            ],
            "labels": self.labels,
            "steps": list(self.steps),
        }

    def quarantine_record(self) -> dict:
        """The telemetry the promotion gate's ``quarantines`` condition reads (R-07):
        a quarantine occurred, so the quarantined ``:edge`` digest is **held from
        promotion**. The wrapper appends this to the quarantine ledger the gate
        queries; a non-zero count fails the gate (``promotion_gate.py``)."""
        return {
            "event": "quarantine",
            "container_id": self.container_id,
            "name": self.name,
            "profile": self.profile,
            "held_digest": self.broken_image,
            "recreated_on": self.recreate_image,
            "durable_mounts_preserved": len(self.preserved_mounts),
        }

    def summary(self) -> str:
        head = (
            f"quarantine {self.name or self.container_id} "
            f"({self.broken_image} -> :stable {self.recreate_image}): "
            f"LOSSLESS — {len(self.preserved_mounts)} host-backed mount(s) preserved"
        )
        return head + "\n" + "\n".join(f"  {i + 1}. {s}" for i, s in enumerate(self.steps))


def plan_quarantine(
    *,
    container: Container,
    stable_ref: str,
    should_quarantine: bool,
) -> QuarantinePlan:
    """Plan a lossless quarantine + rollback for a broken ``:edge`` container (R-17).

    ``should_quarantine`` is the flight surgeon's authoritative verdict and the
    **only** trigger: this refuses any container the surgeon did not flag (a healthy
    container, or a dev-mode breakage the surgeon excluded per R-22). The planner
    does **not** re-derive detection or the profile filter — that is the surgeon's
    job, already done (Dev Spec §5.7 seam); it acts on the verdict and owns the
    **mechanics + the lossless proof**.

    Guards (each fail-loud):

    * ``should_quarantine`` must be True — never quarantine an unflagged container.
    * :func:`assert_lossless` — every durable RW mount is host-backed, or refuse.
    * ``stable_ref`` must differ from the broken image — recreating on the same
      broken ``:edge`` digest is not a rollback (it would re-break immediately).
    """
    if not should_quarantine:
        raise QuarantineError(
            f"refusing to quarantine {container.name or container.id!r}: the flight "
            f"surgeon did not flag it (should_quarantine=False). Quarantine acts ONLY "
            f"on the surgeon's verdict — a healthy container, or a dev-mode breakage "
            f"excluded per R-22, is never quarantined."
        )
    stable = str(stable_ref or "").strip()
    if not stable:
        raise QuarantineError("stable_ref is required — the :stable rollback target to recreate on")

    preserved = assert_lossless(container)

    if stable == container.image.strip():
        raise QuarantineError(
            f"recreate target {stable!r} equals the broken image — a rollback must "
            f"recreate on :stable, not the same broken :edge digest (it would re-break). "
            f"Resolve :stable to its promoted digest first (never the quarantined one)."
        )

    return QuarantinePlan(
        container_id=container.id,
        name=container.name,
        profile=container.profile,
        broken_image=container.image.strip(),
        recreate_image=stable,
        preserved_mounts=preserved,
        labels=dict(container.labels),
    )


# --- CLI ----------------------------------------------------------------------


def _load_inspect(path: str) -> object:
    text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    return json.loads(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--container-inspect",
        required=True,
        metavar="FILE",
        help="`docker inspect <cid>` JSON of the broken container ('-' for stdin)",
    )
    parser.add_argument(
        "--stable-ref",
        required=True,
        help="the resolved :stable image ref to recreate on (the §5.6 rollback target)",
    )
    parser.add_argument(
        "--should-quarantine",
        action="store_true",
        help="the flight surgeon's verdict — REQUIRED; without it the planner refuses "
        "(quarantine acts only on the surgeon's should_quarantine)",
    )
    parser.add_argument(
        "--format",
        choices=("json", "steps", "record"),
        default="json",
        help="stdout shape: full JSON plan (default), the ordered steps, or the "
        "gate-facing quarantine record",
    )
    args = parser.parse_args(argv)

    try:
        container = parse_container(_load_inspect(args.container_inspect))
        plan = plan_quarantine(
            container=container,
            stable_ref=args.stable_ref,
            should_quarantine=args.should_quarantine,
        )
    except (QuarantineError, json.JSONDecodeError, OSError) as exc:
        print(f"quarantine error: {exc}", file=sys.stderr)
        return 2

    print(plan.summary(), file=sys.stderr)
    if args.format == "steps":
        print("\n".join(plan.steps))
    elif args.format == "record":
        print(json.dumps(plan.quarantine_record()))
    else:
        print(json.dumps(plan.as_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
