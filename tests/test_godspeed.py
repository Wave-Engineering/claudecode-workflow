"""
tests/test_godspeed.py — Unit tests for godspeed-lookback.sh

Tests the decaying-mandate autonomy model (cc-workflow#818).
Covers: godspeed_status (arm/halt/unarmed) and godspeed_decision (GO/ASK/STOP/NOOP).
"""

import json
import os
import subprocess
import tempfile
import unittest

SCRIPT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts', 'godspeed-lookback.sh'))


# ---------------------------------------------------------------------------
# Transcript builders
# ---------------------------------------------------------------------------

def _user(text):
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": [{"type": "text", "text": text}]}
    })


def _asst(text):
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}
    })


def _tool_use():
    """Assistant-role tool_use entry — type=='assistant', does NOT count as user turn."""
    return json.dumps({
        "type": "assistant",
        "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}
    })


def _make(*lines):
    return '\n'.join(lines) + '\n'


# ---------------------------------------------------------------------------
# Helpers to invoke the script
# ---------------------------------------------------------------------------

def run_eval(transcript, env=None):
    """Invoke --eval <transcript> and return stdout stripped."""
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write(transcript)
        path = f.name
    try:
        r = subprocess.run(['bash', SCRIPT, '--eval', path],
                           capture_output=True, text=True, timeout=15, env=merged_env)
        return r.stdout.strip()
    finally:
        os.unlink(path)


def run_decide(transcript, last_asst_text, session_id='gs-test-session',
               env=None, sentinel=False):
    """
    Invoke --decide with CC hook JSON.

    Appends an assistant turn (last_asst_text) to the transcript before passing
    to --decide, since that mode extracts last-assistant-text from the file.

    sentinel=True creates /tmp/claude-tests-ran-<session_id> (verified state).
    """
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)

    sentinel_path = f'/tmp/claude-tests-ran-{session_id}'
    if sentinel:
        with open(sentinel_path, 'w') as sf:
            sf.write('1')
    elif os.path.exists(sentinel_path):
        os.unlink(sentinel_path)

    full_transcript = transcript + _asst(last_asst_text) + '\n'
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write(full_transcript)
        path = f.name
    try:
        hook_json = json.dumps({
            'transcript_path': path,
            'session_id': session_id,
            'stop_hook_active': False,
        })
        r = subprocess.run(['bash', SCRIPT, '--decide'],
                           input=hook_json, capture_output=True, text=True,
                           timeout=15, env=merged_env)
        return r.stdout.strip()
    finally:
        os.unlink(path)
        if os.path.exists(sentinel_path):
            os.unlink(sentinel_path)


# ---------------------------------------------------------------------------
# godspeed_status tests
# ---------------------------------------------------------------------------

class TestGodspeedStatus(unittest.TestCase):

    def test_unarmed_no_godspeed(self):
        """No godspeed in transcript → UNARMED."""
        t = _make(_user("please do the thing"), _asst("sure"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_unarmed_assistant_echo(self):
        """
        godspeed appears only in an assistant turn → UNARMED.

        This is the 'assistant echo' guard: if an assistant turn says
        "I understand, godspeed!" that must not arm the mandate.  Only
        type=='user' turns count.
        """
        t = _make(
            _asst("The user said godspeed, so I'll proceed autonomously."),
            _user("yes, continue"),
        )
        self.assertEqual(run_eval(t), "UNARMED")

    def test_armed_most_recent_turn(self):
        """godspeed in most-recent user turn → ARMED 0."""
        t = _make(_user("godspeed"), _asst("proceeding"))
        result = run_eval(t)
        self.assertTrue(result.startswith("ARMED"), f"Expected ARMED, got: {result}")
        self.assertEqual(result.split()[1], "0")

    def test_armed_d_counts_user_turns_only(self):
        """
        d counts user turns since godspeed, excluding assistant entries.

        3 user turns after godspeed → ARMED 3 (N=10 to keep the window manageable).
        """
        t = _make(
            _user("godspeed"),
            _asst("ok"),
            _user("step 1"),
            _user("step 2"),
            _user("step 3"),
        )
        result = run_eval(t, env={'GODSPEED_WINDOW': '10'})
        self.assertTrue(result.startswith("ARMED 3"), f"Expected ARMED 3, got: {result}")

    def test_halted(self):
        """HALT! in a user turn newer than godspeed → HALTED."""
        t = _make(
            _user("godspeed"),
            _asst("running"),
            _user("HALT!"),
        )
        self.assertEqual(run_eval(t), "HALTED")

    def test_aged_out(self):
        """godspeed more than N user turns ago → UNARMED (aged out)."""
        lines = [_user("godspeed")] + [_user(f"turn {i}") for i in range(12)]
        t = _make(*lines)
        self.assertEqual(run_eval(t, env={'GODSPEED_WINDOW': '10'}), "UNARMED")

    def test_tool_use_entries_dont_inflate_d(self):
        """
        Assistant tool_use entries (type=='assistant') are excluded from $user_turns.

        After godspeed: 5 rounds of (tool_use + assistant-text), then one user turn.
        d should be 1 — only user turns count, not tool interleaving.
        """
        lines = [_user("godspeed")]
        for _ in range(5):
            lines.append(_tool_use())
            lines.append(_asst("processing"))
        lines.append(_user("are we there yet?"))
        t = _make(*lines)
        result = run_eval(t, env={'GODSPEED_WINDOW': '10'})
        self.assertTrue(result.startswith("ARMED"), f"Expected ARMED, got: {result}")
        d = int(result.split()[1])
        self.assertEqual(d, 1, f"Expected d=1 (1 user turn after godspeed), got d={d}")


# ---------------------------------------------------------------------------
# godspeed_decision tests
# ---------------------------------------------------------------------------

class TestGodspeedDecision(unittest.TestCase):

    def test_unarmed_noop(self):
        """No mandate active → NOOP (hook stands down)."""
        t = _make(_user("please fix the login page"))
        result = run_decide(t, "I'll look into it.")
        self.assertEqual(result, "NOOP")

    def test_halted_noop(self):
        """HALT! cancels mandate → NOOP."""
        t = _make(_user("godspeed"), _asst("running"), _user("HALT!"))
        result = run_decide(t, "stopping now")
        self.assertEqual(result, "NOOP")

    def test_fresh_mandate_go_unverified(self):
        """
        d=0, bar=0%, unverified=40% → GO.

        At d=0 the bar is 0% and any confidence clears it immediately.
        """
        t = _make(_user("godspeed"))
        result = run_decide(t, "Let me proceed with the next step.")
        self.assertEqual(result, "GO")

    def test_fresh_mandate_go_verified(self):
        """d=0, verified → GO."""
        t = _make(_user("godspeed"))
        result = run_decide(t, "Continuing.", sentinel=True)
        self.assertEqual(result, "GO")

    def test_mid_mandate_ask_unverified(self):
        """
        d=6, N=10 → bar=60%, unverified=40% < 60% → ASK.

        Mandate is active but confidence hasn't cleared the rising bar.
        """
        lines = [_user("godspeed")] + [_user(f"step {i}") for i in range(6)]
        t = _make(*lines)
        result = run_decide(t, "I'll continue.", env={'GODSPEED_WINDOW': '10'})
        self.assertTrue(result.startswith("ASK"), f"Expected ASK, got: {result}")

    def test_mid_mandate_go_verified(self):
        """
        d=6, N=10 → bar=60%, verified=80% ≥ 60% → GO.

        Same position as above but test sentinel present — confidence clears bar.
        """
        lines = [_user("godspeed")] + [_user(f"step {i}") for i in range(6)]
        t = _make(*lines)
        result = run_decide(t, "Proceeding.", env={'GODSPEED_WINDOW': '10'}, sentinel=True)
        self.assertEqual(result, "GO")

    def test_ask_output_fields(self):
        """
        ASK line carries exactly 4 space-separated tokens: ASK <d> <bar_pct> <supplied_pct>.
        Values must be arithmetically correct.
        """
        lines = [_user("godspeed")] + [_user(f"step {i}") for i in range(6)]
        t = _make(*lines)
        result = run_decide(t, "Moving on.", env={'GODSPEED_WINDOW': '10'})
        parts = result.split()
        self.assertEqual(parts[0], "ASK")
        self.assertEqual(len(parts), 4, f"Expected 'ASK d bar supplied', got: {result!r}")
        d, bar, supplied = int(parts[1]), int(parts[2]), int(parts[3])
        self.assertEqual(d, 6)
        self.assertEqual(bar, 60)   # 6*100//10
        self.assertEqual(supplied, 40)   # GODSPEED_UNVERIFIED_CONFIDENCE default

    def test_gated_axis_stop_with_mandate(self):
        """
        Prod-axis keyword in last assistant turn → STOP even under an active mandate.

        The gated-axis check fires before the mandate math — mandate does NOT
        override the ABSOLUTE prod rule.
        """
        t = _make(_user("godspeed"))
        result = run_decide(t, "I'm about to deploy to production.")
        self.assertEqual(result, "STOP")

    def test_gated_axis_stop_no_mandate(self):
        """Prod-axis fires even without any mandate (UNARMED state)."""
        t = _make(_user("please fix the login page"))
        result = run_decide(t, "Let me push this to production.")
        self.assertEqual(result, "STOP")

    def test_assistant_echo_no_arm(self):
        """
        godspeed in an assistant turn (echo) → no mandate → NOOP.

        This is the decision-layer counterpart of TestGodspeedStatus.test_unarmed_assistant_echo.
        """
        t = _make(
            _asst("The user said godspeed, I will act autonomously."),
            _user("continue with the task"),
        )
        result = run_decide(t, "I'll keep going.")
        self.assertEqual(result, "NOOP")


if __name__ == '__main__':
    unittest.main()
