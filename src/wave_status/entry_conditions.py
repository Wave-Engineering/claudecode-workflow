"""Entry-condition (EC) gate for a wave [#1393].

The Python half of Wave-Engineering/mcp-server-sdlc#613. ``wave_ec_sync``
writes each declared EC's latest state into ``phases-waves.json``::

    "entry_conditions": {"EC-1": {"status": "met", "gates": "start", ...}}

and each story names the ECs it needs in its own ``ec`` list. This module
evaluates one wave against that file, by the same rule as the TypeScript
``evaluateWaveGate`` in ``lib/entry-conditions.ts``:

- A wave is held if ANY of its stories names a ``start`` EC that is not ``met``,
  or carries a qualified cross-plan ``depends_on`` ref (``<plan>#<n>``).
- A ``delivery`` EC that is not ``met`` lets the wave start and holds only its
  completion.

FAIL CLOSED. Anything that cannot prove an EC ``met`` reads as not met: a
missing or invalid ``status`` (read as ``unmet``), an EC a story names that the
plan never declares (``undeclared``, gated as ``start``), an ``ec`` or
``depends_on`` field of the wrong shape (``malformed``), and every cross-plan
ref (no cross-plan lookup exists yet, and an unresolved ref must never read as
satisfied).

Pure: no file I/O. The caller reads ``phases-waves.json`` fresh on every call,
so a ``met`` is never remembered — an EC that goes ``met`` → ``reclosed``
holds again on the next read.
"""

from __future__ import annotations

import json
import re

EC_STATUSES: tuple[str, ...] = ("met", "unmet", "reclosed")

#: The ``ec`` id on a hold raised by a story whose ``ec`` field has the wrong
#: shape. There is no EC name to report. Matches ``MALFORMED_EC`` in
#: mcp-server-sdlc's ``lib/entry-conditions.ts``.
MALFORMED_EC = "(malformed ec)"

# ``<plan-id>#<issue>``: a non-empty prefix with no ``/``. The two shapes
# ``depends_on`` already carries, ``#N`` (empty prefix) and ``owner/repo#N``
# (a slash), never match.
_CROSS_PLAN_REF = re.compile(r"^([^/#\s]+)#(\d+)$")


def is_cross_plan_ref(ref: object) -> bool:
    """Return True when *ref* is a qualified cross-plan ``<plan>#<n>`` ref."""
    return isinstance(ref, str) and bool(_CROSS_PLAN_REF.match(ref.strip()))


def has_entry_conditions(plan_data: dict) -> bool:
    """Return True when the plan declares any entry condition."""
    return bool(plan_data.get("entry_conditions"))


def wave_issues(plan_data: dict, wave_id: str) -> list[dict] | None:
    """Return the issue list of *wave_id*, or None if the plan has no such wave."""
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            if wave.get("id") == wave_id:
                return list(wave.get("issues", []))
    return None


def _ec_status(cond: object) -> str:
    """The stored status of a declared EC; missing or invalid reads ``unmet``."""
    status = cond.get("status") if isinstance(cond, dict) else None
    return status if status in EC_STATUSES else "unmet"


def _ec_gates(cond: object) -> str:
    """The declared gate; absent or unknown is ``start``, the stricter gate."""
    gates = cond.get("gates") if isinstance(cond, dict) else None
    return "delivery" if gates == "delivery" else "start"


def _ec_ids(raw: object) -> tuple[list[str], bool]:
    """Split an ``ec`` field into its valid ids and a malformed flag.

    Absent, null and ``[]`` name no EC. Anything else that is not an array of
    non-empty strings is malformed: EC ids are always strings, and dropping a
    bad entry would drop the gate it was meant to set.
    """
    if raw is None:
        return [], False
    if not isinstance(raw, list):
        return [], True
    ids = [e for e in raw if isinstance(e, str) and e]
    return ids, len(ids) != len(raw)


def _js_json(value: object) -> str:
    """``JSON.stringify(value)``, so a malformed ref reads the same as sdlc's."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _dep_holds(raw: object, n: object) -> list[dict]:
    """The ``depends_on`` holds one story raises.

    An entry is an issue number (int) or a non-empty ref string; legacy plans
    carry bare ints (``[99]``), so an int never holds. A qualified cross-plan
    ref holds as ``cross_plan_unresolved``. A non-array value, or an entry of
    any other type, holds as ``malformed``.
    """
    if raw is None:
        return []
    if not isinstance(raw, list):
        return [{"ref": _js_json(raw), "issue": n, "reason": "malformed"}]
    holds = []
    for d in raw:
        if isinstance(d, int) and not isinstance(d, bool):
            continue
        if not (isinstance(d, str) and d.strip()):
            holds.append({"ref": _js_json(d), "issue": n, "reason": "malformed"})
        elif is_cross_plan_ref(d):
            holds.append({"ref": d.strip(), "issue": n, "reason": "cross_plan_unresolved"})
    return holds


def evaluate_wave_gate(entry_conditions: dict | None, issues: list[dict]) -> dict:
    """Evaluate the EC gate for one wave's *issues*.

    Returns ``{start, delivery, depends_on, held}``: ``start`` and
    ``delivery`` are lists of ``{ec, status, gates, issues}`` (sorted by EC
    id), ``depends_on`` is a list of ``{ref, issue, reason}``, and ``held`` is
    True when the wave must not start.
    """
    ecs = entry_conditions if isinstance(entry_conditions, dict) else {}
    start: dict[str, dict] = {}
    delivery: dict[str, dict] = {}
    deps: list[dict] = []

    def _add(bucket: dict[str, dict], ec: str, status: str, gates: str, n: object) -> None:
        hold = bucket.setdefault(ec, {"ec": ec, "status": status, "gates": gates, "issues": []})
        if n not in hold["issues"]:
            hold["issues"].append(n)

    for issue in issues:
        n = issue.get("number")
        ids, bad_ec = _ec_ids(issue.get("ec"))
        if bad_ec:
            _add(start, MALFORMED_EC, "malformed", "start", n)
        for ec in ids:
            if ec not in ecs:
                _add(start, ec, "undeclared", "start", n)
                continue
            status = _ec_status(ecs[ec])
            if status == "met":
                continue
            gates = _ec_gates(ecs[ec])
            _add(delivery if gates == "delivery" else start, ec, status, gates, n)
        deps.extend(_dep_holds(issue.get("depends_on"), n))

    def _sorted(bucket: dict[str, dict]) -> list[dict]:
        def key(ec: str) -> tuple:
            m = re.match(r"^EC-(\d+)$", ec)
            return (0, int(m.group(1)), ec) if m else (1, 0, ec)
        return [bucket[k] for k in sorted(bucket, key=key)]

    start_holds = _sorted(start)
    return {
        "start": start_holds,
        "delivery": _sorted(delivery),
        "depends_on": deps,
        "held": bool(start_holds or deps),
    }


def _issue_list(issues: list) -> str:
    return ", ".join(f"#{n}" for n in issues)


def describe_holds(wave_id: str, holds: list[dict], deps: list[dict], *, verb: str = "held") -> str:
    """One line naming every hold, for a refusal's error message."""
    parts = [
        f"{h['ec']} is {h['status']} ({h['gates']}) for {_issue_list(h['issues'])}"
        for h in holds
    ]
    parts += [
        f"#{d['issue']} depends on {d['ref']}, a cross-plan ref that cannot be resolved yet"
        if d["reason"] == "cross_plan_unresolved"
        else f"#{d['issue']} has a malformed depends_on entry {d['ref']}"
        for d in deps
    ]
    return f"wave {wave_id} is {verb}: {'; '.join(parts)}"


def ec_summary(plan_data: dict, state_data: dict) -> dict:
    """Every EC and ``depends_on`` hold across the plan, read fresh.

    Returns ``{entry_conditions, depends_on}``. ``entry_conditions`` has one
    row per declared or referenced EC, ``{ec, status, gates, holds: [{wave,
    issues}]}``; ``depends_on`` lists each ``{wave, ref, issue, reason}``
    hold. Waves already ``completed`` are skipped. Both lists are empty for a
    plan with no ECs and no cross-plan or malformed refs.
    """
    ecs = plan_data.get("entry_conditions") or {}
    if not isinstance(ecs, dict):
        ecs = {}
    rows: dict[str, dict] = {
        ec: {"ec": ec, "status": _ec_status(c), "gates": _ec_gates(c), "holds": []}
        for ec, c in ecs.items()
    }
    deps: list[dict] = []
    waves_state = state_data.get("waves", {})
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            wid = wave.get("id")
            if waves_state.get(wid, {}).get("status") == "completed":
                continue
            gate = evaluate_wave_gate(ecs, wave.get("issues", []))
            for h in gate["start"] + gate["delivery"]:
                row = rows.setdefault(
                    h["ec"], {"ec": h["ec"], "status": h["status"], "gates": h["gates"], "holds": []}
                )
                row["holds"].append({"wave": wid, "issues": list(h["issues"])})
            deps.extend({"wave": wid, **d} for d in gate["depends_on"])
    return {"entry_conditions": list(rows.values()), "depends_on": deps}
