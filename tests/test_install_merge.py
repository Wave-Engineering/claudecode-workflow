"""Settings merge tests for install.sh merge_settings() function.

Tests the smart merge behavior that adds missing hooks, plugins, and
config from settings.template.json into an existing settings.json
without clobbering user customizations.

Acceptance criteria from issue #112:
- merge_settings() adds missing hooks, plugins, scalars
- Existing hooks, plugins, permissions, scalars are preserved
- Permissions arrays are unioned (no duplicates)
- _comment keys are not merged from template
- .bak backup is created before merge
- --dry-run reports what would change without modifying
- --check mode reports missing hooks and plugins as drift
- Merge is idempotent
- Fresh installs strip _comment keys
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_DIR = Path(__file__).resolve().parent.parent
_INSTALL_SCRIPT = str(_REPO_DIR / "install.sh")
_TEMPLATE_PATH = _REPO_DIR / "config" / "settings.template.json"

# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_HAS_BASH = shutil.which("bash") is not None
_HAS_JQ = shutil.which("jq") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_JQ = pytest.mark.skipif(not _HAS_JQ, reason="jq not available")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox_home(tmp_path: Path) -> Path:
    """Create a sandboxed HOME with .claude/ directory."""
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


def _make_env(home: Path) -> dict[str, str]:
    """Build a subprocess environment with HOME overridden."""
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env


def _run_install(
    args: list[str],
    home: Path,
) -> tuple[int, str, str]:
    """Run install.sh with HOME overridden."""
    result = subprocess.run(
        ["bash", _INSTALL_SCRIPT] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _read_json(path: Path) -> dict:
    """Read and parse a JSON file."""
    return json.loads(path.read_text())


def _write_json(path: Path, data: dict) -> None:
    """Write a dict as JSON to a file."""
    path.write_text(json.dumps(data, indent=2))


def _read_template() -> dict:
    """Read the actual settings.template.json from the repo."""
    return _read_json(_TEMPLATE_PATH)


def _minimal_local_settings() -> dict:
    """A minimal settings.json with only a subset of template config."""
    return {
        "permissions": {
            "allow": [
                "Read",
                "Bash(*)",
                "Ssh(*)",
            ]
        },
        "model": "opus",
        "hooks": {
            "PostToolUse": [
                {
                    "matcher": "*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "~/.claude/my-custom-hook.sh",
                        }
                    ],
                }
            ],
        },
        "enabledPlugins": {
            "context7@claude-plugins-official": True,
            "autofix-bot": True,
        },
        "statusLine": {
            "type": "command",
            "command": "bash ~/.claude/statusline-command.sh",
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestFreshInstallCopiesTemplate:
    """No existing settings.json -> template is copied as-is (minus _comment)."""

    def test_fresh_install_copies_template(self, sandbox_home: Path) -> None:
        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install --config failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        settings_path = sandbox_home / ".claude" / "settings.json"
        assert settings_path.exists(), "settings.json not created on fresh install"

        settings = _read_json(settings_path)
        template = _read_template()

        # Must have the same keys except _comment
        assert "_comment" not in settings, "_comment should be stripped on fresh install"
        assert "_comment" not in settings.get("hooks", {}), (
            "hooks._comment should be stripped on fresh install"
        )

        # Core keys should be present
        assert "permissions" in settings
        assert "hooks" in settings
        assert "enabledPlugins" in settings
        assert "model" in settings


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeAddsMissingHook:
    """Existing settings.json without Stop hook -> Stop hook added."""

    def test_merge_adds_missing_hook(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        # Ensure Stop hook is absent
        assert "Stop" not in local.get("hooks", {})
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed (rc={rc}):\nstdout: {out}\nstderr: {err}"

        merged = _read_json(settings_path)
        assert "Stop" in merged["hooks"], "Stop hook should have been added"
        assert "hooks.Stop" in out, "Output should report Stop hook was added"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergePreservesExistingHooks:
    """Existing hooks are not modified or removed."""

    def test_merge_preserves_existing_hooks(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        custom_hook_cmd = "~/.claude/my-custom-hook.sh"
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        # PostToolUse should still use custom command, not template's
        post_tool = merged["hooks"]["PostToolUse"]
        assert post_tool[0]["hooks"][0]["command"] == custom_hook_cmd, (
            "Existing PostToolUse hook command was overwritten"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeAddsMissingPlugin:
    """Template plugin not in local -> added."""

    def test_merge_adds_missing_plugin(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        template = _read_template()

        # All template plugins should be present
        for plugin_key in template["enabledPlugins"]:
            assert plugin_key in merged["enabledPlugins"], (
                f"Missing template plugin: {plugin_key}"
            )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergePreservesExtraPlugins:
    """User plugins not in template are kept."""

    def test_merge_preserves_extra_plugins(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        assert "autofix-bot" in merged["enabledPlugins"], (
            "User plugin 'autofix-bot' was removed during merge"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeUnionsPermissions:
    """Permissions from both files are unioned."""

    def test_merge_unions_permissions(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        template = _read_template()
        perms = merged["permissions"]["allow"]

        # Template permissions present
        for perm in template["permissions"]["allow"]:
            assert perm in perms, f"Template permission missing: {perm}"

        # User permissions preserved
        assert "Bash(*)" in perms, "User permission Bash(*) missing"
        assert "Ssh(*)" in perms, "User permission Ssh(*) missing"

        # No duplicates
        assert len(perms) == len(set(perms)), (
            f"Duplicate permissions found: {perms}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergePreservesUserPermissions:
    """User-added permissions survive merge."""

    def test_merge_preserves_user_permissions(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        local["permissions"]["allow"].append("Bash(mvn:*)")
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        assert "Bash(mvn:*)" in merged["permissions"]["allow"], (
            "User permission Bash(mvn:*) was removed"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeSkipsCommentKeys:
    """_comment keys from template not merged."""

    def test_merge_skips_comment_keys(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        assert "_comment" not in merged, "_comment should not be merged"
        assert "_comment" not in merged.get("hooks", {}), (
            "hooks._comment should not be merged"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeAddsMissingScalars:
    """Missing top-level scalar (e.g., effortLevel) added."""

    def test_merge_adds_missing_scalars(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        # Ensure effortLevel is absent
        assert "effortLevel" not in local
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        template = _read_template()
        assert "effortLevel" in merged, "effortLevel should have been added"
        assert merged["effortLevel"] == template["effortLevel"], (
            "effortLevel value doesn't match template"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergePreservesExistingScalars:
    """Existing model: opus not overwritten."""

    def test_merge_preserves_existing_scalars(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        local["model"] = "sonnet"
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        assert merged["model"] == "sonnet", (
            "Existing model value was overwritten"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeCreatesBackup:
    """.bak file created before merge."""

    def test_merge_creates_backup(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        bak_path = sandbox_home / ".claude" / "settings.json.bak"
        assert bak_path.exists(), ".bak backup was not created"

        # Backup should contain the original content
        backup = _read_json(bak_path)
        assert backup == local, "Backup content doesn't match original"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeDryRun:
    """--dry-run reports but doesn't modify."""

    def test_merge_dry_run(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)
        original_content = settings_path.read_text()

        rc, out, err = _run_install(["--config", "--dry-run"], sandbox_home)
        assert rc == 0, f"dry-run failed: {err}"

        assert "dry-run" in out.lower() or "dry run" in out.lower(), (
            f"Expected dry-run indicator in output:\n{out}"
        )

        # File should not have been modified
        assert settings_path.read_text() == original_content, (
            "settings.json was modified during dry-run"
        )

        # No .bak should exist
        bak_path = sandbox_home / ".claude" / "settings.json.bak"
        assert not bak_path.exists(), ".bak was created during dry-run"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestCheckReportsMissingHooks:
    """--check mode detects missing hook events."""

    def test_check_reports_missing_hooks(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        # Has PostToolUse but not Stop, SessionStart, SubagentStop
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--check"], sandbox_home)
        assert rc == 0, f"--check failed: {err}"

        # Should report missing Stop hook
        assert "missing hook" in out.lower() or "missing hook: stop" in out.lower(), (
            f"Expected missing hook report in output:\n{out}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestCheckReportsMissingPlugins:
    """--check mode detects missing plugins."""

    def test_check_reports_missing_plugins(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        # Has only context7, not slack, code-review, etc.
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--check"], sandbox_home)
        assert rc == 0, f"--check failed: {err}"

        # Should report at least one missing plugin
        assert "missing plugin" in out.lower(), (
            f"Expected missing plugin report in output:\n{out}"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeAddsStatusLineWhenAbsent:
    """statusLine (an object) should be added when absent from local."""

    def test_merge_adds_statusline(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        del local["statusLine"]
        _write_json(settings_path, local)

        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"install failed: {err}"

        merged = _read_json(settings_path)
        template = _read_template()
        assert "statusLine" in merged, "statusLine should have been added"
        # Strip _comment if present before comparison
        tpl_status = {k: v for k, v in template.get("statusLine", {}).items() if k != "_comment"}
        assert merged["statusLine"] == tpl_status or merged["statusLine"] == template["statusLine"], (
            "statusLine value doesn't match template"
        )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
class TestMergeIdempotent:
    """Running merge twice produces same result."""

    def test_merge_idempotent(self, sandbox_home: Path) -> None:
        settings_path = sandbox_home / ".claude" / "settings.json"
        local = _minimal_local_settings()
        _write_json(settings_path, local)

        # First merge
        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"first merge failed: {err}"
        first_result = _read_json(settings_path)

        # Second merge
        rc, out, err = _run_install(["--config"], sandbox_home)
        assert rc == 0, f"second merge failed: {err}"
        second_result = _read_json(settings_path)

        assert first_result == second_result, (
            "Merge is not idempotent — results differ between runs"
        )
