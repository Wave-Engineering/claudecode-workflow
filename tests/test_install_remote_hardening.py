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


# Since #1360 both installers source one merge, scripts/lib/settings-merge.sh.
_MERGE_LIB = _REPO_DIR / "scripts" / "lib" / "settings-merge.sh"


def test_merge_settings_union_block_present() -> None:
    """The shared merge_settings() holds the union-merge jq pipeline for shared hook events."""
    src = _MERGE_LIB.read_text(encoding="utf-8")
    # The sentinel: the $merged_shared_hooks binding name from the union-merge block.
    assert "$merged_shared_hooks" in src, (
        "merge_settings missing $merged_shared_hooks union-merge block (#556)"
    )
    # And the kit-owned "*"-matcher condition (#734) the old remote fork lacked.
    assert 'map(test("\\\\.local/bin/|\\\\.claude/")) | any' in src, (
        "merge_settings missing the kit-owned union condition (#734)"
    )


def test_merge_settings_reports_added_matchers() -> None:
    """install reports 'matcher \"X\" added' for new matchers."""
    src = _MERGE_LIB.read_text(encoding="utf-8")
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
