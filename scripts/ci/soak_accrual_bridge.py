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

* **``active_since`` = aoe ``created_at``** (§ :func:`build_observations`). ``aoe list
  --json`` exposes a per-session ``created_at`` (the session-creation timestamp); that
  is the session's active-span start. If it is missing/unparseable we fall back to the
  **transcript's earliest entry timestamp** (:func:`_earliest_transcript_ts`). Because
  ``soak_ledger`` watermarks per session, ``active_since`` only shapes the *first*
  accrual pass — every later pass counts only new time past the last recorded ``until``
  — so an imperfect ``active_since`` cannot double-count.
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
        --transcripts-root ~/.claude/projects

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
import subprocess
import sys
from datetime import datetime, timezone
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
DEFAULT_TRANSCRIPTS_ROOT = "~/.claude/projects"

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

    ``active_since`` per session: aoe ``created_at`` (primary), else the transcript's
    earliest entry (fallback). ``active_until`` = ``now`` (the session is live)."""
    created_at: dict[str, object] = {}
    path_by_id: dict[str, str] = {}
    for s in sessions:
        sid = s.get("id")
        if isinstance(sid, str):
            created_at[sid] = s.get("created_at")
            path_by_id[sid] = str(s.get("path", ""))

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

        active_since = created_at.get(sid)
        if sl.parse_ts(active_since) is None:
            active_since = _earliest_transcript_ts(transcripts_root, path_by_id.get(sid, ""))

        observations.append(
            {
                "session": sid,
                "profile": a.get("profile", "unknown"),
                "active_since": active_since,
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
        assessments, sessions, now=now, transcripts_root=transcripts_root
    )
    if dry_run:
        return observations, skipped, []
    results = sl.accrue(observations=observations, ledger_path=ledger_path, now=now)
    return observations, skipped, results


# --- CLI ----------------------------------------------------------------------


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
        "--dry-run",
        action="store_true",
        help="build + print the observations that WOULD accrue; write nothing",
    )
    args = parser.parse_args(argv)

    try:
        observations, skipped, results = run(
            ledger_path=args.ledger,
            transcripts_root=args.transcripts_root,
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
