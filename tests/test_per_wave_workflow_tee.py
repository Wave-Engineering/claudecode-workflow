"""S1.6 / #856 — Workflow-runtime FlightDeck tee.

Asserts the per-wave Workflow emits phase/step (+ a token-metric STUB) at each
spine agent() node, WITHOUT violating TC-2 (no fs/Date/Math.random in the
Workflow SCRIPT body — the emit rides the agent() prompt), and that the token
metric is a clearly-marked #853 stub (R-19). Also confirms the committed bundle
is in sync + valid JS.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_NW = Path(__file__).resolve().parent.parent / "skills" / "nextwave"
_SRC = _NW / "per-wave-workflow.js"
_BUNDLE = _NW / "per-wave-workflow.bundled.js"

_HAS_NODE = shutil.which("node") is not None


@pytest.fixture(scope="module")
def src() -> str:
    return _SRC.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def bundle() -> str:
    return _BUNDLE.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Pure helpers exist and delegate
# ---------------------------------------------------------------------------

class TestHelpers:
    def test_flightdeck_tee_defined(self, src):
        assert "function flightdeckTee(opts)" in src

    def test_tee_agent_defined_and_delegates(self, src):
        assert "function teeAgent(prompt, opts)" in src
        # PURE delegation to the runtime agent(), appending the tee to the prompt.
        assert "return agent(prompt + '\\n' + flightdeckTee(opts), opts)" in src


# ---------------------------------------------------------------------------
# Phase/step + token stub per node
# ---------------------------------------------------------------------------

class TestEmitInstructions:
    def test_emits_step_scoped_by_phase_and_label(self, src):
        # #1026: activity-id is the CAMPAIGN (AID = planId || WAVE_ID), not the wave;
        # `--wave` still tags the current wave for scope.
        assert "wave-status emit step --activity-id '${AID}' --wave '${WAVE_ID}' --phase '${ph}' --label '${label}'" in src


class TestCampaignScoping:
    """#1026: per-wave telemetry keys on the campaign, and a promotion increments
    the wave numerator."""

    def test_aid_is_campaign_scoped(self, src):
        # The tee keys on the campaign (planId), falling back to WAVE_ID only for a
        # bare/test run — this is what stops a separate card spawning per wave.
        assert "const AID = PLAN_ID || WAVE_ID" in src
        # No emit still keys activity-id on WAVE_ID directly.
        assert "--activity-id '${WAVE_ID}'" not in src

    def test_promotion_emits_the_numerator_step(self, src):
        # The terminal node appends a disposition-labeled tee; a `promoted` label is
        # what the flightdeck fold counts (completed++), i.e. the wave numerator.
        assert "flightdeckTee({ phase: 'Promote', label: disposition })" in src

    def test_token_metric_is_a_seamed_null_stub(self, src):
        # A metric named tokens, with NO --value ⇒ null (honest stub), marked #853.
        assert "wave-status emit metric" in src
        assert "--metric tokens" in src
        assert "SEAM #853" in src
        # The token metric line must NOT carry a fabricated --value.
        metric_line = next(
            ln for ln in src.splitlines()
            if "wave-status emit metric" in ln and "--metric tokens" in ln
        )
        assert "--value" not in metric_line

    def test_tee_is_fire_and_forget(self, src):
        assert "fire-and-forget" in src
        assert "|| true" in src  # emit failures are swallowed in the prompt


# ---------------------------------------------------------------------------
# Spine nodes teed; trust-critical nodes intentionally NOT teed
# ---------------------------------------------------------------------------

class TestNodeCoverage:
    def test_five_spine_nodes_teed(self, src):
        assert src.count("await teeAgent(") == 5

    @pytest.mark.parametrize("anchor", [
        "const seed = await teeAgent(",                         # rehydrate
        "const plan = await teeAgent(primePlanPrompt(",         # plan
        "const rec = await teeAgent(primeReconcilePrompt(",     # reconcile
        "const prOpen = await teeAgent(",                       # gate open-pr
        "const promo = await teeAgent(",                        # promote
    ])
    def test_spine_node_uses_tee(self, src, anchor):
        assert anchor in src

    def test_parallel_workers_and_trust_signals_not_teed(self, src):
        # The code-writing workers + the 4 trust signals stay untouched here
        # (their per-node token tee co-delivers with #853).
        assert "teeAgent(workerPrompt(" not in src
        assert "teeAgent(commutativitySignalPrompt(" not in src
        assert "teeAgent(ciSignalPrompt(" not in src
        assert "teeAgent(reviewSignalPrompt(" not in src
        assert "teeAgent(trivySignalPrompt(" not in src


# ---------------------------------------------------------------------------
# TC-2 — no fs/Date/Math.random introduced into the Workflow SCRIPT body
# ---------------------------------------------------------------------------

def _code_only(js: str) -> str:
    """Strip /* */ block comments and full-line // comments so the TC-2 check
    tests executable code, not prose (our own seam comment names the primitives)."""
    import re

    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return "\n".join(
        ln for ln in js.splitlines() if not ln.lstrip().startswith("//")
    )


class TestTC2NoForbiddenPrimitives:
    @pytest.mark.parametrize("banned", ["new Date", "Date.now", "Math.random", "readFileSync", "writeFileSync", "require(", "fs."])
    def test_script_body_free_of_banned_primitive(self, src, banned):
        code = _code_only(src)
        assert banned not in code, f"TC-2 violation: workflow script uses {banned!r}"


# ---------------------------------------------------------------------------
# Committed bundle is in sync + valid
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _HAS_NODE, reason="node not available")
class TestBundle:
    def test_bundle_in_sync(self):
        r = subprocess.run(["node", str(_NW / "bundle.mjs"), "--check"], capture_output=True, text=True)
        assert r.returncode == 0, f"bundle stale — run node bundle.mjs\n{r.stdout}\n{r.stderr}"

    def test_bundle_valid_js(self):
        r = subprocess.run(["node", "--check", str(_BUNDLE)], capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_bundle_carries_five_tees(self, bundle):
        assert bundle.count("await teeAgent(") == 5
        assert "FlightDeck telemetry" in bundle
        assert "SEAM #853" in bundle
