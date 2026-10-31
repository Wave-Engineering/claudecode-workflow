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
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.sandbox_env import sandbox_env


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
    # HOME alone is not a sandbox: see tests/sandbox_env.py (the 2026-10-29 uv wipe).
    return sandbox_env(home)


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
    # install sources the shared merge (#1360); the duplicate guard beside it is
    # opt-in, via _sandbox_with_guard.
    (sandbox_repo / "scripts" / "lib").mkdir(parents=True, exist_ok=True)
    shutil.copy(_REPO_DIR / "scripts" / "lib" / "settings-merge.sh", sandbox_repo / "scripts" / "lib")
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


# ---------------------------------------------------------------------------
# #1225: install is idempotent — no run may register a kit hook twice
# ---------------------------------------------------------------------------

_GUARD = _REPO_DIR / "scripts" / "lib" / "assert-no-duplicate-hooks.sh"

# Path-rooted kit hooks, so the duplicate guard can judge them (bare commands
# are "nothing judgeable" to it). Two events, two kit prefixes.
_KIT_TEMPLATE = {
    "hooks": {
        "Stop": [
            {"matcher": "*", "hooks": [{"type": "command", "command": "~/.claude/scripts/hooks/workflow/a.sh"}]},
            {"matcher": "*", "hooks": [{"type": "command", "command": "~/.local/bin/b.sh"}]},
        ],
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "~/.claude/scripts/hooks/workflow/c.sh"}]},
        ],
    }
}


def _sandbox_with_guard(home: Path, template: dict) -> Path:
    install = _override_template(home, template)
    shutil.copy(_GUARD, install.parent / "scripts" / "lib" / _GUARD.name)
    return install


def _guard(settings: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_GUARD), str(settings)], capture_output=True, text=True, timeout=60
    )


def _registrations(settings: Path) -> list[str]:
    data = _read_json(settings)
    return sorted(
        h["command"] for groups in data["hooks"].values() for g in groups for h in g["hooks"]
    )


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_local_reinstall_registers_nothing_twice(sandbox_home: Path) -> None:
    """The defect: a second ``install --local`` compared the template's ``~/``
    paths against the local file's already-relocated absolute ones, matched
    nothing, and appended the whole kit again — every kit hook doubled per run.

    The second run must add NOTHING. Asserting only that the guard passes would
    be too weak: ``--fix`` would collapse a still-broken merge's output and hide
    it. So the run-2 output must not report a collapse, and the registrations
    must be byte-identical to run 1's."""
    project = sandbox_home.parent / "project"
    project.mkdir(exist_ok=True)
    proj_settings = project / ".claude" / "settings.json"
    install = _sandbox_with_guard(sandbox_home, _KIT_TEMPLATE)

    rc, out, err = _run_sandbox_install(install, ["--config", "--local"], sandbox_home, cwd=project)
    assert _install_ok(rc, out, err), f"run 1 failed: {out}\n{err}"
    first = _registrations(proj_settings)
    assert len(first) == 3, f"fresh install should register the 3 kit hooks once: {first}"

    rc, out, err = _run_sandbox_install(install, ["--config", "--local"], sandbox_home, cwd=project)
    assert _install_ok(rc, out, err), f"run 2 failed: {out}\n{err}"
    assert "collapsed" not in out, (
        f"run 2 needed --fix to collapse duplicates — the merge itself still doubles:\n{out}"
    )
    assert _registrations(proj_settings) == first, "a re-run changed the hook registrations"
    assert _guard(proj_settings).returncode == 0


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_local_install_collapses_a_predoubled_file(sandbox_home: Path) -> None:
    """A project file already doubled by an older install (this repo carried 16
    duplicates) collapses to one registration each on the next install."""
    project = sandbox_home.parent / "project"
    proj = str(project)
    doubled = {
        "hooks": {
            "Stop": [
                {"matcher": "*", "hooks": [{"type": "command", "command": f"{proj}/.claude/scripts/hooks/workflow/a.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": f"{proj}/.claude/scripts/hooks/workflow/a.sh"}]},
            ],
        }
    }
    _write_json(project / ".claude" / "settings.json", doubled)
    assert _guard(project / ".claude" / "settings.json").returncode == 1, "fixture must start doubled"

    install = _sandbox_with_guard(sandbox_home, _KIT_TEMPLATE)
    rc, out, err = _run_sandbox_install(install, ["--config", "--local"], sandbox_home, cwd=project)
    assert _install_ok(rc, out, err), f"install failed: {out}\n{err}"
    assert "collapsed" in out, f"install did not report the collapse:\n{out}"
    regs = _registrations(project / ".claude" / "settings.json")
    assert regs.count(f"{proj}/.claude/scripts/hooks/workflow/a.sh") == 1, regs
    assert _guard(project / ".claude" / "settings.json").returncode == 0


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_local_dependency_check_looks_in_the_project_not_home(sandbox_home: Path) -> None:
    """``check-deps.sh`` expanded the template's ``~/`` hook paths against $HOME
    even under --local, so a hook present in the PROJECT install but not (yet)
    in the global one read as a missing dependency and ``install --local`` exited
    non-zero. Found live on #1225: the two new hooks, freshly installed locally,
    were reported NOT FOUND."""
    project = sandbox_home.parent / "project"
    hook = project / ".claude" / "scripts" / "hooks" / "workflow" / "a.sh"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/bin/sh\nexit 0\n")
    install = _sandbox_with_guard(sandbox_home, {
        "hooks": {"Stop": [{"matcher": "*", "hooks": [
            {"type": "command", "command": "~/.claude/scripts/hooks/workflow/a.sh"}]}]}
    })
    # The real checker, not the sandbox's always-pass stub.
    shutil.copy(_REPO_DIR / "scripts" / "ci" / "check-deps.sh",
                install.parent / "scripts" / "ci" / "check-deps.sh")
    rc, out, err = _run_sandbox_install(install, ["--config", "--local"], sandbox_home, cwd=project)
    combined = out + err
    assert f"hook: {hook}" in combined, f"hook not checked at its project path:\n{combined}"
    assert "NOT FOUND" not in combined, f"a locally-installed hook read as missing:\n{combined}"


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_global_install_also_runs_the_guard(sandbox_home: Path) -> None:
    """The guard runs on EVERY settings file install writes, not only --local:
    a doubled global file collapses too."""
    home = str(sandbox_home)
    doubled = {
        "hooks": {
            "Stop": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.claude/scripts/hooks/workflow/a.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": f"{home}/.claude/scripts/hooks/workflow/a.sh"}]},
            ],
        }
    }
    settings = sandbox_home / ".claude" / "settings.json"
    _write_json(settings, doubled)
    install = _sandbox_with_guard(sandbox_home, _KIT_TEMPLATE)
    rc, out, err = _run_sandbox_install(install, ["--config"], sandbox_home)
    assert _install_ok(rc, out, err), f"install failed: {out}\n{err}"
    assert "collapsed" in out, f"global install did not run the guard:\n{out}"
    assert _guard(settings).returncode == 0


# ---------------------------------------------------------------------------
# #1109: the inline wavemachine stall guard is replaced, not doubled
# ---------------------------------------------------------------------------

# The stall guard as it shipped inline before #1109 (the block reason is cut
# short; everything the installer matches on is verbatim).
_LEGACY_INLINE_GUARD = (
    'state="${CLAUDE_PROJECT_DIR:-.}/.claude/status/state.json"; [ -f "$state" ] || exit 0; '
    "active=$(jq -r '.wavemachine_active // false' \"$state\" 2>/dev/null); "
    '[ "$active" = "true" ] || exit 0; '
    "action=$(jq -r '.current_action.action // \"\"' \"$state\" 2>/dev/null); "
    'case "$action" in awaiting-verdict|hold|promoting) exit 0 ;; esac; '
    "printf '{\"decision\":\"block\",\"reason\":\"/wavemachine is active.\"}'"
)


def _stop_commands(settings: Path) -> list[str]:
    return [h["command"] for g in _read_json(settings)["hooks"]["Stop"] for h in g["hooks"]]


@_SKIP_NO_BASH
@_SKIP_NO_JQ
def test_inline_stall_guard_replaced_by_script(sandbox_home: Path) -> None:
    """An upgraded host that holds the old inline guard ends with exactly one
    guard, the script, and keeps its other Stop hooks; a re-run changes nothing."""
    template = json.loads(_TEMPLATE_PATH.read_text())
    local = {
        "hooks": {
            "Stop": [
                {"matcher": "*", "hooks": [{"type": "command", "command": _LEGACY_INLINE_GUARD}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "my-custom-stop-hook.sh"}]},
            ]
        }
    }
    settings = sandbox_home / ".claude" / "settings.json"
    _write_json(settings, local)
    install = _override_template(sandbox_home, template)

    rc, out, err = _run_sandbox_install(install, ["--config"], sandbox_home)
    assert _install_ok(rc, out, err), f"install failed: {out}\n{err}"
    assert "removed 1 inline wavemachine stall guard" in out, out

    commands = _stop_commands(settings)
    assert not [c for c in commands if "wavemachine_active" in c], "inline guard survived the merge"
    assert sum("wavemachine-stall-guard.sh" in c for c in commands) == 1
    assert "my-custom-stop-hook.sh" in commands
    assert all(g["hooks"] for g in _read_json(settings)["hooks"]["Stop"]), "empty matcher group left behind"

    rc, out, err = _run_sandbox_install(install, ["--config"], sandbox_home)
    assert _install_ok(rc, out, err), f"re-install failed: {out}\n{err}"
    assert "inline wavemachine stall guard" not in out
    assert _stop_commands(settings) == commands
