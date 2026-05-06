"""Tests for skills/nextwave/SKILL.md — kahuna base-ref plumbing (issue #417).

Validates Dev Spec §5.2.3:
- Step 1 (Orchestrator pre-flight) reads ``kahuna_branch`` from wave state and
  passes it forward to Prime(pre-wave).
- Prime(pre-wave) prompt template accepts ``kahuna_branch`` as input and
  forwards it into each Flight prompt when set.
- Flight stub prompt includes the literal directive
  ``Base your work on origin/<kahuna_branch>, not main`` when
  ``kahuna_branch`` is set.
- Prime(post-flight) prompt template uses ``kahuna_branch`` as the
  ``pr_create`` ``base`` parameter when set, and ``main`` otherwise.
- Legacy non-KAHUNA waves (no ``kahuna_branch`` in state) are explicitly
  preserved as a no-change path.

Tests assert content of the live SKILL.md file. They exercise the real
markdown — no mocks, no stubs. Maps to AC-1..AC-4 of the issue.
AC-5 / AC-6 are integration-test-level acceptance criteria (Dev Spec §6.2)
and are out of scope for the SKILL.md unit-level coverage here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths and fixtures
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "nextwave" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the nextwave SKILL.md file once per module."""
    return SKILL_PATH.read_text(encoding="utf-8")


def _section(text: str, header: str) -> str:
    """Return the slice of ``text`` from the matching header to the next
    sibling/parent header (``## `` or ``### ``).

    ``header`` is matched by substring on the line. The slice ends at the
    next line beginning with ``## `` or ``### ``. Used to scope assertions
    to a specific step rather than the whole document.
    """
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if header in line and (line.startswith("## ") or line.startswith("### ")):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## ") or lines[j].startswith("### "):
            end = j
            break
    return "".join(lines[start:end])


def _flight_stub(text: str) -> str:
    """Return the Flight stub prompt section (## heading at end of file)."""
    return _section(text, "Flight stub prompt")


# ---------------------------------------------------------------------------
# Existence + framing
# ---------------------------------------------------------------------------


class TestSkillFileShape:
    """Sanity checks: file exists, frontmatter intact, kahuna terminology
    present at the document level."""

    def test_skill_file_exists(self) -> None:
        assert SKILL_PATH.is_file(), f"missing: {SKILL_PATH}"

    def test_frontmatter_name(self, skill_text: str) -> None:
        assert skill_text.startswith("---\nname: nextwave\n")

    def test_kahuna_branch_referenced(self, skill_text: str) -> None:
        """``kahuna_branch`` MUST appear at least once — sanity check that
        the kahuna plumbing landed somewhere."""
        assert "kahuna_branch" in skill_text


# ---------------------------------------------------------------------------
# AC-1: Prime reads kahuna_branch from wave state and passes into Flight
# prompt (orchestrator + Prime(pre-wave) sides of the chain)
# ---------------------------------------------------------------------------


class TestAC1_PrimeReadsKahunaBranch:
    """The Orchestrator (Step 1) reads ``kahuna_branch`` from wave state and
    feeds it into the Prime(pre-wave) prompt; Prime(pre-wave)'s template
    accepts that input and forwards it into each Flight prompt."""

    def test_step1_reads_wave_state_for_kahuna_branch(self, skill_text: str) -> None:
        """Step 1 explicitly instructs the Orchestrator to read
        ``kahuna_branch`` from wave state."""
        step1 = _section(skill_text, "Step 1 — Orchestrator pre-flight")
        assert step1, "Step 1 section not found"
        assert "kahuna_branch" in step1
        # State source — wave_show or state.json must be named.
        assert "wave_show" in step1 or "state.json" in step1

    def test_step1_routes_kahuna_branch_into_prime_prompt(
        self, skill_text: str
    ) -> None:
        """Step 1 must say the captured kahuna_branch is passed into the
        Prime(pre-wave) prompt."""
        step1 = _section(skill_text, "Step 1 — Orchestrator pre-flight")
        assert "Prime(pre-wave) prompt" in step1 or "Prime(pre-wave)" in step1
        # The capture-and-forward intent must be expressed.
        assert re.search(
            r"pass(?:e[ds])?.*kahuna_branch|kahuna_branch.*(?:pass|input)",
            step1,
            re.IGNORECASE,
        ), "Step 1 must describe passing kahuna_branch into Prime prompt"

    def test_prime_prewave_prompt_lists_kahuna_branch_input(
        self, skill_text: str
    ) -> None:
        """Prime(pre-wave) prompt template's Inputs section lists
        ``Kahuna branch:``."""
        step2 = _section(skill_text, "Step 2 — Prime(pre-wave) prompt contract")
        assert step2, "Step 2 section not found"
        # The bullet form used by other inputs.
        assert re.search(r"-\s+Kahuna branch:\s*`<kahuna_branch>`", step2), (
            "Prime(pre-wave) Inputs must include `- Kahuna branch: "
            "`<kahuna_branch>`` bullet"
        )

    def test_prime_prewave_forwards_kahuna_to_flight_prompt(
        self, skill_text: str
    ) -> None:
        """Prime(pre-wave) instructions tell it to propagate kahuna_branch
        into each Flight prompt when set."""
        step2 = _section(skill_text, "Step 2 — Prime(pre-wave) prompt contract")
        # The instruction must be inside Step 2's prompt body.
        assert "kahuna_branch" in step2
        assert re.search(
            r"pass(?:e[ds])?\s+it\s+into\s+each\s+Flight\s+prompt",
            step2,
            re.IGNORECASE,
        ), "Step 2 must instruct Prime to pass kahuna_branch into Flight prompts"


# ---------------------------------------------------------------------------
# AC-2: Flight prompt template includes the literal directive
# ``Base your work on origin/$KAHUNA_BRANCH, not main``
# ---------------------------------------------------------------------------


class TestAC2_FlightPromptKahunaDirective:
    """Flight stub prompt carries the literal ``Base your work on
    origin/<kahuna_branch>, not main`` directive when ``kahuna_branch`` is
    set."""

    def test_flight_stub_has_base_directive(self, skill_text: str) -> None:
        """The literal directive must appear in the Flight stub prompt
        section. We accept the placeholder form with backticks because the
        skill uses ``<kahuna_branch>`` placeholders throughout."""
        stub = _flight_stub(skill_text)
        assert stub, "Flight stub prompt section not found"
        # Tolerate both backtick-wrapped placeholder and bare form.
        assert re.search(
            r"Base your work on origin/`?<kahuna_branch>`?,\s*not main",
            stub,
        ), "Flight stub must contain 'Base your work on origin/<kahuna_branch>, not main'"

    def test_flight_stub_directive_conditional_on_kahuna_set(
        self, skill_text: str
    ) -> None:
        """The directive must be marked as conditional — omitted when
        ``kahuna_branch`` is unset — to preserve legacy behavior."""
        stub = _flight_stub(skill_text)
        # Some phrasing must mark the line as conditional / omitted in
        # legacy mode. Accept either ``omit`` or ``unset`` wording.
        assert re.search(
            r"omit.*kahuna_branch|kahuna_branch.*unset|legacy",
            stub,
            re.IGNORECASE,
        ), "Flight stub must mark the kahuna directive as conditional"


# ---------------------------------------------------------------------------
# AC-3: Flight's pr_create call uses base=<kahuna_branch> when set, else main
# ---------------------------------------------------------------------------


class TestAC3_PrCreateBaseRouting:
    """Prime(post-flight) — which actually calls ``pr_create`` — uses
    ``base=<kahuna_branch>`` when set, else ``base=main``."""

    def test_post_flight_prompt_lists_kahuna_branch_input(
        self, skill_text: str
    ) -> None:
        """Prime(post-flight) prompt template Inputs section lists
        ``Kahuna branch:``."""
        step3e = _section(skill_text, "3e. Spawn Prime(post-flight)")
        assert step3e, "Step 3e section not found"
        assert re.search(r"-\s+Kahuna branch:\s*`<kahuna_branch>`", step3e), (
            "Prime(post-flight) Inputs must include `- Kahuna branch: "
            "`<kahuna_branch>`` bullet"
        )

    def test_post_flight_pr_create_base_branches(self, skill_text: str) -> None:
        """The pr_create call must reference ``base: <kahuna_branch>`` when
        set, and ``base: "main"`` (or equivalent) otherwise."""
        step3e = _section(skill_text, "3e. Spawn Prime(post-flight)")
        # Both forms must be present somewhere in the step body.
        assert re.search(
            r"pr_create\(\{base:\s*<kahuna_branch>\}\)", step3e
        ), "pr_create must take base: <kahuna_branch> when set"
        assert re.search(
            r"pr_create\(\{base:\s*\"main\"\}\)|base=main",
            step3e,
        ), "pr_create must fall back to base=main when kahuna_branch unset"

    def test_post_flight_describes_kahuna_target(self, skill_text: str) -> None:
        """Step 3e must call out that KAHUNA wave Flight PRs target the
        kahuna branch — never main directly. Cross-reference Dev Spec
        §5.2.2 for the kahuna→main MR."""
        step3e = _section(skill_text, "3e. Spawn Prime(post-flight)")
        assert re.search(
            r"target.*kahuna.*never.*main|never.*main.*kahuna",
            step3e,
            re.IGNORECASE | re.DOTALL,
        ), "Step 3e must specify Flight PRs target kahuna, not main, in KAHUNA mode"


# ---------------------------------------------------------------------------
# AC-4: Legacy non-KAHUNA waves behave identically to today
# ---------------------------------------------------------------------------


class TestAC4_LegacyNonKahunaUnchanged:
    """When wave state has no ``kahuna_branch``, behavior is identical to
    pre-KAHUNA execution: branches off main, PRs target main."""

    def test_step1_describes_legacy_path(self, skill_text: str) -> None:
        """Step 1 must say absent/empty kahuna_branch → legacy behavior
        (base off main)."""
        step1 = _section(skill_text, "Step 1 — Orchestrator pre-flight")
        assert re.search(
            r"absent.*main|empty.*main|legacy.*main|base off `?main`?",
            step1,
            re.IGNORECASE | re.DOTALL,
        ), "Step 1 must describe legacy fallback (no kahuna_branch → base off main)"

    def test_prime_prewave_prompt_describes_legacy_omission(
        self, skill_text: str
    ) -> None:
        """Prime(pre-wave) prompt body must instruct: when kahuna_branch is
        empty, omit the kahuna lines from the Flight prompt."""
        step2 = _section(skill_text, "Step 2 — Prime(pre-wave) prompt contract")
        assert re.search(
            r"empty.*omit|omit.*empty|legacy",
            step2,
            re.IGNORECASE,
        ), "Step 2 must describe the empty/legacy path for the Flight prompt"

    def test_pre_create_worktree_uses_kahuna_or_main(
        self, skill_text: str
    ) -> None:
        """Cross-repo worktree pre-creation step must base off
        ``kahuna_branch`` when set, else ``main``."""
        step1 = _section(skill_text, "Step 1 — Orchestrator pre-flight")
        # Worktree command form: ``origin/<base-ref>`` plus a description of
        # the base-ref selection.
        assert re.search(r"origin/<base-ref>|origin/<kahuna_branch>", step1), (
            "Worktree pre-creation must reference origin/<base-ref> "
            "or origin/<kahuna_branch>"
        )
        assert re.search(
            r"kahuna_branch.*if set.*main|kahuna_branch.*else.*main",
            step1,
            re.IGNORECASE | re.DOTALL,
        ), "Step 1 worktree section must select kahuna_branch if set, else main"


# ---------------------------------------------------------------------------
# Cross-reference: Dev Spec §5.2.3 must be cited at least once.
# Anchors the prose to the authoritative contract per the issue body.
# ---------------------------------------------------------------------------


class TestDevSpecCrossReference:
    """The Dev Spec §5.2.3 reference must remain in the skill so future
    readers can find the authoritative contract."""

    def test_devspec_5_2_3_referenced(self, skill_text: str) -> None:
        assert re.search(r"§\s*5\.2\.3|Dev Spec.*5\.2\.3", skill_text), (
            "Dev Spec §5.2.3 must be cross-referenced from the skill"
        )


# ---------------------------------------------------------------------------
# Regression: Prime(post-flight) prompt must declare the canonical-line
# contract verbatim, list forbidden phrases, and place an Exit shape section
# as the LAST section of the prompt template.
#
# Source incident: Plan #581 wave-2 flight-1 (2026-05-05). The Prime(post-
# flight) sub-agent emitted ``"Sleep is still running. Let me wait for the
# notification."`` instead of the canonical JSON line after a Bash(sleep)
# returned mid-CI-poll loop, breaking the Orchestrator's parse contract.
#
# Issue: claudecode-workflow#606
# Maps to AC-1 (canonical-line + forbidden-phrases sections in prompt) and
# AC-2 (this regression test). AC-3 is integration-test-level.
# ---------------------------------------------------------------------------


def _prime_post_flight_prompt(text: str) -> str:
    """Return the body of the Prime(post-flight) prompt template — the
    blockquote that follows the Step 3e header and runs until the end of
    the blockquote (the next non-blockquote line marks the end).

    The prompt is a markdown blockquote (every line begins with ``> ``).
    We slice from the first blockquote line after the 3e header to the
    last consecutive blockquote line.
    """
    step3e = _section(text, "3e. Spawn Prime(post-flight)")
    if not step3e:
        return ""
    lines = step3e.splitlines(keepends=True)
    in_quote = False
    quote_lines: list[str] = []
    for line in lines:
        if line.startswith(">"):
            in_quote = True
            quote_lines.append(line)
        elif in_quote and line.strip() == "":
            # Blank lines inside a blockquote are sometimes rendered as a
            # bare newline rather than ``>`` — keep collecting unless the
            # next non-blank line breaks out of the quote. Cheaper: append
            # and let the regex assertions ignore it.
            quote_lines.append(line)
        elif in_quote:
            # First non-blockquote, non-blank line after the quote — stop.
            break
    return "".join(quote_lines)


class TestPrimePostFlightCanonicalLineUnderLongCi:
    """Prime(post-flight) prompt declares the canonical-line contract,
    lists forbidden phrases (including the Plan #581 narration), and
    places an Exit shape section as the LAST section of the prompt.

    Test name maps to issue #606's named regression test:
    ``test_prime_post_flight_canonical_line_under_long_ci``.
    """

    def test_step3e_section_exists(self, skill_text: str) -> None:
        """Sanity: Step 3e is present at all."""
        assert _section(skill_text, "3e. Spawn Prime(post-flight)"), (
            "Step 3e (Spawn Prime(post-flight)) section is missing"
        )

    def test_post_flight_prompt_has_exit_shape_section(
        self, skill_text: str
    ) -> None:
        """The prompt template must contain a section literally headed
        ``Exit shape`` (case-insensitive). This is the section that holds
        the canonical-line contract.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        assert prompt, "Prime(post-flight) prompt body could not be located"
        assert re.search(r"^>\s*##\s*Exit shape\s*$", prompt, re.MULTILINE), (
            "Prime(post-flight) prompt must contain a `## Exit shape` section"
        )

    def test_exit_shape_is_last_section_of_prompt(self, skill_text: str) -> None:
        """The ``Exit shape`` section must be the LAST section of the
        prompt template — i.e. no other ``## ``- or ``### ``-level heading
        appears after it inside the blockquote. Rationale: it must be the
        most recent context when the agent composes its final message.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        # Find the Exit shape header line.
        match = re.search(
            r"^>\s*##\s*Exit shape\s*$", prompt, re.MULTILINE
        )
        assert match, "Exit shape header not found"
        tail = prompt[match.end():]
        # No further ``## `` / ``### `` headers in the same blockquote.
        assert not re.search(r"^>\s*##+\s+\S", tail, re.MULTILINE), (
            "Exit shape must be the LAST section in the Prime(post-flight) "
            "prompt — found another header after it"
        )

    def test_canonical_line_shape_stated_verbatim(self, skill_text: str) -> None:
        """The literal canonical-line shape must appear inside the Exit
        shape section. Match the JSON skeleton with PASS|FAIL|BLOCKED.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        # The literal placeholder form used elsewhere in the skill.
        assert re.search(
            r'\{"report_path":"<absolute-path-to-merge-report\.md>",'
            r'"status":"PASS\|FAIL\|BLOCKED"\}',
            prompt,
        ), "Canonical line shape must be stated verbatim with PASS|FAIL|BLOCKED"

    def test_concrete_examples_present(self, skill_text: str) -> None:
        """At least one concrete example of each terminal status must
        appear, so the agent has a literal shape to copy from."""
        prompt = _prime_post_flight_prompt(skill_text)
        # Concrete PASS example — actual JSON, not the placeholder form.
        assert re.search(
            r'\{"report_path":"/tmp/wavemachine/[^"]+","status":"PASS"\}',
            prompt,
        ), "Concrete PASS example missing from Exit shape"
        assert re.search(
            r'\{"report_path":"/tmp/wavemachine/[^"]+","status":"FAIL"\}',
            prompt,
        ), "Concrete FAIL example missing from Exit shape"
        assert re.search(
            r'\{"report_path":"/tmp/wavemachine/[^"]+","status":"BLOCKED"\}',
            prompt,
        ), "Concrete BLOCKED example missing from Exit shape"

    def test_forbidden_phrase_sleep_narration(self, skill_text: str) -> None:
        """The exact narration that broke the contract on Plan #581 must
        be listed as forbidden. This is the load-bearing assertion: if
        someone re-introduces the narration pattern by relaxing this
        section, the test catches it.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        assert re.search(
            r"Sleep is still running\.?\s*Let me wait for the notification",
            prompt,
            re.IGNORECASE,
        ), (
            "Forbidden phrase 'Sleep is still running. Let me wait for the "
            "notification.' must be cited verbatim in the Exit shape "
            "section (Plan #581 incident reference)"
        )

    def test_forbidden_phrases_list_present(self, skill_text: str) -> None:
        """A ``Forbidden phrases`` section must exist — it's the rubric
        the agent reads before emitting its final message."""
        prompt = _prime_post_flight_prompt(skill_text)
        assert re.search(
            r"[Ff]orbidden phrases?", prompt
        ), "Exit shape must contain a 'Forbidden phrases' list"

    def test_polling_loop_discipline_section(self, skill_text: str) -> None:
        """The prompt must explicitly tell the agent NOT to emit narration
        between polling iterations. This addresses the root cause: the
        agent narrating sleep state during a long CI wait.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        # Look for an instruction tying polling-loop iterations to silence.
        assert re.search(
            r"polling[- ]loop|between iterations|between sleeps|"
            r"do not emit.*between|silently",
            prompt,
            re.IGNORECASE,
        ), (
            "Exit shape must include polling-loop discipline — explicitly "
            "instruct the agent to not narrate between sleep iterations"
        )

    def test_plan_581_incident_referenced(self, skill_text: str) -> None:
        """The motivating incident (Plan #581) must be referenced inside
        the prompt so future readers know why this section exists.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        assert re.search(r"Plan #?581|#?581", prompt), (
            "Exit shape must reference Plan #581 (the source incident)"
        )

    def test_canonical_line_regex_cited(self, skill_text: str) -> None:
        """The canonical-line regex (or an equivalent strict pattern) must
        appear in the prompt so the agent has a mechanical check it can
        run against its own output.
        """
        prompt = _prime_post_flight_prompt(skill_text)
        # The regex pattern itself or an unambiguous reference to the JSON
        # shape with PASS|FAIL|BLOCKED.
        assert re.search(
            r"\^\\\{|regex|report_path.*status.*PASS\|FAIL\|BLOCKED",
            prompt,
        ), (
            "Exit shape must cite the canonical-line regex / strict shape "
            "pattern so the agent can self-check before emitting"
        )
