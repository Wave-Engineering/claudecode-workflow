"""
tests/test_godspeed_gated_actions.py — godspeed_gated_actions must fail CLOSED.

Covers cc-workflow#950. `godspeed_gated_actions` extracted commands with
`jq ... 2>/dev/null || true`, so MALFORMED tools_json produced an empty result,
which godspeed_decision reads as "no gated action found" — a fail-OPEN on the
action gate that fires every agent turn.

WHY THESE TESTS CALL THE FUNCTION DIRECTLY (load-bearing — the AC)
-----------------------------------------------------------------
In production, tools_json comes from godspeed_turn_tools, which after #920
guarantees well-formed JSON, the literal EXTRACTION_FAILED, or "[]". Routing a
malformed-input test through godspeed_turn_tools would exercise that UPSTREAM
guard, not this function's own contract — the guard is exactly what hides the
defect. So every test here invokes godspeed_gated_actions (and godspeed_decision)
directly with the payload, the way a future third caller might.

The direction is fail-CLOSED, matching the EXTRACTION_FAILED convention #920
established: an extraction that cannot read its input is not evidence of no
gated action. `[]` remains a legitimate all-clear — the fix must not over-correct
every quiet path into a STOP.
"""

import os
import subprocess
import unittest

SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'scripts', 'godspeed-lookback.sh'))

FORCE_PUSH = '[{"name":"Bash","input":{"command":"git push --force origin main"}}]'


def gated_actions(tools_json):
    """Call godspeed_gated_actions directly; return stdout stripped."""
    r = subprocess.run(
        ['bash', '-c', 'source "$1"; godspeed_gated_actions "$2"', '_', SCRIPT, tools_json],
        capture_output=True, text=True, timeout=15)
    return r.stdout.strip()


def decision(tools_json, arm_status='UNARMED'):
    """Call godspeed_decision directly with the given tools_json; return stdout."""
    r = subprocess.run(
        ['bash', '-c', 'source "$1"; godspeed_decision "$2" "" "sess" "$3"',
         '_', SCRIPT, arm_status, tools_json],
        capture_output=True, text=True, timeout=15)
    return r.stdout.strip()


class TestMalformedInputFailsClosed(unittest.TestCase):
    """Anything that is not a JSON array of objects must be treated as gated."""

    def test_parse_error_fails_closed(self):
        """RED: the reported defect — unparseable JSON read as all-clear.

        `godspeed_gated_actions "{not valid json"` returned empty before the fix;
        empty is how godspeed_decision spells 'nothing gated'.
        """
        self.assertNotEqual(
            gated_actions('{not valid json'), "",
            "malformed JSON produced an empty (all-clear) gated-action list")

    def test_non_array_object_fails_closed(self):
        """RED: valid JSON that is an object, not the expected array."""
        self.assertNotEqual(gated_actions('{"a":1}'), "")

    def test_json_string_fails_closed(self):
        """RED: valid JSON that is a bare string."""
        self.assertNotEqual(gated_actions('"just a string"'), "")

    def test_array_of_non_objects_fails_closed(self):
        """RED: a JSON array whose elements are not objects.

        The extraction does `.[] | select(.name == ...)`; on a number element
        `.name` errors, jq aborts, `2>/dev/null || true` swallows it to empty.
        """
        self.assertNotEqual(gated_actions('[1,2,3]'), "")

    def test_empty_object_fails_closed(self):
        """The `type == "array"` conjunct is load-bearing — pin it.

        For `{}`, `all(.[]; ...)` is vacuously true, so WITHOUT the array
        conjunct the guard would pass `{}` and fail open. Only the conjunct
        closes it, and nothing else in the suite exercises that element. Raised
        by review as minor #2.
        """
        self.assertNotEqual(gated_actions('{}'), "")

    def test_non_object_input_fails_closed(self):
        """RED (residual, caught in review): `.input` is a string, not an object.

        `[{"name":"Bash","input":"..."}]` IS an array of objects, so a
        top-level-only guard passes it — then `.input.command` indexes a string,
        jq errors, and it collapses to empty. The `.input` must be object-or-null.
        """
        self.assertNotEqual(
            gated_actions('[{"name":"Bash","input":"git push --force origin main"}]'), "",
            "a non-object .input slipped the guard and failed open")

    def test_boolean_input_fails_closed(self):
        """RED: `input:false` — the case `(.input // {})` would mishandle.

        `//` replaces false, so a `// {}`-style guard would pass this, then
        `false.command` crashes the extraction. `.input==null or object` is exact.
        """
        self.assertNotEqual(gated_actions('[{"name":"Bash","input":false}]'), "")

    def test_gated_action_not_missed_beside_a_malformed_sibling(self):
        """RED: a real force-push must not be lost because a sibling is malformed.

        With the bad element FIRST, jq aborts the single pass before reaching the
        force-push, so the genuine gated action is missed entirely. Fail-closed on
        the whole payload is the safe resolution — the turn still STOPs.
        """
        payload = ('[{"name":"Bash","input":"x"},'
                   '{"name":"Bash","input":{"command":"git push --force origin main"}}]')
        self.assertNotEqual(gated_actions(payload), "",
                            "force-push missed because a sibling element was malformed")

    def test_failclosed_reason_is_named_not_blank(self):
        """The fail-closed output must be a human-readable reason, not noise.

        godspeed_decision only checks non-empty, but the string lands in the
        block reason a human reads, so it must say WHY.
        """
        out = gated_actions('{not valid json')
        self.assertIn("fail-closed", out)


class TestCleanInputsStayClean(unittest.TestCase):
    """The fix must not over-correct: genuinely-empty paths stay NOOP."""

    def test_empty_array_is_clean(self):
        """GREEN GUARD: [] is a legitimate all-clear, not a fail-closed."""
        self.assertEqual(gated_actions('[]'), "")

    def test_object_without_name_is_clean(self):
        """GREEN GUARD: a valid array of objects with no gated action → empty."""
        self.assertEqual(gated_actions('[{"foo":"bar"}]'), "")

    def test_benign_command_is_clean(self):
        """GREEN GUARD: a non-gated command must not STOP (no over-flagging)."""
        self.assertEqual(
            gated_actions('[{"name":"Bash","input":{"command":"ls -la"}}]'), "")


class TestGatedActionsStillDetected(unittest.TestCase):
    """The fix must not blind the gate to real gated actions."""

    def test_force_push_still_detected(self):
        self.assertIn("git push --force", gated_actions(FORCE_PUSH))

    def test_extraction_failed_still_fails_closed(self):
        """GREEN GUARD: the #920 sentinel still produces a fail-closed reason."""
        out = gated_actions('EXTRACTION_FAILED')
        self.assertNotEqual(out, "")
        self.assertIn("fail-closed", out)


class TestDecisionStopsOnMalformedTools(unittest.TestCase):
    """The end-to-end consequence: a malformed payload must STOP, not NOOP."""

    def test_decision_stops_on_parse_error(self):
        """RED: godspeed_decision returned NOOP on unparseable tools_json."""
        self.assertEqual(decision('{not valid json'), "STOP",
                         "malformed tools_json granted a clean pass")

    def test_decision_stops_on_array_of_non_objects(self):
        """RED: same via the array-of-numbers path."""
        self.assertEqual(decision('[1,2,3]'), "STOP")

    def test_decision_noop_on_empty_array(self):
        """GREEN GUARD: [] is a legitimate stand-down."""
        self.assertEqual(decision('[]'), "NOOP")

    def test_decision_stops_on_real_gated_action(self):
        """GREEN GUARD: the valid gated path is unchanged."""
        self.assertEqual(decision(FORCE_PUSH), "STOP")


if __name__ == '__main__':
    unittest.main()
