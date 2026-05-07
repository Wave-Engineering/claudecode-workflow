"""Tests for skills/nextwave/SKILL.md — kahuna base-ref plumbing (issue #417).

Validates Dev Spec §5.2.3, updated for cc-workflow#580 (Classic mode retired):
- Step 1 (Orchestrator pre-flight) reads ``kahuna_branch`` from wave state and
  passes it forward to Prime(pre-wave). The field MUST be present — there is
  no legacy fallback path; ``/wavemachine``'s pre-flight bootstrap guarantees
  population.
- Prime(pre-wave) prompt template accepts ``kahuna_branch`` as input and
  forwards it into each Flight prompt unconditionally.
- Flight stub prompt includes the directive that work bases on
  ``origin/<kahuna_branch>`` and PRs target ``<kahuna_branch>`` (the kahuna
  branch is the integration target; the project's protected branch is reached
  only via the kahuna→protected-branch MR opened by ``wave_finalize``).
- Prime(post-flight) prompt template uses ``kahuna_branch`` as the
  ``pr_create`` ``base`` parameter unconditionally.

Tests assert content of the live SKILL.md file. They exercise the real
markdown — no mocks, no stubs. Maps to AC-1..AC-3 of the issue. The legacy
non-KAHUNA AC-4 was removed by cc-workflow#580; the test class below kept
the slot for the corresponding "kahuna is unconditional" assertions.
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
        into each Flight prompt. Per cc-workflow#580 the field is always
        populated, so the propagation is unconditional."""
        step2 = _section(skill_text, "Step 2 — Prime(pre-wave) prompt contract")
        # The instruction must be inside Step 2's prompt body.
        assert "kahuna_branch" in step2
        assert re.search(
            r"[Pp]ass\s+`?<?kahuna_branch>?`?\s+into\s+each\s+Flight\s+prompt",
            step2,
        ), "Step 2 must instruct Prime to pass kahuna_branch into Flight prompts"


# ---------------------------------------------------------------------------
# AC-2: Flight prompt template includes the literal directive
# ``Base your work on origin/$KAHUNA_BRANCH, not main``
# ---------------------------------------------------------------------------


class TestAC2_FlightPromptKahunaDirective:
    """Flight stub prompt carries the directive that work bases on
    ``origin/<kahuna_branch>`` and PRs target ``<kahuna_branch>``. Per
    cc-workflow#580 this directive is unconditional — there is no legacy
    fallback to omit it for."""

    def test_flight_stub_has_base_directive(self, skill_text: str) -> None:
        """The directive must appear in the Flight stub prompt section."""
        stub = _flight_stub(skill_text)
        assert stub, "Flight stub prompt section not found"
        # Per cc-workflow#580 the wording is abstract — "the project's
        # protected branch" rather than literal "main" — so the assertion
        # tolerates either the protected-branch phrasing or any other phrasing
        # that names <kahuna_branch> as the base.
        assert re.search(
            r"[Bb]ase your work on\s+origin/`?<kahuna_branch>`?",
            stub,
        ), "Flight stub must instruct: 'Base your work on origin/<kahuna_branch>'"

    def test_flight_stub_directive_is_unconditional(
        self, skill_text: str
    ) -> None:
        """Per cc-workflow#580 the directive must NOT be marked conditional;
        kahuna is the only execution shape."""
        stub = _flight_stub(skill_text)
        # The retired conditional wording must be absent. (Conservative scan —
        # the skill body might mention "omit" in unrelated contexts; what we
        # care about is the specific phrasing that retired Classic mode.)
        assert not re.search(
            r"[Oo]mit this line.*kahuna_branch is unset|kahuna_branch.*unset.*flights then",
            stub,
        ), (
            "Flight stub must NOT mark the kahuna directive as conditional — "
            "per cc-workflow#580 kahuna is unconditional"
        )


# ---------------------------------------------------------------------------
# AC-3: Flight's pr_create call uses base=<kahuna_branch> when set, else main
# ---------------------------------------------------------------------------


class TestAC3_PrCreateBaseRouting:
    """Prime(post-flight) — which actually calls ``pr_create`` — uses
    ``base=<kahuna_branch>`` unconditionally per cc-workflow#580."""

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
        """The pr_create call must reference ``base: <kahuna_branch>``.
        Per cc-workflow#580 there is no fallback to ``base: "main"`` —
        kahuna is the only integration target for Flight PRs."""
        step3e = _section(skill_text, "3e. Spawn Prime(post-flight)")
        assert re.search(
            r"pr_create\(\{base:\s*<kahuna_branch>\}\)", step3e
        ), "pr_create must take base: <kahuna_branch>"
        # Negative assertion: the retired fallback shape MUST NOT be present.
        assert not re.search(
            r"pr_create\(\{base:\s*\"main\"\}\)",
            step3e,
        ), (
            "pr_create must NOT fall back to base=main — per cc-workflow#580 "
            "kahuna is the only Flight-PR integration target"
        )

    def test_post_flight_describes_kahuna_target(self, skill_text: str) -> None:
        """Step 3e must call out that Flight PRs target the kahuna branch —
        never the project's protected branch directly. Cross-reference Dev
        Spec §5.2.2 for the kahuna→protected-branch MR."""
        step3e = _section(skill_text, "3e. Spawn Prime(post-flight)")
        assert re.search(
            r"target.*kahuna.*never.*protected|never.*protected.*kahuna",
            step3e,
            re.IGNORECASE | re.DOTALL,
        ), (
            "Step 3e must specify Flight PRs target kahuna, "
            "not the project's protected branch"
        )


# ---------------------------------------------------------------------------
# AC-4 (post-#580): Kahuna is unconditional — no legacy fallback path
# ---------------------------------------------------------------------------


class TestAC4_KahunaIsUnconditional:
    """Per cc-workflow#580 there is no legacy non-KAHUNA path. Step 1
    refuses to proceed if ``kahuna_branch`` is unset, the Prime(pre-wave)
    prompt template treats the field as always-populated, and worktree
    pre-creation bases off ``origin/<kahuna_branch>`` unconditionally."""

    def test_step1_refuses_when_kahuna_branch_missing(
        self, skill_text: str
    ) -> None:
        """Step 1 must refuse to proceed when ``kahuna_branch`` is missing
        from wave state — it must NOT fall back to a legacy path that
        bases off the project's protected branch."""
        step1 = _section(skill_text, "Step 1 — Orchestrator pre-flight")
        # The new contract: refuse / surface / restart-via-wavemachine when
        # the field is missing — NOT fall back to main.
        assert re.search(
            r"refuse|MUST be present|surface the error|restart",
            step1,
            re.IGNORECASE,
        ), (
            "Step 1 must refuse / surface an error when kahuna_branch is "
            "missing — kahuna is the only execution shape per #580"
        )
        # Negative assertion: the retired fallback wording must be absent.
        assert not re.search(
            r"absent or empty.*flights base off.*main|"
            r"legacy non-KAHUNA",
            step1,
            re.IGNORECASE | re.DOTALL,
        ), "Step 1 must NOT describe a legacy non-KAHUNA fallback path"

    def test_prime_prewave_prompt_treats_kahuna_branch_as_always_set(
        self, skill_text: str
    ) -> None:
        """Prime(pre-wave) prompt body must NOT describe an
        empty/legacy/omit-the-kahuna-lines path."""
        step2 = _section(skill_text, "Step 2 — Prime(pre-wave) prompt contract")
        # Negative: the retired conditional wording must be absent.
        assert not re.search(
            r"omit the kahuna lines|legacy non-KAHUNA|"
            r"if kahuna_branch is empty",
            step2,
            re.IGNORECASE,
        ), (
            "Step 2 must NOT describe an empty/legacy path — "
            "per #580 kahuna_branch is always populated"
        )

    def test_pre_create_worktree_uses_kahuna_branch_unconditionally(
        self, skill_text: str
    ) -> None:
        """Cross-repo worktree pre-creation step bases off
        ``origin/<kahuna_branch>`` unconditionally — no fallback to main."""
        step1 = _section(skill_text, "Step 1 — Orchestrator pre-flight")
        assert re.search(
            r"origin/<kahuna_branch>", step1
        ), "Worktree pre-creation must reference origin/<kahuna_branch>"
        # Negative: no fallback wording.
        assert not re.search(
            r"kahuna_branch.*if set.*main|kahuna_branch.*else.*main",
            step1,
            re.IGNORECASE | re.DOTALL,
        ), "Step 1 worktree section must NOT select 'kahuna_branch if set, else main'"


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
