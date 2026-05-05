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
    # And the matcher-union expression itself.
    assert "$local_arr + ($tpl_arr | map(select(.matcher as $m" in src, (
        "merge_settings missing matcher-array union expression (#556)"
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
