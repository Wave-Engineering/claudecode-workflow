"""Tests for discord-bot message auto-splitting (Wave-Engineering/claudecode-workflow#274).

Exercises the `_split_for_discord` and `_apply_chunk_footer` shell helpers by
sourcing the discord-bot script (which honors a sourcing guard and skips its
subcommand dispatch when sourced) and running bash assertions via subprocess.

No network calls — the splitter is pure string manipulation. A dummy
DISCORD_BOT_TOKEN is provided so the script's auth gate is satisfied.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent
_DISCORD_BOT = str(_REPO_DIR / "skills" / "disc" / "discord-bot")

_HAS_BASH = shutil.which("bash") is not None
_HAS_JQ = shutil.which("jq") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_JQ = pytest.mark.skipif(not _HAS_JQ, reason="jq not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_in_sourced_bot(snippet: str) -> subprocess.CompletedProcess[str]:
    """Run ``snippet`` in a bash subshell with discord-bot sourced.

    The snippet has access to ``_split_for_discord``, ``_apply_chunk_footer``,
    ``_DISCORD_MSG_LIMIT``, and ``_DISCORD_CHUNK_BUDGET``.
    """
    wrapper = f'set -euo pipefail\nsource "{_DISCORD_BOT}"\n{snippet}\n'
    env = {**os.environ, "DISCORD_BOT_TOKEN": "test-token-for-split"}
    return subprocess.run(
        ["bash", "-c", wrapper],
        capture_output=True,
        text=True,
        env=env,
    )


def _count_chunks(input_text: str) -> int:
    """Count NUL-separated chunks emitted by _split_for_discord for input_text."""
    snippet = f"""
input={_bash_quote(input_text)}
_split_for_discord "$input" | tr -cd '\\0' | wc -c
"""
    result = _run_in_sourced_bot(snippet)
    assert result.returncode == 0, f"bash failed: {result.stderr}"
    return int(result.stdout.strip())


def _max_chunk_len(input_text: str) -> int:
    """Return the length (in codepoints) of the longest chunk."""
    snippet = f"""
input={_bash_quote(input_text)}
mapfile -d '' chunks < <(_split_for_discord "$input")
max=0
for c in "${{chunks[@]}}"; do
    (( ${{#c}} > max )) && max=${{#c}}
done
echo "$max"
"""
    result = _run_in_sourced_bot(snippet)
    assert result.returncode == 0, f"bash failed: {result.stderr}"
    return int(result.stdout.strip())


def _first_chunk_len(input_text: str) -> int:
    """Return the length (in codepoints) of the first emitted chunk."""
    snippet = f"""
input={_bash_quote(input_text)}
mapfile -d '' chunks < <(_split_for_discord "$input")
echo "${{#chunks[0]}}"
"""
    result = _run_in_sourced_bot(snippet)
    assert result.returncode == 0, f"bash failed: {result.stderr}"
    return int(result.stdout.strip())


def _rejoin_equals_input(input_text: str) -> bool:
    """Check that concatenating all chunks reproduces the original input exactly."""
    # Write input to a temp file to avoid shell-quoting pitfalls on arbitrary
    # text with shell metacharacters and multi-line content.
    snippet = f"""
input=$(cat <<'DISCORD_TEST_INPUT_EOF'
{input_text}
DISCORD_TEST_INPUT_EOF
)
# The heredoc adds exactly one trailing newline; strip it so the input
# matches what the caller passed.
input="${{input%$'\\n'}}"

mapfile -d '' chunks < <(_split_for_discord "$input")
joined=""
for c in "${{chunks[@]}}"; do joined+="$c"; done
[[ "$joined" == "$input" ]] && echo "MATCH" || echo "DIFFER len_orig=${{#input}} len_joined=${{#joined}}"
"""
    result = _run_in_sourced_bot(snippet)
    assert result.returncode == 0, f"bash failed: {result.stderr}"
    return result.stdout.strip() == "MATCH"


def _bash_quote(text: str) -> str:
    """Wrap a string in single-quotes suitable for bash variable assignment."""
    return "'" + text.replace("'", "'\"'\"'") + "'"


# ---------------------------------------------------------------------------
# Tests: _split_for_discord — size boundaries
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestSplitSizeBoundaries:
    """AC: the splitter respects the 1900-char budget at boundary lengths."""

    def test_empty_string_produces_one_chunk(self) -> None:
        assert _count_chunks("") == 1

    def test_1899_chars_produces_one_chunk(self) -> None:
        assert _count_chunks("a" * 1899) == 1

    def test_1900_chars_produces_one_chunk(self) -> None:
        assert _count_chunks("a" * 1900) == 1

    def test_1901_chars_splits_into_two_chunks(self) -> None:
        assert _count_chunks("a" * 1901) == 2

    def test_all_chunks_at_or_below_budget(self) -> None:
        assert _max_chunk_len("a" * 5000) <= 1900


# ---------------------------------------------------------------------------
# Tests: _split_for_discord — fallback order (newline > space > hard cut)
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestSplitFallbacks:
    """AC: splits prefer newline, then space, then hard cut."""

    def test_hard_cut_at_exact_budget_when_no_whitespace(self) -> None:
        # 5000 'a's with no whitespace → first chunk is exactly 1900 chars
        assert _first_chunk_len("a" * 5000) == 1900

    def test_newline_split_is_lossless(self) -> None:
        # 60 lines of 79 chars + newline = 4800 chars
        lines = "\n".join("x" * 79 for _ in range(60)) + "\n"
        assert _rejoin_equals_input(lines)

    def test_space_fallback_drops_the_space(self) -> None:
        # 1950 'a's, then a space, then 100 'a's → split at the space,
        # neither chunk retains the space
        text = ("a" * 1950) + " " + ("a" * 100)
        snippet = f"""
input={_bash_quote(text)}
mapfile -d '' chunks < <(_split_for_discord "$input")
first="${{chunks[0]}}"
second="${{chunks[1]}}"
# First chunk must not end with a space
[[ "${{first: -1}}" != " " ]] || {{ echo "FIRST_ENDS_WITH_SPACE"; exit 1; }}
# Second chunk must not start with a space
[[ "${{second:0:1}}" != " " ]] || {{ echo "SECOND_STARTS_WITH_SPACE"; exit 1; }}
echo "OK"
"""
        result = _run_in_sourced_bot(snippet)
        assert result.returncode == 0, f"bash failed: {result.stderr}"
        assert result.stdout.strip() == "OK"


# ---------------------------------------------------------------------------
# Tests: _split_for_discord — unicode
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestSplitUnicode:
    """AC: unicode content is split by codepoint count, no corruption."""

    def test_emoji_content_over_budget_splits(self) -> None:
        # "🎉 " = 2 codepoints each. 1000 copies = 2000 codepoints → must split.
        text = "🎉 " * 1000
        assert _count_chunks(text) >= 2

    def test_emoji_chunks_respect_budget(self) -> None:
        text = "🎉 " * 1000
        assert _max_chunk_len(text) <= 1900


# ---------------------------------------------------------------------------
# Tests: _apply_chunk_footer
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestChunkFooter:
    """AC: _apply_chunk_footer appends '\\n(N/M)' to chunk text."""

    def test_footer_format(self) -> None:
        snippet = r"""
out=$(_apply_chunk_footer 2 5 "hello")
expected=$'hello\n(2/5)'
[[ "$out" == "$expected" ]] && echo "OK" || { echo "GOT=$out"; exit 1; }
"""
        result = _run_in_sourced_bot(snippet)
        assert result.returncode == 0, f"bash failed: {result.stderr}"
        assert result.stdout.strip() == "OK"

    def test_footer_preserves_chunk_trailing_newline(self) -> None:
        snippet = r"""
chunk=$'line1\nline2\n'
out=$(_apply_chunk_footer 1 3 "$chunk")
expected=$'line1\nline2\n\n(1/3)'
[[ "$out" == "$expected" ]] && echo "OK" || { printf 'GOT=%q\n' "$out"; exit 1; }
"""
        result = _run_in_sourced_bot(snippet)
        assert result.returncode == 0, f"bash failed: {result.stderr}"
        assert result.stdout.strip() == "OK"


# ---------------------------------------------------------------------------
# Tests: sourcing guard — script can be sourced without running dispatch
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestSourcingGuard:
    """AC: sourcing discord-bot returns cleanly without executing a subcommand."""

    def test_sourcing_does_not_invoke_usage(self) -> None:
        # If the dispatch were active, sourcing would fall through to `usage`
        # and exit 1 because there are no positional args.
        snippet = 'echo "sourced fine"'
        result = _run_in_sourced_bot(snippet)
        assert result.returncode == 0
        assert "sourced fine" in result.stdout
