"""Tests for cc-workflow#601 — long-session drift mitigation in /wavemachine.

Validates two surfaces:

1. The instrumentation script ``scripts/wavemachine/drift-instrumentation.sh``
   exists, is executable, and its self-test subcommand produces three
   well-formed JSON-line events with the canonical event names.
2. The wavemachine SKILL.md documents the mitigation mechanism, names the
   three drift-signal events, references WAVE_AXIOMS.md (and Axiom 9
   specifically), wires the emit call into the Wave-to-Wave Handoff
   tool-use boundary, and lists the rejected alternatives.

These tests assert content of live files — no mocks. The script is invoked
as a real subprocess; the SKILL.md is read from disk. The shape mirrors
``tests/test_wavemachine_skill.py`` and ``tests/test_nextwave_skill.py``.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths and fixtures
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
SKILL_PATH = _ROOT / "skills" / "wavemachine" / "SKILL.md"
SCRIPT_PATH = _ROOT / "scripts" / "wavemachine" / "drift-instrumentation.sh"

# The three canonical event names emitted per wave by the instrumentation.
# These names are the contract — changing them breaks the report subcommand
# and any downstream aggregator.
DRIFT_EVENTS = (
    "wave_message_length_main",
    "wave_stop_hook_blocks",
    "wave_concerns_posts",
)


@pytest.fixture(scope="module")
def skill_text() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# AC-1: Script exists, executable, self-test produces canonical events
# ---------------------------------------------------------------------------


class TestAC1_ScriptShape:
    """The drift-instrumentation script must exist, be executable, and
    expose the three subcommands the SKILL body and post-campaign report
    pipeline rely on (emit-wave-drift, self-test, report)."""

    def test_script_exists(self) -> None:
        assert SCRIPT_PATH.exists(), (
            f"drift-instrumentation script not found at {SCRIPT_PATH}"
        )

    def test_script_is_executable(self) -> None:
        mode = SCRIPT_PATH.stat().st_mode
        assert mode & stat.S_IXUSR, (
            f"drift-instrumentation script is not executable: {SCRIPT_PATH}"
        )

    def test_script_help_lists_subcommands(self) -> None:
        result = subprocess.run(
            [str(SCRIPT_PATH), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Help is allowed on either stdout (--help) or stderr (usage error
        # path); union the streams for the assertion. Bash scripts often
        # mix the two.
        out = result.stdout + result.stderr
        for sub in ("emit-wave-drift", "self-test", "report"):
            assert sub in out, f"--help missing '{sub}' subcommand: {out!r}"

    def test_self_test_emits_three_canonical_events(self) -> None:
        """The self-test subcommand emits exactly three JSON lines, one per
        canonical event, in the documented order (message-length, stop-hook,
        concerns)."""
        result = subprocess.run(
            [str(SCRIPT_PATH), "self-test"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        lines = [ln for ln in result.stdout.strip().splitlines() if ln]
        assert len(lines) == 3, (
            f"expected 3 lines, got {len(lines)}: {lines}"
        )
        events_seen = []
        for line in lines:
            obj = json.loads(line)
            # Schema baseline — every event has these fields.
            for required in ("ts", "server", "level", "event"):
                assert required in obj, (
                    f"event missing '{required}': {obj}"
                )
            assert obj["server"] == "wave", (
                f"event server should be 'wave', got {obj['server']!r}"
            )
            events_seen.append(obj["event"])
        assert events_seen == list(DRIFT_EVENTS), (
            f"self-test event order/names wrong. "
            f"expected {list(DRIFT_EVENTS)}, got {events_seen}"
        )

    def test_self_test_does_not_touch_real_logfile(self, tmp_path) -> None:
        """The self-test subcommand emits to stdout, NOT to the fleet
        logfile. Verify by overriding LOG_FILE to a tmp path and confirming
        nothing is written there."""
        log_file = tmp_path / "mcp.jsonl"
        env = {**os.environ, "LOG_FILE": str(log_file)}
        subprocess.run(
            [str(SCRIPT_PATH), "self-test"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        assert not log_file.exists(), (
            f"self-test wrote to LOG_FILE={log_file}, should be stdout-only"
        )

    def test_emit_wave_drift_rejects_non_integer(self) -> None:
        """Validation: the emit subcommand refuses non-integer counts so
        malformed events never reach the fleet logfile."""
        result = subprocess.run(
            [
                str(SCRIPT_PATH), "emit-wave-drift",
                "--plan", "581",
                "--wave", "3a",
                "--message-length-main", "not-a-number",
                "--stop-hook-blocks", "0",
                "--concerns-posts", "0",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0, (
            "emit-wave-drift accepted non-integer message-length-main"
        )
        assert "integer" in (result.stdout + result.stderr).lower(), (
            "error message should mention the integer requirement"
        )


# ---------------------------------------------------------------------------
# AC-2: Report subcommand aggregates correctly
# ---------------------------------------------------------------------------


class TestAC2_ReportSubcommand:
    """The report subcommand reads a fleet logfile (or test-harness file)
    and aggregates the three drift signals into a per-wave trend table."""

    def test_report_on_self_test_output(self, tmp_path) -> None:
        # Produce a synthetic fleet logfile via self-test.
        log_file = tmp_path / "harness.jsonl"
        with log_file.open("w") as f:
            result = subprocess.run(
                [str(SCRIPT_PATH), "self-test"],
                stdout=f,
                stderr=subprocess.PIPE,
                timeout=10,
                check=True,
            )

        # Report against it.
        result = subprocess.run(
            [str(SCRIPT_PATH), "report", str(log_file)],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        out = result.stdout
        # Header row + at least one data row.
        lines = [ln for ln in out.splitlines() if ln]
        assert len(lines) >= 2, f"report output too short: {out!r}"
        header = lines[0].split("\t")
        assert header == [
            "plan", "wave", "message_length_main",
            "stop_hook_blocks", "concerns_posts"
        ], f"unexpected header: {header}"


# ---------------------------------------------------------------------------
# AC-3: SKILL.md documents the mitigation mechanism
# ---------------------------------------------------------------------------


class TestAC3_SkillDocumentation:
    """The SKILL body must document the chosen mitigation mechanism, name
    the three drift-signal events, reference WAVE_AXIOMS.md (and Axiom 9
    specifically), and document the rejected alternatives."""

    def test_section_heading_present(self, skill_text: str) -> None:
        assert re.search(
            r"^## Periodic Re-Grounding \(drift mitigation\)\s*$",
            skill_text,
            re.MULTILINE,
        ), "SKILL.md must contain '## Periodic Re-Grounding (drift mitigation)' section"

    def test_section_names_three_events(self, skill_text: str) -> None:
        for event in DRIFT_EVENTS:
            assert event in skill_text, (
                f"SKILL.md missing reference to drift event '{event}'"
            )

    def test_section_references_wave_axioms(self, skill_text: str) -> None:
        # WAVE_AXIOMS.md must be named in the section. Per cc-workflow#605
        # it is the canonical source — we cite it, we don't restate it.
        section = _section(skill_text, "Periodic Re-Grounding (drift mitigation)")
        assert "WAVE_AXIOMS.md" in section, (
            "Re-grounding section must cite WAVE_AXIOMS.md as canonical source"
        )

    def test_section_cites_axiom_9(self, skill_text: str) -> None:
        section = _section(skill_text, "Periodic Re-Grounding (drift mitigation)")
        assert "Axiom 9" in section, (
            "Re-grounding section must cite Axiom 9 specifically — "
            "the user-attention-cost / autonomy contract is the load-bearing "
            "axiom this drift work serves"
        )

    def test_section_documents_rejected_alternatives(
        self, skill_text: str
    ) -> None:
        """Per the Notes for the Flight, the rejected alternatives must be
        documented so future readers (and follow-up work) know the design
        tradeoffs were considered."""
        section = _section(skill_text, "Periodic Re-Grounding (drift mitigation)")
        assert "Rejected alternatives" in section or \
               "rejected alternatives" in section, (
            "Re-grounding section must include a 'Rejected alternatives' subsection"
        )
        # Both heavyweight options must be named so the escalation path
        # is explicit.
        for option in ("/engage", "/compact"):
            assert option in section, (
                f"Rejected alternatives must mention {option}"
            )

    def test_script_path_referenced_in_skill(self, skill_text: str) -> None:
        assert "scripts/wavemachine/drift-instrumentation.sh" in skill_text, (
            "SKILL.md must reference scripts/wavemachine/drift-instrumentation.sh "
            "so the wiring is explicit"
        )

    def test_handoff_block_mentions_drift_emit(self, skill_text: str) -> None:
        """The Wave-to-Wave Handoff section must list the drift-instrumentation
        emit as one of the calls in the canonical single tool-use boundary.
        Without this, drift events fire at unspecified times and the
        regression test for the no-narrator-gap contract would still pass
        even if the wiring were silently dropped."""
        handoff = _section(skill_text, "Wave-to-Wave Handoff")
        assert "drift-instrumentation" in handoff, (
            "Wave-to-Wave Handoff section must reference drift-instrumentation "
            "in the canonical tool-use block enumeration"
        )

    def test_non_negotiable_lists_regrounding(self, skill_text: str) -> None:
        """The Non-Negotiables section must include the re-grounding
        contract — without it, the mechanism is documentation, not policy."""
        non_neg = _section(skill_text, "Non-Negotiables")
        assert (
            "re-grounding" in non_neg.lower()
            or "Re-grounding" in non_neg
            or "re-ground" in non_neg.lower()
        ), (
            "Non-Negotiables must include the re-grounding-fires-every-handoff rule"
        )


# ---------------------------------------------------------------------------
# Section helper (mirrors test_wavemachine_skill.py for consistency)
# ---------------------------------------------------------------------------


def _section(text: str, header_substr: str) -> str:
    """Return the slice of ``text`` from the header containing
    ``header_substr`` to the next sibling/parent header."""
    lines = text.splitlines(keepends=True)
    start = None
    for i, line in enumerate(lines):
        if header_substr in line and (
            line.startswith("## ") or line.startswith("### ")
        ):
            start = i
            break
    if start is None:
        return ""
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("## "):
            end = j
            break
    return "".join(lines[start:end])
