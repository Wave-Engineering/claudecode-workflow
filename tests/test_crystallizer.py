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


def _assistant_file_tool(tool_name: str, file_path: str) -> dict:
    """An assistant turn containing a single Write/Edit/MultiEdit tool_use.

    Used by the Files Modified scoping tests (#265) to simulate file
    modifications at arbitrary paths, both inside and outside $PROJECT_DIR.
    """
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"tool_{tool_name.lower()}",
                    "name": tool_name,
                    "input": {"file_path": file_path},
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


class TestFilesModifiedScoping:
    """Tests for the `Files Modified This Session` section of crystallized state.

    Regression tests for #265: a single Claude Code transcript can touch
    files across multiple project roots, because the agent reads from
    sibling repos or the user switches projects within a conversation.
    The crystallizer must filter Write/Edit/MultiEdit paths to those under
    $PROJECT_DIR so that crystallized state for project A doesn't leak
    content from project B.
    """

    def _extract_files_section(self, state_file: Path) -> str:
        return _extract_section(
            state_file, "Files Modified This Session", "Recent Tool Operations"
        )

    def test_files_under_project_dir_included(self, tmp_path):
        """Paths under $PROJECT_DIR appear in the Files Modified section."""
        project_file = str(tmp_path / "src" / "module.py")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", project_file),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert project_file in section

    def test_foreign_project_files_excluded(self, tmp_path):
        """Paths outside $PROJECT_DIR are filtered out."""
        foreign_a = "/home/other/project-alpha/src/main.rs"
        foreign_b = "/home/other/project-beta/lib.ts"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", foreign_a),
            _assistant_file_tool("Edit", foreign_b),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert foreign_a not in section
        assert foreign_b not in section
        # Section should render the empty placeholder
        assert "No files modified" in section

    def test_mixed_local_and_foreign_only_local_kept(self, tmp_path):
        """A transcript mixing local + foreign edits keeps only the local ones."""
        local_file = str(tmp_path / "docs" / "README.md")
        foreign_file = "/home/other/repo/CHANGELOG.md"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Edit", local_file),
            _assistant_file_tool("Write", foreign_file),
            _assistant_file_tool("MultiEdit", str(tmp_path / "src" / "app.py")),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert local_file in section
        assert str(tmp_path / "src" / "app.py") in section
        assert foreign_file not in section
        assert "/home/other/repo" not in section

    def test_write_edit_multiedit_all_filtered(self, tmp_path):
        """The filter applies uniformly to all three file-writing tool names."""
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", "/foreign/write.py"),
            _assistant_file_tool("Edit", "/foreign/edit.py"),
            _assistant_file_tool("MultiEdit", "/foreign/multiedit.py"),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert "/foreign/write.py" not in section
        assert "/foreign/edit.py" not in section
        assert "/foreign/multiedit.py" not in section

    def test_sibling_directory_not_matched_by_prefix(self, tmp_path):
        """A sibling directory sharing a name prefix with $PROJECT_DIR is excluded.

        Guards the `$proj + "/"` anchor — without the trailing slash,
        `startswith("/a/proj")` would match `/a/proj-sibling/file.py`.
        """
        # Create a sibling directory at the same parent as tmp_path
        sibling = tmp_path.parent / (tmp_path.name + "-sibling")
        sibling_file = str(sibling / "leak.py")
        local_file = str(tmp_path / "keep.py")

        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", local_file),
            _assistant_file_tool("Write", sibling_file),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert local_file in section
        assert sibling_file not in section

    def test_camelcase_filepath_fallback_filtered(self, tmp_path):
        """The `filePath` camelCase fallback branch is also scoped.

        Current Claude Code tools all use snake_case `file_path`, but the
        crystallizer's jq filter has a defensive `// .input.filePath`
        fallback for legacy/alternate input shapes. This test exercises
        that fallback branch to ensure the scoping filter applies there
        too — if the fallback is ever actually triggered by a real tool,
        cross-project bleed must not reappear on that code path.
        """
        local_path = str(tmp_path / "local.py")
        foreign_path = "/home/other/foreign.py"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "tool_legacy_local",
                        "name": "Write",
                        "input": {"filePath": local_path},
                    }],
                },
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{
                        "type": "tool_use",
                        "id": "tool_legacy_foreign",
                        "name": "Write",
                        "input": {"filePath": foreign_path},
                    }],
                },
            },
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert local_path in section
        assert foreign_path not in section

    def test_project_dir_with_trailing_slash(self, tmp_path):
        """A PROJECT_DIR argument with a trailing slash still filters correctly.

        Guards the `${PROJECT_DIR%/}` normalization — without it, the anchor
        would become `/path//` and never match anything.
        """
        project_file = str(tmp_path / "work.py")
        foreign_file = "/home/other/work.py"

        outdir = tmp_path / "out"
        outdir.mkdir()
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", project_file),
            _assistant_file_tool("Write", foreign_file),
        ])

        # Pass PROJECT_DIR with a trailing slash
        result = subprocess.run(
            [
                "bash", str(CRYSTALLIZER),
                str(transcript), str(outdir),
                str(tmp_path) + "/",  # trailing slash
                "testsess",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, f"crystallizer failed: {result.stderr}"
        state_file = Path(result.stdout.strip())
        section = _extract_section(
            state_file, "Files Modified This Session", "Recent Tool Operations"
        )

        assert project_file in section
        assert foreign_file not in section


class TestFilesModifiedWindowing:
    """Tests for the windowing and dedup behavior of Files Modified (#272).

    #264 and #268 fixed `USER_MESSAGES` and `ASSISTANT_MESSAGES` by switching
    from line-based `tail -N | head -M` to jq slurp-mode `.[-N:]` slicing on
    whole JSON records. `FILES_MODIFIED` was left on a `sort -u | tail -20`
    pattern which:

      1. Destroyed chronological order (dedup is lexicographic, not insertion).
      2. Kept the 20 *lexicographically-last* unique paths instead of the
         20 *most-recently-modified* paths.

    These tests lock in the correct behavior:
      - Output is the 20 most-recently-modified project-scoped files.
      - Output is in chronological order (oldest → newest).
      - Duplicate edits collapse to the path's latest position.
    """

    def _extract_files_section(self, state_file: Path) -> str:
        return _extract_section(
            state_file, "Files Modified This Session", "Recent Tool Operations"
        )

    def _files_in_section(self, section: str, project_root: Path) -> list[str]:
        """Parse the fenced Files Modified block into an ordered list of paths."""
        lines = section.splitlines()
        # Lines are either bare paths, fence markers, or the header.
        # Keep only lines that look like project paths.
        root = str(project_root)
        return [ln.strip() for ln in lines if ln.strip().startswith(root)]

    def test_most_recent_twenty_survive(self, tmp_path):
        """25 distinct files edited in chronological order → last 20 kept, first 5 dropped."""
        # Use naming that keeps lex and chronological order in sync for this
        # specific test (files are f_01..f_25, chronological == lex ascending)
        # so the behavior we're asserting is about the *count* and *which end*
        # of the window, not about lex-vs-chrono divergence.
        paths = [str(tmp_path / "src" / f"f_{i:02d}.py") for i in range(1, 26)]
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", p) for p in paths
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)
        files = self._files_in_section(section, tmp_path)

        assert len(files) == 20
        # The 5 oldest (f_01..f_05) should be dropped.
        for i in range(1, 6):
            assert str(tmp_path / "src" / f"f_{i:02d}.py") not in files
        # The 20 newest (f_06..f_25) should be present in chronological order.
        expected = [str(tmp_path / "src" / f"f_{i:02d}.py") for i in range(6, 26)]
        assert files == expected

    def test_lexicographic_ordering_not_used(self, tmp_path):
        """A z-prefixed file edited early must not appear after an a-prefixed file edited late.

        This is the regression for the `sort -u | tail -20` bug: lex-sort
        would put all `a_*` paths before `z_*` paths regardless of edit time,
        but the correct behavior is chronological.
        """
        early_z = str(tmp_path / "src" / "zzz_early.py")
        late_a = str(tmp_path / "src" / "aaa_late.py")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", early_z),
            _assistant_file_tool("Edit", late_a),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)
        files = self._files_in_section(section, tmp_path)

        assert files == [early_z, late_a], (
            f"Expected chronological order [zzz_early, aaa_late] but got {files}. "
            "If aaa_late appears first, dedup is still lexicographic."
        )

    def test_duplicate_path_collapses_to_latest_position(self, tmp_path):
        """A file edited multiple times appears exactly once, at its latest chronological position.

        Edit order: A, B, A, C, B → expect [A, C, B]
          - A's last edit is at index 2 (before C at 3 and B at 4)
          - C's last edit is at index 3
          - B's last edit is at index 4
        Sorted by last-index ascending: A, C, B.
        """
        a = str(tmp_path / "A.py")
        b = str(tmp_path / "B.py")
        c = str(tmp_path / "C.py")
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", a),
            _assistant_file_tool("Write", b),
            _assistant_file_tool("Edit", a),
            _assistant_file_tool("Write", c),
            _assistant_file_tool("Edit", b),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)
        files = self._files_in_section(section, tmp_path)

        assert files == [a, c, b], (
            f"Expected last-wins order [A, C, B] but got {files}. "
            "Dedup must keep each path at the position of its LAST edit."
        )

    def test_duplicate_path_counts_as_one_against_window(self, tmp_path):
        """When >20 distinct files exist, duplicate edits of an existing file do not evict others.

        Scenario: 20 distinct files edited, then f_01 is edited AGAIN.
        The output should still contain all 20 distinct files; the re-edit
        of f_01 just moves it to the tail. No file is dropped because dedup
        runs BEFORE the `.[-20:]` slice.
        """
        base = [str(tmp_path / "src" / f"f_{i:02d}.py") for i in range(1, 21)]
        re_edit = base[0]  # f_01.py edited again at the end
        transcript = tmp_path / "t.jsonl"
        events = [_assistant_file_tool("Write", p) for p in base]
        events.append(_assistant_file_tool("Edit", re_edit))
        _write_transcript(transcript, events)

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)
        files = self._files_in_section(section, tmp_path)

        # All 20 distinct files must be present — none evicted by the re-edit.
        assert len(files) == 20
        assert set(files) == set(base)
        # f_01 must now be at the END (its latest position), not at index 0.
        assert files[-1] == re_edit
        assert files[0] != re_edit

    def test_scoping_still_applied_after_windowing_refactor(self, tmp_path):
        """Smoke: the #265 scoping filter still removes foreign paths after the #272 rewrite."""
        local_file = str(tmp_path / "keep.py")
        foreign_file = "/home/other/project/leak.py"
        transcript = tmp_path / "t.jsonl"
        _write_transcript(transcript, [
            _assistant_file_tool("Write", local_file),
            _assistant_file_tool("Edit", foreign_file),
            _assistant_file_tool("MultiEdit", foreign_file),
        ])

        state_file = _run_crystallizer(transcript, tmp_path)
        section = self._extract_files_section(state_file)

        assert local_file in section
        assert foreign_file not in section
        assert "/home/other" not in section
