#!/usr/bin/env python3
"""Mechanical promotion gate — Story 2.3 (#968), Plan #959, Dev Spec §4.4 / §5.6.

The gate that decides whether a candidate `:edge` digest may be promoted to
`:stable`. It is a **conjunctive query over FlightDeck + CI** (§5.6): the four
mechanical conditions — throwaway-CI E2E-01 green, dogfood soak met, zero
quarantines, zero open Sev-1 — must **all** be green before promotion is
permitted, and promotion retags the **exact digest E2E-01 tested**.

Requirements this module is the guard for:

* **R-07** — WHEN all mechanical conditions are green THEN `:edge → :stable`
  promotion is permitted, retagging the exact digest E2E-01 tested; a human ACK
  shall only *confirm* a green gate, never *substitute* for it. (PC-6: promotion
  is mechanical, not a feeling.)
* **R-23** — the digest E2E-01 tested, the digest promoted, and the digest the
  fleet pulls are identical. Folded into the conjunction: the throwaway-CI
  condition is green only when CI passed *for the digest being promoted*, so a
  green result for a different digest cannot promote this one.

Design — **one green path, fail-closed** (assertion-liveness, D7):

* A condition is green **only** when its signal is explicitly, affirmatively
  green. A missing, unknown, ``None``, or non-conforming signal is **RED**, never
  assumed green. There is no override, no ack, and no missing-data shortcut that
  can move a red gate to green.
* :func:`promote` is the **only** code path that yields a promotable digest. It
  raises :class:`GateError` unless (in this order) the mechanical conjunction is
  green **and** the operator ACK confirms it. Checking the conjunction *before*
  the ack is load-bearing: it encodes "the ACK can only fire after the query is
  green" and "a human ACK can never substitute for a red condition" (R-07).
* The digest it returns is exactly ``report.target_digest`` — never a re-resolved
  moving tag — so the caller retags precisely the bytes E2E-01 tested (R-23).

The module never touches the network or a registry; it reasons purely over the
signals handed to it. Sourcing those signals (a FlightDeck query for soak /
quarantines / Sev-1, the CI result for the throwaway-CI ring) and performing the
exact-digest retag live in ``scripts/ci/promote-oakandwave-image.sh``.

CLI::

    python3 promotion_gate.py --target-digest ghcr.io/o/w@sha256:… \\
        --ci-passed true --ci-digest ghcr.io/o/w@sha256:… \\
        --soak-hours 48 --soak-required-hours 24 \\
        --quarantines 0 --open-sev1 0 --ack

Prints the digest to promote on stdout and exits 0 only when the gate is green
and the ACK confirms it; otherwise prints the red summary to stderr and exits 2.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass

# The four mechanical conditions of the promotion gate (§5.6), in report order.
CONDITION_ORDER = ("throwaway_ci", "soak", "quarantines", "sev1")

CONDITION_LABELS = {
    "throwaway_ci": "throwaway-CI E2E-01 smoke green for the tested digest",
    "soak": "dogfood soak requirement met",
    "quarantines": "zero quarantines",
    "sev1": "zero open Sev-1",
}

# A full, immutable registry digest pin: `registry/path@sha256:<64 hex>`. A
# moving tag (`…:edge`) has no `@sha256:` and is refused — the gate promotes the
# content-addressed digest E2E-01 tested, never a re-resolvable tag (R-23).
_DIGEST_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-fA-F]{64}$")


class GateError(ValueError):
    """A promotion-gate contract violation. Raised LOUD, never swallowed."""


def _is_digest_ref(ref: object) -> bool:
    """True iff ``ref`` is a full immutable ``…@sha256:<64hex>`` registry pin."""
    return isinstance(ref, str) and bool(_DIGEST_RE.match(ref.strip()))


def _same_digest(a: object, b: object) -> bool:
    """True iff ``a`` and ``b`` are the same immutable digest ref (R-23).

    Both must be full digest pins; comparison is case-insensitive and
    whitespace-trimmed (registry paths are lowercased at build time). A bare
    ``sha256:…`` or a moving tag never matches a full ref — fail-closed."""
    if not (_is_digest_ref(a) and _is_digest_ref(b)):
        return False
    assert isinstance(a, str) and isinstance(b, str)  # narrowed by _is_digest_ref
    return a.strip().lower() == b.strip().lower()


def _require_digest(ref: str) -> None:
    if not _is_digest_ref(ref):
        raise GateError(
            f"target digest must be an immutable registry pin "
            f"(registry/image@sha256:<64hex>), got {ref!r} — the gate promotes "
            f"the exact digest E2E-01 tested, never a moving tag (R-23)"
        )


@dataclass(frozen=True)
class Condition:
    """One mechanical condition and whether it is affirmatively green."""

    name: str
    green: bool
    detail: str = ""


@dataclass(frozen=True)
class GateReport:
    """The evaluated gate for a specific candidate digest."""

    target_digest: str
    conditions: tuple[Condition, ...]

    @property
    def green(self) -> bool:
        """The conjunction, **fail-closed**: green iff every one of the four
        mechanical conditions is present AND affirmatively green. A missing or
        extra condition makes the gate red — the set must be exactly the four."""
        names = {c.name for c in self.conditions}
        if names != set(CONDITION_ORDER):
            return False
        return all(c.green for c in self.conditions)

    def red(self) -> list[Condition]:
        """The conditions blocking promotion (empty iff :attr:`green`)."""
        return [c for c in self.conditions if not c.green]

    def summary(self) -> str:
        lines = [f"promotion gate for {self.target_digest}:"]
        for c in self.conditions:
            mark = "green" if c.green else "RED"
            label = CONDITION_LABELS.get(c.name, c.name)
            suffix = f" — {c.detail}" if c.detail else ""
            lines.append(f"  [{mark}] {label}{suffix}")
        verdict = "GREEN — promotion permitted (pending operator ACK)" if self.green \
            else "RED — promotion refused"
        lines.append(f"  => {verdict}")
        return "\n".join(lines)


def evaluate_gate(
    *,
    target_digest: str,
    ci_passed: bool | None,
    ci_digest: str | None,
    soak_hours: float | None,
    soak_required_hours: float,
    quarantine_count: int | None,
    open_sev1_count: int | None,
) -> GateReport:
    """Evaluate the four mechanical conditions for ``target_digest``.

    Every condition is **fail-closed**: it is green only on an explicit, correct
    signal; ``None`` / missing / malformed ⇒ red. The throwaway-CI condition
    additionally requires the CI result to be *for this digest* (R-23), so a
    green for a different digest cannot carry this one.
    """
    _require_digest(target_digest)

    # 1. throwaway-CI E2E-01 green — AND bound to THIS digest (R-23).
    if ci_passed is not True:
        ci_green, ci_detail = False, "E2E-01 has not reported a green smoke"
    elif not _is_digest_ref(ci_digest):
        ci_green, ci_detail = False, "E2E-01 result carries no immutable digest ref"
    elif not _same_digest(ci_digest, target_digest):
        ci_green = False
        ci_detail = (
            f"E2E-01 tested {ci_digest!r} but promotion targets "
            f"{target_digest!r} — refusing (R-23: the digest tested is the "
            f"digest promoted)"
        )
    else:
        ci_green, ci_detail = True, f"E2E-01 green for {target_digest}"

    # 2. dogfood soak met.
    if not isinstance(soak_hours, (int, float)) or isinstance(soak_hours, bool):
        soak_green = False
        soak_detail = "soak telemetry unavailable"
    elif soak_hours >= soak_required_hours:
        soak_green = True
        soak_detail = f"{soak_hours:g}h ≥ {soak_required_hours:g}h required"
    else:
        soak_green = False
        soak_detail = f"{soak_hours:g}h < {soak_required_hours:g}h required"

    # 3. zero quarantines.
    if not isinstance(quarantine_count, int) or isinstance(quarantine_count, bool):
        quar_green, quar_detail = False, "quarantine telemetry unavailable"
    elif quarantine_count == 0:
        quar_green, quar_detail = True, "0 quarantines"
    else:
        quar_green, quar_detail = False, f"{quarantine_count} quarantine(s) during soak"

    # 4. zero open Sev-1.
    if not isinstance(open_sev1_count, int) or isinstance(open_sev1_count, bool):
        sev_green, sev_detail = False, "Sev-1 telemetry unavailable"
    elif open_sev1_count == 0:
        sev_green, sev_detail = True, "0 open Sev-1"
    else:
        sev_green, sev_detail = False, f"{open_sev1_count} open Sev-1"

    return GateReport(
        target_digest=target_digest.strip(),
        conditions=(
            Condition("throwaway_ci", ci_green, ci_detail),
            Condition("soak", soak_green, soak_detail),
            Condition("quarantines", quar_green, quar_detail),
            Condition("sev1", sev_green, sev_detail),
        ),
    )


def promote(report: GateReport, *, operator_ack: bool) -> str:
    """The **only** path to a promotable digest.

    Returns the digest to retag ``:edge → :stable`` — exactly
    ``report.target_digest``, the bytes E2E-01 tested (R-23). Raises
    :class:`GateError` unless the mechanical gate is green **and** the operator
    ACK confirms it.

    Order is load-bearing: the conjunction is checked **before** the ACK, so a
    red condition raises regardless of the ACK. The ACK can only *confirm* an
    already-green gate; it can never *substitute* for a red condition (R-07).
    """
    if not report.green:
        blocked = ", ".join(
            f"{c.name} ({c.detail})" if c.detail else c.name for c in report.red()
        )
        raise GateError(
            "promotion refused — mechanical gate is RED; failing condition(s): "
            f"{blocked}. A human ACK cannot substitute for a red condition (R-07)."
        )
    if operator_ack is not True:
        raise GateError(
            "mechanical gate is green but the operator ACK has not confirmed it — "
            "promotion requires an explicit ACK, and only AFTER the query is "
            "green (R-07)."
        )
    return report.target_digest


# --- CLI ----------------------------------------------------------------------


def _tri_bool(value: str | None) -> bool | None:
    """Parse a tri-state signal: true/false → bool, anything else → None (red)."""
    if value is None:
        return None
    v = value.strip().lower()
    if v in ("true", "1", "yes", "pass", "passed", "green"):
        return True
    if v in ("false", "0", "no", "fail", "failed", "red"):
        return False
    return None


def _opt_number(value: str | None, cast):
    """Parse an optional count/hours signal; unparsable/absent → None (red)."""
    if value is None:
        return None
    try:
        return cast(value.strip())
    except (ValueError, TypeError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--target-digest",
        required=True,
        help="the candidate digest to promote (registry/image@sha256:…)",
    )
    parser.add_argument("--ci-passed", default=None, help="E2E-01 smoke result (true/false)")
    parser.add_argument("--ci-digest", default=None, help="the digest E2E-01 tested")
    parser.add_argument("--soak-hours", default=None, help="accrued dogfood soak hours")
    parser.add_argument(
        "--soak-required-hours", default="24", help="soak hours required (default 24)"
    )
    parser.add_argument("--quarantines", default=None, help="quarantine count during soak")
    parser.add_argument("--open-sev1", default=None, help="open Sev-1 count")
    parser.add_argument(
        "--ack",
        action="store_true",
        help="operator ACK — only confirms an already-green gate, never substitutes",
    )
    args = parser.parse_args(argv)

    try:
        report = evaluate_gate(
            target_digest=args.target_digest,
            ci_passed=_tri_bool(args.ci_passed),
            ci_digest=args.ci_digest,
            soak_hours=_opt_number(args.soak_hours, float),
            soak_required_hours=float(args.soak_required_hours),
            quarantine_count=_opt_number(args.quarantines, int),
            open_sev1_count=_opt_number(args.open_sev1, int),
        )
    except GateError as exc:
        print(f"promotion-gate error: {exc}", file=sys.stderr)
        return 2

    print(report.summary(), file=sys.stderr)

    try:
        digest = promote(report, operator_ack=args.ack)
    except GateError as exc:
        print(f"promotion-gate: {exc}", file=sys.stderr)
        return 2

    # The one line stdout emits is the digest to retag — the exact bytes E2E-01
    # tested (R-23). The wrapper consumes this and retags :edge → :stable.
    print(digest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
