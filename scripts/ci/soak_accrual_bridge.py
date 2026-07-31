#!/usr/bin/env python3
"""Auto-soak accrual bridge — surgeon --live → soak_ledger.accrue (#1008).

Prior waves built the soak **writer** (``soak_ledger.py``, Story 4.2 / #975) and the
host-side health **probe** (``surgeon.py``, Story 3.1 / #970), but nothing in a live
path connected them: ``soak_ledger.accrue`` was only ever driven by hand-built
observations in a test. So during a real dogfood cutover **soak never accrued → the
promotion gate's ``SOAK_HOURS`` never filled → ``:edge`` could never auto-promote to
``:stable``** (R-07/R-08 unit-proven but not live-wired). This module is that missing
connective tissue.

Why a SEPARATE orchestrator (not a surgeon change): per **R-15** the flight surgeon
imports **only the standard library** so a broken container's kit can never shape its
verdict — it therefore *cannot* import ``soak_ledger``. This bridge is the orchestrator
the issue calls for: it *runs* the surgeon (subprocess ``--live``) and *feeds* its
verdicts to ``soak_ledger.accrue`` (import). The surgeon stays kit-independent; the
bridge is allowed to import both sides.

The flow (all three steps are here, none in shell — project rule):

1. **Gather** — subprocess ``surgeon.py --live`` for each session's health verdict
   (status / broken / normalized ``oaw.profile`` label) and ``aoe list --json`` for
   each session's ``created_at`` (the session-start time). Both are injectable seams
   (``surgeon_runner`` / ``aoe_runner``) so the whole pipeline is hermetically testable
   with **no live aoe/docker**.
2. **Map** (:func:`build_observations`, the pure, fully-tested core) — for every
   **running** session, emit one ``soak_ledger`` observation
   ``{session, profile, active_since, active_until, broken}``.
3. **Accrue** — hand the observations to ``soak_ledger.accrue``, which appends the
   FlightDeck soak ledger the promotion gate reads.

Two design decisions worth scrutiny (documented at their code sites):

* **``active_since`` = ``max(created_at, now − LOOK_BACK)``** — a bounded per-pass
  look-back (§ :func:`build_observations`). ``aoe list --json`` exposes a per-session
  ``created_at`` (the session-start time; the transcript's earliest entry is the
  fallback), but the surgeon's health verdict is **point-in-time at ``now``**: it
  certifies the session clean *now*, not across its whole history. Crediting the raw
  ``[created_at, now]`` span from one end-of-window verdict would **assert** clean time
  that was never sampled — violating R-07 ("soak is measured, never asserted") two
  ways: (a) the *first* observation of an N-hour-old session would back-credit all N
  hours of un-health-checked history; (b) a broken→recovered flap would back-credit the
  broken interval — a broken pass writes no record, so the watermark does not advance,
  and the next clean pass's span would reach back across the dirty gap (contradicting
  §4.3 "clean work only accrues soak"). Clamping ``active_since`` to ``now − LOOK_BACK``
  bounds **both**: each pass credits at most ``LOOK_BACK`` of time, ending at the ``now``
  it just health-verified; a recovered session can only reach back ``LOOK_BACK`` from
  ``now``, so a broken gap older than ``LOOK_BACK`` is never credited. The operator's
  contract: run the pass at least every ``LOOK_BACK`` (``OAW_SOAK_LOOKBACK_HOURS``,
  default 1h — set it to the cron cadence). A skipped/late pass merely under-credits the
  uncovered clean time — soak is earned, never granted; under-credit is safe,
  over-credit is the hazard. ``soak_ledger``'s per-session watermark still prevents any
  double-count across overlapping passes.
* **The bridge selects on ``running`` only; candidacy (R-22) is delegated to
  ``soak_ledger.accrue``.** Only a *running* session has an open span ending "now"
  (``active_until = now``); an idle/stopped one has finished and must not have idle time
  counted as soak. The dev-mode exclusion (R-22) and the broken-session exclusion (§4.3)
  are **not** re-implemented here — they are ``soak_ledger``'s single source of truth
  (via ``profiles.is_candidate``), which reports each exclusion *with a reason*. Feeding
  a running dev-mode/broken session to ``accrue`` yields a visible "skipped — reason"
  outcome; pre-filtering it in the bridge would make it a silent drop. So the bridge
  passes every running session's profile through unchanged and lets the one R-22
  enforcement point decide.

CLI::

    # accrue soak from the current live :edge dogfood ring
    python3 soak_accrual_bridge.py --ledger ~/.oaw/soak/ledger.jsonl \\
        --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts

    # preview what WOULD accrue, writing nothing
    python3 soak_accrual_bridge.py --dry-run

Prints a human summary (fed / skipped / accrued, with reasons) on stderr and the JSON
of the appended soak records on stdout; exits 0 normally.

NOTE — the LIVE end-to-end proof (real aoe sessions on ``:edge`` → gate soak fills over
time) rides an actual operator cutover (MV-04/MV-06 territory, Dev Spec §6.3 E2E-02).
The hermetic tests here prove the mapping + accrual with injected surgeon/aoe output;
they deliberately do **not** require live aoe/docker.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
SURGEON_PY = REPO_ROOT / "scripts" / "flight-surgeon" / "surgeon.py"
CONTAINER_DIR = REPO_ROOT / "containers" / "oakandwave-workflow"

# soak_ledger is the FlightDeck soak WRITER (Story 4.2). The bridge is the orchestrator
# that feeds it — it CAN import it (unlike the deliberately kit-independent surgeon,
# R-15). Path-style import, mirroring the tests (no PYTHONPATH dependency).
sys.path.insert(0, str(CONTAINER_DIR))
import soak_ledger as sl  # noqa: E402

# The surgeon is imported ONLY for the ``active_since`` transcript fallback resolver
# (:func:`_earliest_transcript_ts`) — the live health verdict itself comes from the
# ``surgeon.py --live`` SUBPROCESS (its JSON), never from these helpers. Importing the
# stdlib-only surgeon into the bridge does not weaken R-15 (the surgeon stays
# kit-independent); the bridge is the orchestrator that is allowed to import both sides.
sys.path.insert(0, str(SURGEON_PY.parent))
import surgeon as sg  # noqa: E402

DEFAULT_LEDGER = "~/.oaw/soak/ledger.jsonl"
# Mirror the surgeon's own default rather than re-spelling it. Spelling it
# independently is what let this drift: the surgeon moved off ~/.claude/projects
# (#1064) and now REFUSES that root, so a stale default here made the whole
# accrual loop exit non-zero and accrue ZERO soak — :edge could never promote,
# which is exactly what #1008 exists to prevent.
DEFAULT_TRANSCRIPTS_ROOT = sg.DEFAULT_TRANSCRIPTS_ROOT

# The bounded per-pass look-back (hours). Each pass credits at most this much time,
# ending at the ``now`` it just health-verified — so a point-in-time "clean now"
# verdict never back-credits un-sampled history (first-pass full-age credit) nor a
# broken→recovered gap (R-07 "measured, never asserted"; §4.3 "clean work only"). The
# operator sets ``OAW_SOAK_LOOKBACK_HOURS`` to the accrual cron cadence: LOOK_BACK must
# be >= the interval between passes, or clean time between passes is silently
# under-credited (safe direction); much larger than the interval widens the residual
# broken-gap a recovery pass can reach back over, so keep it ~= the cadence.
DEFAULT_LOOKBACK_HOURS = 1.0
LOOKBACK_ENV = "OAW_SOAK_LOOKBACK_HOURS"

RUNNING = "running"


class BridgeError(RuntimeError):
    """A bridge orchestration failure (a gather subprocess failed). Raised LOUD."""


# --- gather seams (subprocess by default; injectable for hermetic tests) ------


def _run(cmd: list[str], *, timeout: float = 60.0) -> str:
    """Run a gather command and return stdout, or raise :class:`BridgeError`.

    Unlike the surgeon's best-effort ``_run`` (which swallows failure to a degraded
    signal), the bridge fails **loud** on a broken gather: a silent empty gather would
    accrue zero soak and look like "nothing to accrue", masking a real outage —
    exactly the config-exists-≠-works trap. A red gather must be visible."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BridgeError(f"gather command failed to launch: {' '.join(cmd)}: {exc}") from exc
    if proc.returncode != 0:
        raise BridgeError(
            f"gather command exited {proc.returncode}: {' '.join(cmd)}\n{proc.stderr.strip()}"
        )
    return proc.stdout


def _parse_json_list(text: str) -> list[dict]:
    """Parse a JSON array of objects, tolerating empty output (⇒ ``[]``)."""
    if not text.strip():
        return []
    data = json.loads(text)
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def gather_surgeon_assessments(transcripts_root: object, *, runner=_run) -> list[dict]:
    """Run ``surgeon.py --live`` and return its assessment list (one per session).

    Each assessment is ``surgeon.Assessment.as_dict()``: ``container_id`` / ``title`` /
    normalized ``profile`` (dogfood|dev-mode|unknown) / ``health`` (status, broken,
    last_activity, …). This is the authoritative R-16/R-22 verdict. Run WITHOUT
    ``--fail-on-quarantine`` — the bridge wants the JSON, not the exit-code signal."""
    out = runner(
        [
            "python3",
            str(SURGEON_PY),
            "--live",
            "--transcripts-root",
            str(Path(str(transcripts_root)).expanduser()),
        ]
    )
    return _parse_json_list(out)


def gather_aoe_sessions(*, runner=_run) -> list[dict]:
    """Run ``aoe list --json`` and return the raw session list.

    Each session carries ``id`` (== the surgeon's ``container_id``), ``created_at`` (the
    session-start time used as ``active_since``), and ``path`` (used only for the
    transcript fallback). Verified shape, ``aoe 1.13.0``:
    ``{"id","title","path","group","tool","profile","created_at","workspace_repos"}``.
    NOTE: aoe's ``profile`` field is the *workspace* profile ("default"), **not** the
    ``oaw.profile`` container label — the label comes from the surgeon assessment."""
    return _parse_json_list(runner(["aoe", "list", "--json"]))


# --- active_since fallback: the transcript's earliest entry --------------------


def _earliest_transcript_ts(transcripts_root: object, project_path: str) -> str | None:
    """The earliest timestamp in a session's host-backed transcript, or ``None``.

    The fallback ``active_since`` when ``aoe``'s ``created_at`` is absent/unparseable.
    Resolves the transcript with the SAME resolver the surgeon uses (kept DRY by
    importing it) so the bridge and the probe agree on which file is a session's
    transcript, then returns its earliest entry's ISO timestamp (≈ session start)."""
    if not project_path:
        return None
    root = Path(str(transcripts_root)).expanduser()
    path = sg._newest_transcript_for(root, project_path)
    if path is None:
        return None
    earliest: datetime | None = None
    for entry in sg.read_transcript(path):
        ts = sg.parse_timestamp(entry.get("timestamp"))
        if ts is not None and (earliest is None or ts < earliest):
            earliest = ts
    return earliest.isoformat() if earliest is not None else None


# --- the pure mapping core (fully hermetically tested) ------------------------


def build_observations(
    assessments: list[dict],
    sessions: list[dict],
    *,
    now: datetime,
    transcripts_root: object = DEFAULT_TRANSCRIPTS_ROOT,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
) -> tuple[list[dict], list[tuple[str, str]]]:
    """Map surgeon assessments + aoe sessions → ``soak_ledger`` observations.

    Returns ``(observations, skipped)`` where ``skipped`` is ``[(session, reason)]`` —
    a session the bridge did not feed to ``accrue`` (mirrors soak_ledger's
    never-a-silent-drop principle).

    Selection is on **``running``** only (see the module docstring): only a running
    session has an open span ending at ``now``. Candidacy (dev-mode, R-22) and
    cleanliness (broken, §4.3) are **not** filtered here — every running session's
    profile + broken flag is passed straight through, and ``soak_ledger.accrue`` applies
    those exclusions at its single enforcement point, with a reason.

    ``active_since`` per session is the session-start signal — aoe ``created_at``
    (primary), else the transcript's earliest entry (fallback) — **clamped up to
    ``now − lookback_hours``**. The clamp is load-bearing: the surgeon's verdict is
    point-in-time at ``now``, so a pass may only credit the window it actually sampled.
    Without it the first pass would back-credit a session's whole age, and a
    broken→recovered flap would back-credit the dirty gap (see the module docstring's
    sampling-model argument). A session with no start signal at all still gets
    ``active_since = now − lookback`` (it is running + clean now; credit only the
    bounded look-back). ``active_until`` = ``now`` (the session is live)."""
    created_at: dict[str, object] = {}
    path_by_id: dict[str, str] = {}
    for s in sessions:
        sid = s.get("id")
        if isinstance(sid, str):
            created_at[sid] = s.get("created_at")
            path_by_id[sid] = str(s.get("path", ""))

    floor = now - timedelta(hours=lookback_hours)

    observations: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for a in assessments:
        health = a.get("health") if isinstance(a.get("health"), dict) else {}
        sid = str(a.get("container_id", a.get("id", "?")))
        status = str(health.get("status", "")).strip().lower()

        if status != RUNNING:
            skipped.append(
                (
                    sid,
                    f"status={status or 'unknown'}: not running — no open soak span "
                    "(only a running session accrues; its span ends at now)",
                )
            )
            continue

        # Session-start signal: created_at (primary), transcript-earliest (fallback).
        start = sl.parse_ts(created_at.get(sid))
        if start is None:
            start = sl.parse_ts(_earliest_transcript_ts(transcripts_root, path_by_id.get(sid, "")))
        # Clamp UP to the look-back floor: credit at most `lookback_hours`, ending at the
        # health-verified `now`. With no start signal, the floor itself is the start.
        effective_since = max(start, floor) if start is not None else floor

        observations.append(
            {
                "session": sid,
                "profile": a.get("profile", "unknown"),
                "active_since": effective_since.isoformat(),
                "active_until": now.isoformat(),
                "broken": bool(health.get("broken", False)),
            }
        )
    return observations, skipped


# --- the top-level pass -------------------------------------------------------


def run(
    *,
    ledger_path: object = DEFAULT_LEDGER,
    transcripts_root: object = DEFAULT_TRANSCRIPTS_ROOT,
    lookback_hours: float = DEFAULT_LOOKBACK_HOURS,
    now: datetime | None = None,
    dry_run: bool = False,
    surgeon_runner=_run,
    aoe_runner=_run,
) -> tuple[list[dict], list[tuple[str, str]], list]:
    """Gather → map → accrue. Returns ``(observations, skipped, accrual_results)``.

    ``dry_run`` builds and returns the observations but accrues nothing (``results``
    is empty) — a preview for the operator. The gather seams are injected so tests
    drive the whole pipeline with fixture surgeon/aoe output and no live aoe/docker."""
    now = now or datetime.now(timezone.utc)
    assessments = gather_surgeon_assessments(transcripts_root, runner=surgeon_runner)
    sessions = gather_aoe_sessions(runner=aoe_runner)
    observations, skipped = build_observations(
        assessments,
        sessions,
        now=now,
        transcripts_root=transcripts_root,
        lookback_hours=lookback_hours,
    )
    if dry_run:
        return observations, skipped, []
    results = sl.accrue(observations=observations, ledger_path=ledger_path, now=now)
    return observations, skipped, results


# --- CLI ----------------------------------------------------------------------


def _default_lookback() -> float:
    """The look-back default: ``OAW_SOAK_LOOKBACK_HOURS`` if a valid positive float,
    else :data:`DEFAULT_LOOKBACK_HOURS`. A malformed env value falls back (never
    crashes the pass) — the operator's misconfiguration must not silently corrupt soak."""
    raw = os.environ.get(LOOKBACK_ENV)
    if raw is None:
        return DEFAULT_LOOKBACK_HOURS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_LOOKBACK_HOURS
    return value if value > 0 else DEFAULT_LOOKBACK_HOURS


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--ledger",
        default=DEFAULT_LEDGER,
        help=f"soak .jsonl ledger to append to (default {DEFAULT_LEDGER})",
    )
    parser.add_argument(
        "--transcripts-root",
        default=DEFAULT_TRANSCRIPTS_ROOT,
        help=f"root the surgeon resolves host-backed transcripts under "
        f"(default {DEFAULT_TRANSCRIPTS_ROOT})",
    )
    parser.add_argument(
        "--lookback-hours",
        type=float,
        default=_default_lookback(),
        help=f"bounded per-pass look-back in hours — each pass credits at most this "
        f"much time, verified clean at now (env {LOOKBACK_ENV}, default "
        f"{DEFAULT_LOOKBACK_HOURS}h; set it to your accrual cron cadence)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="build + print the observations that WOULD accrue; write nothing",
    )
    args = parser.parse_args(argv)

    try:
        observations, skipped, results = run(
            ledger_path=args.ledger,
            transcripts_root=args.transcripts_root,
            lookback_hours=args.lookback_hours,
            dry_run=args.dry_run,
        )
    except (BridgeError, sl.SoakError, OSError, json.JSONDecodeError) as exc:
        print(f"soak-accrual-bridge error: {exc}", file=sys.stderr)
        return 2

    print("soak-accrual bridge:", file=sys.stderr)
    for sid, reason in skipped:
        print(f"  [skip] {sid} — {reason}", file=sys.stderr)
    if args.dry_run:
        for obs in observations:
            print(
                f"  [would-feed] {obs['session']} ({obs['profile']}) "
                f"since={obs['active_since']} broken={obs['broken']}",
                file=sys.stderr,
            )
        print(
            f"  => [dry-run] {len(observations)} running session(s) would be fed to "
            f"soak_ledger.accrue; nothing written",
            file=sys.stderr,
        )
        print(json.dumps(observations, indent=2))
        return 0

    written = [r for r in results if r.accrued]
    total = sum(r.record["hours"] for r in written)  # type: ignore[index]
    for r in results:
        mark = "SOAK" if r.accrued else "skip"
        print(f"  [{mark}] {r.session} ({r.profile}) — {r.reason}", file=sys.stderr)
    print(
        f"  => {len(written)} record(s) written to {args.ledger}, "
        f"{total:g}h candidate soak accrued from {len(observations)} running session(s)",
        file=sys.stderr,
    )
    print(json.dumps([r.record for r in written], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
