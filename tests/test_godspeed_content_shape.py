"""
tests/test_godspeed_content_shape.py — content-shape and arming-form tests.

Covers cc-workflow#920 (`.message.content` is often a plain string; jq aborts and
the crash is swallowed into a default) and cc-workflow#921 (hook-generated text
arms the mandate it gates).

WHY THIS FILE EXISTS SEPARATELY FROM test_godspeed.py
-----------------------------------------------------
`test_godspeed.py`'s `_user()` builds `content` as an ARRAY, unconditionally, and
so does every other builder in it. That suite was green through three shipped
fail-opens because the shape it exercises is not the shape production carries.
Measured across the full local corpus (one workstation), and RE-DERIVED rather
than inherited when this suite was written:

    original sweep   transcripts with >=1 user-role string content  3651/3821 = 95.6%
    re-derived       transcripts with >=1 user-role string content  3606/3776 = 95.5%
    re-derived       transcripts unreadable by a strict jq slurp        5      (torn writes)
    original sweep   user messages: 20,174 string / 119,269 array            = 14.5%

The re-derivation reproduces both headline claims. A FIRST attempt at it returned
92.8%, because the measuring script used `head -c` and `jq -s` — truncating
mid-line and aborting on torn lines, so unreadable files silently became
non-hits. The instrument carried the very defect it was measuring, and
undercounted it. Re-run with the lenient line-wise parse this branch introduces,
it reproduces.

jq aborts on the FIRST string it meets, so the per-file failure is total, not
proportional. The per-message ratio is supporting evidence; 95.5% is the defect.

A NOTE ON VACUOUS GREEN (load-bearing — do not "simplify" this away)
--------------------------------------------------------------------
The #921 arming-form tests are written in ARRAY form on purpose.

In STRING form they would pass today for the wrong reason: #920 makes the jq
crash, the crash is swallowed to `UNARMED`, and a test asserting "not armed"
would go green against a detector that is simply dead. That is a test that was
never red, which proves nothing.

So: #921 assertions run in array form (genuinely red today), and the
string-form variants are marked as #920-dependent — they can only become
meaningful once arming actually runs.
"""

import json
import os
import re
import subprocess
import tempfile
import unittest

from tests.test_godspeed import (
    _asst, _asst_tools, _make, _user, run_decide, run_eval)

SCRIPT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'scripts', 'godspeed-lookback.sh'))


# ---------------------------------------------------------------------------
# Transcript builders reproducing REAL shapes.
#
# Sampled from ~/.claude/projects/**/*.jsonl rather than invented. The envelope
# keys below are the ones a real user record actually carries; the load-bearing
# difference from _user() is `content` being a bare string.
# ---------------------------------------------------------------------------

def _user_str(text):
    """User turn with `content` as a plain STRING — the shape in 95.5% of files."""
    return json.dumps({
        "type": "user",
        "message": {"role": "user", "content": text},
    })


def _user_str_real_envelope(text):
    """String content carrying the full envelope observed on real records.

    Positive control: proves the crash is driven by the content shape and not by
    some missing sibling key.
    """
    return json.dumps({
        "type": "user",
        "userType": "external",
        "isSidechain": False,
        "cwd": "/home/user/repo",
        "sessionId": "ffffffff-0000-4000-8000-000000000001",
        "version": "2.0.0",
        "gitBranch": "main",
        "uuid": "ffffffff-0000-4000-8000-000000000002",
        "parentUuid": None,
        "timestamp": "2026-07-20T00:00:00.000Z",
        "message": {"role": "user", "content": text},
    })


def _user_content(value):
    """User turn with an arbitrary `content` value — crash simulator.

    Used only to prove a crash is reported rather than swallowed. Shapes other
    than string/array were NOT observed in the corpus; this is deliberately
    synthetic and is not a claim about real data.
    """
    return json.dumps({"type": "user", "message": {"role": "user", "content": value}})


def _write_tmp(content, case):
    """Persist transcript text to a temp .jsonl and return its path.

    Used by tests that drive a shell function directly rather than via
    `run_eval`, which manages its own temp file. `case` is the TestCase, used to
    register cleanup — an earlier revision took no cleanup and leaked a file per
    call into /tmp on every run.
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write(content)
        path = f.name
    case.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
    return path


def _torn_write(line_a, line_b):
    """Two JSON objects concatenated with no newline — a real torn write.

    Observed on 5 / 3776 transcripts (re-derived) as
    `jq: parse error: Invalid numeric literal`, e.g.
    `...LlwqhUPdY6Dphw{"parentUuid":...` — a racing append, not NaN.
    `godspeed_status` uses `jq -rs` (slurp), so ONE torn line anywhere in the
    scan window kills the entire window.
    """
    return line_a + line_b


HOOK = os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', 'scripts',
                 'stop-action-bias-detector.sh'))


def emitted_sentinels():
    """Sentinels the hook actually EMITS, read from the emitting script.

    An earlier revision hardcoded these under a comment claiming they were read
    from the source — a comment describing an intention rather than the code,
    which would have stopped the next reader from adding the protection it
    promised. Reading them for real turned up two things a literal never would:

      1. The sentinels are emitted by `stop-action-bias-detector.sh`, not by
         `godspeed-lookback.sh`, which is where the first attempt looked.
      2. `[godspeed-STOP]` is emitted NOWHERE in the current tree.

    (2) is not dead weight in the exclusion list, though — see
    LEGACY_STOP_SENTINEL below.
    """
    with open(HOOK, encoding='utf-8') as fh:
        return sorted(set(re.findall(r'\[godspeed-[A-Za-z0-9_-]+\]', fh.read())))


GATE_SENTINEL = "[godspeed-GATE]"
CHECKPOINT_SENTINEL = "[godspeed-checkpoint]"

# Emitted by an OLDER revision of the hook and still present in real transcripts
# on this workstation — the corpus sweep found it verbatim:
#
#   Stop hook feedback:
#   [godspeed-STOP] Gated axis detected (prod/deploy/irreversible keyword)...
#
# The scan window reaches back over transcripts written by previous versions, so
# an exclusion list that covers only what the CURRENT build emits is wrong. This
# is why the test below asserts emitted ⊆ excluded rather than equality.
LEGACY_STOP_SENTINEL = "[godspeed-STOP]"


# ---------------------------------------------------------------------------
# #920 — content shape
# ---------------------------------------------------------------------------

class TestStringContentArms(unittest.TestCase):
    """A string-content turn must be read, not crashed over."""

    def test_string_content_godspeed_arms(self):
        """RED: string content carrying `godspeed` → ARMED 0 (today: UNARMED via crash)."""
        t = _make(_user_str("godspeed"))
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_string_content_real_envelope_arms(self):
        """RED: same, with the real record envelope."""
        t = _make(_user_str_real_envelope("godspeed"))
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_mixed_string_and_array_arms(self):
        """RED: the real-world shape — both forms interleaved in one transcript.

        This is the case both prior suites lacked entirely.
        """
        t = _make(
            _user("please start"),
            _asst("ok"),
            _user_str("godspeed"),
        )
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_one_string_turn_does_not_blind_the_whole_scan(self):
        """RED: a single string turn must not kill an otherwise-array transcript.

        Mirrors the measured red-first case: 1 string among 27 user turns killed
        the entire scan.

        The assertion is EXACT, not `!= "UNARMED"`. The weak form is satisfied by
        `UNKNOWN`, by `HALTED`, and by any garbage status — it would pass against
        an implementation that still lost the window, which is the very pattern
        this file condemns 30 lines below. Caught in review; it had survived
        because writing the rule down is not the same as applying it.

        7 user turns (`godspeed`, the string-prose turn, 5 fillers), so reversed
        the arming turn sits at index 6.
        """
        lines = [_user_str("some prose with no keyword")]
        for _ in range(5):
            lines.append(_user("filler"))
            lines.append(_asst("ack"))
        lines.insert(0, _user("godspeed"))
        t = _make(*lines)
        self.assertEqual(run_eval(t), "ARMED 6",
                         "one string-content turn blinded the whole window")

    def test_halt_in_string_content_disarms(self):
        """RED: HALT! must be honoured in string form too.

        Fails OPEN today in the dangerous direction: the crash returns UNARMED,
        which happens to look safe here, but the same blindness means a HALT!
        that should override an ARMED state is never seen.
        """
        t = _make(_user("godspeed"), _asst("working"), _user_str("HALT!"))
        self.assertEqual(run_eval(t), "HALTED")


class TestCrashIsNotSilent(unittest.TestCase):
    """A detector that crashed must be observably different from one reporting all-clear."""

    def test_torn_write_does_not_blind_the_window(self):
        """RED: a torn line must be DROPPED and the window recovered — not just reported.

        `jq -rs` slurps, so this one bad line blinds the entire window. Today the
        parse error is swallowed by `2>/dev/null || echo "UNARMED"`.

        Asserts the STRONGER of the two AC clauses. An earlier version of this
        test asserted only `!= "UNARMED"`, which `UNKNOWN` satisfies — that would
        have passed against an implementation that still lost the whole window,
        i.e. a test weaker than the criterion it was written for. A torn line is
        durable, so a fatal parse failure would leave that session's mandate
        permanently unarmable.

        `ARMED 0`, not `ARMED 1`: the torn line is the one carrying the later
        "more" turn, so dropping it makes `godspeed` the most-recent user turn.
        Recovery is not free — a dropped record shifts `d`, which is why the drop
        is announced on stderr (next test) rather than performed quietly. It is
        still strictly better than losing the window: `d` off by one ages the
        mandate slightly fast, in the safe direction.

        Discriminating in both directions: a blinded window yields `UNARMED`, so
        this cannot pass by accident against the unfixed script.
        """
        t = _torn_write(_user("godspeed") + "\n" + "LlwqhUPdY6Dphw", _user("more") + "\n")
        self.assertEqual(
            run_eval(t), "ARMED 0",
            "torn line blinded the scan instead of being dropped")

    def test_torn_write_recovery_is_announced_on_stderr(self):
        """RED: recovery must not be silent — a dropped record is still data loss."""
        t = _torn_write(_user("godspeed") + "\n" + "LlwqhUPdY6Dphw", _user("more") + "\n")
        with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
            f.write(t)
            path = f.name
        try:
            r = subprocess.run(['bash', SCRIPT, '--eval', path],
                               capture_output=True, text=True, timeout=15)
            self.assertIn("unparseable", r.stderr,
                          "dropped a transcript record with nothing on stderr")
        finally:
            os.unlink(path)

    def test_unknown_content_type_reports_unknown(self):
        """RED: a content shape the extractor cannot handle must report UNKNOWN.

        EXACT, not `!= "UNARMED"`. The weak form is passed by `ARMED 0` — i.e. by
        an implementation that grants an unrequested autonomy mandate off input
        it could not read, which is strictly worse than the bug being fixed.
        A test that green-lights the worst outcome is not a test.
        """
        t = _make(_user_content(42))
        self.assertEqual(
            run_eval(t), "UNKNOWN",
            "unhandled content type swallowed into a clean-looking default")

    def test_missing_transcript_still_unarmed(self):
        """GREEN GUARD: a genuinely absent file is a legitimate UNARMED, not UNKNOWN.

        Keeps the fix from over-correcting every quiet path into a loud one.
        """
        r = subprocess.run(['bash', SCRIPT, '--eval', '/nonexistent/transcript.jsonl'],
                           capture_output=True, text=True, timeout=15)
        self.assertEqual(r.stdout.strip(), "UNARMED")


class TestDegradedScanFailsClosedForTheActionGate(unittest.TestCase):
    """A recovered-but-incomplete scan must not read as 'nothing gated'.

    The split this class pins: `godspeed_status` ACCEPTS a dropped line (its `d`
    shifts one turn, in the safe direction) while `godspeed_turn_tools` REFUSES
    it. Same crash, opposite safe direction, because one answer grants latitude
    and the other withholds it.

    Found in review, and it is the #920 signature rebuilt inside the #920 fix: a
    torn write is a racing APPEND, so the dropped line sits at the write head —
    exactly where the current turn's assistant records live. Returning a
    well-formed but incomplete tool list renders "I dropped the evidence" as "no
    gated action found".
    """

    def _torn_at_write_head(self):
        """Transcript whose LAST line — this turn's tool_use — is torn."""
        return (_user("do it") + "\n"
                + _asst("ok") + "\n"
                + "TORN" + _asst_tools(
                    "pushing", [{"name": "Bash",
                                 "input": {"command": "git push --force origin main"}}])
                + "\n")

    def test_turn_tools_reports_extraction_failed_on_dropped_line(self):
        r = subprocess.run(
            ['bash', '-c', 'source "$1"; godspeed_turn_tools "$2"', '_', SCRIPT,
             _write_tmp(self._torn_at_write_head(), self)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(r.stdout.strip(), "EXTRACTION_FAILED",
                         "a scan that dropped a line reported a clean tool list")

    def test_status_still_recovers_on_the_same_transcript(self):
        """The other half of the split — status must NOT refuse the same input."""
        r = subprocess.run(
            ['bash', '-c', 'source "$1"; godspeed_status "$2"', '_', SCRIPT,
             _write_tmp(_user("godspeed") + "\n" + "TORN" + _user("x") + "\n", self)],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(r.stdout.strip(), "ARMED 0",
                         "status refused a recoverable window and became unarmable")

    def test_degraded_withholds_armed_when_a_dropped_line_carried_halt(self):
        """RED: the drop must not be able to hide a HALT!.

        A torn write is a racing append, so the dropped line sits at the write
        head — exactly where a just-typed `HALT!` lives. Dropping it and
        reporting ARMED is a fail-open on the one input whose purpose is to
        revoke autonomy, and ARMED additionally makes precheck-asking-detector.sh
        stand down.

        Paired with `test_torn_write_does_not_blind_the_window`, which has the
        same shape MINUS the HALT: that one must still return ARMED. Together
        they pin the distinction — the verdict is withheld because the dropped
        bytes could have carried a halt, not merely because a drop occurred.
        Without the pair, "withhold on any drop" would pass one and fail the
        other, and #920's own criterion (a torn line must not blind the window)
        would be quietly given up.
        """
        t = (_user("godspeed") + "\n"
             + "TORN" + json.dumps({
                 "type": "user",
                 "message": {"role": "user", "content": "HALT!"}}) + "\n")
        self.assertEqual(run_eval(t), "UNKNOWN",
                         "a dropped line carrying HALT! still produced a mandate")

    def test_wholly_unreadable_window_is_unknown_not_unarmed(self):
        """Every line unparseable → an empty stream slurps to `[]` and runs CLEAN.

        Without an explicit guard this returns a confident UNARMED, rc=0, for a
        window that could not be read at all — the loudest possible fail-open
        wearing a clean result's clothes.
        """
        t = "GARBAGE ONE\nGARBAGE TWO\nGARBAGE THREE\n"
        self.assertEqual(run_eval(t), "UNKNOWN")


class TestActionGateWithStringContent(unittest.TestCase):
    """#917's gate fails OPEN under #920 — the dangerous direction."""

    def test_gated_action_detected_despite_string_content_turn(self):
        """RED: a gated action must STOP even when the turn holds string content.

        Today the extraction crashes, LAST_TOOL_USES=[], and the gate reports
        'nothing found' — a fail-open on a safety control.

        Measured transition on this exact fixture: pre-fix `NOOP` (the gate saw
        nothing because the extraction had crashed), post-fix `STOP`.
        """
        t = _make(_user("godspeed"), _asst("ok"), _user_str("carry on"))
        out = run_decide(
            t, "pushing now",
            tools=[{"name": "Bash", "input": {"command": "git push --force origin main"}}])
        self.assertEqual(out, "STOP",
                         "gated action was not detected in a string-content turn")


# ---------------------------------------------------------------------------
# #921 — arming form and hook-echo exclusion
#
# Array form throughout: see the module docstring. In string form these pass
# today for the wrong reason.
# ---------------------------------------------------------------------------

class TestArmingForm(unittest.TestCase):
    """Every string below is REAL, taken from ~/.claude/projects/**/*.jsonl.

    An earlier draft of this fix implemented the issue's prose — "the message IS
    the token, or leads with it" — and rejected 3 of the 4 genuine arming turns
    in the corpus. The issue's description of the form was itself an unmeasured
    claim; it read as settled because it sat next to measured claims. These
    fixtures exist so that cannot recur silently.
    """

    def test_bare_token_arms(self):
        """REAL: the bare form."""
        self.assertEqual(run_eval(_make(_user("godspeed"))), "ARMED 0")

    def test_leading_token_arms(self):
        """Sentence-initial with a trailing clause."""
        self.assertEqual(run_eval(_make(_user("godspeed, go"))), "ARMED 0")

    def test_real_trailing_vocative_arms(self):
        """REAL corpus turn — trailing token with a vocative. Rejected by the first draft."""
        t = _make(_user(
            "agreed.  continuous, phas-boundary reporting.  godspeed, my friend"))
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_real_trailing_slash_command_arms(self):
        """REAL corpus turn — slash-prefixed trailing token. Rejected by the first draft."""
        t = _make(_user(
            "thank you.  please be as autonomous as you can safely be.  /godspeed"))
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_real_mid_sentence_slash_command_arms(self):
        """REAL corpus turn — slash form mid-sentence. Rejected by the first draft.

        The token does not lead its sentence here ("so /godspeed"), which is why
        a position-only rule cannot express this idiom.
        """
        t = _make(_user(
            "roll them in.  im working with lots of agents, so /godspeed"))
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_real_interrogative_does_not_arm(self):
        """REAL corpus turn — asking ABOUT the mandate must not arm it."""
        t = _make(_user("are you in godspeed mode?"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_real_code_quoted_question_does_not_arm(self):
        """REAL corpus turn — slash-prefixed but code-quoted inside a question."""
        t = _make(_user("how do we turn off `/godspeed`?"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_real_enumeration_does_not_arm(self):
        """REAL corpus turn — the token ENDS the message but is a list item.

        This is the case that killed a "trailing token within N characters"
        candidate: it passed 12 of 13 measured cases, and the one it failed
        showed the threshold was fitted to the examples rather than derived
        from the idiom.
        """
        t = _make(_user(
            "agentc can merge w/o user approval in wavemachine, lazyriver, and godspeed"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_mid_sentence_mention_does_not_arm(self):
        """A mention inside a sentence is not an instruction."""
        t = _make(_user("I was reading the godspeed docs earlier today"))
        self.assertEqual(run_eval(t), "UNARMED")


class TestHookEchoDoesNotArm(unittest.TestCase):
    """The inversion: the brake must not press the accelerator.

    EVERY fixture here embeds ` /godspeed` — a slash form preceded by a space,
    which the arming form accepts on its own. That is load-bearing and must not
    be "tidied" out.

    An earlier revision used block text like `[godspeed-GATE] ... git push
    --force`, which contains no armable form at all: no ` /godspeed`, and no
    `godspeed` after a sentence boundary. Those fixtures were rejected by the
    ARMING FORM, never by the sentinel exclusion — so deleting the sentinel
    clause from `is_machine_turn` left the whole class green. A test asserting a
    property it does not exercise, in the file whose own docstring condemns
    exactly that. Verified before and after:

        fixture with ` /godspeed`   with sentinel clause -> arms=false
                                    without it           -> arms=true
    """

    def test_gate_sentinel_does_not_arm(self):
        """RED: the Stop hook's own block text lands as a user turn — it must not arm."""
        t = _make(_user(
            f"{GATE_SENTINEL} Gated action detected this turn: /godspeed"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_checkpoint_sentinel_does_not_arm(self):
        """RED: the checkpoint echo must not arm."""
        t = _make(_user(
            f"{CHECKPOINT_SENTINEL} Mandate at d=3/N=200 — re-issue with /godspeed"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_stop_sentinel_does_not_arm(self):
        """RED: the legacy sentinel must not arm either."""
        t = _make(_user(
            f"{LEGACY_STOP_SENTINEL} stopping for approval; resume with /godspeed"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_halt_inside_hook_echo_does_not_disarm(self):
        """A hook echo must not DISARM — the opposite direction from the tests above.

        An exclusion that only ever suppressed arming would leave this hole open:
        the hook's own block text quotes the gated action, and block text about a
        halt must not revoke a live mandate.

        An earlier revision labelled this "cannot be made red" and claimed the
        arithmetic cancels. That was analysis, not measurement, and it was wrong
        — it assumed the echo also ARMS (true under HEAD's bare `\\bgodspeed\\b`,
        false under the corrected arming form). Measured by stripping the
        sentinel marker out of the shared envelope regex:

            with the exclusion     -> ARMED 0
            without the exclusion  -> HALTED

        So it discriminates. Note WHERE the protection comes from, because it is
        not where it looks: the sentinel turn is dropped by the TURN-COUNTING
        filter (`counts_as_human_turn`) before `halts` ever runs. Stripping only
        the guard inside `halts` changes nothing — verified. The guard in `halts`
        is therefore redundant today, and deliberately kept: it is the one that
        still holds if the counting filter is ever narrowed.
        """
        t = _make(_user("godspeed"), _asst("working"),
                  _user(f"{GATE_SENTINEL} operator said HALT! in an earlier session"))
        self.assertEqual(run_eval(t), "ARMED 0")

    def test_roundtrip_gate_block_leaves_state_unchanged(self):
        """RED: the full inversion path — gated action → STOP → block text → still UNARMED.

        This is the acceptance criterion in prose: a gated STOP followed by the
        agent's reply must leave the mandate state unchanged.
        """
        t = _make(
            _user("do the thing"),
            _asst("ok"),
            _user(f"{GATE_SENTINEL} Gated action detected this turn: terraform apply; /godspeed"),
            _asst("understood, stopping"),
        )
        self.assertEqual(run_eval(t), "UNARMED")


class TestArmingFormStringShape(unittest.TestCase):
    """#920-dependent: only meaningful once arming actually runs on string content.

    Kept explicit rather than omitted — after #920 these are the tests that stop
    the suite from re-acquiring the array-only blind spot.
    """

    def test_prose_mention_string_content_does_not_arm(self):
        t = _make(_user_str("are you in godspeed mode?"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_gate_sentinel_string_content_does_not_arm(self):
        t = _make(_user_str(f"{GATE_SENTINEL} Gated action detected this turn: /godspeed"))
        self.assertEqual(run_eval(t), "UNARMED")


def run_decision(arm_status, tools_json, last_text="", session="gs-dec-test"):
    """Drive godspeed_decision directly, bypassing transcript extraction.

    The fail-closed and whitelist behaviours are the reason this branch exists
    and they were asserted only by comment. Driving the function directly is the
    only way to exercise an arm status the extractor would never produce — which
    is precisely the input the whitelist exists to survive.
    """
    r = subprocess.run(
        ['bash', '-c',
         'source "$1"; godspeed_decision "$2" "$3" "$4" "$5"',
         '_', SCRIPT, arm_status, last_text, session, tools_json],
        capture_output=True, text=True, timeout=15)
    return r.stdout.strip()


class TestFailClosedOnUnreadableTurn(unittest.TestCase):
    """EXTRACTION_FAILED must never render as 'no gated action found'."""

    def test_decision_stops_on_extraction_failed(self):
        """RED: an extraction that crashed is not evidence of no gated action."""
        self.assertEqual(run_decision("UNARMED", "EXTRACTION_FAILED"), "STOP")

    def test_decision_stops_on_extraction_failed_even_when_armed(self):
        """A mandate speeds up autonomous work; it does not make a crash invisible."""
        self.assertEqual(run_decision("ARMED 0", "EXTRACTION_FAILED"), "STOP")

    def test_gated_reason_names_the_failure(self):
        """'I could not look' and 'I looked and found nothing' must not render alike."""
        r = subprocess.run(
            ['bash', '-c',
             'source "$1"; godspeed_gated_actions "EXTRACTION_FAILED"',
             '_', SCRIPT],
            capture_output=True, text=True, timeout=15)
        self.assertIn("extraction failed", r.stdout,
                      "unreadable turn produced an empty gated-action list")


class TestArmStatusWhitelist(unittest.TestCase):
    """Only a well-formed `ARMED <d>` may reach the mandate path.

    A blacklist (`UNARMED|HALTED` → stand down, everything else → mandate) would
    make an UNRECOGNISED status grant autonomy. That is not hypothetical: jq
    stderr is captured into the status on some paths, so a contaminated string
    must fall to NOOP, not through to the ARMED branch with a garbage `d`.
    """

    def test_unknown_stands_down(self):
        self.assertEqual(run_decision("UNKNOWN", "[]"), "NOOP")

    def test_unarmed_stands_down(self):
        self.assertEqual(run_decision("UNARMED", "[]"), "NOOP")

    def test_halted_stands_down(self):
        self.assertEqual(run_decision("HALTED", "[]"), "NOOP")

    def test_contaminated_status_stands_down(self):
        """RED against a blacklist: jq diagnostic text that merely contains ARMED."""
        self.assertEqual(
            run_decision("jq: error (at <stdin>:70) ARMED 3", "[]"), "NOOP",
            "an unrecognised status reached the mandate path")

    def test_armed_prefix_without_digits_stands_down(self):
        self.assertEqual(run_decision("ARMEDGARBAGE", "[]"), "NOOP")


class TestEveryEmittedSentinelIsExcluded(unittest.TestCase):
    """The #921 contract, stated as an invariant instead of three literals.

    Every sentinel the hook EMITS must be unable to arm the mandate. Asserting
    that against the emitter — rather than against strings retyped here — is what
    makes the suite self-maintaining: adding a fourth sentinel to the hook
    without adding it to the prelude exclusion turns this red, which is exactly
    the mistake that produced #921 in the first place.
    """

    def test_the_emitter_still_has_sentinels(self):
        """Guard the guard: if the extraction silently found nothing, everything
        below would vacuously pass."""
        self.assertTrue(
            emitted_sentinels(),
            "no [godspeed-*] sentinels found in %s — extraction is broken, and "
            "every exclusion test below would pass vacuously" % HOOK)

    def test_no_emitted_sentinel_can_arm(self):
        for sentinel in emitted_sentinels():
            with self.subTest(sentinel=sentinel):
                t = _make(_user("%s block text that itself names /godspeed"
                                % sentinel))
                self.assertEqual(
                    run_eval(t), "UNARMED",
                    "%s arms the mandate it gates" % sentinel)

    def test_legacy_sentinel_still_excluded(self):
        """Not currently emitted, but present in real transcripts the scan reads."""
        t = _make(_user("%s stopping for approval; resume with /godspeed"
                        % LEGACY_STOP_SENTINEL))
        self.assertEqual(run_eval(t), "UNARMED")


class TestCorpusFalsePositives(unittest.TestCase):
    """Regressions for the 13 false arms found by sweeping 3772 real transcripts.

    The first draft of the #921 fix armed 17 of the 40 real user turns that
    mention the token; only 4 were genuine. Every string below is REAL, and each
    one armed the mandate before the arming form was corrected.

    These exist because fixture-driven testing could not have found this: the
    fixtures encoded the same assumption the implementation did.
    """

    def test_repo_file_path_does_not_arm(self):
        """REAL: `scripts/godspeed-lookback.sh` contains the substring `/godspeed`.

        Merely NAMING the detector armed it. This one turn shape covers a code
        review prompt, a `git status` paste, and a subagent task notification.
        """
        t = _make(_user(" M scripts/godspeed-lookback.sh"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_code_review_prompt_does_not_arm(self):
        """REAL corpus turn — a review prompt naming the changed files."""
        t = _make(_user(
            "Review all files changed on the current branch vs main. "
            "Changed: scripts/godspeed-lookback.sh, scripts/precheck-asking-detector.sh"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_double_quoted_mention_does_not_arm(self):
        """REAL corpus turn — BJ discussing the feature, not invoking it."""
        t = _make(_user(
            'i think it destroys the usefulness of "/godspeed"'))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_task_notification_does_not_arm(self):
        """REAL: a subagent completion notification quoting a file path."""
        t = _make(_user(
            "<task-notification>\n<task-id>a4e6a30cbe89b1318</task-id>\n"
            "reviewed the hook, then /godspeed\n</task-notification>"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_compaction_summary_quoting_an_arming_turn_does_not_arm(self):
        """REAL and the nastiest: a summary QUOTING a past arming turn.

        Machine-generated, and it reproduces the exact idiom verbatim. Without
        the machine-turn exclusion, every compaction would re-arm whatever the
        summary happened to quote.
        """
        t = _make(_user(
            "This session is being continued from a previous conversation that "
            "ran out of context. The summary below covers it.\n"
            '  - BJ said "please be as autonomous as you can safely be. /godspeed"'))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_skill_body_injection_does_not_arm(self):
        """REAL: a skill body injected as a user turn."""
        t = _make(_user(
            "Base directory for this skill: /home/bakerb/.claude/skills/disc\n"
            "ARGUMENTS: send babelfish a bug report w.r.t. godspeed issues"))
        self.assertEqual(run_eval(t), "UNARMED")

    def test_pasted_multiline_example_does_not_arm(self):
        """The `\\n\\s*` clause armed on any line beginning with the token.

        Pasting a quoted example is routine in this repo. Dropping that clause
        cost nothing: all four genuine corpus turns arm via the slash form or a
        sentence boundary.
        """
        t = _make(_user(
            "here is the doc section:\n\ngodspeed, my friend\n\nwhat do you think?"))
        self.assertEqual(run_eval(t), "UNARMED")


class TestCorpusTruePositives(unittest.TestCase):
    """The 4 genuine arming turns found in 3772 transcripts. All must survive.

    Guards the opposite direction from TestCorpusFalsePositives: a narrowing that
    also rejected real arming turns would be a silent removal of a feature BJ
    uses, and would look identical to a clean pass.
    """

    # Verbatim corpus turns. The sweep armed exactly these four after the fix,
    # and the count is quoted as evidence in three separate comments — so the
    # list length is part of the claim and must not drift from it.
    REAL_ARMING_TURNS = [
        "agreed.  continuous, phas-boundary reporting.  godspeed, my friend",
        "thank you.  please be as autonomous as you can safely be.  /godspeed",
        "roll them in.  im working with lots of agents, so /godspeed",
        "ok, i am gonna put you back in godspeed mod, but i left you a list of "
        "places you can find good test targets in. feel like you have excercised "
        "the kit well.  /godspeed",
    ]

    def test_the_list_still_matches_the_measured_count(self):
        """The 4-of-40 figure is load-bearing evidence; pin it to the fixtures."""
        self.assertEqual(
            len(self.REAL_ARMING_TURNS), 4,
            "the measured count (4) and this fixture list have drifted apart")

    def test_all_real_arming_turns_still_arm(self):
        for turn in self.REAL_ARMING_TURNS:
            with self.subTest(turn=turn[:48]):
                self.assertEqual(
                    run_eval(_make(_user(turn))), "ARMED 0",
                    "a genuine arming turn stopped arming")

    def test_bare_token_arms(self):
        """SYNTHETIC, and labelled so — a bare `godspeed` turn is NOT in the corpus.

        An earlier revision listed this alongside the four real turns under a
        docstring calling them all real, and described it as "REAL: the bare
        form". Checked: no turn in the 40 reduces to the bare token. Supporting
        it is still correct — it is the documented idiom and the cheapest thing
        BJ could type — but it is a design choice, not a corpus observation, and
        the two must not be quoted as if they were the same kind of evidence.
        """
        self.assertEqual(run_eval(_make(_user("godspeed"))), "ARMED 0")


class TestSlashCommandTurnsCountButDoNotArm(unittest.TestCase):
    """A slash command is machine-FORMATTED but human-ISSUED, and that splits.

    `<command-name>/precheck</command-name>` is written by Claude Code, so it
    must not arm — but BJ typed it, so it is a real interaction and the mandate
    must still decay across it. Folding both into one predicate silently widened
    autonomy: `d` rose slower than the decay model intends, lowering `bar_pct`
    and returning GO where the model meant ASK. In this fleet /precheck, /scp
    and /scpmmr are frequent, so the effect is not marginal.
    """

    def _command_turn(self, name):
        return _user("<command-message>%s is running…</command-message>\n"
                     "<command-name>%s</command-name>" % (name.lstrip('/'), name))

    def test_command_turn_counts_toward_decay(self):
        """RED against a single predicate: the command turn must consume a turn.

        Excluded from counting -> ARMED 0. Counted -> ARMED 1.
        """
        t = _make(_user("godspeed"), _asst("ok"), self._command_turn("/precheck"))
        self.assertEqual(run_eval(t), "ARMED 1",
                         "a slash-command turn did not decay the mandate")

    def test_command_turn_does_not_arm(self):
        """The other half: the envelope must not arm even when it names the token."""
        t = _make(self._command_turn("/godspeed"))
        self.assertEqual(run_eval(t), "UNARMED",
                         "a command envelope armed the mandate")


if __name__ == '__main__':
    unittest.main()
