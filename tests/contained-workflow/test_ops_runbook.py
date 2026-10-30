"""The ops runbook's promote commands are ones the wrapper can actually run (#1359).

§3 used to name scripts/flightdeck/query-gate-signals.sh, which never existed, set
PROMOTE_ACK where the wrapper reads OPERATOR_ACK, and never set DIGEST_REF, which
the wrapper requires. These read the runbook against the wrapper itself.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RUNBOOK = REPO / "docs" / "contained-workflow" / "ops-runbook.md"
WRAPPER = REPO / "scripts" / "ci" / "promote-oakandwave-image.sh"


def _section_3() -> str:
    text = RUNBOOK.read_text()
    m = re.search(r"^## 3\..*?(?=^## 4\.)", text, re.MULTILINE | re.DOTALL)
    assert m, "ops-runbook.md has no §3"
    return m.group(0)


def _code_blocks(text: str) -> str:
    return "\n".join(re.findall(r"```bash\n(.*?)```", text, re.DOTALL))


def test_every_named_script_exists() -> None:
    paths = sorted(set(re.findall(r"scripts/[A-Za-z0-9_./-]+", RUNBOOK.read_text())))
    assert paths
    missing = [p for p in paths if not (REPO / p.rstrip(".")).exists()]
    assert not missing, f"the runbook names scripts that do not exist: {missing}"


def test_runbook_promote_block_matches_the_wrapper() -> None:
    sec = _section_3()
    assert "query-gate-signals" not in sec
    assert "PROMOTE_ACK" not in RUNBOOK.read_text()
    block = _code_blocks(sec)
    assert block, "§3 has no bash block"
    read = set(re.findall(r"\$\{([A-Z_][A-Z0-9_]*)", WRAPPER.read_text()))
    used = set(re.findall(r"\b([A-Z_][A-Z0-9_]*)=", block))
    assert not used - read, f"§3 sets variables the wrapper never reads: {sorted(used - read)}"
    for var in ("DIGEST_REF", "THROWAWAY_CI_PASSED", "QUARANTINE_TELEMETRY_ABSENT",
                "SEV1_TELEMETRY_ABSENT", "OPERATOR_ACK"):
        assert f"{var}=" in block, f"§3 does not set {var}"


def test_section_3_lists_three_gate_conditions() -> None:
    sec = _section_3()
    assert "all three" in sec and "all four" not in sec
    assert "soak met" not in sec
