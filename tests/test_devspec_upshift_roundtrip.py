"""Round-trip test for `/devspec upshift` → `wave-status init` (#850/ENG-4).

The `phases-waves.json` that `/devspec upshift` emits must load into `wave-status
init` (v3 schema) with ZERO hand-edits. The upshift→v3 transform used to live only
inside the sdlc `wave_init` handler (`normalizePlanJson`), so the decoupled
`wave-status init` CLI path (which `/wavemachine` bootstrap and ENG-3a's workaround
hit) had no normalization: the legacy shape (`waves[].name` + `waves[].stories[].issue`,
no top-level `project`) failed v3 init. This test pins the emitter's contract by
extracting the CANONICAL example from the upshift template (skills/devspec/SKILL.md
Step 6) and feeding it straight into `init_state` — proving the template emits v3.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from wave_status.state import (  # noqa: E402
    CURRENT_SCHEMA_VERSION,
    init_state,
    load_json,
    status_dir,
)

_SKILL = Path(__file__).resolve().parent.parent / "skills" / "devspec" / "SKILL.md"


def _upshift_phases_waves_example() -> dict:
    """Extract the canonical phases-waves.json JSON from the upshift template's Step 6."""
    text = _SKILL.read_text(encoding="utf-8")
    step6 = text.split("### Step 6", 1)
    assert len(step6) == 2, "devspec upshift template must have a Step 6 (write phases-waves.json)"
    m = re.search(r"```json\n(.*?)\n```", step6[1], re.DOTALL)
    assert m, "Step 6 must contain a ```json canonical phases-waves.json example"
    return json.loads(m.group(1))


class TestUpshiftEmitsV3Shape:
    def test_example_parses_as_json(self) -> None:
        _upshift_phases_waves_example()  # raises if the template JSON is malformed

    def test_v3_required_fields_present(self) -> None:
        plan = _upshift_phases_waves_example()
        # Top-level project is REQUIRED by v3 init.
        assert "project" in plan, "v3 upshift must emit top-level 'project'"
        assert "repo" in plan and "base_branch" in plan, "v3 upshift emits repo + base_branch"
        for phase in plan["phases"]:
            for wave in phase["waves"]:
                assert "id" in wave, "each wave keyed by 'id' (v3), not 'name'"
                assert "issues" in wave and wave["issues"], "each wave has a non-empty 'issues' array"
                for issue in wave["issues"]:
                    assert "number" in issue, "each issue has 'number' (v3), not 'issue'/'id'"
                    assert "depends_on" in issue, "each issue keeps depends_on (harmless extra)"

    def test_no_legacy_shape(self) -> None:
        plan = _upshift_phases_waves_example()
        for phase in plan["phases"]:
            for wave in phase["waves"]:
                assert "stories" not in wave, "legacy 'stories' key must be gone (v3 uses 'issues')"
                assert "name" not in wave, "legacy wave 'name' key must be gone (v3 uses 'id')"


class TestUpshiftLoadsIntoWaveStatusInit:
    def test_upshift_example_bootstraps_wave_status_init(self, tmp_path: Path) -> None:
        """The literal upshift template output loads clean into wave-status init (v3)."""
        plan = _upshift_phases_waves_example()
        # No hand-edits: feed the emitter's output straight into init.
        init_state(plan, tmp_path)

        d = status_dir(tmp_path)
        state = load_json(d / "state.json")
        assert state["schema_version"] == CURRENT_SCHEMA_VERSION == 3

        # Waves keyed by id, all pending at init.
        assert set(state["waves"]) == {"P1W1"}
        assert state["waves"]["P1W1"]["status"] == "pending"

        # Issues keyed by the qualified ref owner/repo#N (repo supplied → v3 qualified keys).
        repo = plan["repo"]
        assert f"{repo}#501" in state["issues"], "issues keyed by qualified owner/repo#N (v3)"
        assert f"{repo}#502" in state["issues"]

        # current_wave points at the first wave — a clean bootstrap, zero hand-edits.
        assert state["current_wave"] == "P1W1"

    def test_init_rejects_the_old_legacy_shape(self, tmp_path: Path) -> None:
        """Guard: the pre-#850 legacy shape (no project, waves[].name/stories) fails init —
        this is exactly the skew #850 fixes by moving the emitter to v3."""
        legacy = {
            "plan_id": 499,
            "slug": "x",
            "phases": [
                {"name": "P1", "waves": [
                    {"name": "P1W1", "stories": [{"id": "1.1", "issue": 501, "depends_on": []}]},
                ]},
            ],
        }
        with pytest.raises(ValueError, match="missing required field 'project'"):
            init_state(legacy, tmp_path)
