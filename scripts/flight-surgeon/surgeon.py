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
    python3 surgeon.py --live --transcripts-root ~/.oaw/state/$OAW_MAJOR/transcripts

Emits a JSON report on stdout (one assessment per container) and a human summary
on stderr; exits 0 normally, or non-zero with ``--fail-on-quarantine`` if any
container is a quarantine-eligible break (a signal a watcher/cron can act on).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

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


# --- transcript root (#1064) --------------------------------------------------
#
# Sandbox transcripts are host-backed at ~/.oaw/state/<major>/transcripts (mounted
# to the container's ~/.claude/projects by mounts.d/05-transcripts.toml). This
# default USED to be ~/.claude/projects — the live fleet's own store — which is a
# confident wrong answer rather than a miss: `_newest_transcript_for` returns the
# newest .jsonl matching the workspace slug, so a container resolved against that
# root picks up a NATIVE session's transcript. Measured 2026-07-30 on this host: a
# container on the cc-workflow workspace resolved to the live native session's
# file, 19s stale.
#
# The failure is bidirectional. Natives running -> their transcripts are fresh ->
# every container reads healthy and quarantine never fires. Natives stopped (the
# big-bang cut-over) -> those transcripts go stale at once -> running containers
# read stalled and healthy candidates are false-quarantined.
#
# The default is the state ROOT, not a <major>-specific path: this module depends
# on the standard library only (R-15) and must not import the mount resolver to
# interpolate <major>. Resolution rglobs, so `~/.oaw/state` finds
# `<major>/transcripts/<slug>/*.jsonl` under any major — correct but deliberately
# wider than R-20's per-major isolation. Callers that know the major SHOULD pass
# the exact root (dogfood-cutover.sh does); this default only guarantees the bare
# `surgeon.py --live` invocation stays inside the sandbox tree rather than
# resolving fleet transcripts.
def _default_transcripts_root() -> str:
    """Sandbox transcript root, narrowed to $OAW_MAJOR when the fleet sets it.

    Spanning majors is not merely untidy: `_newest_transcript_for` picks by mtime
    across everything `rglob` reaches, so a freshly-launched major-8 container
    that has not written yet resolves to the leftover major-7 file for the same
    workspace — stale, therefore running+flat, therefore FALSE QUARANTINE. That is
    the same mechanic this issue fixes, narrowed from cross-fleet to cross-major,
    and R-20 exists precisely to keep majors isolated.

    `os.environ` is stdlib, so this respects R-15 (no mount-resolver import).
    """
    major = os.environ.get("OAW_MAJOR", "").strip()
    if major:
        return f"~/.oaw/state/{major}/transcripts"
    return "~/.oaw/state"


DEFAULT_TRANSCRIPTS_ROOT = _default_transcripts_root()

# Any transcripts root inside this tree is the live fleet's, not a sandbox's.
LIVE_FLEET_TREE = ".claude"


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
    # False when no transcript could be resolved for this session. A container with
    # no transcript classifies "running, no timestamped activity yet" -> broken=False,
    # i.e. it reads HEALTHY. The promotion gate consumes this JSON (not the stderr
    # warning), so the distinction between "measured and fine" and "never measured"
    # has to travel with the verdict (#1075). Defaults True so the observation-file
    # path — where the caller supplied entries directly — is unaffected.
    transcript_resolved: bool = True

    def as_dict(self) -> dict:
        return {
            "container_id": self.container_id,
            "title": self.title,
            "profile": self.profile,
            "quarantine_eligible": self.quarantine_eligible,
            "should_quarantine": self.should_quarantine,
            "transcript_resolved": self.transcript_resolved,
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
    a = assess(
        container_id=rec.get("container_id", rec.get("id", "?")),
        title=rec.get("title", "?"),
        status=rec.get("status"),
        profile=rec.get("profile"),
        entries=entries,
        now=now,
        last_growth=parse_timestamp(rec.get("last_growth")),
        **params,
    )
    # _gather_live stamps this; an observation file that omits it is treated as
    # resolved, preserving the pre-#1075 contract for hand-authored observations.
    return replace(a, transcript_resolved=bool(rec.get("transcript_resolved", True)))


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
        # UNMEASURED outranks "ok": a session with no resolvable transcript
        # classifies broken=False and would print [ok], which is the human summary
        # disagreeing with the machine verdict about the one thing that matters —
        # whether anything was actually checked (#1075).
        if a.should_quarantine:
            mark = "QUARANTINE"
        elif a.health.broken:
            mark = "BROKEN(excluded)"
        elif not a.transcript_resolved:
            mark = "UNMEASURED"
        else:
            mark = "ok"
        lines.append(
            f"  [{mark}] {a.title} ({a.container_id}) "
            f"status={a.health.status} profile={a.profile} state={a.health.state}"
        )
        for r in a.reasons:
            lines.append(f"      - {r}")
    n_q = sum(1 for a in assessments if a.should_quarantine)
    n_u = sum(1 for a in assessments if not a.transcript_resolved)
    tail = f", {n_u} UNMEASURED (no transcript resolved)" if n_u else ""
    lines.append(
        f"  => {len(assessments)} watched, {n_q} quarantine-eligible break(s){tail}"
    )
    return "\n".join(lines)


def _load_observations(path: str) -> list[dict]:
    text = sys.stdin.read() if path == "-" else Path(path).expanduser().read_text()
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("observations"), list):
        data = data["observations"]
    if not isinstance(data, list):
        raise SurgeonError("observations must be a JSON list (or {observations: [...]})")
    return data


class FleetTranscriptRootError(SurgeonError):
    """The transcripts root points at the live fleet's store, not a sandbox's.

    Subclasses SurgeonError deliberately: as a bare RuntimeError it escaped
    ``main()``'s ``except`` tuple, so the carefully-worded refusal arrived as the
    tail of a stack trace and the exit code was 1 instead of the documented 2
    (usage error). One taxonomy, one exit contract.
    """


def assert_sandbox_transcripts_root(root: Path, *, allow_fleet: bool = False) -> None:
    """Refuse a transcripts root inside the live-fleet tree (#1064).

    A container resolved against ``~/.claude/projects`` does not fail to find a
    transcript — it finds a NATIVE session's and classifies confidently on it.
    That is why this raises instead of warning: a warning on a probe whose whole
    job is to notice silence would itself be noise the operator learns to skip.

    ``allow_fleet=True`` is the deliberate escape hatch for the pre-cut-over case
    where the fleet IS the thing being watched.
    """
    if allow_fleet:
        return
    # Check BOTH forms. resolve() follows symlinks, so a fleet whose ~/.claude is
    # a symlink to /mnt/data/claude-config resolves to parts containing no
    # ".claude" and the guard would pass on the fleet's actual store — failing
    # OPEN, the one direction this whole issue is about. mount_resolver's
    # check_sandbox_scoped_memory reasons over normalized path TEXT and never
    # touches the filesystem; this matches that.
    candidates = {root.parts}
    try:
        candidates.add(root.resolve().parts)
    except OSError:
        pass
    if any(LIVE_FLEET_TREE in parts for parts in candidates):
        raise FleetTranscriptRootError(
            f"transcripts root {root} is inside the live-fleet tree "
            f"({LIVE_FLEET_TREE}). Sandbox transcripts are host-backed under "
            f"{DEFAULT_TRANSCRIPTS_ROOT}/<major>/transcripts "
            "(mounts.d/05-transcripts.toml). Resolving a container against the "
            "fleet's store yields a confident verdict about the wrong process — "
            "healthy while natives run, stalled once they stop. Pass "
            "--allow-fleet-transcripts only if you mean to watch the fleet itself."
        )


def _gather_live(args, runner=_run) -> list[dict]:
    """Best-effort live gather over aoe sessions.

    UNPROVEN seam (Dev Spec TC-7 / §5.N, exercised by MV-04/MV-06): mapping a
    sandbox session to its host-backed transcript path and its ``oaw.profile``
    label depends on aoe's sandbox mount/label layout, which cannot be proven
    without a running sandbox. This resolves the transcript path under a
    configurable ``--transcripts-root`` (best-effort, newest ``.jsonl`` under the
    session's project) and leaves the profile ``unknown`` unless a label is wired.
    """
    # Refuse FIRST — before spending two aoe subprocesses on a root we reject.
    root = Path(args.transcripts_root).expanduser()
    assert_sandbox_transcripts_root(
        root, allow_fleet=getattr(args, "allow_fleet_transcripts", False)
    )
    sessions = discover_sessions(runner)
    states = parse_status_table(runner(["aoe", "status", "-v"]))
    records: list[dict] = []
    unresolved: list[str] = []
    for s in sessions:
        title = s.get("title", "?")
        transcript = _newest_transcript_for(
            root, s.get("path", ""),
            allow_fleet=getattr(args, "allow_fleet_transcripts", False),
        )
        if transcript is None:
            unresolved.append(title)
        records.append(
            {
                "container_id": s.get("id", "?"),
                "title": title,
                "status": states.get(title, STATUS_UNKNOWN),
                "profile": s.get("profile_label", PROFILE_UNKNOWN),
                "transcript": str(transcript) if transcript else "",
                # Distinguish "read it, agent is fine" from "found no transcript".
                # Without this an unresolved session yields transcript "" ->
                # read_transcript [] -> classify_health "no timestamped activity
                # yet" -> broken=False, and the promotion gate accrues soak for a
                # session whose health was never measured. Silence that reads as
                # health is the failure class this issue exists to remove.
                "transcript_resolved": transcript is not None,
            }
        )
    if unresolved:
        print(
            f"surgeon: WARNING {len(unresolved)}/{len(sessions)} session(s) had NO "
            f"resolvable transcript under {root} — their health was NOT measured: "
            + ", ".join(unresolved),
            file=sys.stderr,
        )
    return records


# aoe mounts a session's workspace at /workspace/<name> inside the sandbox, NOT at
# its host path. Measured from a live container during MV-05 (2026-07-31):
#
#   docker inspect  ->  /tmp/mv05-ws -> /workspace/mv05-ws,  WorkingDir /workspace/mv05-ws
#   /proc/<claude>/cwd (in-container)  ->  /workspace/mv05-ws
#
# Claude Code derives its transcript dir from CWD, so a containerised agent writes
# under `-workspace-<name>` while `aoe list` reports the HOST path (`/tmp/mv05-ws`).
# Slugging the host path yields `-tmp-mv05-ws`, which can never match — so before
# #1075 the surgeon resolved NOTHING for any containerised session, every container
# read healthy, quarantine never fired, and soak accrued on unmeasured sessions.
#
# Nothing in the repo documents this mapping (mounts.d targets /home/ubuntu/..., the
# docs say "host-backed" without a container-side path, and aoe is a compiled
# binary), which is why static verification could not catch it and MV-05 did.
CONTAINER_WORKSPACE_ROOT = "/workspace"


def container_workspace_path(host_path: str) -> str:
    """The in-container path aoe mounts ``host_path`` at.

    Convention, not contract — this repo does not own aoe's mount layout, so it is
    pinned by MV-05 reading a real container rather than by belief. If aoe changes
    it, the manual-verification cross-check is what catches it; a silent mismatch
    here is exactly the failure #1075 fixes.
    """
    name = PurePosixPath(host_path.rstrip("/")).name
    # No basename ("/", "", ".") -> return empty so the caller treats it as
    # unresolved. Falling back to host_path would be the one path this function
    # exists to avoid.
    return f"{CONTAINER_WORKSPACE_ROOT}/{name}" if name else ""


def _slug(path: str) -> str:
    """The inner part of Claude Code's project-dir name: `/` -> `-`, ends stripped.

    NOT the full directory name — CC keeps a LEADING dash (`/workspace/x` ->
    `-workspace-x`). Callers add it. An earlier docstring claimed this produced the
    whole name, which was only harmless because the match was a loose substring.
    """
    return path.strip("/").replace("/", "-")


def _newest_transcript_for(
    root: Path, project_path: str, *, allow_fleet: bool = False
) -> Path | None:
    """The newest ``.jsonl`` under ``root`` for ``project_path``.

    ``project_path`` is the HOST path (what ``aoe list`` reports). The transcript is
    written by the agent INSIDE the container, so the lookup slugs the *container*
    workspace path — see CONTAINER_WORKSPACE_ROOT above. Returns None if nothing
    matches, which callers must surface (``transcript_resolved``) rather than treat
    as health.
    """
    if not root.is_dir() or not project_path:
        return None
    # Fleet mode watches NATIVE sessions, whose cwd IS the host path — converting
    # to /workspace/<name> would match nothing and report every fleet session
    # unmeasured. That is the pre-cut-over configuration, i.e. the one usable
    # today, so the escape hatch has to reach here and not stop at _gather_live.
    lookup = project_path if allow_fleet else container_workspace_path(project_path)
    slug = _slug(lookup)
    if not slug or slug == ".":
        # An empty slug would disable filtering entirely (`if slug and ...` below),
        # returning the newest .jsonl ANYWHERE under the root and calling it
        # resolved — precisely the confident-wrong-verdict this issue removes.
        return None
    best: Path | None = None
    best_mtime = -1.0
    # EXACT parent-directory match, not a substring of the full path. Claude Code
    # names the dir with a LEADING dash (`-workspace-mv05-ws`), and a substring test
    # let `workspace-app` match `-workspace-app-2/...` — a wedged agent inheriting a
    # neighbour's transcript is the same wrong-process verdict, one level down.
    want = f"-{slug}"
    for jsonl in root.rglob("*.jsonl"):
        if jsonl.parent.name != want:
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
        default=DEFAULT_TRANSCRIPTS_ROOT,
        help=(
            "root to resolve host-backed sandbox transcripts under (--live); "
            f"default {DEFAULT_TRANSCRIPTS_ROOT}. Pointing this at "
            "~/.claude/projects resolves the NATIVE fleet's transcripts, not the "
            "containers' — see --allow-fleet-transcripts"
        ),
    )
    parser.add_argument(
        "--allow-fleet-transcripts",
        action="store_true",
        help=(
            "permit a --transcripts-root inside the live-fleet tree (~/.claude). "
            "Refused by default: a container resolved against a fleet transcript "
            "yields a confident verdict about the wrong process (#1064)"
        ),
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
