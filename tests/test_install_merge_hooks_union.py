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
    cwd: Path | None = None,
) -> tuple[int, str, str]:
    result = subprocess.run(
        ["bash", str(sandbox_install)] + args,
        capture_output=True,
        text=True,
        env=_make_env(home),
        cwd=str(cwd) if cwd is not None else None,
        timeout=120,
    )
    return result.returncode, result.stdout, result.stderr


def _install_ok(rc: int, out: str, err: str) -> bool:
    """Accept a non-zero exit caused solely by the late-stage dependency
    audit (legitimately missing in a sandbox HOME). See #753."""
    if rc == 0:
        return True
    combined = (out or "") + (err or "")
    return "dependenc" in combined and "missing" in combined


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


# ---------------------------------------------------------------------------
# #734: distinct KIT hooks sharing matcher "*" must all deploy (Stop array)
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_kit_multi_hook_same_matcher_all_deploy(sandbox_home: Path) -> None:
    """The kit ships several distinct hooks under matcher '*' (e.g. the Stop
    array). When local already has one of them, the OTHER kit hooks must be
    merged in (not dropped by a matcher-keyed union), while a user's own '*'
    hook is preserved and identical kit hooks are not duplicated."""
    template = {
        "hooks": {
            "Stop": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.local/bin/precheck-asking-detector.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.local/bin/stop-action-bias-detector.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "state=\"${CLAUDE_PROJECT_DIR:-.}/.claude/status/state.json\"; exit 0"}]},
            ]
        }
    }
    local = {
        "hooks": {
            "Stop": [
                # one kit hook already present (must not be duplicated)
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.local/bin/precheck-asking-detector.sh"}]},
                # a user's own '*' hook (non-kit) — must be preserved, never clobbered
                {"matcher": "*", "hooks": [{"type": "command", "command": "my-custom-stop-hook.sh"}]},
            ]
        }
    }
    settings_path = sandbox_home / ".claude" / "settings.json"
    _write_json(settings_path, local)

    sandbox_install = _override_template(sandbox_home, template)
    rc, _stdout, _stderr = _run_sandbox_install(sandbox_install, ["--config"], sandbox_home)
    assert rc == 0

    merged = _read_json(settings_path)
    commands = [h["command"] for e in merged["hooks"]["Stop"] for h in e["hooks"]]
    # All three kit hooks present.
    assert sum(c == "~/.local/bin/precheck-asking-detector.sh" for c in commands) == 1, "precheck-asking present exactly once (no duplicate)"
    assert any("stop-action-bias-detector.sh" in c for c in commands), "the absent kit hook must be merged in (#734)"
    assert any(".claude/status/state.json" in c for c in commands), "the kit's inline wavemachine guard (kit path) must be merged in"
    # User's own hook preserved.
    assert any(c == "my-custom-stop-hook.sh" for c in commands), "user's custom '*' hook must be preserved"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_user_override_of_kit_hook_not_resurrected(sandbox_home: Path) -> None:
    """A NON-kit user hook under '*' still overrides per #556 AC2 — a bare
    template command sharing the matcher is not layered on top."""
    template = {
        "hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "default-bare.sh"}]}]}
    }
    local = {
        "hooks": {"Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "user-customized.sh"}]}]}
    }
    settings_path = sandbox_home / ".claude" / "settings.json"
    _write_json(settings_path, local)
    sandbox_install = _override_template(sandbox_home, template)
    rc, _, _ = _run_sandbox_install(sandbox_install, ["--config"], sandbox_home)
    assert rc == 0
    commands = [h["command"] for e in _read_json(settings_path)["hooks"]["Stop"] for h in e["hooks"]]
    assert "user-customized.sh" in commands
    assert "default-bare.sh" not in commands, "a non-kit template hook must not override a user hook on a shared matcher"


# ---------------------------------------------------------------------------
# --local: project-scoped settings merge + kit hook-path relocation
# ---------------------------------------------------------------------------

@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_local_settings_merge_into_project(sandbox_home: Path) -> None:
    """``--local --config`` merges into the PROJECT's settings.json (under
    <cwd>/.claude/), not the global $HOME one, and writes the .bak there."""
    template = {
        "hooks": {
            "SessionStart": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "default-session-start.sh"}]},
                {"matcher": "compact", "hooks": [{"type": "command", "command": "session-start-compact.sh"}]},
            ]
        }
    }
    local = {
        "hooks": {
            "SessionStart": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "user-session-start.sh"}]}
            ]
        }
    }
    # Pre-seed the PROJECT settings, NOT the global one.
    project = sandbox_home.parent / "project"
    project.mkdir(exist_ok=True)
    proj_settings = project / ".claude" / "settings.json"
    _write_json(proj_settings, local)

    sandbox_install = _override_template(sandbox_home, template)
    rc, out, err = _run_sandbox_install(
        sandbox_install, ["--config", "--local"], sandbox_home, cwd=project
    )
    assert _install_ok(rc, out, err), f"--local --config failed: {out}\n{err}"

    # Merge happened in the PROJECT file.
    merged = _read_json(proj_settings)
    matchers = [e["matcher"] for e in merged["hooks"]["SessionStart"]]
    assert "*" in matchers and "compact" in matchers, (
        "template matcher must merge into the project-local settings"
    )
    # .bak written next to the project settings.
    assert (project / ".claude" / "settings.json.bak").exists(), (
        "merge .bak should be created in the project, not global"
    )
    # Global settings untouched (never created).
    assert not (sandbox_home / ".claude" / "settings.json").exists(), (
        "--local merge must not create a global settings.json"
    )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_local_hook_path_resolution(sandbox_home: Path) -> None:
    """--local rewrites KIT-OWNED ~/ hook paths to ABSOLUTE project-local
    paths, while leaving foreign absolute paths and $CLAUDE_PROJECT_DIR
    inline hooks untouched. Proves the §4 path-rewriting contract."""
    template = {
        "statusLine": {
            "type": "command",
            "command": "bash ~/.claude/statusline-command.sh",
        },
        "hooks": {
            "Stop": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.claude/scripts/hooks/x.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.local/bin/y.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "/opt/foreign/z.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "state=\"${CLAUDE_PROJECT_DIR:-.}/.claude/state.json\"; exit 0"}]},
            ]
        },
    }
    project = sandbox_home.parent / "project"
    project.mkdir(exist_ok=True)

    sandbox_install = _override_template(sandbox_home, template)
    # Fresh install (no pre-existing project settings) exercises the
    # fresh-copy rewrite path. --config so only the settings work runs.
    rc, out, err = _run_sandbox_install(
        sandbox_install, ["--config", "--local"], sandbox_home, cwd=project
    )
    assert _install_ok(rc, out, err), f"--local --config failed: {out}\n{err}"

    proj_claude = project / ".claude"
    merged = _read_json(proj_claude / "settings.json")
    cmds = {
        h["command"]
        for e in merged["hooks"]["Stop"]
        for h in e["hooks"]
    }
    proj = str(project)

    # x.sh: kit Cellar hooks path → absolute <project>/.claude/scripts/hooks/x.sh
    assert f"{proj}/.claude/scripts/hooks/x.sh" in cmds, (
        f"kit Cellar hook not relocated to absolute project path; got {cmds}"
    )
    # y.sh: kit farm path → absolute <project>/.claude/bin/y.sh
    assert f"{proj}/.claude/bin/y.sh" in cmds, (
        f"kit farm hook not relocated to absolute project path; got {cmds}"
    )
    # statusLine rewritten to absolute project path.
    assert merged["statusLine"]["command"] == f"bash {proj}/.claude/statusline-command.sh", (
        f"statusLine not relocated; got {merged['statusLine']['command']!r}"
    )
    # Foreign absolute path UNCHANGED.
    assert "/opt/foreign/z.sh" in cmds, "foreign absolute hook must be left untouched"
    # $CLAUDE_PROJECT_DIR inline hook UNCHANGED.
    assert any("${CLAUDE_PROJECT_DIR:-.}/.claude/state.json" in c for c in cmds), (
        "CLAUDE_PROJECT_DIR inline hook must be left untouched"
    )
    # No surviving ~/ in any KIT-owned command (foreign /opt and the inline
    # hook never had a ~/ to begin with).
    for c in cmds:
        if c.startswith("/opt/") or "CLAUDE_PROJECT_DIR" in c:
            continue
        assert "~/" not in c, f"kit command still has unexpanded ~/: {c!r}"
    assert "~/" not in merged["statusLine"]["command"], (
        "statusLine still has unexpanded ~/"
    )
