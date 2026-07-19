"""Tests for skills/mmr/SKILL.md — the CI gate must be default-DENY.

Why this file exists (cc-workflow#925):

`/mmr`'s CI gate was inert on GitHub for its entire life. Three facts composed:

  1. `gh pr checks --json` does not exist on gh 2.45.0, the fleet version.
  2. The adapter reads results only on exitCode == 0, so `checks.summary` kept
     its `'none'` initialiser — and the call still returned ok: true.
  3. `/mmr` blocked on `has_failures` and waited on `pending`. Nothing required
     a PASS.

`'none'` matched neither branch, so every GitHub merge fell through to the merge
step. The gate reported fine and did nothing.

The defect is the *shape*, not the value: a blocklist of known-bad states
silently permits every state nobody thought of. These tests pin the allowlist so
a future edit cannot quietly restore the blocklist form.

This matters more than it looks because several paths merge with **no human**:
kahuna sandboxes (`/precheck` auto-approves), `/wavemachine`, `/lazyriver`, and
an armed `godspeed` mandate. Removing the human raises this gate from a second
opinion to the only opinion.
"""

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
MMR_PATH = _ROOT / "skills" / "mmr" / "SKILL.md"
PRECHECK_PATH = _ROOT / "skills" / "precheck" / "SKILL.md"


@pytest.fixture
def mmr_text() -> str:
    """Read the /mmr SKILL.md file."""
    return MMR_PATH.read_text(encoding="utf-8")


@pytest.fixture
def precheck_text() -> str:
    """Read the /precheck SKILL.md file."""
    return PRECHECK_PATH.read_text(encoding="utf-8")


class TestMmrCiGateIsDefaultDeny:
    def test_gate_requires_an_explicit_pass(self, mmr_text: str) -> None:
        """The gate must name all_passed as the condition to PROCEED.

        Fails against the pre-#925 skill, which never mentioned all_passed at
        all — it only enumerated the states that stop.
        """
        assert re.search(
            r"Proceed \*\*only\*\* if `checks\.summary == \"all_passed\"`", mmr_text
        ), (
            "the CI gate must require an explicit passing signal; a blocklist "
            "of failure states merges on everything it did not anticipate. "
            "NOTE: a bare `'all_passed' in mmr_text` would pass against a skill "
            "reading `NEVER merge if summary == \"all_passed\"` — the literal "
            "must be pinned in its PROCEED context, not merely present"
        )

    def test_unrecognised_summary_stops(self, mmr_text: str) -> None:
        """An unknown future value must stop, and the skill must say so.

        The original defect was not that `none` was mishandled — it is that
        ANY unenumerated value read as permission. Pinning only `none` would
        fix the instance and leave the class.
        """
        assert re.search(
            r"any other value\s+STOPs|Any other value\b.*STOP", mmr_text, re.I
        ), "the skill must state that values outside the allowlist stop"

    def test_none_is_not_treated_as_a_pass(self, mmr_text: str) -> None:
        """`none` means the query told us nothing — never that checks passed."""
        assert re.search(r"`?none`?\s+is not evidence of passing", mmr_text, re.I), (
            "the skill must state explicitly that a `none` summary is an absence "
            "of information, not a passing result"
        )

    def test_none_distinguishes_its_two_causes(self, mmr_text: str) -> None:
        """No checks configured and a failed query need different responses.

        Collapsing them is the same defect one layer down — a result that
        cannot distinguish "checked and found nothing" from "did not look".
        """
        assert re.search(r"no checks configured", mmr_text, re.I), (
            "the skill must name 'no checks configured' as one cause of `none`"
        )
        assert re.search(r"the query failed", mmr_text, re.I), (
            "the skill must name 'the query failed' as the other cause of `none`"
        )

    def test_never_rule_is_an_allowlist_not_a_blocklist(self, mmr_text: str) -> None:
        """The summary rule at the foot of the skill inherits the same defect.

        Pinning step 3 alone would leave a contradicting blocklist rule in the
        same file, and a reader consulting the rules section would get the old,
        permissive behaviour.
        """
        assert re.search(r"ONLY merge if .*all_passed", mmr_text), (
            "the rules section must be phrased as an allowlist"
        )
        assert not re.search(
            r"NEVER merge if `checks\.summary == \"has_failures\"`\s*$",
            mmr_text,
            re.M,
        ), (
            "the bare blocklist rule must not survive — it permits every state "
            "it does not enumerate"
        )


class TestAutonomousPathsDependOnThisGate:
    def test_precheck_lists_the_ci_gate_as_non_bypassable(
        self, precheck_text: str
    ) -> None:
        """Sandbox auto-approval must not compose with a skippable CI gate."""
        block = re.search(
            r"\*\*Non-bypassable items:\*\*.*?(?=\n\n)", precheck_text, re.S
        )
        assert block, "the non-bypassable items list is missing"
        assert re.search(r"CI gate", block.group(0), re.I), (
            "the CI gate must appear in the non-bypassable list; it is the last "
            "control on any path where the human approval is removed"
        )

    def test_the_other_autonomous_paths_are_named(self, precheck_text: str) -> None:
        """The kahuna sandbox is NOT the only path that merges without a human.

        Naming only the sandbox understates the exposure — an agent reading
        that would conclude non-sandbox work is human-gated, which is false
        under /wavemachine's auto mode and an armed godspeed mandate.

        `/lazyriver` was named here in an earlier draft and it was WRONG: it is
        a probe→journal→judge→steer goal-seek loop with no merge path at all.
        The first version of this test asserted its presence, which would have
        made the suite go red the moment someone corrected the prose. **A test
        that fails when you fix a factual error is worse than no test** — it
        converts the documentation bug into a reason not to fix it.
        """
        block = re.search(
            r"the kahuna sandbox is not the only path.*?(?=\n\n)",
            precheck_text,
            re.S | re.I,
        )
        assert block, "the autonomous-paths paragraph is missing"
        para = block.group(0)

        for mode in ("wavemachine", "godspeed"):
            assert mode in para, (
                f"/{mode} merges without a human and must be named IN the "
                f"paragraph documenting the CI gate as last control — a bare "
                f"whole-file substring check passes on any incidental mention"
            )

    def test_lazyriver_is_not_claimed_to_merge(self, precheck_text: str) -> None:
        """Pin the correction so the wrong claim cannot come back.

        Asserting absence is normally a weak test, but here the failure mode is
        specific and recurring: `/lazyriver` reads like a wave-family skill, so
        it is a natural thing to list alongside /wavemachine by association
        rather than by checking. If it is reintroduced it must be as an
        explicit exclusion, which is what the negative lookahead allows.
        """
        for m in re.finditer(r"lazyriver", precheck_text):
            window = precheck_text[max(0, m.start() - 200) : m.end() + 200]
            assert re.search(r"not\b|no merge path|deliberately", window, re.I), (
                "/lazyriver has no merge path; it may only appear here as an "
                "explicit exclusion, never in the list of paths that merge "
                "without a human"
            )


class TestDefaultDenyDoesNotBecomeATotalBlock:
    """Default-deny must escalate to a working source, not refuse outright.

    `pr_status` returns summary 'none' for EVERY GitHub PR on gh 2.45.0, so a
    bare "stop on anything but all_passed" converts a silent-permit into a
    fleet-wide merge block. Measured on the same PR, seconds apart:

        pr_status(32)   -> {total:0, passed:0, summary:"none"}
        pr_wait_ci(32)  -> {total:2, passed:2, failed:0, pending:0}

    They do not share a code path. Only pr_status is blind.
    """

    def test_none_escalates_to_pr_wait_ci(self, mmr_text: str) -> None:
        assert re.search(r"do NOT stop outright", mmr_text), (
            "on `none` the skill must escalate to a working source rather than "
            "refusing — pr_status is blind on every GitHub PR"
        )
        # NOT `re.search(r"pr_wait_ci.*authoritative", mmr_text, re.S)` — with
        # re.S the greedy `.*` spans the whole file, so it matches the mention
        # of pr_wait_ci in the Tools Used list at the top against the word
        # "authoritative" anywhere below, including a sentence saying it is NOT
        # authoritative. Anchor to one line instead.
        assert re.search(
            r"call `pr_wait_ci\(number\)` and treat \*\*its\*\* result as authoritative",
            mmr_text,
        ), "pr_wait_ci must be named as the authoritative fallback, in one clause"

    def test_states_why_a_bare_deny_is_useless(self, mmr_text: str) -> None:
        """The reasoning must survive, or someone 'simplifies' it back."""
        assert re.search(r"total merge block", mmr_text), (
            "the skill must record that a bare default-deny blocks every merge, "
            "so a future edit does not reintroduce it as a simplification"
        )

    def test_two_blind_sources_is_a_stop(self, mmr_text: str) -> None:
        assert re.search(r"unable to confirm a pass is a stop", mmr_text), (
            "if pr_wait_ci also cannot establish a result, that must STOP"
        )

    def test_escalation_is_itself_an_allowlist(self, mmr_text: str) -> None:
        """The INNER gate must be an allowlist too — this is the one that bit.

        The first version of #925 converted the outer gate (`checks.summary`)
        from a blocklist to an allowlist and then wrote the escalation as a
        blocklist: it enumerated the `pr_wait_ci` statuses that STOP and let
        everything else through. `no_checks_required` was already live (mcp-server-sdlc#416)
        and unlisted, so the escalation would have merged on it.

        Every assertion in this file passed against that hole. That is the
        proof that prose-substring tests pin wording rather than behaviour —
        so this one pins the COMPLETENESS of the enumeration, which is the
        actual failure mode, rather than the presence of a slogan.
        """
        assert re.search(
            r"[Ee]very other status STOPs, including ones not listed here", mmr_text
        ), "the pr_wait_ci escalation must be phrased as an allowlist"
        assert re.search(r"`?no_checks_required`?\s*→\s*\*\*STOP", mmr_text), (
            "`no_checks_required` must be named as an explicit STOP — it is a "
            "definite, successful verdict whose plain-English name reads as "
            "permission, so it is the value most likely to be mis-read"
        )
        assert re.search(r"`\{ok: false\}` or any error envelope\s*→\s*\*\*STOP", mmr_text), (
            "an {ok:false} envelope must STOP explicitly; 'report and suggest' "
            "is not a stop, and it is the softest link in a default-deny gate"
        )

    def test_no_human_branch_halts_rather_than_improvising(self, mmr_text: str) -> None:
        """'A human decides' has no addressee on the autonomous paths.

        /precheck lists this gate as non-bypassable precisely because it is the
        last control once the human is gone — so the branch that defers TO a
        human must say what happens when there isn't one. An underspecified
        branch is where an autonomous agent improvises, and improvising toward
        'proceed' is the failure the whole gate exists to prevent.
        """
        assert re.search(r"If there is no human — HALT", mmr_text), (
            "the skill must define the no-human case explicitly rather than "
            "leaving 'a human decides' as the terminal instruction"
        )
        assert re.search(r"wave-hold", mmr_text), (
            "the halt must emit a structured blocker the wave gate can "
            "escalate, not merely stop"
        )

    def test_escalation_survives_the_upstream_fix(self, mmr_text: str) -> None:
        """The escalation must not be deleted when `pr_status` becomes truthful.

        `mcp-server-sdlc#491` (PR #495) makes GitHub's `pr_status` report real
        results, which makes the escalation branch *look* like dead code. It is
        not: mcp-server-sdlc#494 records the identical silent-permissive shape on GitLab —
        `no_pipeline_data` returned with `ok: true` — and it is still open.

        This is the instance-vs-class distinction the whole file is about, one
        layer up: fixing the reporter we measured does not fix reporters we
        have not measured. The escalation is written against ANY unrecognised
        summary so it covers variants nobody has named yet, and narrowing it to
        the value we happened to observe would restore the blocklist shape.
        """
        assert re.search(r"[Dd]o not delete the escalation", mmr_text), (
            "the skill must warn against removing the escalation once the "
            "upstream reporter is fixed — it reads as dead code and is not"
        )
        assert "mcp-server-sdlc#494" in mmr_text, (
            "the skill must cite the still-open GitLab variant; without a live "
            "counter-example the warning is an assertion a future editor can "
            "reasonably dismiss"
        )
