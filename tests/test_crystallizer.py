"""Tests for context-crystallizer/lib/crystallizer.sh.

Exercises the real shell script via subprocess, writing synthetic transcripts
into tmp_path and parsing the resulting context-state markdown file.

Covers the #264 bug class: the `Recent User Instructions` section leaked
skill invocation bodies and tool_result content because the jq filter
accepted any text block inside user-type entries. Real user prompts are
delivered as plain strings; skill invocations and tool results are arrays.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CRYSTALLIZER = REPO_ROOT / "context-crystallizer" / "lib" / "crystallizer.sh"


def _write_transcript(path: Path, entries: list[dict]) -> None:
    """Write a list of transcript entries as JSONL."""
    with path.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _run_crystallizer(transcript: Path, tmp_path: Path) -> Path:
    """Run crystallizer.sh and return the path to the generated state file."""
    outdir = tmp_path / "out"
    outdir.mkdir()
    result = subprocess.run(
        ["bash", str(CRYSTALLIZER), str(transcript), str(outdir), str(tmp_path), "testsess"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"crystallizer failed: {result.stderr}"
    # Script prints the output file path on stdout
    output_file = Path(result.stdout.strip())
    assert output_file.exists(), f"crystallizer did not create {output_file}"
    return output_file


def _extract_section(state_file: Path, header: str, next_header: str) -> str:
    """Extract the body of a markdown section between two headers."""
    text = state_file.read_text()
    start = text.index(f"## {header}")
    end = text.index(f"## {next_header}", start)
    # Drop the header line itself
    body_start = text.index("\n", start) + 1
    return text[body_start:end].strip()


# ---------------------------------------------------------------------------
# Transcript entry builders
# ---------------------------------------------------------------------------

def _user_string(text: str) -> dict:
    """A real user prompt — content is a plain string."""
    return {"type": "user", "message": {"role": "user", "content": text}}


def _user_skill_invocation(skill_body: str) -> dict:
    """A skill invocation — content is an array with a single text block.

    This shape is emitted when the user types a slash command like /precheck;
    Claude Code loads the SKILL.md body into a "user"-type turn.
    """
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": skill_body}],
        },
    }


def _user_tool_result(tool_use_id: str, result_text: str) -> dict:
    """A tool response — content is an array with a tool_result block."""
    return {
        "type": "user",
        "message": {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_text,
                }
            ],
        },
    }


def _assistant_text(text: str) -> dict:
    """An assistant text response."""
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
        },
    }


def _assistant_mixed(text: str, with_thinking: bool = False) -> dict:
    """An assistant response mixing text with tool_use and optional thinking.

    Assistant content arrays legitimately contain multiple block types; the
    crystallizer should extract only the text portion.
    """
    blocks = []
    if with_thinking:
        blocks.append({"type": "thinking", "thinking": "internal deliberation"})
    blocks.append({"type": "text", "text": text})
    blocks.append({
        "type": "tool_use",
        "id": "tool_xyz",
        "name": "Bash",
        "input": {"command": "ls"},
    })
    return {
        "type": "assistant",
        "message": {"role": "assistant", "content": blocks},
    }


def _assistant_tool_use_only() -> dict:
    """An assistant turn that is pure tool_use with no text.

    These should be excluded from the Recent Assistant Context window —
    they don't represent an assistant "response" worth recording.
    """
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "tool_abc",
                    "name": "Read",
                    "input": {"file_path": "/etc/hostname"},
                }
            ],
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRecentUserInstructions:
    """Tests for the `Recent User Instructions` section of crystallized state."""

    def test_plain_user_prompts_captured(self, tmp_path):
        """Real user prompts (string content) appear in the output."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("first question"),
            _assistant_text("first answer"),
            _user_string("second question"),
            _assistant_text("second answer"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent User Instructions", "Recent Assistant Context"
        )

        assert "first question" in section
        assert "second question" in section

    def test_skill_invocation_body_excluded(self, tmp_path):
        """Skill bodies (text arrays) must NOT leak into user instructions.

        Regression test for #264: the original filter used
        `map(select(.type == "text") | .text)` which incorrectly captured
        skill-invocation text blocks as user messages.
        """
        skill_body = "LEAKED_SKILL_BODY_MARKER do not include this in user instructions"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("real prompt"),
            _user_skill_invocation(skill_body),
            _assistant_text("did something"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent User Instructions", "Recent Assistant Context"
        )

        assert "real prompt" in section
        assert "LEAKED_SKILL_BODY_MARKER" not in section

    def test_tool_result_content_excluded(self, tmp_path):
        """Tool results must NOT leak into user instructions."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("run a command please"),
            _assistant_text("sure"),
            _user_tool_result("tool_abc", "LEAKED_TOOL_OUTPUT_MARKER stdout line 1"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent User Instructions", "Recent Assistant Context"
        )

        assert "run a command please" in section
        assert "LEAKED_TOOL_OUTPUT_MARKER" not in section

    def test_chronological_order_most_recent_last(self, tmp_path):
        """User messages appear in transcript order, most recent last."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("alpha"),
            _user_string("bravo"),
            _user_string("charlie"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent User Instructions", "Recent Assistant Context"
        )

        alpha_pos = section.index("alpha")
        bravo_pos = section.index("bravo")
        charlie_pos = section.index("charlie")
        assert alpha_pos < bravo_pos < charlie_pos

    def test_window_limited_to_last_ten(self, tmp_path):
        """Only the last 10 user prompts are captured."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string(f"msg_{i:02d}") for i in range(15)
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent User Instructions", "Recent Assistant Context"
        )

        # Last 10 are msg_05 .. msg_14
        assert "msg_05" in section
        assert "msg_14" in section
        # First 5 are dropped
        assert "msg_00" not in section
        assert "msg_04" not in section

    def test_multiline_user_prompt_preserved(self, tmp_path):
        """A single multi-line user prompt appears intact.

        Regression test for the pre-existing line-based windowing bug that
        #264 also fixed: `tail -20 | head -10` on jq's text output truncated
        multi-line messages mid-content. Slurp + array slicing handles
        records atomically.
        """
        multiline = "line one\nline two\nline three"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("before"),
            _user_string(multiline),
            _user_string("after"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent User Instructions", "Recent Assistant Context"
        )

        assert "line one" in section
        assert "line two" in section
        assert "line three" in section
        assert "before" in section
        assert "after" in section


class TestRecentAssistantContext:
    """Tests for the `Recent Assistant Context` section of crystallized state.

    Regression tests for #268: the assistant-side extraction had the same
    line-based windowing bug as the user-side (#264). Content filter was
    correct (assistant arrays legitimately have text blocks), but
    `tail -30 | head -15` had no record-boundary semantics.
    """

    def test_plain_assistant_responses_captured(self, tmp_path):
        """Real assistant text responses appear in the output."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("hi"),
            _assistant_text("first response"),
            _user_string("thanks"),
            _assistant_text("second response"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent Assistant Context", "Recovery Instructions"
        )

        assert "first response" in section
        assert "second response" in section

    def test_mixed_blocks_extract_text_only(self, tmp_path):
        """Text is extracted from content arrays mixing text + tool_use + thinking.

        Unlike the user side (#264), assistant content arrays legitimately
        mix block types. The filter must keep the text and drop the rest.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _user_string("go"),
            _assistant_mixed("visible text portion", with_thinking=True),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent Assistant Context", "Recovery Instructions"
        )

        assert "visible text portion" in section
        # tool_use and thinking metadata must NOT appear
        assert "internal deliberation" not in section
        assert "tool_xyz" not in section
        assert '"command"' not in section

    def test_tool_use_only_turns_excluded(self, tmp_path):
        """Assistant turns with no text (pure tool_use) are excluded.

        The `select(length > 0)` clause after normalization drops these —
        they aren't meaningful "responses" worth recording as context.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_text("before-tool"),
            _assistant_tool_use_only(),
            _assistant_text("after-tool"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent Assistant Context", "Recovery Instructions"
        )

        assert "before-tool" in section
        assert "after-tool" in section
        # Verify no stray "- " bullets from empty entries
        bullets = [line for line in section.splitlines() if line.startswith("- ")]
        assert len(bullets) == 2, f"Expected 2 bullets, got {len(bullets)}: {bullets!r}"

    def test_chronological_order_most_recent_last(self, tmp_path):
        """Assistant responses appear in transcript order, most recent last."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_text("resp_alpha"),
            _assistant_text("resp_bravo"),
            _assistant_text("resp_charlie"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent Assistant Context", "Recovery Instructions"
        )

        alpha_pos = section.index("resp_alpha")
        bravo_pos = section.index("resp_bravo")
        charlie_pos = section.index("resp_charlie")
        assert alpha_pos < bravo_pos < charlie_pos

    def test_window_limited_to_last_fifteen(self, tmp_path):
        """Only the last 15 assistant responses are captured.

        Key regression test for #268: the original `tail -30 | head -15`
        returned the OLDEST 15 when the output was small, or a mid-range
        slice when the output was large. Either way, never the most recent.
        """
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_text(f"resp_{i:02d}") for i in range(20)
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent Assistant Context", "Recovery Instructions"
        )

        # Last 15 are resp_05 .. resp_19
        assert "resp_05" in section
        assert "resp_19" in section
        # First 5 are dropped
        assert "resp_00" not in section
        assert "resp_04" not in section

    def test_multiline_assistant_response_preserved(self, tmp_path):
        """A multi-line assistant response appears intact."""
        multiline = "thinking about it\nstep one\nstep two\nfinal answer"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_text("before"),
            _assistant_text(multiline),
            _assistant_text("after"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = _extract_section(
            state_file, "Recent Assistant Context", "Recovery Instructions"
        )

        assert "thinking about it" in section
        assert "step one" in section
        assert "step two" in section
        assert "final answer" in section
        assert "before" in section
        assert "after" in section
