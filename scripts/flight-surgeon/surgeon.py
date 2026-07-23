#!/usr/bin/env python3
"""Flight surgeon — host-side health probe. Story 3.1 (#970), Plan #959, Dev Spec §5.7.

The flight surgeon is a **host-side** process (running ``:stable`` or bare) that
watches each ``:edge`` dogfood container and decides whether it is broken — by
reading the container's **host-backed ``.jsonl`` transcript directly**. The
transcript is written by the harness *below* the kit, so the probe is
**fate-independent**: a wedged, looping, or OOM-killed agent cannot corrupt the
signal the surgeon reads, and the surgeon needs **nothing from inside the
container** — no ``docker exec``, no kit import, no MCP call (R-15).

Requirements this module is the guard for:

* **R-15** — a host-side probe detects a broken ``:edge`` container by reading its
  host-backed transcript directly, **without depending on the container's kit**.
  Realised here as: :func:`read_transcript` parses the ``.jsonl`` straight off the
  host filesystem, and the whole module imports **only the Python standard
  library** — there is no path by which a broken container's kit can shape the
  verdict.
* **R-16** — WHILE a container's aoe status is ``running`` AND its transcript has
  not grown for N minutes (**stall**), OR it shows a **loop** signal, the probe
  classifies it broken. Both signals are gated on ``running`` (:func:`classify_health`):
  a flat or repetitive transcript while the agent is ``idle``/``waiting``/``stopped``
  is normal (it finished, or is awaiting input), never a break.
* **R-22** — the probe filters on the **profile label**; **dev-mode** runs and
  breakages do **not** trip quarantine (:func:`quarantine_eligible`). A broken
  dev-mode container is still *classified* broken (visible), but is marked
  ``should_quarantine = False`` so it never trips quarantine or pollutes the soak.

Design — **fail-safe toward detection** (assertion-liveness, D7):

* A break is only asserted on an explicit, positive signal (running + timed-flat,
  or a concrete repeating tool cycle). Ambiguity (no timestamps yet, a just-
  launched container) is **not** a break — the probe must not false-quarantine a
  healthy agent that is legitimately mid-thought.
* Conversely, **quarantine exclusion requires an explicit ``dev-mode`` label**. An
  unlabeled or unknown-profile candidate is treated as quarantine-*eligible*, so a
  broken candidate can never silently escape the probe merely by lacking a label
  (the profile-label mechanism itself is Story 4.1 / #974; this probe *consumes*
  it — R-21/R-22).

Separation of concerns — this module **detects and classifies only**. It performs
**no quarantine action** (stop / ``docker rm`` / recreate on ``:stable``): that is
Story 3.2 (#971), which consumes this module's ``should_quarantine`` verdict. The
live discovery seams (mapping a sandbox container to its host-backed transcript
path, and reading the ``oaw.profile`` label) are UNPROVEN against a real sandbox
(Dev Spec TC-7 / §5.N) and are exercised by MV-04/MV-06; the pure classifier below
is the story's canonical oracle (``tests/contained-workflow/test_surgeon.py``).

CLI::

    # classify a set of observations (each names its host-backed transcript path)
    python3 surgeon.py --observations obs.json

    # best-effort live gather over aoe sessions (flags the UNPROVEN seams)
    python3 surgeon.py --live --transcripts-root ~/.claude/projects

Emits a JSON report on stdout (one assessment per container) and a human summary
on stderr; exits 0 normally, or non-zero with ``--fail-on-quarantine`` if any
container is a quarantine-eligible break (a signal a watcher/cron can act on).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# --- tunable thresholds (all overridable at the CLI) --------------------------

# A `running` container whose transcript has not grown for this long is stalled
# (R-16 "flat-for-N-min"). Generous by default: a legitimately long tool call or
# a deep think must not trip it — a running agent silent for 15 min is dead.
DEFAULT_STALL_SECONDS = 15 * 60

# Loop signal: the same tool action (name + input) repeated this many times at the
# transcript tail, or a short cycle repeated this many times, is "no forward
# progress" (Dev Spec §5.7 "same tool K times").
DEFAULT_LOOP_MIN_REPEATS = 5
# The longest repeating cycle length considered (e.g. period 2 = A B A B ...).
DEFAULT_LOOP_MAX_PERIOD = 4


# --- aoe run states -----------------------------------------------------------

RUNNING = "running"
WAITING = "waiting"
IDLE = "idle"
STOPPED = "stopped"
ERROR = "error"
STATUS_UNKNOWN = "unknown"

_RUN_STATES = {RUNNING, WAITING, IDLE, STOPPED, ERROR, STATUS_UNKNOWN}


def normalize_status(value: object) -> str:
    """Normalize an aoe session state (the ``aoe status -v`` headers RUNNING /
    WAITING / IDLE / STOPPED / ERROR) to a lowercase token; anything else →
    ``unknown``. Unknown is treated as *not running*, so the break signals — which
    are gated on ``running`` (R-16) — never fire on an unrecognised state."""
    if not isinstance(value, str):
        return STATUS_UNKNOWN
    v = value.strip().lower()
    return v if v in _RUN_STATES else STATUS_UNKNOWN


# --- profiles (R-21 / R-22) ---------------------------------------------------

DOGFOOD = "dogfood"  # candidate — feeds the gate, quarantine-eligible
DEV_MODE = "dev-mode"  # skills-overlay ON, non-candidate — EXCLUDED from quarantine
PROFILE_UNKNOWN = "unknown"

_DEV_MODE_ALIASES = {"dev-mode", "dev_mode", "devmode", "dev"}
_DOGFOOD_ALIASES = {"dogfood", "dogfood-ring", "candidate"}


def normalize_profile(value: object) -> str:
    """Normalize a container's profile label to ``dev-mode`` / ``dogfood`` /
    ``unknown``. The label key/values are owned by Story 4.1 (#974); this probe
    consumes them. Only an explicit dev-mode marker excludes from quarantine."""
    if not isinstance(value, str):
        return PROFILE_UNKNOWN
    v = value.strip().lower()
    if v in _DEV_MODE_ALIASES:
        return DEV_MODE
    if v in _DOGFOOD_ALIASES:
        return DOGFOOD
    return PROFILE_UNKNOWN


def quarantine_eligible(profile: object) -> bool:
    """dev-mode is EXCLUDED from quarantine (R-22); everything else is eligible.

    Exclusion requires an **explicit** ``dev-mode`` label: an unlabeled/unknown
    candidate stays quarantine-eligible so a broken candidate can never escape the
    probe simply by carrying no label. (R-21: dev-mode is the *labeled*
    non-candidate; absence of that label means "candidate".)"""
    return normalize_profile(profile) != DEV_MODE


# --- transcript parsing (host-side, kit-independent) --------------------------


def parse_timestamp(value: object) -> datetime | None:
    """Parse an ISO-8601 transcript timestamp to an aware UTC datetime, or None.

    Tolerates the trailing ``Z`` and naive stamps (assumed UTC). A malformed or
    missing stamp is ``None`` — never an exception (a partially flushed tail must
    not crash the probe)."""
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


def read_transcript(path: object) -> list[dict]:
    """Parse a host-backed Claude Code ``.jsonl`` transcript into a list of entries.

    Reads the file **directly off the host filesystem** — no container exec, no kit
    import (R-15). Each line is one JSON object; blank and malformed lines are
    skipped (fate-independent: a truncated last line from a hard-killed agent must
    degrade the signal, not crash the probe). A missing file yields ``[]``."""
    p = Path(str(path)).expanduser()
    if not p.is_file():
        return []
    entries: list[dict] = []
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
                entries.append(obj)
    return entries


def last_activity(entries: list[dict]) -> datetime | None:
    """The most recent entry timestamp across the transcript, or None if none carry
    a parseable timestamp. Uses the max (not merely the last line) so an
    out-of-order or malformed tail cannot understate freshness."""
    latest: datetime | None = None
    for e in entries:
        if not isinstance(e, dict):
            continue
        ts = parse_timestamp(e.get("timestamp"))
        if ts is not None and (latest is None or ts > latest):
            latest = ts
    return latest


def _stable_input_key(obj: object) -> str:
    """A canonical, order-stable key for a tool_use ``input`` so two identical
    calls compare equal regardless of dict key order."""
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return repr(obj)


def tool_signatures(entries: list[dict]) -> list[str]:
    """The chronological sequence of tool-use signatures (``name:input``) across the
    transcript. Loop detection runs on **tool actions only** — the Dev Spec's
    "same tool K times" heuristic (§5.7) — deliberately ignoring assistant/user
    prose so ordinary repeated phrasing can never be mistaken for a loop."""
    sigs: list[str] = []
    for e in entries:
        if not isinstance(e, dict):
            continue
        msg = e.get("message")
        content = msg.get("content") if isinstance(msg, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                name = block.get("name", "?")
                sigs.append(f"{name}:{_stable_input_key(block.get('input'))}")
    return sigs


@dataclass(frozen=True)
class LoopResult:
    looping: bool
    detail: str = ""


def detect_loop(
    signatures: list[str],
    *,
    min_repeats: int = DEFAULT_LOOP_MIN_REPEATS,
    max_period: int = DEFAULT_LOOP_MAX_PERIOD,
) -> LoopResult:
    """Detect a "no forward progress" loop in a tool-signature sequence.

    Two shapes, checked at the **tail** (the live edge of the transcript):

    * a single action repeated ``min_repeats`` times in a row (period-1); and
    * a period-``p`` cycle (2..``max_period``) repeated ``min_repeats`` times —
      e.g. an ``A B A B A B`` two-tool ping-pong.

    Conservative by construction: it needs ``min_repeats`` *consecutive* identical
    blocks ending at the tail, so a loop that has since broken (forward progress
    resumed) does not read as looping."""
    n = len(signatures)
    if min_repeats < 1 or n < min_repeats:
        return LoopResult(False)

    # period-1: the same action repeated at the tail.
    last = signatures[-1]
    run = 0
    for s in reversed(signatures):
        if s == last:
            run += 1
        else:
            break
    if run >= min_repeats:
        return LoopResult(True, f"the same tool action repeated {run}x at the tail: {last}")

    # period-p cycle repeated at the tail.
    for period in range(2, max_period + 1):
        if n < period * min_repeats:
            continue
        block = signatures[-period:]
        reps = 0
        idx = n
        while idx - period >= 0 and signatures[idx - period : idx] == block:
            reps += 1
            idx -= period
        if reps >= min_repeats:
            return LoopResult(
                True, f"a period-{period} tool cycle repeated {reps}x at the tail"
            )
    return LoopResult(False)


# --- health classification (R-16) ---------------------------------------------

HEALTHY = "healthy"
STALLED = "stalled"
LOOPING = "looping"


@dataclass(frozen=True)
class HealthVerdict:
    status: str
    broken: bool
    stalled: bool
    looping: bool
    reasons: tuple[str, ...]
    idle_seconds: float | None
    last_activity: datetime | None

    @property
    def state(self) -> str:
        if self.stalled and self.looping:
            return "stalled+looping"
        if self.stalled:
            return STALLED
        if self.looping:
            return LOOPING
        return HEALTHY

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "state": self.state,
            "broken": self.broken,
            "stalled": self.stalled,
            "looping": self.looping,
            "idle_seconds": self.idle_seconds,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            "reasons": list(self.reasons),
        }


def classify_health(
    *,
    entries: list[dict],
    status: object,
    now: datetime | None = None,
    last_growth: datetime | None = None,
    stall_after_seconds: float = DEFAULT_STALL_SECONDS,
    loop_min_repeats: int = DEFAULT_LOOP_MIN_REPEATS,
    loop_max_period: int = DEFAULT_LOOP_MAX_PERIOD,
) -> HealthVerdict:
    """Classify one container's health from its transcript + aoe status (R-16).

    Both break signals are **gated on ``running``**: a flat or repetitive
    transcript while ``idle``/``waiting``/``stopped``/``error``/``unknown`` is not a
    break — the agent is not executing, so silence is expected. While ``running``:

    * **stall** — the transcript has not grown for ``stall_after_seconds``. Growth
      time is ``max`` of the last entry's timestamp and any externally observed
      ``last_growth`` (a watcher's file-mtime probe). With neither available the
      stall dimension is *unevaluated* (never asserted) — a just-launched container
      must not read as stalled.
    * **loop** — :func:`detect_loop` finds a repeating tool cycle at the tail.
    """
    now = now or datetime.now(timezone.utc)
    st = normalize_status(status)

    growth = last_activity(entries)
    if last_growth is not None and (growth is None or last_growth > growth):
        growth = last_growth
    idle_seconds = (now - growth).total_seconds() if growth is not None else None

    if st != RUNNING:
        return HealthVerdict(
            status=st,
            broken=False,
            stalled=False,
            looping=False,
            reasons=(
                f"status={st}: not running — a flat or repetitive transcript is "
                f"not a stall/loop while the agent is not executing (R-16 gates "
                f"both signals on running)",
            ),
            idle_seconds=idle_seconds,
            last_activity=growth,
        )

    reasons: list[str] = []

    stalled = idle_seconds is not None and idle_seconds >= stall_after_seconds
    if stalled:
        reasons.append(
            f"running + transcript flat for {idle_seconds / 60:.1f} min "
            f"(>= {stall_after_seconds / 60:.0f} min threshold) [R-16 stall]"
        )
    elif idle_seconds is None:
        reasons.append(
            "running but no timestamped activity yet — stall not timed "
            "(possibly just launched); not asserting a break"
        )

    loop = detect_loop(
        tool_signatures(entries),
        min_repeats=loop_min_repeats,
        max_period=loop_max_period,
    )
    looping = loop.looping
    if looping:
        reasons.append(f"running + loop signal: {loop.detail} [R-16 loop]")

    broken = stalled or looping
    if not broken:
        reasons.append(
            f"running + transcript progressing "
            f"({'idle %.1f min < threshold' % (idle_seconds / 60) if idle_seconds is not None else 'active'}), "
            f"no loop signal — healthy"
        )

    return HealthVerdict(
        status=st,
        broken=broken,
        stalled=stalled,
        looping=looping,
        reasons=tuple(reasons),
        idle_seconds=idle_seconds,
        last_activity=growth,
    )


# --- container assessment (health + profile filter) ---------------------------


@dataclass(frozen=True)
class Assessment:
    container_id: str
    title: str
    profile: str
    health: HealthVerdict
    quarantine_eligible: bool
    should_quarantine: bool
    reasons: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "title": self.title,
            "profile": self.profile,
            "quarantine_eligible": self.quarantine_eligible,
            "should_quarantine": self.should_quarantine,
            "health": self.health.as_dict(),
            "reasons": list(self.reasons),
        }


def assess(
    *,
    container_id: str,
    title: str,
    status: object,
    profile: object,
    entries: list[dict],
    now: datetime | None = None,
    last_growth: datetime | None = None,
    stall_after_seconds: float = DEFAULT_STALL_SECONDS,
    loop_min_repeats: int = DEFAULT_LOOP_MIN_REPEATS,
    loop_max_period: int = DEFAULT_LOOP_MAX_PERIOD,
) -> Assessment:
    """Assess one container: classify health (R-16), then apply the profile filter
    (R-22). ``should_quarantine`` is True **iff** the container is broken AND
    quarantine-eligible; a broken **dev-mode** container is reported broken but
    excluded (``should_quarantine = False``), never tripping quarantine or soak."""
    health = classify_health(
        entries=entries,
        status=status,
        now=now,
        last_growth=last_growth,
        stall_after_seconds=stall_after_seconds,
        loop_min_repeats=loop_min_repeats,
        loop_max_period=loop_max_period,
    )
    prof = normalize_profile(profile)
    eligible = quarantine_eligible(profile)
    reasons = list(health.reasons)
    if health.broken and not eligible:
        reasons.append(
            f"profile={prof}: dev-mode is EXCLUDED from quarantine — this breakage "
            f"does not trip quarantine or count toward soak [R-22]"
        )
    return Assessment(
        container_id=str(container_id),
        title=str(title),
        profile=prof,
        health=health,
        quarantine_eligible=eligible,
        should_quarantine=bool(health.broken and eligible),
        reasons=tuple(reasons),
    )


def assess_record(rec: dict, *, now: datetime | None = None, **params) -> Assessment:
    """Assess one observation record from the ``--observations`` manifest.

    Each record: ``container_id``, ``title``, ``status``, ``profile``, and either a
    ``transcript`` (host path — read directly, R-15) or inline ``entries``. An
    optional ``last_growth`` (ISO-8601) supplies a watcher's file-mtime probe."""
    if not isinstance(rec, dict):
        raise SurgeonError(f"observation must be an object, got {type(rec).__name__}")
    if "entries" in rec:
        entries = rec["entries"] if isinstance(rec["entries"], list) else []
    else:
        entries = read_transcript(rec.get("transcript", ""))
    return assess(
        container_id=rec.get("container_id", rec.get("id", "?")),
        title=rec.get("title", "?"),
        status=rec.get("status"),
        profile=rec.get("profile"),
        entries=entries,
        now=now,
        last_growth=parse_timestamp(rec.get("last_growth")),
        **params,
    )


class SurgeonError(ValueError):
    """A flight-surgeon contract violation. Raised LOUD, never swallowed."""


# --- aoe-side discovery helpers (the live seam) -------------------------------


def parse_status_table(text: str) -> dict[str, str]:
    """Parse ``aoe status -v`` (human output) into ``{session_title: state}``.

    The output groups sessions under uppercase state headers — ``RUNNING (1):``,
    ``IDLE (8):``, ``STOPPED (20):``, and (when present) ``WAITING`` / ``ERROR`` —
    followed by ``  <spinner> <title> <tool> <path>`` lines. This maps each title
    to its lowercased state so the gather step can correlate a session's state with
    its transcript (R-16 needs the ``running`` gate)."""
    states: dict[str, str] = {}
    current: str | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line:
            continue
        stripped = line.strip()
        header = stripped.split(" ", 1)[0].rstrip(":").lower()
        # A header line starts at column 0 and names a known state.
        if not line[0].isspace() and header in _RUN_STATES:
            current = header
            continue
        if current is None:
            continue
        # A session row: "<spinner> <title> <tool> <path>". Drop the leading
        # spinner glyph, then take the first whitespace-delimited field as title.
        parts = stripped.split()
        if not parts:
            continue
        # The first token is a spinner glyph (non-word); the title follows.
        fields = parts[1:] if len(parts) > 1 else parts
        if fields:
            states[fields[0]] = current
    return states


def _run(cmd: list[str], *, timeout: float = 30.0) -> str:
    """Run a command and return stdout (empty string on any failure — the live
    gather is best-effort; the deterministic contract is the observations path)."""
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


def discover_sessions(runner=_run) -> list[dict]:
    """List aoe sessions via ``aoe list --json`` (id/title/path/profile/...)."""
    out = runner(["aoe", "list", "--json"])
    if not out.strip():
        return []
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []
    return [s for s in data if isinstance(s, dict)] if isinstance(data, list) else []


# --- reporting / CLI ----------------------------------------------------------


def report_summary(assessments: list[Assessment]) -> str:
    lines = ["flight surgeon — health report:"]
    for a in assessments:
        mark = "QUARANTINE" if a.should_quarantine else ("BROKEN(excluded)" if a.health.broken else "ok")
        lines.append(
            f"  [{mark}] {a.title} ({a.container_id}) "
            f"status={a.health.status} profile={a.profile} state={a.health.state}"
        )
        for r in a.reasons:
            lines.append(f"      - {r}")
    n_q = sum(1 for a in assessments if a.should_quarantine)
    lines.append(f"  => {len(assessments)} watched, {n_q} quarantine-eligible break(s)")
    return "\n".join(lines)


def _load_observations(path: str) -> list[dict]:
    text = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text()
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("observations"), list):
        data = data["observations"]
    if not isinstance(data, list):
        raise SurgeonError("observations must be a JSON list (or {observations: [...]})")
    return data


def _gather_live(args, runner=_run) -> list[dict]:
    """Best-effort live gather over aoe sessions.

    UNPROVEN seam (Dev Spec TC-7 / §5.N, exercised by MV-04/MV-06): mapping a
    sandbox session to its host-backed transcript path and its ``oaw.profile``
    label depends on aoe's sandbox mount/label layout, which cannot be proven
    without a running sandbox. This resolves the transcript path under a
    configurable ``--transcripts-root`` (best-effort, newest ``.jsonl`` under the
    session's project) and leaves the profile ``unknown`` unless a label is wired.
    """
    sessions = discover_sessions(runner)
    states = parse_status_table(runner(["aoe", "status", "-v"]))
    root = Path(args.transcripts_root).expanduser()
    records: list[dict] = []
    for s in sessions:
        title = s.get("title", "?")
        transcript = _newest_transcript_for(root, s.get("path", ""))
        records.append(
            {
                "container_id": s.get("id", "?"),
                "title": title,
                "status": states.get(title, STATUS_UNKNOWN),
                "profile": s.get("profile_label", PROFILE_UNKNOWN),
                "transcript": str(transcript) if transcript else "",
            }
        )
    return records


def _newest_transcript_for(root: Path, project_path: str) -> Path | None:
    """Best-effort: the newest ``.jsonl`` under ``root`` whose name encodes
    ``project_path`` (Claude Code escapes the project path into the dir name).
    Returns None if nothing matches — the seam MV-04/MV-06 nail down."""
    if not root.is_dir() or not project_path:
        return None
    slug = project_path.strip("/").replace("/", "-")
    best: Path | None = None
    best_mtime = -1.0
    for jsonl in root.rglob("*.jsonl"):
        if slug and slug not in str(jsonl):
            continue
        try:
            m = jsonl.stat().st_mtime
        except OSError:
            continue
        if m > best_mtime:
            best, best_mtime = jsonl, m
    return best


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--observations",
        metavar="FILE",
        help="JSON manifest of container observations ('-' for stdin)",
    )
    src.add_argument(
        "--live",
        action="store_true",
        help="best-effort live gather over aoe sessions (flags the UNPROVEN seams)",
    )
    parser.add_argument(
        "--transcripts-root",
        default="~/.claude/projects",
        help="root to resolve host-backed transcripts under (--live)",
    )
    parser.add_argument(
        "--stall-seconds", type=float, default=DEFAULT_STALL_SECONDS,
        help=f"stall threshold in seconds (default {DEFAULT_STALL_SECONDS})",
    )
    parser.add_argument(
        "--loop-min-repeats", type=int, default=DEFAULT_LOOP_MIN_REPEATS,
        help=f"loop: min consecutive repeats (default {DEFAULT_LOOP_MIN_REPEATS})",
    )
    parser.add_argument(
        "--loop-max-period", type=int, default=DEFAULT_LOOP_MAX_PERIOD,
        help=f"loop: max cycle period (default {DEFAULT_LOOP_MAX_PERIOD})",
    )
    parser.add_argument(
        "--fail-on-quarantine", action="store_true",
        help="exit non-zero if any container is a quarantine-eligible break",
    )
    args = parser.parse_args(argv)

    params = dict(
        stall_after_seconds=args.stall_seconds,
        loop_min_repeats=args.loop_min_repeats,
        loop_max_period=args.loop_max_period,
    )

    try:
        records = _gather_live(args) if args.live else _load_observations(args.observations)
        now = datetime.now(timezone.utc)
        assessments = [assess_record(r, now=now, **params) for r in records]
    except (SurgeonError, OSError, json.JSONDecodeError) as exc:
        print(f"flight-surgeon error: {exc}", file=sys.stderr)
        return 2

    print(report_summary(assessments), file=sys.stderr)
    print(json.dumps([a.as_dict() for a in assessments], indent=2))

    if args.fail_on_quarantine and any(a.should_quarantine for a in assessments):
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
