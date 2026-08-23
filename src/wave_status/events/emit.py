"""FlightDeck emit core — durable buffer + fire-and-forget shipper (S1.1 / #863).

The lowest-deterministic-layer emitter. Every state change routes through
:func:`emit`, which:

1. builds + validates the event against the S0.1 contract
   (:mod:`wave_status.events`);
2. atomically appends it as one JSONL line to the durable local buffer
   (``~/.claude/status/events.jsonl`` by default) [R-01];
3. ships it non-blocking to ``$FLIGHTDECK_INGEST_URL`` with bearer-token auth,
   in a daemon thread, off the caller's hot path [R-02];
4. replays unsent buffered lines in order via an offset marker when the ingest
   endpoint recovers [R-04].

**Contract: never raises to the caller.** Emit is instrumentation; a bug here
must never break a state mutation, a Stop hook, or a Workflow node. Every public
entrypoint swallows all exceptions (R-03). **Stdlib-only** (TC-1) — POST via
``urllib.request``, no third-party HTTP client.

DI-seams (env vars):

- ``FLIGHTDECK_INGEST_URL``   — POST target. **Unset ⇒ buffer-only**, never ships,
  never raises (R-03 default).
- ``FLIGHTDECK_INGEST_TOKEN`` — bearer token for the ``Authorization`` header.
- ``FLIGHTDECK_INGEST_TIMEOUT`` — POST timeout seconds (default 2).
- ``FLIGHTDECK_EVENTS_PATH``  — override the buffer file (test isolation).
- ``FLIGHTDECK_EMIT_DISABLED``— hard off switch (no-op emit).
- ``FLIGHTDECK_ACTIVITY_ID`` / ``FLIGHTDECK_AGENT`` / ``FLIGHTDECK_LOG_REF`` —
  scope defaults for :func:`emit_state_event`.
- ``FLIGHTDECK_SCOPE_PATH``   — override the #1148 scope-marker file (test
  isolation). Unset ⇒ ``<cwd>/.claude/status/flightdeck-scope.json``.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import os
import sys
import threading
import urllib.request
from pathlib import Path

from wave_status.events import build_event, now_iso, validate_event

__all__ = [
    "emit",
    "emit_state_event",
    "ship",
    "replay",
    "buffer_path",
    "activity_id_for_root",
    "flush_pending_ships",
]

# Sentinel so ``value=None`` (a seamed-absent metric, #853 token stub) is
# distinguishable from "value not supplied".
_UNSET = object()

# Daemon threads started by `_ship_async`, not yet joined (#1149). Populated
# here, drained by `flush_pending_ships` — see that function's docstring for
# why the join lives at the true top-level exit point and nowhere else.
_pending_ships: list[threading.Thread] = []

# Map the ergonomic snake_case emit() kwargs to the schema's camelCase keys.
# ``activity_type`` and ``host`` (#947) are additive convention fields — the
# schema's ``additionalProperties: true`` carries them; both validators ignore
# unknown keys. ``activityType: session`` marks presence (never a campaign card);
# ``host`` is the emitting machine, distinct from ``agent`` (Dev-Name).
_FIELD_KEYS: dict[str, str] = {
    "wave": "wave",
    "phase": "phase",
    "flight": "flight",
    "agent": "agent",
    "log_ref": "logRef",
    "concern_kind": "concernKind",
    "source": "source",
    "metric": "metric",
    "unit": "unit",
    "action": "action",
    "label": "label",
    "detail": "detail",
    "activity_type": "activityType",
    "host": "host",
}


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def buffer_path() -> Path:
    """Resolve the durable buffer path (env override → default ~/.claude)."""
    override = os.environ.get("FLIGHTDECK_EVENTS_PATH")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".claude" / "status" / "events.jsonl"


def _offset_path(buffer: Path) -> Path:
    """The offset-marker sidecar for *buffer* (records bytes already shipped)."""
    return Path(str(buffer) + ".offset")


def activity_id_for_root(root: object) -> str:
    """Derive a stable ``activityId`` for a repo *root*.

    ``FLIGHTDECK_ACTIVITY_ID`` wins (an operator/driver can pin one campaign id);
    otherwise the repo directory name. Falls back to ``"unknown"`` — never raises.
    """
    env = os.environ.get("FLIGHTDECK_ACTIVITY_ID")
    if env:
        return env
    try:
        name = Path(str(root)).resolve().name
        return name or "unknown"
    except Exception:
        return "unknown"


def _dev_name_from(path: Path) -> str | None:
    """Read ``dev_name`` from a JSON identity file, or ``None``. Never raises
    (missing file, malformed JSON, non-dict, and empty name all yield ``None``)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("dev_name")
        return name if isinstance(name, str) and name else None
    except Exception:
        return None


def resolve_agent(root: object) -> str | None:
    """Resolve the emitting agent's Dev-Name for the FlightDeck card title (#1026).

    Resolution order, mirroring ``scripts/flightdeck-session-emit.sh`` and the
    CLAUDE.md identity rule:

    1. ``FLIGHTDECK_AGENT`` env (an operator/driver can pin it);
    2. the canonical ``<root>/.claude/agent-identity.json`` ``dev_name``;
    3. the legacy ``/tmp/claude-agent-<md5(root)>.json`` ``dev_name`` — the
       transition-window fallback while the fleet cycles off the /tmp scheme.

    Returns ``None`` when none resolve, so the card render falls back to the
    project label rather than showing a hostname. Never raises.
    """
    env = os.environ.get("FLIGHTDECK_AGENT")
    if env:
        return env
    root_s = str(root)
    name = _dev_name_from(Path(root_s) / ".claude" / "agent-identity.json")
    if name:
        return name
    try:
        digest = hashlib.md5(root_s.encode("utf-8")).hexdigest()  # noqa: S324 (non-crypto keying)
    except Exception:
        return None
    return _dev_name_from(Path("/tmp") / f"claude-agent-{digest}.json")


# ---------------------------------------------------------------------------
# Buffer write (atomic append) + offset marker
# ---------------------------------------------------------------------------

def _atomic_append(buffer: Path, line: str) -> None:
    """Append one JSONL *line* to *buffer* atomically.

    Uses a single ``os.write`` to an ``O_APPEND`` fd — the kernel serializes
    concurrent appends of a small record, so interleaved writers never tear a
    line (POSIX ``O_APPEND`` semantics).
    """
    buffer.parent.mkdir(parents=True, exist_ok=True)
    data = (line + "\n").encode("utf-8")
    fd = os.open(str(buffer), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def _read_offset(buffer: Path) -> int:
    try:
        return int(_offset_path(buffer).read_text(encoding="utf-8").strip() or "0")
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# FlightDeck scope marker (#1148) — the writer half of mcp-server-sdlc#537.
#
# `sdlc-server`'s own handlers (ci_wait_run, pr_merge, wave_finalize,
# commutativity_verify, drift_*, wave_ci_trust_level) run inside the MCP SERVER
# process, which is already spawned by the time a campaign starts. A driver's
# in-session `export FLIGHTDECK_ACTIVITY_ID=...` (skills/wavemachine/SKILL.md)
# runs in a Bash tool subprocess and can never reach that already-running
# process's env — confirmed live via /proc/<pid>/environ on three running
# servers, each frozen at spawn with no FLIGHTDECK_ACTIVITY_ID at all, falling
# through to a repo-basename card (#1144's sdlc-server-side mechanism).
#
# This marker is the fix: a small durable per-repo file, read FRESH on every
# call (no restart dependency), that the CLI writes the moment it knows the
# campaign's real scope — construction, not one more line of skill prose for a
# driver to forget.
#
# CONTRACT (identical on the read side, mcp-server-sdlc#537):
#   path:  <cwd>/.claude/status/flightdeck-scope.json
#   shape: {"activityId": "<str>", "agent": "<str|null>", "updatedAt": "<ISO8601>"}

def _scope_marker_path() -> Path:
    override = os.environ.get("FLIGHTDECK_SCOPE_PATH")
    if override:
        return Path(override).expanduser()
    return Path.cwd() / ".claude" / "status" / "flightdeck-scope.json"


def _write_scope_marker(activity_id: str, agent: str | None) -> None:
    """Atomic write: temp file in the SAME directory, then os.replace() —
    guarantees a same-filesystem rename (mirrors state.py's save_json, R-33).

    Unlike save_json, this never raises to the caller (R-01/R-03: a broken
    marker write must never fail the emit that triggered it) — but a failure
    still cleans up its own temp file rather than leaving an orphan behind in
    .claude/status/ (gitignored, so an orphan would silently accumulate,
    one per failed write, forever).
    """
    fd = None
    try:
        path = _scope_marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"activityId": activity_id, "agent": agent, "updatedAt": now_iso()}
        fd = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(path.parent), suffix=".tmp", delete=False
        )
        json.dump(payload, fd)
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(fd.name, path)
    except Exception:
        if fd is not None:
            try:
                fd.close()
            except Exception:
                pass
            try:
                os.unlink(fd.name)
            except OSError:
                pass


def _clear_scope_marker_if_matching(activity_id: str) -> None:
    """Clear the marker on activity_end, but ONLY if it names the activity that
    is actually ending. An unrelated activity_end in the same repo (a session
    close, a different activity) must not wipe a live campaign's marker out
    from under it. Never raises.
    """
    try:
        path = _scope_marker_path()
        current = json.loads(path.read_text(encoding="utf-8"))
        # Read-check-unlink is NOT atomic: a concurrent activity_start for a
        # DIFFERENT campaign in this repo could land between the read and the
        # unlink, and this would delete that new marker instead of the one it
        # checked. Accepted rather than locked — the wavemachine pre-flight
        # already refuses a second concurrent campaign per repo, so the window
        # requires two overlapping campaigns to matter, and a lockfile is
        # disproportionate for fire-and-forget instrumentation.
        if current.get("activityId") == activity_id:
            path.unlink()
    except Exception:
        pass


def _write_offset(buffer: Path, offset: int) -> None:
    try:
        _offset_path(buffer).write_text(str(offset), encoding="utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Shipper (fire-and-forget POST + ordered replay)
# ---------------------------------------------------------------------------

def _post(url: str, body: str) -> bool:
    """POST *body* to *url* with optional bearer auth. True on 2xx, else False.

    Never raises — a down/unreachable ingest returns False so the caller keeps
    the event buffered (R-03).
    """
    token = os.environ.get("FLIGHTDECK_INGEST_TOKEN")
    try:
        timeout = float(os.environ.get("FLIGHTDECK_INGEST_TIMEOUT", "2"))
    except (TypeError, ValueError):
        timeout = 2.0
    try:
        req = urllib.request.Request(
            url,
            data=body.encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            return 200 <= int(status) < 300
    except Exception:
        return False


def ship(buffer: Path | None = None) -> int:
    """Replay unsent buffered lines to the ingest endpoint, in order.

    Reads from the offset marker to EOF; POSTs each complete line; advances the
    offset only past a line that shipped 2xx. On the first failure it STOPS,
    leaving the offset at the unshipped line so the next call resumes in order
    (R-04). Returns the number of lines shipped. No-op (0) when
    ``FLIGHTDECK_INGEST_URL`` is unset (DI-seam, R-03). Never raises.
    """
    url = os.environ.get("FLIGHTDECK_INGEST_URL")
    if not url:
        return 0
    buf = buffer or buffer_path()
    shipped = 0
    try:
        if not buf.exists():
            return 0
        offset = _read_offset(buf)
        with open(buf, "r", encoding="utf-8") as f:
            try:
                f.seek(offset)
            except Exception:
                f.seek(0)
            while True:
                line = f.readline()
                if not line:
                    break
                if not line.endswith("\n"):
                    # Partial line (a writer is mid-append) — retry next round.
                    break
                stripped = line.strip()
                if stripped and not _post(url, stripped):
                    break  # keep offset here; ordered replay on recovery.
                _write_offset(buf, f.tell())
                if stripped:
                    shipped += 1
    except Exception:
        return shipped
    return shipped


#: Alias — the spec's "replay unsent buffered lines" IS :func:`ship`.
replay = ship


def _ship_async(buffer: Path) -> None:
    """Fire :func:`ship` in a daemon thread so the caller never blocks (R-02).

    The thread is registered in :data:`_pending_ships` so a true top-level exit
    can bound-join it (:func:`flush_pending_ships`, #1149) — never joined here,
    which would defeat R-02 for every in-process caller.
    """
    if not os.environ.get("FLIGHTDECK_INGEST_URL"):
        return  # DI-seam: buffer-only, no thread.
    try:
        t = threading.Thread(
            target=ship, args=(buffer,), daemon=True, name="flightdeck-ship"
        )
        t.start()
        _pending_ships.append(t)
    except Exception:
        pass


def _flush_std_streams() -> None:
    """Best-effort ``stdout``/``stderr`` flush ahead of ``os._exit`` (#1149).

    Never raises: a closed pipe on the READING end (``wave-status show |
    head -1``) makes ``flush()`` raise ``BrokenPipeError``, and letting that
    propagate out of a ``finally`` block would skip the ``os._exit()`` call
    right after it — turning a clean, fast exit into a shutdown traceback.
    Best-effort is the correct contract here anyway: os._exit truncates an
    unflushed buffer no worse than any other abrupt exit would.
    """
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        sys.stderr.flush()
    except Exception:
        pass


def flush_pending_ships(timeout: float | None = None) -> None:
    """Bound-join every outstanding shipper thread before a REAL process exit.

    #1149: a daemon thread mid-flight in an SSL/socket call when CPython's
    interpreter finalization tears down C-extension state it still depends on
    is a known segfault class. `_ship_async` never blocks its caller (R-02) —
    that contract must hold for every IN-PROCESS caller of :func:`emit`
    (``_cmd_emit``, ``_cmd_campaign_head``, direct test calls), so this
    function must be called ONLY from :func:`_run_as_script` — never from
    :func:`emit`, :func:`main`, or any command handler. Calling it anywhere
    else reintroduces exactly the caller-blocking cost R-02 exists to avoid,
    on every state mutation, not just the crash-prone one.

    `_run_as_script` has THREE callers, not two — this is the exact blind
    spot that let the original fix land as dead code in production (a code
    review caught it before merge, not after): this module's own
    ``if __name__ == "__main__":`` guard, ``wave_status/__main__.py``'s
    (the real ``wave-status`` CLI's entry when invoked as
    ``python -m wave_status``), and the zipapp shim
    ``scripts/ci/build.sh`` generates for the SHIPPED ``wave-status``
    binary — the one that matters in production, since it imports
    ``wave_status.__main__`` as a module rather than running it, so neither
    ``__main__`` guard fires there at all. Any new packaging/invocation path
    added later needs to route through `_run_as_script` too, or it silently
    reopens #1149.

    Bounded, not indefinite: an unbounded join would hang the CLI forever
    against a truly dead/hanging ingest endpoint — the same failure mode R-02
    was built to avoid, just moved to a different call site. *timeout*
    defaults to ``FLIGHTDECK_INGEST_TIMEOUT`` (the same bound a single
    in-flight POST is already allowed to take), so the worst case this adds
    to a real process exit is one more instance of a cost the process was
    already prepared to pay.

    Never raises (R-03). Clears :data:`_pending_ships` unconditionally —
    whether a thread finished, is still running past the timeout, or joining
    it raised, waiting on it a second time serves no purpose.

    This join is bounded PER THREAD, so `ship()`'s own internal backlog
    replay can still legitimately exceed *timeout* in total — a thread can be
    abandoned here mid-POST if the buffer had a lot of catching up to do.
    That's fine ONLY because both call sites follow this with `os._exit()`,
    not a normal return: no `Py_Finalize` runs, so an abandoned in-flight
    thread has nothing left to race and can't trigger the crash class this
    fix exists for. **The join buys delivery; `os._exit()` buys crash
    safety — they are not substitutes for each other.** If a future change
    ever "simplifies" a call site back to a bare return/`sys.exit()`, the
    abandoned-thread case reopens #1149 exactly as it was before this fix,
    even with this join still in place.
    """
    if timeout is None:
        try:
            timeout = float(os.environ.get("FLIGHTDECK_INGEST_TIMEOUT", "2"))
        except (TypeError, ValueError):
            timeout = 2.0
    threads, _pending_ships[:] = list(_pending_ships), []
    for t in threads:
        try:
            t.join(timeout=timeout)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# emit — the one entrypoint
# ---------------------------------------------------------------------------

def emit(
    kind: str,
    *,
    activity_id: str | None = None,
    wave: str | None = None,
    phase: str | None = None,
    flight: str | int | None = None,
    agent: str | None = None,
    log_ref: str | None = None,
    concern_kind: str | None = None,
    source: str | None = None,
    metric: str | None = None,
    value: object = _UNSET,
    unit: str | None = None,
    action: str | None = None,
    label: str | None = None,
    detail: object = None,
    activity_type: str | None = None,
    host: str | None = None,
    buffer: Path | None = None,
    ship_now: bool = True,
) -> dict | None:
    """Build, validate, buffer, and (non-blocking) ship one event.

    Returns the event dict, or ``None`` if it could not be built/validated or
    buffered. **Never raises** (R-01/R-03). ``value`` uses a sentinel so an
    explicit ``value=None`` (seamed-absent metric) round-trips as JSON ``null``.
    """
    if os.environ.get("FLIGHTDECK_EMIT_DISABLED"):
        return None

    fields: dict[str, object] = {}
    local = {
        "wave": wave, "phase": phase, "flight": flight, "agent": agent,
        "log_ref": log_ref, "concern_kind": concern_kind, "source": source,
        "metric": metric, "unit": unit, "action": action, "label": label,
        "detail": detail, "activity_type": activity_type, "host": host,
    }
    for snake, val in local.items():
        if val is not None:
            fields[_FIELD_KEYS[snake]] = val
    if value is not _UNSET:
        fields["value"] = value  # preserved even when None (token stub, R-19)

    try:
        aid = activity_id or os.environ.get("FLIGHTDECK_ACTIVITY_ID") or "unknown"
        event = build_event(kind, activity_id=aid, **fields)
        validate_event(event)
    except Exception:
        return None

    buf = buffer or buffer_path()
    try:
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=False)
        _atomic_append(buf, line)
    except Exception:
        return event  # built/validated but couldn't buffer — still never raise.

    if ship_now:
        _ship_async(buf)
    return event


def emit_state_event(root: object, kind: str, **fields: object) -> dict | None:
    """Convenience wrapper for state.py mutators (S1.2).

    Derives ``activityId`` from *root* and picks up ``agent`` / ``log_ref`` from
    the environment, then delegates to :func:`emit`. Never raises.
    """
    try:
        return emit(
            kind,
            activity_id=activity_id_for_root(root),
            agent=resolve_agent(root),
            log_ref=os.environ.get("FLIGHTDECK_LOG_REF"),
            **fields,
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI (used by the session hook S1.7 and the Workflow tee S1.6 via
# `wave-status emit …`; also runnable as `python -m wave_status.events.emit`).
# ---------------------------------------------------------------------------

def _build_arg_fields(args) -> dict:
    fields: dict[str, object] = {}
    for name in (
        "wave", "phase", "flight", "agent", "log_ref", "concern_kind",
        "source", "metric", "unit", "action", "label", "detail",
        "activity_type", "host",
    ):
        val = getattr(args, name, None)
        if val is not None:
            fields[name] = val
    # For a metric, always carry `value` (None ⇒ honest seamed-absent stub).
    if args.metric is not None:
        if args.value is None:
            fields["value"] = None
        else:
            fields["value"] = _coerce_value(args.value)
    return fields


def _coerce_value(raw: str) -> object:
    for cast in (int, float):
        try:
            return cast(raw)
        except (TypeError, ValueError):
            continue
    return raw


def main(argv: list[str] | None = None) -> int:
    """``wave-status emit`` / ``python -m wave_status.events.emit``.

    Emits one event and prints it as JSON. Always exits 0 — emit is
    fire-and-forget instrumentation; a non-zero exit must never fail a hook or a
    Workflow node.
    """
    import argparse

    p = argparse.ArgumentParser(
        prog="wave-status emit",
        description="Emit one FlightDeck event to the durable buffer + ingest.",
    )
    p.add_argument("kind", help="Event kind (activity_start|phase|step|metric|concern|blocked_on_human|ci_wait|activity_end)")
    p.add_argument("--activity-id", dest="activity_id", default=None)
    p.add_argument("--wave", default=None)
    p.add_argument("--phase", default=None)
    p.add_argument("--flight", default=None)
    p.add_argument("--agent", default=None)
    p.add_argument("--log-ref", dest="log_ref", default=None)
    p.add_argument("--concern-kind", dest="concern_kind", default=None)
    p.add_argument("--source", default=None)
    p.add_argument("--metric", default=None, help="metric name (kind=metric)")
    p.add_argument("--value", default=None, help="metric value; omit for a seamed-absent stub")
    p.add_argument("--unit", default=None)
    p.add_argument("--action", default=None)
    p.add_argument("--label", default=None)
    p.add_argument("--detail", default=None)
    p.add_argument(
        "--detail-json", dest="detail_json", default=None,
        help="structured detail payload as a JSON string, decoded before emit so the "
             "buffered event carries an OBJECT rather than a string (#1145). Prefer this "
             "over --detail for any new caller that has a structured payload; --detail "
             "stays for free-form prose (schema permits 'string or structured'). Wins "
             "over --detail if both are given.",
    )
    p.add_argument("--activity-type", dest="activity_type", default=None,
                   help="convention field: campaign|float|session (#947)")
    p.add_argument("--host", default=None,
                   help="emitting host — distinct from --agent (Dev-Name)")
    p.add_argument("--no-ship", dest="ship_now", action="store_false", default=True)
    args = p.parse_args(argv)

    try:
        fields = _build_arg_fields(args)
        if args.detail_json is not None:
            fields["detail"] = json.loads(args.detail_json)
        event = emit(
            args.kind,
            activity_id=args.activity_id,
            ship_now=args.ship_now,
            **fields,
        )
        if event is not None:
            # BEFORE print(): if stdout is closed or full, print() can raise,
            # and this must not be skipped as a result — it is the whole point
            # of this CLI call succeeding.
            #
            # #1148: give sdlc-server's own handlers something live to resolve
            # scope from, since their process env is frozen at spawn. Only on
            # a RESOLVED id — writing a marker for the "unknown" fallback would
            # poison the read side's own fallback chain with that literal string,
            # worse than leaving no marker at all.
            aid = event.get("activityId")
            # CAMPAIGN ONLY, by allowlist not denylist. The session hook
            # (scripts/flightdeck-session-emit.sh) ALSO emits activity_start —
            # every new Claude Code session in this repo triggers one — and its
            # legacy-retry path drops --activity-type entirely when an older
            # installed CLI rejects the flag (argparse exit 2). A denylist on
            # "session" would leak straight through that path: args.activity_type
            # would read None, not "session", and a routine session start would
            # silently clobber a LIVE campaign's marker with a presence id. The
            # wavemachine driver always pins --activity-type campaign — since
            # #1145, via `wave-status campaign-head` (__main__.py:_cmd_campaign_head),
            # which delegates to this same main() precisely to keep this marker
            # write; nothing else emits "float" today.
            if args.kind == "activity_start" and args.activity_type == "campaign" and aid != "unknown":
                _write_scope_marker(aid, event.get("agent"))
            elif args.kind == "activity_end" and aid:
                _clear_scope_marker_if_matching(aid)
            print(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
    except Exception:
        pass  # fire-and-forget: never fail the caller.
    return 0


def _run_as_script() -> None:
    """The real top-level entry-point body for this module's standalone form
    (``python -m wave_status.events.emit ...``) — the one place it's safe to
    both join outstanding shipper threads and skip normal interpreter
    finalization. See `flush_pending_ships`'s docstring for why this must
    never move into `main()` itself (it's called in-process elsewhere, and a
    bad move here would either block those callers or kill a test run).

    Factored out of the ``if __name__ == "__main__":`` guard so tests can
    call it directly with ``os._exit`` mocked — actually invoking
    ``os._exit`` would kill the test process, and the whole point of it is
    that it can't be caught.
    """
    _code = 1
    try:
        _code = main()
    finally:
        flush_pending_ships()
        _flush_std_streams()
    # os._exit, not SystemExit/return: skips Py_Finalize's interpreter
    # teardown entirely, which is what the daemon-thread-shutdown race needs
    # to exist at all. Safe here specifically because flush_pending_ships()
    # just ran — nothing this module does relies on atexit/GC finalizers
    # (verified: no `atexit`, no `__del__`, no buffered writes other than the
    # stdout/stderr just flushed above; the buffer append and scope-marker
    # write are already fsync'd+closed before `main()` returns).
    os._exit(_code)


if __name__ == "__main__":
    _run_as_script()
