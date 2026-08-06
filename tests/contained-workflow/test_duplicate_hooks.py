"""No hook may be registered twice in the image's settings (#1094).

The baked `settings.json` carried `wtf-post-tool-use.sh` under BOTH
`~/.local/share/…` and `/home/ubuntu/.local/share/…` — the same file, so it fired
twice on every tool use. It survived for weeks because nothing ever asked the
question; the assertion exists so the build asks it every time.

Identity is the SCRIPT PLUS ITS ARGUMENTS, resolved — matching `bootstrap.sh`'s
runtime `key()` exactly, because a build gate that drew the line elsewhere would
either reject a config the runtime accepts or pass one the runtime treats as two.

So the cases below run in both directions: the spellings that must COLLAPSE
(tilde vs absolute, and the `[ -x … ] || exit 0;` guard #1107 wraps commands in),
and the ones that must stay DISTINCT (different arguments, different matchers,
different events, and two scripts that merely share an interpreter).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
ASSERT = REPO / "scripts" / "ci" / "assert-no-duplicate-hooks.sh"
DOCKERFILE = REPO / "containers" / "oakandwave-workflow" / "Dockerfile"

HOOK = ".local/share/wtf-server/hooks/wtf-post-tool-use.sh"


def _run(tmp_path: Path, settings: object | None) -> subprocess.CompletedProcess[str]:
    p = tmp_path / "settings.json"
    if settings is not None:
        p.write_text(json.dumps(settings, indent=2))
    return subprocess.run(
        ["bash", str(ASSERT), str(p)],
        capture_output=True,
        text=True,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )


def _one_group(*commands: str, event: str = "PostToolUse", matcher: str = "") -> dict:
    return {
        "hooks": {
            event: [
                {
                    "matcher": matcher,
                    "hooks": [{"type": "command", "command": c} for c in commands],
                }
            ]
        }
    }


def test_the_exact_production_duplicate_is_caught(tmp_path: Path) -> None:
    """The real #1094 pair: the tilde form from settings.template.json and the
    absolute form wtf-server's installer added afterwards. $HOME is the tmpdir
    here, so the absolute spelling is written against it."""
    proc = _run(tmp_path, _one_group(f"~/{HOOK}", f"{tmp_path}/{HOOK}"))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "duplicate registration" in proc.stderr
    assert "RUNS twice" in proc.stderr


def test_the_guard_wrapper_does_not_hide_a_duplicate(tmp_path: Path) -> None:
    """A guarded and a bare spelling are ONE hook. Keying on the guard's leading
    `[` would call them two and report all-clear — which is the shape that would
    quietly re-admit this bug on every container the fleet actually runs."""
    guarded = f"[ -x ~/{HOOK} ] || exit 0; ~/{HOOK}"
    proc = _run(tmp_path, _one_group(guarded, f"{tmp_path}/{HOOK}"))
    assert proc.returncode == 1, proc.stdout + proc.stderr


def test_arguments_make_it_a_DIFFERENT_hook(tmp_path: Path) -> None:
    """Identity must match bootstrap.sh's runtime `key()`, which includes the
    arguments. `flightdeck-session-emit.sh idle` and `… close` are genuinely two
    hooks; calling them one would hard-fail the image build on a correct config.

    An earlier version of this asserted the opposite and would have done exactly
    that the next time a verb was added under an existing event+matcher.
    """
    proc = _run(tmp_path, _one_group(f"~/{HOOK} idle", f"~/{HOOK} close"))
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_two_scripts_sharing_an_interpreter_are_not_a_duplicate(tmp_path: Path) -> None:
    """Keying on the bare first token would call these one hook and fail the
    build on a legitimate configuration."""
    proc = _run(tmp_path, _one_group("python3 /a.py", "python3 /b.py"))
    assert proc.returncode == 2, proc.stdout + proc.stderr  # nothing judgeable


def test_an_interpreter_prefix_does_not_hide_a_duplicate(tmp_path: Path) -> None:
    """The false-PASS direction of the same mistake: `bash ~/x` vs `~/x` would
    resolve to `bash` and the path, missing a real duplicate. settings.template
    already uses the `bash ~/...` form, so this shape is live."""
    proc = _run(tmp_path, _one_group(f"bash ~/{HOOK}", f"bash {tmp_path}/{HOOK}"))
    # Neither is path-rooted at the head, so neither carries identity — the point
    # is that we do NOT invent one from a token that is not a script.
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_the_aoe_guard_style_hook_is_not_a_phantom_duplicate(tmp_path: Path) -> None:
    """aoe writes its own hooks as `[ -n "$AOE_INSTANCE_ID" ] || exit 0; …`.
    Those heads are `[`, not a script — two of them must not read as duplicates."""
    proc = _run(
        tmp_path,
        _one_group(
            '[ -n "$AOE_INSTANCE_ID" ] || exit 0; /bin/echo one',
            '[ -n "$AOE_INSTANCE_ID" ] || exit 0; /bin/echo two',
        ),
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_tilde_expands_against_the_settings_file_not_ambient_HOME(tmp_path: Path) -> None:
    """THE ONE THE OTHER TESTS CANNOT SEE. Every other case here sets $HOME to
    the same dir the settings file lives under, so an implementation reading
    `~` from the environment passes them all. Run it as a user whose $HOME
    differs — an operator checking a container's file from a host shell — and an
    env-derived home stops matching, reporting "no duplicates" over the exact bug
    this exists to catch.
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    settings = home / ".claude" / "settings.json"
    settings.write_text(json.dumps(_one_group(f"~/{HOOK}", f"{home}/{HOOK}")))

    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    proc = subprocess.run(
        ["bash", str(ASSERT), str(settings)],
        capture_output=True,
        text=True,
        env={"HOME": str(elsewhere), "PATH": "/usr/bin:/bin"},
        timeout=60,
    )
    assert proc.returncode == 1, (
        "the duplicate went undetected because `~` was expanded against the "
        f"caller's $HOME instead of the settings file's own home: {proc.stdout}{proc.stderr}"
    )


def test_a_hooks_block_with_nothing_judgeable_is_not_a_pass(tmp_path: Path) -> None:
    """Same doctrine as the no-hooks case, one level down: if every entry is
    skipped, a clean result would be reported over zero inspected registrations."""
    proc = _run(tmp_path, _one_group("echo hi", "true"))
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "ZERO judgeable" in proc.stderr


def test_a_non_object_root_is_unusable_input_not_a_duplicate(tmp_path: Path) -> None:
    proc = _run(tmp_path, ["not", "an", "object"])
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_the_assertion_is_executable() -> None:
    """The Dockerfile execs it directly. If it lands in git mode 644 the suite is
    green and the image build dies with permission denied — discoverable only at
    build time. Repo convention (test_gate, test_quarantine, …) asserts this."""
    assert os.access(ASSERT, os.X_OK), f"{ASSERT} must be executable"


def test_distinct_scripts_are_not_a_duplicate(tmp_path: Path) -> None:
    """The assertion must discriminate, not just fire."""
    proc = _run(tmp_path, _one_group(f"~/{HOOK}", "~/.claude/scripts/other.sh"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no duplicates" in proc.stdout


def test_same_script_under_different_matchers_is_legitimate(tmp_path: Path) -> None:
    """The kit deliberately registers one script under several matchers —
    context-freshness-warn ships under both `startup` and `resume`. Flagging that
    would make the assertion unusable against the real settings file."""
    settings = {
        "hooks": {
            "SessionStart": [
                {"matcher": "startup", "hooks": [{"type": "command", "command": "~/x.sh"}]},
                {"matcher": "resume", "hooks": [{"type": "command", "command": "~/x.sh"}]},
            ]
        }
    }
    proc = _run(tmp_path, settings)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_same_script_under_different_events_is_legitimate(tmp_path: Path) -> None:
    settings = {
        "hooks": {
            "SessionStart": [
                {"matcher": "", "hooks": [{"type": "command", "command": "~/x.sh"}]}
            ],
            "PostToolUse": [
                {"matcher": "", "hooks": [{"type": "command", "command": "~/x.sh"}]}
            ],
        }
    }
    assert _run(tmp_path, settings).returncode == 0


def test_no_hooks_at_all_is_not_a_pass(tmp_path: Path) -> None:
    """An empty denominator is the failure mode this whole issue is an instance
    of — a question nobody asked. "Asked and found nothing" must be
    distinguishable from "did not ask"."""
    proc = _run(tmp_path, {})
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "NO hooks" in proc.stderr


def test_missing_settings_file_is_not_a_pass(tmp_path: Path) -> None:
    proc = _run(tmp_path, None)
    assert proc.returncode == 2, proc.stdout + proc.stderr


def test_the_build_runs_the_assertion_last_over_the_shipped_settings() -> None:
    """An assertion the image build never invokes is the defect it is written to
    prevent, one level up.

    Position is part of the contract, not decoration: the whole claim is that it
    checks the state that SHIPS, after `./install` and every MCP installer have
    written their registrations. Run before them and it would pass over the
    template's intent while the duplicate lands afterwards — green, and blind to
    the exact bug. Comment lines are stripped so the prose explaining this cannot
    satisfy the check.
    """
    directives = [
        line
        for line in DOCKERFILE.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    body = "\n".join(directives)
    assert "assert-no-duplicate-hooks.sh" in body

    idx_assert = next(i for i, l in enumerate(directives) if "assert-no-duplicate-hooks.sh" in l)
    idx_install = max(i for i, l in enumerate(directives) if "./install" in l)
    assert idx_assert > idx_install, (
        "the assertion runs BEFORE ./install — it would check the template's "
        "intent rather than what the MCP installers actually wrote"
    )
    assert "/home/ubuntu/.claude/settings.json" in directives[idx_assert], (
        "the assertion must name the settings file that ships"
    )
