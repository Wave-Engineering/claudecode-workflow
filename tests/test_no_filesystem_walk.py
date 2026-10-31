"""Tests for the "Never Walk the Whole Filesystem" rule in CLAUDE.md (#1374).

On 2026-10-30 a subagent's `find /` went into a self-recursive kio-fuse mount and held a
shared host at load ~105 for about 90 minutes. The kit's CLAUDE.md, which /ccfold merges
into every project, now bans recursive searches from `/`, names what to use instead, and
says to carry the rule into subagent briefs.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLAUDE = (REPO / "CLAUDE.md").read_text(encoding="utf-8")
HEADING = "Never Walk the Whole Filesystem"


def section(text: str, heading: str) -> str:
    """The body of the `## <heading>` section, up to the next `## ` heading."""
    m = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert m, f"no '## {heading}' section"
    return m.group(1)


def test_section_exists_near_secrets():
    heads = re.findall(r"^## (.+)$", CLAUDE, re.M)
    assert HEADING in heads
    # It sits beside the other host-safety rule, right after Secrets and Sensitive Files.
    assert heads.index(HEADING) == heads.index("Secrets and Sensitive Files") + 1


def test_section_bans_root_walks():
    s = section(CLAUDE, HEADING)
    for cmd in ("`find /`", "`bfs /`", "`fd . /`", "`du /`", "`grep -r`", "`rg`"):
        assert cmd in s, cmd
    assert "`/run`" in s
    assert "FUSE" in s


def test_section_names_interpreter_lookups():
    s = section(CLAUDE, HEADING)
    for lookup in ("os.path.dirname(pkg.__file__)", "pip show -f", "npm root -g", "go env GOMODCACHE"):
        assert lookup in s, lookup
    for root in ("~/.local", "~/.cache", "/usr/lib/python3*", "/opt"):
        assert root in s, root


def test_section_gives_bounded_fallback():
    s = section(CLAUDE, HEADING)
    assert "-xdev" in s
    assert "timeout 60" in s
    for pruned in ("/proc", "/sys", "/run", "/mnt", "/media"):
        assert f"-path {pruned}" in s, pruned


def test_section_reaches_subagent_briefs():
    s = section(CLAUDE, HEADING)
    assert re.search(r"subagent brief", s, re.I)


def test_section_fallback_itself_is_not_a_root_walk():
    # The fallback example must name a root of the caller's choosing, never `/`.
    s = section(CLAUDE, HEADING)
    fallback = next(line for line in s.splitlines() if "-xdev" in line)
    assert "find <root>" in fallback
    assert "find / " not in fallback
