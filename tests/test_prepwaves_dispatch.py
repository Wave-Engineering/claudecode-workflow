"""tests/test_prepwaves_dispatch.py — per-wave dispatch regression tests.

Story 1.3 (#825, Plan #822 Executor Model). Design of record:
``docs/executor-model-devspec.md`` §8 Story 1.3; requirements R-01–R-07; test
procedures IT-01 (/prepwaves classification) and IT-02 (/nextwave enforcement).

Two verification surfaces, deliberately split — this mirrors the wave-1a
review-gate finding ("pin the engine, not the prose"):

  * CLASSIFICATION (Story 1.1, R-02/R-03/R-04) is a *behavioral* rule the
    ``/prepwaves`` agent applies at prep time — CT-02 says the deliverable is
    SKILL.md + docs, no executable classifier. So there is no engine to call;
    the strongest mechanical check is a regression on the Step 4.A four-rule
    contract table in ``skills/prepwaves/SKILL.md`` (exactly what IT-01
    prescribes: "verifiable via … the skill's wave plan presentation"). Tests
    1–3 parse that table and assert each rule's condition → dispatch mapping.

  * ENFORCEMENT (Story 1.2, CT-01/R-06) *does* have a pure engine —
    ``skills/nextwave/dispatch.js`` — which per-wave-workflow.js calls on every
    planned flight group. Test 4 exercises that real function (via node), not
    prose, to pin the backward-compatible "absent dispatch → serialize" default.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths and fixtures
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent.parent
PREPWAVES_SKILL = _ROOT / "skills" / "prepwaves" / "SKILL.md"
DISPATCH_JS = _ROOT / "skills" / "nextwave" / "dispatch.js"


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read the prepwaves SKILL.md once per module (the live doc, no mocks)."""
    return PREPWAVES_SKILL.read_text(encoding="utf-8")


def _parse_dispatch_table(skill_text: str) -> dict[int, dict[str, str]]:
    """Parse the Step 4.A ``| Rule | Condition | dispatch |`` classification table.

    Returns ``{rule_num: {"condition", "dispatch_cell", "dispatch_token"}}`` where
    ``dispatch_token`` is the FIRST backticked value in the dispatch cell — the
    canonical classification (rule 2's cell also mentions ``fan`` in prose, so the
    leading token is the one that matters).
    """
    lines = skill_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if (
            len(cells) == 3
            and cells[0].lower() == "rule"
            and cells[1].lower() == "condition"
            and "dispatch" in cells[2].lower()
        ):
            header_idx = i
            break
    assert header_idx is not None, (
        f"Step 4.A dispatch classification table header not found in {PREPWAVES_SKILL}"
    )

    rules: dict[int, dict[str, str]] = {}
    for line in lines[header_idx + 1 :]:
        s = line.strip()
        if not s.startswith("|"):
            break  # table ended
        cells = [c.strip() for c in s.strip("|").split("|")]
        if len(cells) != 3:
            continue
        if set(cells[0]) <= set("-: "):
            continue  # markdown separator row
        if not re.fullmatch(r"\d+", cells[0]):
            continue
        m = re.search(r"`([^`]+)`", cells[2])
        rules[int(cells[0])] = {
            "condition": cells[1],
            "dispatch_cell": cells[2],
            "dispatch_token": m.group(1) if m else "",
        }
    return rules


@pytest.fixture(scope="module")
def dispatch_rules(skill_text: str) -> dict[int, dict[str, str]]:
    rules = _parse_dispatch_table(skill_text)
    assert len(rules) >= 4, (
        f"expected the four-rule Step 4.A table, parsed {len(rules)} rule row(s)"
    )
    return rules


def _rule_matching(rules, predicate):
    """Return the single table row whose condition matches ``predicate`` (or None)."""
    hits = [r for r in rules.values() if predicate(r["condition"])]
    return hits[0] if len(hits) == 1 else (hits[0] if hits else None)


# ---------------------------------------------------------------------------
# 1. Width-1 waves → serialize  (R-02)
# ---------------------------------------------------------------------------

def test_dispatch_width1_serialize(dispatch_rules):
    """A width-1 wave must classify ``dispatch: serialize`` [R-02]."""
    row = _rule_matching(
        dispatch_rules, lambda c: re.search(r"width\s*=\s*1", c, re.I) is not None
    )
    assert row is not None, "no 'Width = 1' rule found in the Step 4.A table"
    assert row["dispatch_token"] == "serialize", (
        f"Width-1 wave must be `serialize`, got `{row['dispatch_token']}` [R-02]"
    )
    assert row["dispatch_token"] != "fan", "a width-1 wave must never fan"


# ---------------------------------------------------------------------------
# 2. Clean-independent width-N waves → fan  (R-04, guarded by R-07 bias)
# ---------------------------------------------------------------------------

def test_dispatch_fan_independent(dispatch_rules, skill_text):
    """Width-N, all-independent, mechanical work → ``dispatch: fan`` [R-04].

    Also asserts the asymmetric-bias note (R-07) that guards ``fan`` is present:
    ``fan`` is the only wave-killing misclassification, so the default-serialize
    bias documenting *why* it is gated must accompany the rule.
    """
    row = _rule_matching(dispatch_rules, lambda c: "mechanical" in c.lower())
    assert row is not None, "no 'mechanical / independent' fan rule in the Step 4.A table"

    cond = row["condition"].lower()
    assert re.search(r"width\s*>\s*1", cond), (
        "the fan rule must require width > 1 (single-flight waves never fan)"
    )
    assert "independent" in cond, "the fan rule must require verified-independent flights"
    assert row["dispatch_token"] == "fan", (
        f"clean-independent mechanical width-N wave must be `fan`, "
        f"got `{row['dispatch_token']}` [R-04]"
    )

    # R-07: asymmetric bias — default is serialize; a wrong fan can kill a wave.
    assert re.search(r"default is\s+`?serialize`?", skill_text, re.I), (
        "the asymmetric-bias note ('default is serialize') must be documented [R-07]"
    )
    assert re.search(r"wrong\s+`?fan`?", skill_text, re.I), (
        "the note must state a wrong `fan` is the wave-killing misclassification [R-07]"
    )


# ---------------------------------------------------------------------------
# 3. Intra-wave dependency edge → serialize, HARD GATE  (R-03)
# ---------------------------------------------------------------------------

def test_dispatch_hard_gate_intra_dep(dispatch_rules):
    """Any intra-wave dependency edge forces ``serialize`` as a hard gate [R-03].

    Unlike the asymmetric bias (a soft default), an intra-dep edge is never
    overridable to ``fan`` regardless of width — the F-8-class safety property.
    """
    row = _rule_matching(
        dispatch_rules,
        lambda c: "intra-wave dependency" in c.lower() or "dependency edge" in c.lower(),
    )
    assert row is not None, "no intra-wave dependency-edge rule in the Step 4.A table"
    assert row["dispatch_token"] == "serialize", (
        f"intra-dep wave must be `serialize`, got `{row['dispatch_token']}` [R-03]"
    )
    assert "hard gate" in row["dispatch_cell"].lower(), (
        "intra-dep serialize must be documented as a HARD GATE (never overridable "
        "to fan) [R-03]"
    )


# ---------------------------------------------------------------------------
# 4. Absent dispatch → serialize, enforced by the nextwave engine  (CT-01)
# ---------------------------------------------------------------------------

_NODE_EVAL = """
const p = process.argv[1];
const { normalizeDispatch, applyDispatchCeiling } = await import(p);
process.stdout.write(JSON.stringify({
  norm_absent:  normalizeDispatch(undefined),
  norm_null:    normalizeDispatch(null),
  norm_empty:   normalizeDispatch(''),
  norm_unknown: normalizeDispatch('parallel-please'),
  ceil_absent:  applyDispatchCeiling([7, 2, 3], undefined),
  ceil_fan:     applyDispatchCeiling([7, 2, 3], 'fan'),
}));
"""


def _node_dispatch_eval() -> dict:
    """Invoke the real ``skills/nextwave/dispatch.js`` engine and return its output.

    Exercises the exact pure functions per-wave-workflow.js calls, so the
    backward-compat default is pinned at the enforcement seam, not in prose.
    """
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not found — required to exercise the nextwave dispatch engine")
    assert DISPATCH_JS.is_file(), f"missing dispatch engine: {DISPATCH_JS}"
    r = subprocess.run(
        [node, "--input-type=module", "-e", _NODE_EVAL, DISPATCH_JS.as_uri()],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert r.returncode == 0, f"node dispatch eval failed (rc={r.returncode}):\n{r.stderr}"
    return json.loads(r.stdout)


def test_dispatch_backward_compat():
    """A wave/plan with no ``dispatch`` field is treated as ``serialize`` [CT-01].

    Legacy phases-waves.json written before this field existed must keep
    executing single-file — an absent/null/unknown hint must never fan.
    """
    out = _node_dispatch_eval()

    # normalize: every non-fan / absent form collapses to the serialize default.
    assert out["norm_absent"] == "serialize", "absent dispatch must normalize to serialize"
    assert out["norm_null"] == "serialize"
    assert out["norm_empty"] == "serialize"
    assert out["norm_unknown"] == "serialize", "unknown hints must never accidentally fan"

    # ceiling: a legacy multi-issue group with no dispatch runs one flight at a time.
    assert out["ceil_absent"] == [7], (
        "absent dispatch must serialize the flight group to single-file [CT-01]"
    )
    # sanity anchor: an explicit fan still fans, so the default isn't 'always serialize'.
    assert out["ceil_fan"] == [7, 2, 3], "explicit fan must keep the parallel group [R-06]"
