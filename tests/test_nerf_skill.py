"""Skill-text guard for /nerf after mcp-server-nerf#32.

nerf's darts are percentages of the context window used, and nerf_darts /
nerf_budget reject token counts. A /nerf skill that still teaches `200k` makes
every documented invocation fail, so the skill and its reference entry must not
teach token counts, and must not describe the deleted analyzer.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILL = ROOT / "skills" / "nerf" / "SKILL.md"
REFERENCE = ROOT / "docs" / "skill-reference.md"


def _nerf_reference_section() -> str:
    text = REFERENCE.read_text(encoding="utf-8")
    start = text.index("/nerf")
    end = text.index("/precheck", start)
    return text[start:end]


def test_no_token_count_examples():
    token_example = re.compile(r"/nerf[^\n]*\b\d+(\.\d+)?[kKmM]\b")
    for name, text in (("SKILL.md", SKILL.read_text(encoding="utf-8")), ("skill-reference", _nerf_reference_section())):
        assert not token_example.search(text), f"{name} still shows a token-count /nerf example"


def test_no_suffix_expansion_rule():
    assert "200000" not in SKILL.read_text(encoding="utf-8")


def test_no_analyzer():
    for text in (SKILL.read_text(encoding="utf-8"), _nerf_reference_section()):
        assert "analyzer" not in text.lower()


def test_teaches_percentages():
    text = SKILL.read_text(encoding="utf-8")
    assert "percent" in text.lower()
    assert "/nerf darts 51 63 85" in _nerf_reference_section()


def test_legacy_python_config_lib_is_gone():
    # skills/nerf/lib/nerf_config.py wrote absolute-token `darts` into the same
    # /tmp/nerf-<sid>.json the MCP server owns; nothing called it.
    assert not (ROOT / "skills" / "nerf" / "lib").exists()
