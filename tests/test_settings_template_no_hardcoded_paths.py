"""Guard: config/settings.template.json must not hardcode a developer-home path.

Regression test for #1015 — a `/home/bakerb/.local/share/wtf-server/hooks/…`
wtf-server hook path was baked into the COMMITTED template, breaking for every
other user/install (the path does not exist) and leaking in the oakandwave-
workflow image. Hook command paths must be portable: `~/`-relative (Claude Code
expands `~` to $HOME at hook-exec time) or $CLAUDE_PROJECT_DIR-relative — never
an absolute `/home/<user>/…`.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = REPO_ROOT / "config" / "settings.template.json"

# Any absolute path rooted at a specific user's home directory.
_ABS_HOME = re.compile(r"/home/[^/\s\"]+/")


def test_settings_template_has_no_hardcoded_home_paths() -> None:
    text = TEMPLATE.read_text()
    matches = sorted(set(_ABS_HOME.findall(text)))
    assert not matches, (
        "config/settings.template.json must not hardcode an absolute "
        "/home/<user>/ path — use a ~/ path, which expands to $HOME at "
        f"hook-exec time. Offending prefixes: {matches}"
    )
