#!/usr/bin/env python3
"""Rolling per-agent :stable adoption — Story 2.4 (#969), Plan #959, Dev Spec §4.5 / §5.8.

The counterpart to the promotion gate (Story 2.3): 2.3 *publishes* :stable by
retagging the exact tested digest; this module decides how a **fleet agent
adopts** that :stable — per-agent, rolling, at container-recreate, never
mid-session (R-08), with same-major coexistence (R-18).

Requirements this module is the guard for:

* **R-08** — WHEN a minor/patch :stable is published, the fleet adopts it
  per-agent at container-recreate, **NOT by synchronized flip**. Adoption is a
  pure decision evaluated against **this** agent's currently-running version at
  **its own** recreate boundary; there is no fleet broadcast and no code path
  that mutates a *running* container. A running container is pinned by digest, so
  a :stable retag can never reach it — only the next recreate resolves the moving
  tag and consumes this decision. Each agent adopts when *it* recreates:
  rolling, per-agent, never a stop-the-world flip.

* **R-18** — agents on the same major interoperate over shared state; within-major
  shared-state changes are additive + forward-tolerant. The kit major partitions
  the durable-state namespace (``~/.oaw/state/<major>/``, R-20 — the same seam the
  mount resolver enforces), so an updated agent (new minor) and a not-yet-updated
  agent (old minor) resolve the **same** namespace and coexist; different majors
  resolve **different** namespaces (isolated, never corrupting). A **major** cross
  is therefore never auto-adopted at recreate — it is an opt-in, deliberate cross
  (§5.8: the developer decides when to cross a major).

Design — one auto-adopt path, fail-loud (assertion-liveness, D7):

* :func:`decide_adoption` is the **only** path that yields an ``adopt`` verdict,
  and it does so ONLY for a same-major target. A different major ``hold``s unless
  the caller explicitly opts into the cross. A malformed version is an
  :class:`AdoptionError`, never silently skipped.
* The module never touches docker, a registry, or the network — it reasons purely
  over the ``(current, target)`` version pair handed to it. Resolving :stable to
  its digest + version and performing the recreate live in the wrapper
  (``scripts/ci/adopt-stable.sh``).

CLI::

    # decide (versions only): prints the verdict summary to stderr, action to stdout
    python3 adoption.py --current-version 8.2.0 --target-version 8.3.0

    # plan a recreate (with digests): stdout is the digest to launch at recreate
    python3 adoption.py --current-ref REPO@sha256:… --current-version 8.2.0 \\
        --target-ref REPO@sha256:… --target-version 8.3.0 --format json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import PurePosixPath

# The sandbox-scoped durable-state root, major-partitioned (R-20). This is the
# SAME seam the mount resolver fences at (mount_resolver.STATE_ROOT_PARTS); a
# colocated test asserts the two agree so the coexistence namespace and the mount
# guard can never drift apart.
STATE_ROOT_PARTS = (".oaw", "state")  # ~/.oaw/state/<major>/

# Verdicts. `adopt` is the only one that moves the agent onto :stable.
ADOPT = "adopt"
NOOP = "noop"
HOLD = "hold"

# Coexistence classes for a (running, other) version pair.
SHARED_COMPATIBLE = "shared-compatible"  # same major — one namespace, additive/forward-tolerant
ISOLATED = "isolated"  # different major — separate namespaces, isolated not corrupting

# A bare/tagged semver: major.minor.patch with an optional -prerelease / +build.
_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:[-+](?P<pre>[0-9A-Za-z.-]+))?$")
# A content-addressed digest ref carries no semver — the caller must read the
# image's OCI version label instead of parsing the ref.
_DIGEST_RE = re.compile(r"@sha256:[0-9a-fA-F]{64}$")


class AdoptionError(ValueError):
    """An adoption-decision contract violation. Raised LOUD, never swallowed."""


@dataclass(frozen=True, order=True)
class SemVer:
    """A (major, minor, patch) triple. Ordering compares only those three;
    prerelease/build metadata is retained for display but excluded from ordering
    (a promotion within a major is decided by the triple, per §5.8)."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = field(default=None, compare=False)

    def __str__(self) -> str:
        base = f"{self.major}.{self.minor}.{self.patch}"
        return f"{base}-{self.prerelease}" if self.prerelease else base

    @property
    def triple(self) -> tuple[int, int, int]:
        return (self.major, self.minor, self.patch)


def parse_semver(value: object) -> SemVer:
    """Parse a semver from a bare version (``8.2.0``, ``v8.2.0``, ``0.0.0-dev``)
    or a tagged image ref (``registry/img:8.2.0``). A digest ref (``…@sha256:…``)
    carries no semver and is rejected — read the OCI version label instead.

    Raises :class:`AdoptionError` on anything unparseable (fail-loud — a version
    the fleet cannot reason about must never be silently adopted)."""
    if isinstance(value, SemVer):
        return value
    if not isinstance(value, str) or not value.strip():
        raise AdoptionError(f"version must be a non-empty semver string, got {value!r}")
    s = value.strip()
    if _DIGEST_RE.search(s):
        raise AdoptionError(
            f"cannot parse a semver from the digest ref {s!r} — a digest carries "
            f"no version; read the image's org.opencontainers.image.version label"
        )
    # If it's a tagged ref (has a '/' path then a ':tag'), take the tag part.
    tail = s.rsplit("/", 1)[-1]
    if ":" in tail:
        s = tail.rsplit(":", 1)[-1]
    s = s.lstrip("v")
    m = _SEMVER_RE.match(s)
    if not m:
        raise AdoptionError(
            f"unparseable semver {value!r} — expected major.minor.patch "
            f"(optionally -prerelease), e.g. 8.3.0 or a registry/img:8.3.0 tag"
        )
    return SemVer(int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group("pre"))


def classify_coexistence(a: object, b: object) -> str:
    """Classify how two agents' versions share durable state (R-18/R-20).

    Same major ⇒ ``shared-compatible`` (one ``~/.oaw/state/<major>/`` namespace,
    within-major changes additive + forward-tolerant, so updated and
    not-yet-updated agents coexist). Different major ⇒ ``isolated`` (separate
    namespaces — mixing majors is isolated, never corrupting)."""
    va, vb = parse_semver(a), parse_semver(b)
    return SHARED_COMPATIBLE if va.major == vb.major else ISOLATED


def state_namespace(major: int | str, home: str | PurePosixPath = "~") -> str:
    """The major-partitioned durable-state namespace ``<home>/.oaw/state/<major>/``.

    The coexistence primitive: two agents map to the same namespace iff they share
    a major. Mirrors the path the mount resolver's R-03 guard fences to."""
    try:
        m = int(str(major).split(".", 1)[0])
    except ValueError as exc:
        raise AdoptionError(f"major must be an int or semver, got {major!r}") from exc
    root = PurePosixPath(str(home))
    return str(root.joinpath(*STATE_ROOT_PARTS, str(m)))


@dataclass(frozen=True)
class AdoptionDecision:
    """The per-agent adoption verdict for (current → target) at recreate."""

    action: str  # adopt | noop | hold
    current: SemVer
    target: SemVer
    coexistence: str  # shared-compatible | isolated
    reason: str

    @property
    def adopt(self) -> bool:
        return self.action == ADOPT

    def as_dict(self) -> dict:
        return {
            "action": self.action,
            "current": str(self.current),
            "target": str(self.target),
            "coexistence": self.coexistence,
            "reason": self.reason,
        }

    def summary(self) -> str:
        verb = {
            ADOPT: "ADOPT at recreate",
            NOOP: "NOOP — already current",
            HOLD: "HOLD on current major",
        }.get(self.action, self.action)
        return (
            f"adoption {self.current} -> {self.target}: {verb}\n"
            f"  coexistence: {self.coexistence}\n"
            f"  reason: {self.reason}"
        )


def decide_adoption(
    current: object,
    target: object,
    *,
    allow_major_cross: bool = False,
) -> AdoptionDecision:
    """Decide, for THIS agent, whether to adopt ``target`` (:stable) at its next
    container-recreate — the single auto-adopt path (R-08).

    * Same triple ⇒ ``noop`` (already on this :stable).
    * Same major, different minor/patch ⇒ ``adopt`` at recreate — a minor/patch
      bump, safe by same-major compat (R-18). This is the rolling, per-agent
      adoption: it follows :stable in either direction (a rollback publishes a
      prior digest to :stable; the agent adopts it at *its* next recreate).
    * Different major ⇒ ``hold`` unless ``allow_major_cross`` — a major cross is
      opt-in and deliberate (§5.8), never an automatic recreate-time flip. The two
      agents coexist in isolated ``~/.oaw/state/<major>/`` namespaces meanwhile.

    Malformed versions raise :class:`AdoptionError` (fail-loud)."""
    cur = parse_semver(current)
    tgt = parse_semver(target)
    coex = classify_coexistence(cur, tgt)

    if tgt.triple == cur.triple:
        return AdoptionDecision(
            NOOP, cur, tgt, coex,
            f"already on :stable {tgt}; nothing to adopt at recreate",
        )
    if tgt.major == cur.major:
        direction = "upgrade" if tgt.triple > cur.triple else "rollback"
        return AdoptionDecision(
            ADOPT, cur, tgt, coex,
            f"same-major minor/patch {direction} ({cur} -> {tgt}) — adopt at the "
            f"next container-recreate (rolling, per-agent; never mid-session). "
            f"Same-major compat (R-18) lets it coexist with agents still on {cur}",
        )
    if allow_major_cross:
        return AdoptionDecision(
            ADOPT, cur, tgt, coex,
            f"major cross {cur.major} -> {tgt.major} explicitly opted in (§5.8); "
            f"the agent moves to the isolated {state_namespace(tgt.major)} namespace",
        )
    return AdoptionDecision(
        HOLD, cur, tgt, coex,
        f"target major {tgt.major} != current major {cur.major}: a major cross is "
        f"opt-in and deliberate (§5.8), never an automatic recreate-time flip. "
        f"Agents on {cur.major} and {tgt.major} coexist in isolated namespaces "
        f"({state_namespace(cur.major)} vs {state_namespace(tgt.major)})",
    )


@dataclass(frozen=True)
class RecreatePlan:
    """What the recreate wrapper should launch, and what to keep for rollback."""

    action: str  # adopt | noop | hold
    launch_ref: str  # the image ref to run at recreate
    prior_ref: str  # the ref the agent was on — retained so rollback is a repoint
    decision: AdoptionDecision

    def as_dict(self) -> dict:
        d = self.decision.as_dict()
        d.update(launch_ref=self.launch_ref, prior_ref=self.prior_ref)
        return d


def plan_recreate(
    *,
    current_ref: str,
    current_version: object,
    target_ref: str,
    target_version: object,
    allow_major_cross: bool = False,
) -> RecreatePlan:
    """Bind an :class:`AdoptionDecision` to concrete image refs for the wrapper.

    On ``adopt`` the agent recreates on ``target_ref`` and ``prior_ref`` (the
    pre-adoption digest) is what a rollback repoints to (§5.6 — rollback = repoint
    at the prior :stable digest). On ``hold``/``noop`` it recreates on
    ``current_ref`` (stays on its current major); a running session is never
    touched — this only shapes the *next* launch."""
    decision = decide_adoption(
        current_version, target_version, allow_major_cross=allow_major_cross
    )
    launch = target_ref if decision.adopt else current_ref
    return RecreatePlan(
        action=decision.action,
        launch_ref=launch,
        prior_ref=current_ref,
        decision=decision,
    )


# --- CLI ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--current-version", required=True, help="the agent's current semver")
    parser.add_argument("--target-version", required=True, help=":stable's semver")
    parser.add_argument("--current-ref", default=None, help="the agent's current image ref")
    parser.add_argument("--target-ref", default=None, help=":stable's resolved image ref")
    parser.add_argument(
        "--allow-major-cross",
        action="store_true",
        help="opt into a major cross (§5.8) — never automatic at recreate",
    )
    parser.add_argument(
        "--format",
        choices=("action", "json"),
        default="action",
        help="stdout shape: the bare action, or the full JSON plan/decision",
    )
    args = parser.parse_args(argv)

    try:
        if args.current_ref and args.target_ref:
            plan = plan_recreate(
                current_ref=args.current_ref,
                current_version=args.current_version,
                target_ref=args.target_ref,
                target_version=args.target_version,
                allow_major_cross=args.allow_major_cross,
            )
            decision, payload = plan.decision, plan.as_dict()
            machine = plan.launch_ref if args.format == "action" else json.dumps(payload)
        else:
            decision = decide_adoption(
                args.current_version,
                args.target_version,
                allow_major_cross=args.allow_major_cross,
            )
            payload = decision.as_dict()
            machine = decision.action if args.format == "action" else json.dumps(payload)
    except AdoptionError as exc:
        print(f"adoption error: {exc}", file=sys.stderr)
        return 2

    print(decision.summary(), file=sys.stderr)
    print(machine)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
