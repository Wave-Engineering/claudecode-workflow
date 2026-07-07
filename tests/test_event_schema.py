"""S0.1 / #860 — the shared event schema + typed constants.

Verifies:
- ``schema.json`` parses and its ``$defs`` enums equal the Python constants
  (the two never drift — TC-4);
- a sample payload for every one of the 8 event kinds validates;
- every state.py action maps to a valid event kind (the S1.2 action→kind table);
- the concern/metric conditional requirements are enforced;
- malformed events are rejected.
"""

from __future__ import annotations

import pytest

from wave_status.events import (
    ACTION_TO_KIND,
    CONCERN_KINDS,
    CONCERN_SOURCES,
    EVENT_KINDS,
    EventValidationError,
    build_event,
    kind_for_action,
    load_schema,
    validate_event,
)


# ---------------------------------------------------------------------------
# schema.json ↔ constants drift
# ---------------------------------------------------------------------------

class TestSchemaConstantsInSync:
    def test_schema_parses(self):
        schema = load_schema()
        assert schema["title"] == "FlightDeck Event"
        assert schema["schemaVersion"] == 1

    def test_event_kind_enum_matches_constant(self):
        schema = load_schema()
        assert tuple(schema["$defs"]["eventKind"]["enum"]) == EVENT_KINDS

    def test_concern_kind_enum_matches_constant(self):
        schema = load_schema()
        assert tuple(schema["$defs"]["concernKind"]["enum"]) == CONCERN_KINDS

    def test_concern_source_enum_matches_constant(self):
        schema = load_schema()
        assert tuple(schema["$defs"]["concernSource"]["enum"]) == CONCERN_SOURCES

    def test_required_top_level_keys(self):
        schema = load_schema()
        assert set(schema["required"]) == {"kind", "activityId", "ts"}

    def test_eight_event_kinds(self):
        assert len(EVENT_KINDS) == 8
        assert EVENT_KINDS == (
            "activity_start",
            "phase",
            "step",
            "metric",
            "concern",
            "blocked_on_human",
            "ci_wait",
            "activity_end",
        )

    def test_six_concern_kinds(self):
        assert set(CONCERN_KINDS) == {
            "workaround",
            "di-seam",
            "forced-default",
            "gate-override",
            "self-approval",
            "unresolved-todo",
        }


# ---------------------------------------------------------------------------
# Every kind's sample payload validates
# ---------------------------------------------------------------------------

def _sample_for(kind: str) -> dict:
    extra: dict = {}
    if kind == "concern":
        extra = {"concernKind": "workaround", "source": "coded"}
    elif kind == "metric":
        extra = {"metric": "latency", "value": 1234, "unit": "ms"}
    return build_event(kind, activity_id="campaign-x", wave="wave-1", **extra)


class TestEveryKindValidates:
    @pytest.mark.parametrize("kind", EVENT_KINDS)
    def test_kind_sample_validates(self, kind):
        validate_event(_sample_for(kind))

    def test_build_event_stamps_defaults(self):
        ev = build_event("step", activity_id="a")
        assert ev["kind"] == "step"
        assert ev["activityId"] == "a"
        assert ev["ts"]  # non-empty
        assert ev["schemaVersion"] == 1

    def test_build_event_drops_none_scope_but_keeps_metric_value(self):
        ev = build_event("metric", activity_id="a", metric="tokens", value=None, wave=None)
        assert "wave" not in ev  # None scope dropped
        assert "value" in ev and ev["value"] is None  # seamed-absent metric preserved


# ---------------------------------------------------------------------------
# action → kind mapping (feeds S1.2)
# ---------------------------------------------------------------------------

class TestActionToKind:
    @pytest.mark.parametrize("action,kind", list(ACTION_TO_KIND.items()))
    def test_every_action_maps_to_valid_kind(self, action, kind):
        assert kind in EVENT_KINDS

    def test_state_action_vocabulary_covered(self):
        # The current_action.action strings state.py can write.
        vocab = {
            "idle", "pre-flight", "planning", "post-wave-review", "in-flight",
            "merging", "waiting-on-meatbag", "waiting-ci", "launching",
            "awaiting-verdict", "promoting", "hold",
        }
        assert vocab <= set(ACTION_TO_KIND)

    def test_unknown_action_defaults_to_step(self):
        assert kind_for_action("brand-new-action") == "step"


# ---------------------------------------------------------------------------
# Rejection paths
# ---------------------------------------------------------------------------

class TestRejection:
    def test_bad_kind_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event({"kind": "nope", "activityId": "a", "ts": "t"})

    def test_missing_activity_id_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event({"kind": "step", "ts": "t"})

    def test_missing_ts_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event({"kind": "step", "activityId": "a"})

    def test_concern_without_concern_kind_rejected(self):
        ev = build_event("concern", activity_id="a", source="coded")
        with pytest.raises(EventValidationError):
            validate_event(ev)

    def test_concern_bad_source_rejected(self):
        ev = build_event("concern", activity_id="a", concernKind="workaround", source="bogus")
        with pytest.raises(EventValidationError):
            validate_event(ev)

    def test_metric_without_name_rejected(self):
        ev = build_event("metric", activity_id="a", value=1)
        with pytest.raises(EventValidationError):
            validate_event(ev)

    def test_non_dict_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event("not-an-event")

    def test_bad_scope_type_rejected(self):
        with pytest.raises(EventValidationError):
            validate_event({"kind": "step", "activityId": "a", "ts": "t", "wave": 123})
