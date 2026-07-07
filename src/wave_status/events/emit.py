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
"""

from __future__ import annotations

import json
import os
import threading
import urllib.request
from pathlib import Path

from wave_status.events import build_event, validate_event

__all__ = [
    "emit",
    "emit_state_event",
    "ship",
    "replay",
    "buffer_path",
    "activity_id_for_root",
]

# Sentinel so ``value=None`` (a seamed-absent metric, #853 token stub) is
# distinguishable from "value not supplied".
_UNSET = object()

# Map the ergonomic snake_case emit() kwargs to the schema's camelCase keys.
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
    """Fire :func:`ship` in a daemon thread so the caller never blocks (R-02)."""
    if not os.environ.get("FLIGHTDECK_INGEST_URL"):
        return  # DI-seam: buffer-only, no thread.
    try:
        threading.Thread(
            target=ship, args=(buffer,), daemon=True, name="flightdeck-ship"
        ).start()
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
        "detail": detail,
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
            agent=os.environ.get("FLIGHTDECK_AGENT"),
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
    p.add_argument("--no-ship", dest="ship_now", action="store_false", default=True)
    args = p.parse_args(argv)

    try:
        event = emit(
            args.kind,
            activity_id=args.activity_id,
            ship_now=args.ship_now,
            **_build_arg_fields(args),
        )
        if event is not None:
            print(json.dumps(event, separators=(",", ":"), ensure_ascii=False))
    except Exception:
        pass  # fire-and-forget: never fail the caller.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
