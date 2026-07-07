"""FlightDeck event contract — typed constants + stdlib validation (S0.1 / #860).

This package is the lowest-deterministic-layer emit contract for FlightDeck
(Dev Spec §5.1, TC-4). ``schema.json`` (sibling file) is the versioned,
language-neutral contract that BOTH the Python emitter (:mod:`wave_status.events.emit`)
and the TypeScript ingest service validate against — schema, not shared code.

This module mirrors that schema as typed Python constants and provides a
**stdlib-only** validator (no ``jsonschema`` dependency — CT-01 / TC-1), so the
emit hot path stays dependency-free. ``test_event_schema.py`` pins the Python
constants against the ``schema.json`` enums so the two never drift.

Design note (#853 token gate): the ``metric`` kind carries a ``value`` that may
be ``None`` — a seamed-absent metric (the token cell stubs until #853 lands;
R-19/TC-7: never fabricated, explicitly absent).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

__all__ = [
    "SCHEMA_VERSION",
    "EVENT_KINDS",
    "CONCERN_KINDS",
    "CONCERN_SOURCES",
    "SCOPE_TAGS",
    "ACTION_TO_KIND",
    "now_iso",
    "kind_for_action",
    "build_event",
    "validate_event",
    "load_schema",
    "EventValidationError",
]

# ---------------------------------------------------------------------------
# The contract — kept in lockstep with schema.json ($defs). test_event_schema
# asserts these equal the schema enums.
# ---------------------------------------------------------------------------

SCHEMA_VERSION = 1

#: The eight deterministic event kinds.
EVENT_KINDS: tuple[str, ...] = (
    "activity_start",
    "phase",
    "step",
    "metric",
    "concern",
    "blocked_on_human",
    "ci_wait",
    "activity_end",
)

#: The six concern categories (kind == "concern").
CONCERN_KINDS: tuple[str, ...] = (
    "workaround",
    "di-seam",
    "forced-default",
    "gate-override",
    "self-approval",
    "unresolved-todo",
)

#: Where a concern originated: a coded escape hatch, or an agent declaration.
CONCERN_SOURCES: tuple[str, ...] = ("coded", "declared")

#: The canonical scope-tag key set carried by every event (Dev Spec §5.1).
SCOPE_TAGS: tuple[str, ...] = (
    "activityId",
    "kind",
    "phase",
    "wave",
    "flight",
    "agent",
    "ts",
    "logRef",
)

# ---------------------------------------------------------------------------
# state.py action vocabulary → event kind (S0.1 → consumed by S1.2).
#
# Each ``current_action.action`` value that state.py writes maps to exactly one
# event kind. ``_set_action`` uses this table so every coarse-state transition
# emits a correctly-typed event without a per-call-site kind literal.
# ---------------------------------------------------------------------------

ACTION_TO_KIND: dict[str, str] = {
    "idle": "step",
    "pre-flight": "phase",
    "planning": "phase",
    "post-wave-review": "phase",
    "in-flight": "step",
    "merging": "step",
    "waiting-on-meatbag": "blocked_on_human",
    "waiting-ci": "ci_wait",
    "launching": "step",
    "awaiting-verdict": "step",
    "promoting": "step",
    "hold": "blocked_on_human",
}


class EventValidationError(ValueError):
    """Raised by :func:`validate_event` when an event violates the contract.

    A ``ValueError`` subclass so callers that already catch ``ValueError`` (the
    emitter swallows it and buffers nothing) keep working unchanged.
    """


def now_iso() -> str:
    """Return an ISO-8601 UTC timestamp (mirrors ``state._now_iso``)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def kind_for_action(action: str) -> str:
    """Map a state.py ``current_action.action`` to its event kind.

    Unknown actions default to ``"step"`` — an additive-safe fallback so a new
    action string can never make an emit raise (the emitter is fire-and-forget).
    """
    return ACTION_TO_KIND.get(action, "step")


# Optional scope keys and their allowed python types (None always allowed).
_SCOPE_TYPES: dict[str, tuple[type, ...]] = {
    "phase": (str,),
    "wave": (str,),
    "flight": (str, int),
    "agent": (str,),
    "logRef": (str,),
}


def build_event(
    kind: str,
    *,
    activity_id: str,
    ts: str | None = None,
    **fields: object,
) -> dict:
    """Construct a normalized, contract-shaped event dict.

    Stamps ``kind``, ``activityId``, ``ts`` (defaulting to :func:`now_iso`) and
    ``schemaVersion``. Any ``fields`` whose value is ``None`` are dropped so the
    buffered JSONL stays compact and optional scope tags are simply absent
    (never ``null``) — EXCEPT ``value``, which is preserved even when ``None``
    so a seamed-absent metric (#853 token stub) round-trips honestly.

    Does NOT validate — call :func:`validate_event` on the result.
    """
    event: dict = {
        "kind": kind,
        "activityId": activity_id,
        "ts": ts or now_iso(),
        "schemaVersion": SCHEMA_VERSION,
    }
    for key, val in fields.items():
        if val is None and key != "value":
            continue
        event[key] = val
    return event


def validate_event(event: object) -> None:
    """Validate *event* against the contract; raise :class:`EventValidationError`.

    Stdlib-only, hand-rolled to mirror ``schema.json`` (no ``jsonschema`` dep).
    Checks, in order:

    - the event is a dict;
    - ``kind`` present and in :data:`EVENT_KINDS`;
    - ``activityId`` a non-empty str;
    - ``ts`` a non-empty str;
    - optional scope tags, when present and non-null, carry an allowed type;
    - ``kind == "concern"`` ⇒ ``concernKind`` in :data:`CONCERN_KINDS` and
      ``source`` in :data:`CONCERN_SOURCES`;
    - ``kind == "metric"`` ⇒ ``metric`` name is a non-empty str.
    """
    if not isinstance(event, dict):
        raise EventValidationError(
            f"event must be a dict, got {type(event).__name__}"
        )

    kind = event.get("kind")
    if kind not in EVENT_KINDS:
        raise EventValidationError(
            f"invalid event kind {kind!r}; must be one of {EVENT_KINDS}"
        )

    activity_id = event.get("activityId")
    if not isinstance(activity_id, str) or not activity_id:
        raise EventValidationError(
            "event 'activityId' must be a non-empty string"
        )

    ts = event.get("ts")
    if not isinstance(ts, str) or not ts:
        raise EventValidationError("event 'ts' must be a non-empty string")

    for key, allowed in _SCOPE_TYPES.items():
        if key in event and event[key] is not None:
            if not isinstance(event[key], allowed):
                names = "/".join(t.__name__ for t in allowed)
                raise EventValidationError(
                    f"scope tag '{key}' must be {names} or absent"
                )

    if kind == "concern":
        ck = event.get("concernKind")
        if ck not in CONCERN_KINDS:
            raise EventValidationError(
                f"concern 'concernKind' must be one of {CONCERN_KINDS}, got {ck!r}"
            )
        src = event.get("source")
        if src not in CONCERN_SOURCES:
            raise EventValidationError(
                f"concern 'source' must be one of {CONCERN_SOURCES}, got {src!r}"
            )

    if kind == "metric":
        name = event.get("metric")
        if not isinstance(name, str) or not name:
            raise EventValidationError(
                "metric event 'metric' (name) must be a non-empty string"
            )


def load_schema() -> dict:
    """Load and parse the sibling ``schema.json`` contract.

    Uses ``importlib.resources`` when available (works inside the zipapp), with a
    ``__file__``-relative fallback for source-tree reads. This is the CONTRACT
    artifact used by tests and the TS-service drift check; runtime validation
    (:func:`validate_event`) does NOT depend on it.
    """
    try:
        from importlib.resources import files

        return json.loads(
            files(__package__).joinpath("schema.json").read_text(encoding="utf-8")
        )
    except Exception:
        path = Path(__file__).resolve().parent / "schema.json"
        return json.loads(path.read_text(encoding="utf-8"))
