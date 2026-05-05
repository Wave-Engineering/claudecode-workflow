"""Hook matcher-array union tests for ``merge_settings()`` in ``install``.

Covers issue #556: ``merge_settings()`` previously only added wholly-new
event keys from the template to a user's ``~/.claude/settings.json``. When
an event key already existed locally (e.g. ``SessionStart``), template
matcher entries inside that array were silently dropped — the upgrade
left the user with a half-wired hooks block.

This test file is intentionally self-contained — it does NOT depend on
``tests/test_install_merge.py`` (which has known pre-existing failures from
the ``install.sh`` -> ``install`` rename). It writes synthetic template +
local fixtures, invokes ``./install --config`` with ``HOME`` overridden,
and asserts the post-merge JSON shape.

Acceptance criteria from #556:

1. After ``./install`` runs against a settings.json that has
   ``SessionStart: [{matcher: "*", ...}]``, the resulting file has BOTH
   ``*`` and any new template matchers (e.g. ``compact``).
2. User customizations on existing matchers are NOT overwritten.
3. ``./install --check`` reports the actual gap when a matcher is missing
   locally.
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
_INSTALL_SCRIPT = str(_REPO_DIR / "install")
_TEMPLATE_PATH = _REPO_DIR / "config" / "settings.template.json"


# ---------------------------------------------------------------------------
# Skip conditions
# ---------------------------------------------------------------------------

_HAS_BASH = shutil.which("bash") is not None
_HAS_JQ = shutil.which("jq") is not None

_SKIP_NO_BASH = pytest.mark.skipif(not _HAS_BASH, reason="bash not available")
_SKIP_NO_JQ = pytest.mark.skipif(not _HAS_JQ, reason="jq not available")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    return env


def _run_install(args: list[str], home: Path) -> tuple[int, str, str]:
    """Run ``./install <args>`` with HOME overridden."""
    result = subprocess.run(
        ["bash", _INSTALL_SCRIPT] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def _override_template(home: Path, template_data: dict) -> Path:
    """Copy install + a *modified* template into a sandbox repo and return
    the path to the sandbox install script.

    The sandbox repo contains a minimal layout: just enough for
    ``./install --config`` to run merge_settings(). We rewrite the template
    in place inside the sandbox so the test can assert behavior on a
    controlled template without mutating the real repo.
    """
    sandbox_repo = home.parent / "sandbox_repo"
    sandbox_repo.mkdir(exist_ok=True)
    # Copy install script
    shutil.copy(_INSTALL_SCRIPT, sandbox_repo / "install")
    (sandbox_repo / "install").chmod(0o755)
    # Copy required structure: config/, scripts/ci/check-deps.sh stub
    (sandbox_repo / "config").mkdir(exist_ok=True)
    _write_json(sandbox_repo / "config" / "settings.template.json", template_data)
    (sandbox_repo / "scripts" / "ci").mkdir(parents=True, exist_ok=True)
    (sandbox_repo / "scripts" / "ci" / "check-deps.sh").write_text(
        "#!/usr/bin/env bash\ncheck_deps() { return 0; }\n"
    )
    (sandbox_repo / "scripts" / "ci" / "check-deps.sh").chmod(0o755)
    return sandbox_repo / "install"


def _run_sandbox_install(
    sandbox_install: Path,
    args: list[str],
    home: Path,
) -> tuple[int, str, str]:
    result = subprocess.run(
        ["bash", str(sandbox_install)] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def sandbox_home(tmp_path: Path) -> Path:
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    (home / ".claude" / "skills").mkdir(parents=True)
    return home


# ---------------------------------------------------------------------------
# AC1: template adds a new matcher to an existing event key
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_merge_adds_missing_matcher_to_existing_event(sandbox_home: Path) -> None:
    """After merge, a SessionStart array that started with one matcher has
    both the original matcher AND the template's new matcher."""
    template = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "default-session-start.sh"}
                    ],
                },
                {
                    "matcher": "compact",
                    "hooks": [
                        {"type": "command", "command": "session-start-compact.sh"}
                    ],
                },
            ]
        }
    }
    local = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "user-session-start.sh"}
                    ],
                }
            ]
        }
    }
    settings_path = sandbox_home / ".claude" / "settings.json"
    _write_json(settings_path, local)

    sandbox_install = _override_template(sandbox_home, template)
    rc, _stdout, _stderr = _run_sandbox_install(sandbox_install, ["--config"], sandbox_home)
    assert rc == 0

    merged = _read_json(settings_path)
    matchers = [entry["matcher"] for entry in merged["hooks"]["SessionStart"]]
    assert "*" in matchers, "original local '*' matcher must survive merge"
    assert "compact" in matchers, "template's new 'compact' matcher must be appended"


# ---------------------------------------------------------------------------
# AC2: user customizations on existing matchers are not overwritten
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_merge_preserves_user_customization_on_shared_matcher(
    sandbox_home: Path,
) -> None:
    """When both local and template have a ``*`` matcher under the same
    event but with different ``hooks[].command`` values, the local entry
    is preserved unchanged. The template entry is NOT layered on top."""
    template = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "default-script.sh"}
                    ],
                }
            ]
        }
    }
    local = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "user-customized.sh"}
                    ],
                }
            ]
        }
    }
    settings_path = sandbox_home / ".claude" / "settings.json"
    _write_json(settings_path, local)

    sandbox_install = _override_template(sandbox_home, template)
    rc, _stdout, _stderr = _run_sandbox_install(sandbox_install, ["--config"], sandbox_home)
    assert rc == 0

    merged = _read_json(settings_path)
    star_entries = [
        e for e in merged["hooks"]["SessionStart"] if e["matcher"] == "*"
    ]
    assert len(star_entries) == 1, "exactly one '*' entry expected (no duplication)"
    commands = [h["command"] for h in star_entries[0]["hooks"]]
    assert "user-customized.sh" in commands, "user's command must be preserved"
    assert "default-script.sh" not in commands, (
        "template command must NOT overwrite or layer on top of user's command "
        "for an already-present matcher"
    )


# ---------------------------------------------------------------------------
# AC3: ./install --check reports missing matchers as drift
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_check_reports_missing_matcher_in_existing_event(
    sandbox_home: Path,
) -> None:
    """``./install --check`` must surface a missing matcher within an
    already-present event key as actual drift (not "already present")."""
    template = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "default-session-start.sh"}
                    ],
                },
                {
                    "matcher": "compact",
                    "hooks": [
                        {"type": "command", "command": "session-start-compact.sh"}
                    ],
                },
            ]
        }
    }
    local = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "user-session-start.sh"}
                    ],
                }
            ]
        }
    }
    settings_path = sandbox_home / ".claude" / "settings.json"
    _write_json(settings_path, local)

    sandbox_install = _override_template(sandbox_home, template)
    rc, stdout, stderr = _run_sandbox_install(sandbox_install, ["--check"], sandbox_home)
    output = stdout + stderr
    # ``--check`` exits 0 by project convention (drift count is reported in
    # the summary line, not via the exit code), so we assert by output
    # content. A passing run is fine — it just must NOT be silent on the
    # gap.
    assert rc == 0, f"--check should not error out (rc={rc}, stderr={stderr})"

    # The specific matcher gap should be named in the output.
    assert "compact" in output, (
        f"--check output should name the missing matcher 'compact'. Got:\n{output}"
    )
    assert "SessionStart" in output, (
        f"--check output should name the affected event 'SessionStart'. Got:\n{output}"
    )
    # And the report should NOT claim the event is fully covered.
    # (A pre-fix run would print "settings.json hook SessionStart (present)"
    # with no drift line — ensure we now get an explicit "missing matcher"
    # drift signal.)
    assert "missing matcher" in output.lower(), (
        f"--check output should describe the gap as a missing matcher. Got:\n{output}"
    )
    # Summary line should reflect the drift count.
    assert "out of sync" in output.lower(), (
        f"--check summary should report items out of sync. Got:\n{output}"
    )


# ---------------------------------------------------------------------------
# Bonus: idempotence — second merge is a no-op (no duplicate matchers)
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_matcher_union_is_idempotent(sandbox_home: Path) -> None:
    """Running the merge twice produces the same result — no duplicate
    matcher entries are created on the second pass."""
    template = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "default-session-start.sh"}
                    ],
                },
                {
                    "matcher": "compact",
                    "hooks": [
                        {"type": "command", "command": "session-start-compact.sh"}
                    ],
                },
            ]
        }
    }
    local = {
        "hooks": {
            "SessionStart": [
                {
                    "matcher": "*",
                    "hooks": [
                        {"type": "command", "command": "user-session-start.sh"}
                    ],
                }
            ]
        }
    }
    settings_path = sandbox_home / ".claude" / "settings.json"
    _write_json(settings_path, local)

    sandbox_install = _override_template(sandbox_home, template)
    rc1, _, _ = _run_sandbox_install(sandbox_install, ["--config"], sandbox_home)
    assert rc1 == 0
    after_first = _read_json(settings_path)

    rc2, _, _ = _run_sandbox_install(sandbox_install, ["--config"], sandbox_home)
    assert rc2 == 0
    after_second = _read_json(settings_path)

    # Same number of matchers in the SessionStart array on both runs.
    assert (
        len(after_first["hooks"]["SessionStart"])
        == len(after_second["hooks"]["SessionStart"])
    ), "second merge must not duplicate matchers"
    # And the matcher set is exactly {"*", "compact"}.
    matchers = sorted(e["matcher"] for e in after_second["hooks"]["SessionStart"])
    assert matchers == ["*", "compact"]
