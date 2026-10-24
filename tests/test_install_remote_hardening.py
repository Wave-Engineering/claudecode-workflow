"""install-remote.sh hardening port tests (cc-workflow #540, #556, #560).

Static-analysis tests confirming that the three install-hardening features
present in `install` were ported into `scripts/install-remote.sh`:

- #540 logrotate policy:    --with-logrotate / --without-logrotate flags
- #556 hook union-merge:    matcher-array union pipeline in merge_settings()
- #560 Cellar + symlink-farm: $CELLAR_DIR constant + Cellar/farm helpers

These are intentionally surface-level checks (look for sentinels in the
source); the deeper behavioral tests live in tests/test_install_*.py
against the `install` script itself, which carries the canonical
implementation.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

_REPO_DIR = Path(__file__).resolve().parent.parent
_INSTALL_REMOTE = _REPO_DIR / "scripts" / "install-remote.sh"


def _read() -> str:
    assert _INSTALL_REMOTE.is_file(), f"missing: {_INSTALL_REMOTE}"
    return _INSTALL_REMOTE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# #560 Cellar + symlink-farm layout
# ---------------------------------------------------------------------------


def test_cellar_dir_constant_exists() -> None:
    """install-remote.sh defines CELLAR_DIR pointing at ~/.claude/scripts."""
    src = _read()
    # Must be at top-level (not inside a function), and resolve to the same
    # path the install script uses.
    assert re.search(
        r'^CELLAR_DIR="\$HOME/\.claude/scripts"\s*$',
        src,
        re.MULTILINE,
    ), "CELLAR_DIR constant not found at top of install-remote.sh"


def test_cellar_helpers_present() -> None:
    """Core Cellar + farm helpers were ported from install."""
    src = _read()
    for fn in (
        "cellar_deploy",
        "farm_symlink",
        "farm_symlink_skill_helper",
        "cellar_install_skill_helper",
        "enumerate_farm_targets",
        "reap_stale_cellar_symlinks",
        "safeguard_user_file",
        "resolve_symlink_target",
    ):
        assert re.search(rf"^{fn}\(\)\s*\{{", src, re.MULTILINE), (
            f"helper {fn}() not found — Cellar layout port incomplete"
        )


def test_enumerate_farm_targets_uses_portable_pattern() -> None:
    """BSD/macOS-portable: find ... | sed 's|^./||', NOT find -printf '%f\\n'."""
    src = _read()
    assert "find . -maxdepth 1 -type f | sed 's|^\\./||'" in src, (
        "enumerate_farm_targets must use the portable find|sed pattern; "
        "find -printf is GNU-only and silently empties on BSD/macOS"
    )
    # Also confirm we never invoke GNU-only -printf '%f\n' or '%P\n' as actual
    # find arguments. Mentions in code comments (lines starting with `#`) are
    # OK — those are documentation of what we're avoiding.
    code_lines = [
        line
        for line in src.splitlines()
        if not line.lstrip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    assert "-printf '%P\\n'" not in code_only, (
        "GNU find -printf '%P\\n' invoked — breaks BSD/macOS"
    )
    assert "-printf '%f\\n'" not in code_only, (
        "GNU find -printf '%f\\n' invoked — breaks BSD/macOS"
    )


# ---------------------------------------------------------------------------
# #556 Hook union-merge in merge_settings
# ---------------------------------------------------------------------------


def test_merge_settings_union_block_present() -> None:
    """merge_settings() includes the union-merge jq pipeline for shared hook events."""
    src = _read()
    # The sentinel: the $merged_shared_hooks binding name from install's
    # union-merge block. Its presence indicates the union pipeline was ported.
    assert "$merged_shared_hooks" in src, (
        "merge_settings missing $merged_shared_hooks union-merge block (#556)"
    )
    # And the matcher-union expression itself, with #734's kit-ownership clause.
    assert "$local_arr + ($tpl_arr | map(select(" in src, (
        "merge_settings missing matcher-array union expression (#556)"
    )
    assert "(.matcher as $m | $local_matchers | index($m) | not)" in src
    assert 'test("\\\\.local/bin/|\\\\.claude/")' in src, (
        "merge_settings missing the #734 kit-ownership clause"
    )


def test_merge_settings_reports_added_matchers() -> None:
    """--check / install reports 'matcher \"X\" added' for new matchers."""
    src = _read()
    assert 'matcher \\"$m\\" added' in src, (
        "merge_settings missing per-matcher 'added' reporting (#556)"
    )


# ---------------------------------------------------------------------------
# #540 Logrotate policy
# ---------------------------------------------------------------------------


def test_logrotate_flags_parsed() -> None:
    """--with-logrotate and --without-logrotate are arg-loop entries."""
    src = _read()
    # Both flags must appear as `case` arms in the main arg-loop.
    assert re.search(r"--with-logrotate\)", src), (
        "--with-logrotate flag not parsed in arg loop (#540)"
    )
    assert re.search(r"--without-logrotate\)", src), (
        "--without-logrotate flag not parsed in arg loop (#540)"
    )
    # And they should drive a tri-state mode variable.
    assert "LOGROTATE_MODE=" in src, (
        "LOGROTATE_MODE tri-state not initialized (#540)"
    )


def test_logrotate_helpers_present() -> None:
    """Logrotate helpers were ported from install."""
    src = _read()
    for fn in (
        "logrotate_supported",
        "install_logrotate_config",
        "uninstall_logrotate_config",
        "check_logrotate_status",
        "render_logrotate_template",
    ):
        assert re.search(rf"^{fn}\(\)\s*\{{", src, re.MULTILINE), (
            f"helper {fn}() not found — logrotate port incomplete (#540)"
        )


def test_logrotate_macos_no_op() -> None:
    """logrotate_supported gates on Linux + logrotate-on-PATH."""
    src = _read()
    # Must check uname AND command -v logrotate.
    assert 'uname -s' in src and 'Linux' in src, (
        "logrotate_supported must Linux-gate via uname -s (#540)"
    )
    assert 'command -v logrotate' in src, (
        "logrotate_supported must check logrotate is on PATH (#540)"
    )


def test_logrotate_template_substitution() -> None:
    """{{HOME}} marker is rendered before sudo install."""
    src = _read()
    assert "{{HOME}}" in src, (
        "render_logrotate_template missing {{HOME}} substitution (#540)"
    )


def test_logrotate_dry_run_honored() -> None:
    """install_logrotate_config respects $DRY_RUN."""
    src = _read()
    # The function should branch on DRY_RUN before sudo install.
    assert re.search(
        r"install_logrotate_config\(\)\s*\{[^}]*DRY_RUN",
        src,
        re.DOTALL,
    ), "install_logrotate_config must check $DRY_RUN before mutating /etc (#540)"


# ---------------------------------------------------------------------------
# #1238 skill backups moved out of the skills tree
# ---------------------------------------------------------------------------


def test_relocate_skill_baks_runs_before_skills_install() -> None:
    src = _read()
    assert re.search(r"relocate_skill_baks\n\tfor skill_dir in \"\$release_dir\"/skills/\*/", src), (
        "install-remote.sh must sweep skill .bak files before installing skills (#1238)"
    )


def test_relocate_skill_baks_moves_every_bak_out(tmp_path: Path) -> None:
    """Behavioral: the function itself, extracted from install-remote.sh and run, on a
    skills dir that is a symlink (dotfiles-style), which the sweep must still enter."""
    func = re.search(r"^relocate_skill_baks\(\) \{.*?^\}$", _read(), re.MULTILINE | re.DOTALL)
    assert func, "relocate_skill_baks() not found in install-remote.sh"
    real = tmp_path / "dotfiles-skills"
    real.mkdir()
    (tmp_path / ".claude").mkdir()
    skills = tmp_path / ".claude" / "skills"
    skills.symlink_to(real)
    planted = [skills / "a" / "SKILL.md.bak", skills / "b" / "tours" / "t.md.bak"]
    for f in planted:
        f.parent.mkdir(parents=True)
        f.write_text(f"old {f.name}\n")
    (skills / "a" / "SKILL.md").write_text("live\n")
    script = (
        'info() { echo "$*"; }\n'
        f'SKILLS_DIR="{skills}"\nCLAUDE_DIR="{tmp_path / ".claude"}"\nDRY_RUN=false\n'
        f"{func.group(0)}\nrelocate_skill_baks\n"
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert list(skills.rglob("*.bak")) == []
    assert (skills / "a" / "SKILL.md").read_text() == "live\n"
    for f in planted:
        assert (tmp_path / ".claude" / "backups" / "skills" / f.relative_to(skills)).read_text() == f"old {f.name}\n"


# ---------------------------------------------------------------------------
# #1109 / #734: release upgrades replace the inline stall guard and deploy new
# kit "*" Stop hooks
# ---------------------------------------------------------------------------

_LEGACY_INLINE_GUARD = (
    'state="${CLAUDE_PROJECT_DIR:-.}/.claude/status/state.json"; [ -f "$state" ] || exit 0; '
    "active=$(jq -r '.wavemachine_active // false' \"$state\" 2>/dev/null); "
    '[ "$active" = "true" ] || exit 0; '
    "printf '{\"decision\":\"block\",\"reason\":\"/wavemachine is active.\"}'"
)


def _run_remote_merge(tmp_path: Path, local: dict) -> tuple[subprocess.CompletedProcess[str], dict]:
    """Extract merge_settings() and its helper from install-remote.sh and run
    them against the REAL settings template and *local*."""
    src = _read()
    funcs = [
        re.search(rf"^{name}\(\) \{{.*?^\}}$", src, re.MULTILINE | re.DOTALL)
        for name in ("remove_legacy_inline_stall_guard", "merge_settings")
    ]
    assert all(funcs), "remove_legacy_inline_stall_guard() / merge_settings() not found"
    target = tmp_path / "settings.json"
    target.write_text(json.dumps(local))
    template = _REPO_DIR / "config" / "settings.template.json"
    script = (
        'info() { echo "$*"; }\nskip() { :; }\n'
        + "\n".join(f.group(0) for f in funcs)
        + f'\nmerge_settings "{template}" "{target}"\n'
    )
    result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60)
    return result, json.loads(target.read_text())


def test_remote_merge_replaces_inline_stall_guard(tmp_path: Path) -> None:
    local = {
        "hooks": {
            "Stop": [
                {"matcher": "*", "hooks": [{"type": "command", "command": "~/.local/bin/precheck-asking-detector.sh"}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": _LEGACY_INLINE_GUARD}]},
                {"matcher": "*", "hooks": [{"type": "command", "command": "my-custom-stop-hook.sh"}]},
            ]
        }
    }
    result, merged = _run_remote_merge(tmp_path, local)
    assert result.returncode == 0, result.stderr
    assert "removed 1 inline wavemachine stall guard" in result.stdout
    commands = [h["command"] for g in merged["hooks"]["Stop"] for h in g["hooks"]]
    assert not [c for c in commands if "wavemachine_active" in c], "inline guard survived"
    # #734: the kit's "*" Stop hook is added although a "*" group already exists.
    assert sum("wavemachine-stall-guard.sh" in c for c in commands) == 1
    assert sum(c == "~/.local/bin/precheck-asking-detector.sh" for c in commands) == 1
    assert "my-custom-stop-hook.sh" in commands
    assert all(g["hooks"] for g in merged["hooks"]["Stop"])

    # A second run changes nothing.
    again, remerged = _run_remote_merge(tmp_path, merged)
    assert again.returncode == 0, again.stderr
    assert remerged["hooks"]["Stop"] == merged["hooks"]["Stop"]
