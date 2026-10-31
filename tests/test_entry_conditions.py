"""Entry-condition gate in the wave-status CLI [#1393].

The Python half of Wave-Engineering/mcp-server-sdlc#613: ``preflight``,
``planning`` and ``flight-plan`` refuse and hold a wave with an unmet
``start`` EC; ``complete`` refuses while any EC holds the wave; ``show``
renders the ECs. Every refusal test has a positive control, the same wave with
its EC ``met``, that passes. ``wave_ec_sync`` is simulated by rewriting
``phases-waves.json`` directly, which is all it does.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from wave_status.entry_conditions import (  # noqa: E402
    EC_RECORD_HINT,
    MALFORMED_EC,
    ec_summary,
    evaluate_wave_gate,
    is_cross_plan_ref,
)
from wave_status.state import (  # noqa: E402
    complete,
    extend_state,
    hold_wave,
    init_state,
    load_json,
    planning,
    preflight,
    save_json,
    show,
    status_dir,
    store_flight_plan,
)


def _plan(ec_status: str | None = "unmet", gates: str = "start", **issue_extra) -> dict:
    """A two-wave plan whose wave-1 issue #1 names EC-1."""
    ec: dict = {"gates": gates}
    if ec_status is not None:
        ec["status"] = ec_status
    return {
        "project": "ec-test",
        "entry_conditions": {"EC-1": ec},
        "phases": [
            {
                "name": "P1",
                "waves": [
                    {
                        "id": "wave-1",
                        "issues": [
                            {"number": 1, "title": "One", "depends_on": [], "ec": ["EC-1"], **issue_extra},
                            {"number": 2, "title": "Two", "depends_on": [1]},
                        ],
                    },
                    {"id": "wave-2", "issues": [{"number": 3, "title": "Three", "depends_on": [2]}]},
                ],
            }
        ],
    }


def _sync(root: Path, ec: str, status: str) -> None:
    """Do what wave_ec_sync does: rewrite one EC's status in phases-waves.json."""
    path = status_dir(root) / "phases-waves.json"
    plan = load_json(path)
    plan["entry_conditions"][ec]["status"] = status
    save_json(path, plan)


def _wave(root: Path, wave_id: str = "wave-1") -> dict:
    return load_json(status_dir(root) / "state.json")["waves"][wave_id]


# ---------------------------------------------------------------------------
# The pure gate
# ---------------------------------------------------------------------------


class TestEvaluateWaveGate:
    def test_unmet_start_holds(self) -> None:
        gate = evaluate_wave_gate({"EC-1": {"status": "unmet", "gates": "start"}},
                                  [{"number": 1, "ec": ["EC-1"]}])
        assert gate["held"] is True
        assert gate["start"] == [{"ec": "EC-1", "status": "unmet", "gates": "start", "issues": [1]}]

    def test_met_start_passes(self) -> None:
        gate = evaluate_wave_gate({"EC-1": {"status": "met", "gates": "start"}},
                                  [{"number": 1, "ec": ["EC-1"]}])
        assert gate == {"start": [], "delivery": [], "depends_on": [], "held": False}

    @pytest.mark.parametrize("cond", [{}, {"status": "maybe"}, {"status": None}, "met"])
    def test_missing_or_invalid_status_reads_unmet(self, cond: object) -> None:
        gate = evaluate_wave_gate({"EC-1": cond}, [{"number": 1, "ec": ["EC-1"]}])
        assert gate["held"] is True
        assert gate["start"][0]["status"] == "unmet"

    def test_unknown_gates_reads_start(self) -> None:
        gate = evaluate_wave_gate({"EC-1": {"status": "unmet", "gates": "later"}},
                                  [{"number": 1, "ec": ["EC-1"]}])
        assert gate["held"] is True and gate["start"][0]["gates"] == "start"

    def test_undeclared_ec_holds_as_start(self) -> None:
        gate = evaluate_wave_gate({}, [{"number": 4, "ec": ["EC-9"]}])
        assert gate["start"] == [{"ec": "EC-9", "status": "undeclared", "gates": "start", "issues": [4]}]

    def test_delivery_does_not_hold_start(self) -> None:
        gate = evaluate_wave_gate({"EC-1": {"status": "unmet", "gates": "delivery"}},
                                  [{"number": 1, "ec": ["EC-1"]}])
        assert gate["held"] is False
        assert gate["delivery"][0]["ec"] == "EC-1"

    @pytest.mark.parametrize("raw", ["EC-1", [1], [""], [{"id": "EC-1"}], {"EC-1": True}])
    def test_malformed_ec_holds(self, raw: object) -> None:
        gate = evaluate_wave_gate({"EC-1": {"status": "met"}}, [{"number": 5, "ec": raw}])
        assert gate["held"] is True
        assert gate["start"] == [{"ec": MALFORMED_EC, "status": "malformed", "gates": "start", "issues": [5]}]

    @pytest.mark.parametrize("raw", [None, []])
    def test_absent_or_empty_ec_names_none(self, raw: object) -> None:
        assert evaluate_wave_gate({}, [{"number": 5, "ec": raw}])["held"] is False

    def test_mixed_ec_list_is_malformed_as_a_whole(self) -> None:
        """As sdlc#614 reads it: one bad entry makes the whole field malformed."""
        gate = evaluate_wave_gate({"EC-1": {"status": "unmet"}}, [{"number": 5, "ec": ["EC-1", 7]}])
        assert [h["ec"] for h in gate["start"]] == [MALFORMED_EC]

    def test_integral_float_depends_on_is_readable(self) -> None:
        assert evaluate_wave_gate(None, [{"number": 6, "depends_on": [2.0]}])["held"] is False
        assert evaluate_wave_gate(None, [{"number": 6, "depends_on": [2.5]}])["held"] is True

    def test_refusal_wording_matches_sdlc(self) -> None:
        from wave_status.entry_conditions import describe_holds
        gate = evaluate_wave_gate(None, [{"number": 5, "ec": "EC-1", "depends_on": [None]}])
        assert describe_holds("w1", gate["start"], gate["depends_on"]) == (
            "wave w1 is held: #5: `ec` is not an array of EC ids; "
            "#5 has an unreadable depends_on entry null"
        )

    def test_holds_sort_numerically(self) -> None:
        ecs = {f"EC-{n}": {"status": "unmet"} for n in (10, 2)}
        gate = evaluate_wave_gate(ecs, [{"number": 1, "ec": ["EC-10", "EC-2"]}])
        assert [h["ec"] for h in gate["start"]] == ["EC-2", "EC-10"]

    def test_superscript_digit_in_an_id_does_not_crash(self) -> None:
        gate = evaluate_wave_gate({}, [{"number": 1, "ec": ["EC²", "EC-1"]}])
        assert {h["ec"] for h in gate["start"]} == {"EC²", "EC-1"}

    def test_malformed_sorts_first_as_sdlc_does(self) -> None:
        """localeCompare(numeric) puts punctuation before letters."""
        gate = evaluate_wave_gate(
            {"EC-2": {"status": "unmet"}},
            [{"number": 1, "ec": ["EC-2"]}, {"number": 2, "ec": "bad"}],
        )
        assert [h["ec"] for h in gate["start"]] == [MALFORMED_EC, "EC-2"]

    def test_cross_plan_ref_holds(self) -> None:
        gate = evaluate_wave_gate(None, [{"number": 6, "depends_on": ["plan-a#12"]}])
        assert gate["held"] is True
        assert gate["depends_on"] == [{"ref": "plan-a#12", "issue": 6, "reason": "cross_plan_unresolved"}]

    def test_legacy_depends_on_shapes_pass(self) -> None:
        """Positive control: ints, ``#N`` and ``owner/repo#N`` are not cross-plan."""
        gate = evaluate_wave_gate(None, [{"number": 6, "depends_on": [99, "#5", "org/repo#5"]}])
        assert gate["held"] is False

    @pytest.mark.parametrize(
        "raw, ref",
        [("#5", '"#5"'), (5, "5"), ({"a": 1}, '{"a":1}'), ([""], '""'), ([None], "null"), ([True], "true")],
    )
    def test_malformed_depends_on_holds(self, raw: object, ref: str) -> None:
        gate = evaluate_wave_gate(None, [{"number": 6, "depends_on": raw}])
        assert gate["held"] is True
        assert gate["depends_on"] == [{"ref": ref, "issue": 6, "reason": "malformed"}]
        assert gate["start"] == []

    @pytest.mark.parametrize("ref", ["plan-a#1", "  p#2 "])
    def test_is_cross_plan_ref(self, ref: str) -> None:
        assert is_cross_plan_ref(ref)

    @pytest.mark.parametrize("ref", ["#1", "org/repo#1", "plan-a", 3, None, "a b#1"])
    def test_is_not_cross_plan_ref(self, ref: object) -> None:
        assert not is_cross_plan_ref(ref)


# ---------------------------------------------------------------------------
# preflight / planning / flight-plan refuse and hold
# ---------------------------------------------------------------------------


class TestStartGate:
    @pytest.mark.parametrize("step", [preflight, planning])
    def test_unmet_start_refuses_and_holds(self, tmp_path: Path, step) -> None:
        init_state(_plan("unmet"), tmp_path)
        with pytest.raises(ValueError, match=r"EC-1 is unmet \(start\) for #1"):
            step(tmp_path)
        wave = _wave(tmp_path)
        assert wave["status"] == "held"
        assert wave["held_by"] == [{"ec": "EC-1", "status": "unmet", "gates": "start", "issues": [1]}]

    @pytest.mark.parametrize("step", [preflight, planning])
    def test_met_start_passes(self, tmp_path: Path, step) -> None:
        init_state(_plan("met"), tmp_path)
        step(tmp_path)
        assert "held_by" not in _wave(tmp_path)
        assert _wave(tmp_path)["status"] != "held"

    def test_missing_status_refuses(self, tmp_path: Path) -> None:
        init_state(_plan(None), tmp_path)
        with pytest.raises(ValueError, match="EC-1 is unmet"):
            preflight(tmp_path)

    def test_flight_plan_refuses(self, tmp_path: Path) -> None:
        init_state(_plan("unmet"), tmp_path)
        with pytest.raises(ValueError, match="Refusing flight-plan"):
            store_flight_plan([{"issues": [1, 2], "status": "pending"}], tmp_path)
        assert load_json(status_dir(tmp_path) / "flights.json") == {"flights": {}}
        assert _wave(tmp_path)["status"] == "held"

    def test_flight_plan_met_stores(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        store_flight_plan([{"issues": [1, 2], "status": "pending"}], tmp_path)
        assert load_json(status_dir(tmp_path) / "flights.json")["flights"]["wave-1"]

    def test_refusal_names_every_hold(self, tmp_path: Path) -> None:
        plan = _plan("unmet")
        plan["entry_conditions"]["EC-2"] = {"status": "reclosed", "gates": "start"}
        plan["phases"][0]["waves"][0]["issues"][1]["ec"] = ["EC-2"]
        plan["phases"][0]["waves"][0]["issues"][1]["depends_on"] = ["other#4"]
        init_state(plan, tmp_path)
        with pytest.raises(ValueError) as exc:
            preflight(tmp_path)
        msg = str(exc.value)
        assert "EC-1 is unmet (start) for #1" in msg
        assert "EC-2 is reclosed (start) for #2" in msg
        assert "#2 depends on other#4" in msg
        assert _wave(tmp_path)["held_by_depends_on"] == [
            {"ref": "other#4", "issue": 2, "reason": "cross_plan_unresolved"}
        ]

    def test_unresolved_cross_plan_ref_refuses(self, tmp_path: Path) -> None:
        init_state(_plan("met", depends_on=["plan-b#7"]), tmp_path)
        with pytest.raises(ValueError, match="plan-b#7"):
            preflight(tmp_path)
        assert _wave(tmp_path)["status"] == "held"

    def test_same_repo_ref_passes(self, tmp_path: Path) -> None:
        """Positive control for the cross-plan test: a ``#N`` ref is not cross-plan."""
        init_state(_plan("met", depends_on=["#2", 2]), tmp_path)
        preflight(tmp_path)
        assert _wave(tmp_path)["status"] == "pending"

    def test_met_clears_an_ec_hold(self, tmp_path: Path) -> None:
        init_state(_plan("unmet"), tmp_path)
        with pytest.raises(ValueError):
            planning(tmp_path)
        _sync(tmp_path, "EC-1", "met")
        result = planning(tmp_path)
        wave = result["waves"]["wave-1"]
        assert wave["status"] == "in_progress"
        assert "held_by" not in wave

    def test_clean_preflight_returns_ec_hold_to_pending(self, tmp_path: Path) -> None:
        init_state(_plan("unmet"), tmp_path)
        with pytest.raises(ValueError):
            preflight(tmp_path)
        _sync(tmp_path, "EC-1", "met")
        preflight(tmp_path)
        assert _wave(tmp_path)["status"] == "pending"

    def test_clean_gate_keeps_a_promotion_hold(self, tmp_path: Path) -> None:
        """A hold_wave() hold is not the EC gate's to clear."""
        init_state(_plan("met"), tmp_path)
        hold_wave("wave-1", tmp_path, detail="gate HOLD: ci")
        preflight(tmp_path)
        assert _wave(tmp_path)["status"] == "held"
        assert _wave(tmp_path)["hold_detail"] == "gate HOLD: ci"


class TestReclosed:
    def test_reclosed_holds_again(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        planning(tmp_path)
        assert _wave(tmp_path)["status"] == "in_progress"
        _sync(tmp_path, "EC-1", "reclosed")
        with pytest.raises(ValueError, match="EC-1 is reclosed"):
            store_flight_plan([{"issues": [1], "status": "pending"}], tmp_path)
        assert _wave(tmp_path)["status"] == "held"
        assert _wave(tmp_path)["held_by"][0]["status"] == "reclosed"

    def test_mid_run_hold_clears_back_to_in_progress(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        planning(tmp_path)
        _sync(tmp_path, "EC-1", "reclosed")
        with pytest.raises(ValueError):
            store_flight_plan([{"issues": [1], "status": "pending"}], tmp_path)
        assert _wave(tmp_path)["ec_held_from"] == "in_progress"
        _sync(tmp_path, "EC-1", "met")
        store_flight_plan([{"issues": [1], "status": "pending"}], tmp_path)
        wave = _wave(tmp_path)
        assert wave["status"] == "in_progress"
        assert "ec_held_from" not in wave

    def test_rehold_keeps_the_first_prior_status(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        planning(tmp_path)
        _sync(tmp_path, "EC-1", "unmet")
        for _ in range(2):
            with pytest.raises(ValueError):
                preflight(tmp_path)
        assert _wave(tmp_path)["ec_held_from"] == "in_progress"

    def test_cached_met_in_state_is_never_read(self, tmp_path: Path) -> None:
        """Planting a met in state.json does not open the gate; the plan decides."""
        init_state(_plan("unmet"), tmp_path)
        state_path = status_dir(tmp_path) / "state.json"
        state = load_json(state_path)
        state["entry_conditions"] = {"EC-1": {"status": "met"}}
        state["waves"]["wave-1"]["held_by"] = []
        save_json(state_path, state)
        with pytest.raises(ValueError, match="EC-1 is unmet"):
            preflight(tmp_path)


# ---------------------------------------------------------------------------
# complete
# ---------------------------------------------------------------------------


class TestComplete:
    def test_held_wave_never_completes(self, tmp_path: Path) -> None:
        init_state(_plan("unmet"), tmp_path)
        with pytest.raises(ValueError):
            preflight(tmp_path)
        with pytest.raises(ValueError, match="held from completion"):
            complete(tmp_path, wave_id="wave-1")
        state = load_json(status_dir(tmp_path) / "state.json")
        assert state["waves"]["wave-1"]["status"] == "held"
        assert state["current_wave"] == "wave-1"

    def test_refusals_say_post_the_line_as_plain_text(self, tmp_path: Path) -> None:
        """Both holds say how to post the line so sdlc's parser counts it: no code span."""
        init_state(_plan("unmet"), tmp_path)
        messages = []
        for step in (lambda: preflight(tmp_path), lambda: complete(tmp_path, wave_id="wave-1")):
            with pytest.raises(ValueError) as exc:
                step()
            messages.append(str(exc.value))
        for msg in messages:
            assert msg.endswith(EC_RECORD_HINT)
            assert "alone in its own comment" in msg
            assert "no backticks" in msg
            assert "`" not in EC_RECORD_HINT

    def test_met_wave_completes(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        planning(tmp_path)
        result = complete(tmp_path, wave_id="wave-1")
        assert result["waves"]["wave-1"]["status"] == "completed"
        assert result["current_wave"] == "wave-2"

    def test_reclosed_after_start_blocks_complete(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        planning(tmp_path)
        _sync(tmp_path, "EC-1", "reclosed")
        with pytest.raises(ValueError, match="EC-1 is reclosed"):
            complete(tmp_path)
        assert _wave(tmp_path)["status"] == "held"

    def test_delivery_ec_allows_start_and_holds_close(self, tmp_path: Path) -> None:
        init_state(_plan("unmet", gates="delivery"), tmp_path)
        preflight(tmp_path)
        planning(tmp_path)
        store_flight_plan([{"issues": [1, 2], "status": "pending"}], tmp_path)
        assert _wave(tmp_path)["status"] == "in_progress"
        assert _wave(tmp_path)["delivery_held_by"][0]["ec"] == "EC-1"
        with pytest.raises(ValueError, match=r"EC-1 is unmet \(delivery\) for #1"):
            complete(tmp_path)
        assert _wave(tmp_path)["status"] == "in_progress"

    def test_recomplete_after_reclose_stays_completed(self, tmp_path: Path) -> None:
        """complete is idempotent on a completed wave, even after an EC recloses."""
        init_state(_plan("met"), tmp_path)
        planning(tmp_path)
        complete(tmp_path, wave_id="wave-1")
        _sync(tmp_path, "EC-1", "reclosed")
        result = complete(tmp_path, wave_id="wave-1")
        wave = result["waves"]["wave-1"]
        assert wave["status"] == "completed"
        assert not ({"held_by", "delivery_held_by", "ec_held_from"} & wave.keys())

    def test_delivery_ec_met_completes(self, tmp_path: Path) -> None:
        init_state(_plan("unmet", gates="delivery"), tmp_path)
        planning(tmp_path)
        _sync(tmp_path, "EC-1", "met")
        result = complete(tmp_path)
        assert result["waves"]["wave-1"]["status"] == "completed"
        assert "delivery_held_by" not in result["waves"]["wave-1"]


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------


class TestShow:
    def test_show_lists_ecs_and_holds(self, tmp_path: Path) -> None:
        plan = _plan("unmet")
        plan["entry_conditions"]["EC-2"] = {"status": "met", "gates": "delivery"}
        init_state(plan, tmp_path)
        summary = show(tmp_path)
        assert summary["wave_held"] is True
        assert summary["entry_conditions"] == [
            {"ec": "EC-1", "status": "unmet", "gates": "start",
             "holds": [{"wave": "wave-1", "issues": [1]}]},
            {"ec": "EC-2", "status": "met", "gates": "delivery", "holds": []},
        ]

    def test_show_skips_completed_waves(self) -> None:
        plan = _plan("unmet")
        state = {"waves": {"wave-1": {"status": "completed"}}}
        assert ec_summary(plan, state)["entry_conditions"][0]["holds"] == []

    def test_cli_renders_ec_block(self, temp_git_repo: Path, run_cli) -> None:
        (temp_git_repo / "plan.json").write_text(json.dumps(_plan("unmet", depends_on=["p#9"])))
        assert run_cli(["init", "plan.json"], temp_git_repo)[0] == 0
        rc, out, err = run_cli(["preflight"], temp_git_repo)
        assert rc == 1
        assert "EC-1 is unmet (start) for #1" in err
        rc, out, _ = run_cli(["show"], temp_git_repo)
        assert rc == 0
        assert "HELD (entry conditions)" in out
        assert "Entry conditions:\n  EC-1: unmet (start)\n    holds wave-1: #1" in out
        assert "depends_on p#9 (cross_plan_unresolved): holds wave-1: #1" in out

    def test_cli_flight_plan_exits_nonzero(self, temp_git_repo: Path, run_cli) -> None:
        (temp_git_repo / "plan.json").write_text(json.dumps(_plan("unmet")))
        (temp_git_repo / "flights.json").write_text(json.dumps([{"issues": [1], "status": "pending"}]))
        assert run_cli(["init", "plan.json"], temp_git_repo)[0] == 0
        rc, _, err = run_cli(["flight-plan", "flights.json"], temp_git_repo)
        assert rc == 1
        assert "Refusing flight-plan" in err

    def test_cli_refusal_regenerates_the_dashboard(self, temp_git_repo: Path, run_cli) -> None:
        (temp_git_repo / "plan.json").write_text(json.dumps(_plan("unmet")))
        assert run_cli(["init", "plan.json"], temp_git_repo)[0] == 0
        dash = status_dir(temp_git_repo) / "dashboard.html"
        dash.unlink(missing_ok=True)
        rc, _, _ = run_cli(["preflight"], temp_git_repo)
        assert rc == 1
        assert dash.exists(), "a refusal still regenerates the dashboard"

    def test_cli_met_control(self, temp_git_repo: Path, run_cli) -> None:
        (temp_git_repo / "plan.json").write_text(json.dumps(_plan("met")))
        assert run_cli(["init", "plan.json"], temp_git_repo)[0] == 0
        assert run_cli(["preflight"], temp_git_repo)[0] == 0
        rc, out, _ = run_cli(["show"], temp_git_repo)
        assert "HELD" not in out
        assert "Entry conditions:\n  EC-1: met (start)" in out


# ---------------------------------------------------------------------------
# Plans without ECs are unchanged
# ---------------------------------------------------------------------------

_LEGACY = {
    "project": "legacy",
    "phases": [
        {
            "name": "P1",
            "waves": [
                {"id": "wave-1", "issues": [{"number": 1, "title": "One", "depends_on": []}]},
                {"id": "wave-2", "issues": [{"number": 2, "title": "Two", "depends_on": [1, "#1", "org/r#1"]}]},
            ],
        }
    ],
}

_EC_KEYS = {"held_by", "held_by_depends_on", "delivery_held_by"}


class TestLegacy:
    def test_lifecycle_adds_no_keys(self, tmp_path: Path) -> None:
        init_state(copy.deepcopy(_LEGACY), tmp_path)
        before = load_json(status_dir(tmp_path) / "phases-waves.json")
        preflight(tmp_path)
        planning(tmp_path)
        store_flight_plan([{"issues": [1], "status": "pending"}], tmp_path)
        complete(tmp_path)
        planning(tmp_path)
        complete(tmp_path)
        state = load_json(status_dir(tmp_path) / "state.json")
        assert "entry_conditions" not in state
        for wave in state["waves"].values():
            assert wave["status"] == "completed"
            assert not (_EC_KEYS & wave.keys())
        assert load_json(status_dir(tmp_path) / "phases-waves.json") == before

    def test_show_has_no_ec_section(self, temp_git_repo: Path, run_cli) -> None:
        (temp_git_repo / "plan.json").write_text(json.dumps(_LEGACY))
        assert run_cli(["init", "plan.json"], temp_git_repo)[0] == 0
        rc, out, _ = run_cli(["show"], temp_git_repo)
        assert rc == 0
        assert "Entry conditions" not in out
        assert "HELD" not in out

    def test_promotion_hold_still_completes(self, tmp_path: Path) -> None:
        init_state(copy.deepcopy(_LEGACY), tmp_path)
        planning(tmp_path)
        hold_wave("wave-1", tmp_path, detail="gate HOLD: ci")
        assert complete(tmp_path, wave_id="wave-1")["waves"]["wave-1"]["status"] == "completed"


class TestExtend:
    def test_extend_merges_ec_declarations(self, tmp_path: Path) -> None:
        init_state(_plan("met"), tmp_path)
        ext = {
            "entry_conditions": {"EC-1": {"status": "unmet"}, "EC-3": {"status": "unmet"}},
            "phases": [{"name": "P2", "waves": [{"id": "wave-9", "issues": [{"number": 9, "ec": ["EC-3"]}]}]}],
        }
        extend_state(ext, tmp_path)
        ecs = load_json(status_dir(tmp_path) / "phases-waves.json")["entry_conditions"]
        assert ecs["EC-1"]["status"] == "met", "an EC already declared keeps its synced state"
        assert ecs["EC-3"]["status"] == "unmet"

    def test_extend_without_ecs_adds_no_key(self, tmp_path: Path) -> None:
        init_state(copy.deepcopy(_LEGACY), tmp_path)
        extend_state({"phases": [{"name": "P2", "waves": [{"id": "wave-9", "issues": [{"number": 9}]}]}]},
                     tmp_path)
        assert "entry_conditions" not in load_json(status_dir(tmp_path) / "phases-waves.json")
