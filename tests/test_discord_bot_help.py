"""Tests for discord-bot per-subcommand --help output.

Exercises the real discord-bot script via subprocess, providing a dummy
DISCORD_BOT_TOKEN to satisfy the auth gate. Only the help output paths are
tested — no network calls are made.
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


def _run_help(subcommand: str) -> subprocess.CompletedProcess[str]:
    """Run ``discord-bot <subcommand> --help`` and return the result."""
    env = {**os.environ, "DISCORD_BOT_TOKEN": "test-token-for-help"}
    return subprocess.run(
        [_DISCORD_BOT, subcommand, "--help"],
        capture_output=True,
        text=True,
        env=env,
    )


def _run_short_help(subcommand: str) -> subprocess.CompletedProcess[str]:
    """Run ``discord-bot <subcommand> -h`` and return the result."""
    env = {**os.environ, "DISCORD_BOT_TOKEN": "test-token-for-help"}
    return subprocess.run(
        [_DISCORD_BOT, subcommand, "-h"],
        capture_output=True,
        text=True,
        env=env,
    )


# ---------------------------------------------------------------------------
# Tests: send --help
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestSendHelp:
    """AC: discord-bot send --help shows usage with args and flags."""

    def test_send_help_exits_zero(self) -> None:
        result = _run_help("send")
        assert result.returncode == 0

    def test_send_help_shows_usage_line(self) -> None:
        result = _run_help("send")
        assert "Usage: discord-bot send" in result.stdout

    def test_send_help_shows_channel_id_arg(self) -> None:
        result = _run_help("send")
        assert "<channel-id>" in result.stdout

    def test_send_help_shows_message_arg(self) -> None:
        result = _run_help("send")
        assert "<message>" in result.stdout

    def test_send_help_shows_embed_flag(self) -> None:
        result = _run_help("send")
        assert "--embed" in result.stdout

    def test_send_help_shows_attach_flag(self) -> None:
        result = _run_help("send")
        assert "--attach" in result.stdout

    def test_send_short_help_works(self) -> None:
        result = _run_short_help("send")
        assert result.returncode == 0
        assert "Usage: discord-bot send" in result.stdout


# ---------------------------------------------------------------------------
# Tests: read --help
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestReadHelp:
    """AC: discord-bot read --help shows usage, mentions default limit."""

    def test_read_help_exits_zero(self) -> None:
        result = _run_help("read")
        assert result.returncode == 0

    def test_read_help_shows_usage_line(self) -> None:
        result = _run_help("read")
        assert "Usage: discord-bot read" in result.stdout

    def test_read_help_shows_channel_id_arg(self) -> None:
        result = _run_help("read")
        assert "<channel-id>" in result.stdout

    def test_read_help_shows_limit_flag(self) -> None:
        result = _run_help("read")
        assert "--limit" in result.stdout

    def test_read_help_documents_default_limit(self) -> None:
        result = _run_help("read")
        assert "default: 20" in result.stdout

    def test_read_help_shows_after_flag(self) -> None:
        result = _run_help("read")
        assert "--after" in result.stdout

    def test_read_short_help_works(self) -> None:
        result = _run_short_help("read")
        assert result.returncode == 0
        assert "Usage: discord-bot read" in result.stdout


# ---------------------------------------------------------------------------
# Tests: create-channel --help
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestCreateChannelHelp:
    """AC: discord-bot create-channel --help mentions --category."""

    def test_create_channel_help_exits_zero(self) -> None:
        result = _run_help("create-channel")
        assert result.returncode == 0

    def test_create_channel_help_shows_usage_line(self) -> None:
        result = _run_help("create-channel")
        assert "Usage: discord-bot create-channel" in result.stdout

    def test_create_channel_help_shows_guild_id_arg(self) -> None:
        result = _run_help("create-channel")
        assert "<guild-id>" in result.stdout

    def test_create_channel_help_shows_topic_flag(self) -> None:
        result = _run_help("create-channel")
        assert "--topic" in result.stdout

    def test_create_channel_help_shows_category_flag(self) -> None:
        result = _run_help("create-channel")
        assert "--category" in result.stdout

    def test_create_channel_short_help_works(self) -> None:
        result = _run_short_help("create-channel")
        assert result.returncode == 0
        assert "Usage: discord-bot create-channel" in result.stdout


# ---------------------------------------------------------------------------
# Tests: resolve --help
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestResolveHelp:
    """AC: discord-bot resolve --help notes text-channel-only behavior."""

    def test_resolve_help_exits_zero(self) -> None:
        result = _run_help("resolve")
        assert result.returncode == 0

    def test_resolve_help_shows_usage_line(self) -> None:
        result = _run_help("resolve")
        assert "Usage: discord-bot resolve" in result.stdout

    def test_resolve_help_shows_guild_id_arg(self) -> None:
        result = _run_help("resolve")
        assert "<guild-id>" in result.stdout

    def test_resolve_help_shows_channel_name_arg(self) -> None:
        result = _run_help("resolve")
        assert "<channel-name>" in result.stdout

    def test_resolve_help_notes_text_only(self) -> None:
        result = _run_help("resolve")
        assert "text channels only" in result.stdout.lower()

    def test_resolve_help_mentions_type_zero(self) -> None:
        result = _run_help("resolve")
        assert "type 0" in result.stdout

    def test_resolve_short_help_works(self) -> None:
        result = _run_short_help("resolve")
        assert result.returncode == 0
        assert "Usage: discord-bot resolve" in result.stdout


# ---------------------------------------------------------------------------
# Tests: create-thread --help (bonus coverage)
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestCreateThreadHelp:
    """Bonus: create-thread --help shows usage with auto-archive flag."""

    def test_create_thread_help_exits_zero(self) -> None:
        result = _run_help("create-thread")
        assert result.returncode == 0

    def test_create_thread_help_shows_usage_line(self) -> None:
        result = _run_help("create-thread")
        assert "Usage: discord-bot create-thread" in result.stdout

    def test_create_thread_help_shows_auto_archive(self) -> None:
        result = _run_help("create-thread")
        assert "--auto-archive" in result.stdout


# ---------------------------------------------------------------------------
# Tests: list-channels --help (bonus coverage)
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestListChannelsHelp:
    """Bonus: list-channels --help shows usage with type filter flag."""

    def test_list_channels_help_exits_zero(self) -> None:
        result = _run_help("list-channels")
        assert result.returncode == 0

    def test_list_channels_help_shows_usage_line(self) -> None:
        result = _run_help("list-channels")
        assert "Usage: discord-bot list-channels" in result.stdout

    def test_list_channels_help_shows_type_flag(self) -> None:
        result = _run_help("list-channels")
        assert "--type" in result.stdout


# ---------------------------------------------------------------------------
# Tests: create-channel error message mentions --category (Finding 2)
# ---------------------------------------------------------------------------


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestCreateChannelErrorMessage:
    """Finding 2: create-channel error message should mention --category."""

    def test_error_without_args_mentions_category(self) -> None:
        env = {**os.environ, "DISCORD_BOT_TOKEN": "test-token-for-help"}
        result = subprocess.run(
            [_DISCORD_BOT, "create-channel"],
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode != 0
        assert "--category" in result.stderr
