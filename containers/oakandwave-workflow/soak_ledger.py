#!/usr/bin/env python3
"""Dogfood soak accrual — Story 4.2 (#975), Plan #959, Dev Spec §4.3 / §5.6 (R-07).

The FlightDeck soak **writer**. Prior waves built everything that *reads* soak —
the promotion gate's soak condition (``promotion_gate.py``) and the profile-filtered
roll-up (``profiles.aggregate_gate_signals``) — but nothing *wrote* it. The gate's
soak condition could therefore never go green from real dogfood work, because no
code path turned clean dogfood work into soak records. This module is that missing
writer: it turns a dogfood container's **clean work span** into a soak record and
appends it to the FlightDeck soak ledger (``~/.oaw/soak/ledger.jsonl``) that the
gate consumes through the profile filter.

The record shape is exactly what ``profiles.aggregate_gate_signals`` folds:
``{"event": "soak", "profile": <label>, "hours": <float>, ...}`` — so a record
written here flows, unchanged, into the ``--soak-hours`` signal
``promote-oakandwave-image.sh`` feeds the gate. This closes the FlightDeck loop:
**surgeon watches → clean spans accrue here → gate reads the filtered soak** (§4.3:
"the flight surgeon watches each container; clean work accrues soak in FlightDeck").

Requirements this module is the writer for:

* **R-07** — soak is one of the four mechanical promotion conditions. This is the
  only code that produces the soak signal, so "the gate is mechanical" extends to
  "soak is measured, never asserted": a record is written only for a real, clean,
  candidate work span.
* **R-21 / R-22** — accrual filters on the profile label. A **dev-mode** session
  never accrues soak (:func:`accrue_record` returns ``None`` for it), reusing
  ``profiles.is_candidate`` as the single source of truth for "what counts" — so
  the writer and the gate-side filter can never disagree about candidacy.

Design — **soak is earned, never granted** (assertion-liveness, D7):

* A record is emitted **only** for a candidate profile (dev-mode excluded, R-22),
  **only** for clean work (``broken`` sessions accrue nothing — §4.3 "*clean* work
  accrues soak"; a stalled/looping/quarantined session's dirty span is not soak),
  and **only** for a strictly-positive span.
* Accrual is **watermarked per session**: :func:`accrue` reads the last ``until``
  already recorded for a session and counts only the *new* clean time since then, so
  running the accrual pass repeatedly (a cron, a soak loop) can never double-count a
  span. Idempotent by construction — re-running with no new activity writes nothing.
* Every exclusion is a *returned reason*, never a silent drop: :func:`accrue`
  reports what it wrote AND what it skipped and why, so a dogfood session that fails
  to accrue is visible, not mysteriously stuck at zero soak.

CLI::

    # accrue from an observations manifest (the surgeon's shape + a clean span)
    python3 soak_ledger.py --observations obs.json --ledger ~/.oaw/soak/ledger.jsonl

Prints a human summary (written / skipped, with reasons) on stderr and the JSON of
the appended records on stdout; exits 0 normally.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# profiles.py is the canonical owner of the profile label + candidacy (R-21/R-22).
# soak_ledger is a candidate-telemetry writer and CAN import it (unlike the
# deliberately kit-independent surgeon, R-15) — so "what counts as a candidate" has
# exactly one definition, shared by the writer here and the gate-side filter.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import profiles as pf  # noqa: E402

# The default FlightDeck soak ledger — the same path profiles.py's CLI documents
# and promote-oakandwave-image.sh reads via OAW_SOAK_LEDGER. One JSON object/line.
DEFAULT_LEDGER = "~/.oaw/soak/ledger.jsonl"

SOAK_EVENT = "soak"


class SoakError(ValueError):
    """A soak-accrual contract violation. Raised LOUD, never swallowed."""


def parse_ts(value: object) -> datetime | None:
    """Parse an ISO-8601 timestamp to an aware UTC datetime, or ``None``.

    Tolerates a trailing ``Z`` and naive stamps (assumed UTC). A malformed/absent
    stamp is ``None`` — never an exception (a soak pass must degrade a bad record,
    not crash the accrual)."""
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def clamped_window(
    active_since: object,
    active_until: object,
    *,
    watermark: datetime | None = None,
) -> tuple[datetime | None, datetime | None, float]:
    """The watermark-clamped accrual window: ``(effective_start, end, hours)``.

    The single clamp primitive both :func:`soak_hours` and :func:`accrue_record` use,
    so the counted hours and the audit ``since`` can never describe different windows.
    ``effective_start`` is ``max(active_since, watermark)`` — a watermark (the last
    ``until`` already recorded for this session) makes a re-run count only the *new*
    time since the prior accrual, never re-counting a recorded span. An unparseable
    or non-positive span yields ``hours == 0.0`` (nothing to accrue), never negative."""
    start = parse_ts(active_since)
    end = parse_ts(active_until)
    if start is None or end is None:
        return start, end, 0.0
    effective_start = watermark if (watermark is not None and watermark > start) else start
    delta = (end - effective_start).total_seconds()
    return effective_start, end, (delta / 3600.0 if delta > 0 else 0.0)


def soak_hours(
    active_since: object,
    active_until: object,
    *,
    watermark: datetime | None = None,
) -> float:
    """The clean-work hours to accrue for one span, watermark-clamped (see
    :func:`clamped_window`). A convenience for a caller that wants only the hours."""
    return clamped_window(active_since, active_until, watermark=watermark)[2]


@dataclass(frozen=True)
class AccrualResult:
    """One session's accrual outcome: the record written (or ``None``), and why."""

    session: str
    profile: str
    record: dict | None
    reason: str

    @property
    def accrued(self) -> bool:
        return self.record is not None


def accrue_record(
    *,
    session: str,
    profile: object,
    active_since: object,
    active_until: object,
    watermark: datetime | None = None,
    broken: bool = False,
) -> AccrualResult:
    """Build the soak record for one dogfood session, or explain the exclusion.

    Emits a record **iff** (in this order):

    1. the profile is a **candidate** — dev-mode is excluded (R-22); an
       unlabeled/unknown profile is a candidate (fail-safe toward measuring, mirrors
       ``profiles.is_candidate`` and the surgeon's ``quarantine_eligible``);
    2. the work is **clean** — a ``broken`` (stalled / looping / quarantined) session
       accrues nothing (§4.3: *clean* work accrues soak); and
    3. the watermark-clamped span is **strictly positive**.

    Any failing gate returns ``record=None`` with a human ``reason`` — never a silent
    zero. The record carries ``profile`` + ``hours`` (what the gate reads) plus the
    ``session`` and ``since``/``until`` bounds (audit + the next pass's watermark)."""
    prof = pf.normalize_profile(profile)
    if not pf.is_candidate(profile):
        return AccrualResult(session, prof, None, f"profile={prof}: dev-mode is non-candidate — no soak (R-22)")
    if broken:
        return AccrualResult(session, prof, None, "session is broken/quarantined — clean work only accrues soak (§4.3)")
    effective_start, end, hours = clamped_window(active_since, active_until, watermark=watermark)
    if effective_start is None or end is None:
        return AccrualResult(session, prof, None, "unparseable active span — no soak to accrue")
    if hours <= 0:
        wm = f" since watermark {watermark.isoformat()}" if watermark is not None else ""
        return AccrualResult(session, prof, None, f"no new clean span to accrue{wm}")
    record = {
        "event": SOAK_EVENT,
        "profile": prof,
        "session": str(session),
        "since": effective_start.isoformat(),
        "until": end.isoformat(),
        "hours": hours,
    }
    return AccrualResult(session, prof, record, f"accrued {hours:g}h of clean {prof} soak")


def read_ledger(path: object) -> list[dict]:
    """Read the soak ``.jsonl`` ledger into a list of records. Missing ⇒ ``[]``;
    blank and malformed lines are skipped (a partially-written tail must not crash
    the accrual)."""
    p = Path(str(path)).expanduser()
    if not p.is_file():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(obj)
    return out


def session_watermarks(records: list[dict]) -> dict[str, datetime]:
    """The latest recorded ``until`` per session across existing soak records.

    This is the per-session watermark the next accrual clamps against, so a repeated
    pass counts only new clean time. Only ``event == "soak"`` records with a
    parseable ``until`` contribute; anything else is ignored."""
    marks: dict[str, datetime] = {}
    for r in records:
        if str(r.get("event", SOAK_EVENT)) != SOAK_EVENT:
            continue
        session = r.get("session")
        until = parse_ts(r.get("until"))
        if not isinstance(session, str) or until is None:
            continue
        if session not in marks or until > marks[session]:
            marks[session] = until
    return marks


def append_record(path: object, record: dict) -> None:
    """Append one soak record as a JSON line, creating the ledger + parents if
    absent. The ledger is host-backed (durable) so soak survives a container
    ``docker rm`` — the stateless-container invariant (R-01) applies to soak too."""
    p = Path(str(path)).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n")


def aggregate_or_zero(ledger_path: object = DEFAULT_LEDGER) -> float:
    """The current candidate soak total (hours) in the ledger, or ``0.0`` if empty.

    Reads the ledger back through the **same profile filter the gate uses**
    (``profiles.aggregate_gate_signals``), so "how much soak have we accrued" answers
    with exactly the number the promotion gate will see — dev-mode already excluded
    (R-22). A convenience for the cutover/operator and the soak loop's progress check;
    the gate itself sources this through ``promote-oakandwave-image.sh``'s
    ``OAW_SOAK_LEDGER`` seam, not this helper."""
    signals = pf.aggregate_gate_signals(
        soak_records=read_ledger(ledger_path), quarantine_records=[]
    )
    return float(signals["soak_hours"])


def accrue(
    *,
    observations: list[dict],
    ledger_path: object = DEFAULT_LEDGER,
    now: datetime | None = None,
) -> list[AccrualResult]:
    """Accrue soak for a batch of dogfood session observations (the top-level pass).

    Each observation: ``session``, ``profile``, ``active_since`` and an
    ``active_until`` (defaulting to ``now`` for a still-running session), and an
    optional ``broken`` flag (a surgeon verdict). Reads the existing ledger once for
    per-session watermarks, builds each session's record (skipping dev-mode, broken,
    and empty spans with a reason), and appends the survivors. Returns every
    :class:`AccrualResult` — written and skipped alike — so nothing is a silent drop.
    """
    now = now or datetime.now(timezone.utc)
    watermarks = session_watermarks(read_ledger(ledger_path))
    results: list[AccrualResult] = []
    for obs in observations:
        if not isinstance(obs, dict):
            raise SoakError(f"observation must be an object, got {type(obs).__name__}")
        session = str(obs.get("session", obs.get("container_id", obs.get("id", "?"))))
        result = accrue_record(
            session=session,
            profile=obs.get("profile"),
            active_since=obs.get("active_since"),
            active_until=obs.get("active_until", now),
            watermark=watermarks.get(session),
            broken=bool(obs.get("broken", False)),
        )
        if result.record is not None:
            append_record(ledger_path, result.record)
        results.append(result)
    return results


# --- CLI ----------------------------------------------------------------------


def _load_observations(path: str) -> list[dict]:
    text = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text()
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("observations"), list):
        data = data["observations"]
    if not isinstance(data, list):
        raise SoakError("observations must be a JSON list (or {observations: [...]})")
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--observations",
        metavar="FILE",
        required=True,
        help="JSON manifest of dogfood session observations ('-' for stdin)",
    )
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"soak .jsonl ledger to append to (default {DEFAULT_LEDGER})",
    )
    args = parser.parse_args(argv)

    try:
        observations = _load_observations(args.observations)
        results = accrue(observations=observations, ledger_path=args.ledger)
    except (SoakError, OSError, json.JSONDecodeError) as exc:
        print(f"soak-accrual error: {exc}", file=sys.stderr)
        return 2

    written = [r for r in results if r.accrued]
    total = sum(r.record["hours"] for r in written)  # type: ignore[index]
    print("soak accrual:", file=sys.stderr)
    for r in results:
        mark = "SOAK" if r.accrued else "skip"
        print(f"  [{mark}] {r.session} ({r.profile}) — {r.reason}", file=sys.stderr)
    print(
        f"  => {len(written)} record(s) written to {args.ledger}, {total:g}h candidate soak accrued",
        file=sys.stderr,
    )
    print(json.dumps([r.record for r in written], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
