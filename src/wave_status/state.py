"""State machine, JSON I/O, atomic writes, and path helpers.

All business logic for the wave execution lifecycle.  No presentation,
no CLI, no HTML.  Functions operate on Python dicts (loaded JSON) and
use load_json / save_json for persistence.

Requires Python 3.10+ stdlib only — no external dependencies [CT-01].
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_project_root() -> Path:
    """Discover the git repository root from the current working directory.

    Raises ``ValueError`` when not inside a git repository [R-31, R-34].
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(result.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise ValueError(
            "Error: not inside a git repository. "
            "Run this command from within a git repo."
        )


def status_dir(root: Path) -> Path:
    """Return the path to ``<root>/.claude/status/``."""
    return root / ".claude" / "status"


def html_path(root: Path) -> Path:
    """Return the path to the generated HTML dashboard."""
    return root / ".status-panel.html"


def ensure_status_dir(root: Path) -> Path:
    """Create ``.claude/status/`` if absent [R-35] and return its path."""
    d = status_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Atomic JSON I/O [R-33]
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    """Read and parse a JSON file, returning a dict."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict) -> None:
    """Atomically write *data* as JSON to *path*.

    Writes to a ``tempfile.NamedTemporaryFile`` in the **same directory**
    as *path* (guaranteeing same-filesystem rename), then calls
    ``os.replace()`` for an atomic swap [R-33].
    """
    parent = path.parent
    parent.mkdir(parents=True, exist_ok=True)
    fd = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(parent),
        suffix=".tmp",
        delete=False,
    )
    try:
        json.dump(data, fd, indent=2)
        fd.write("\n")
        fd.flush()
        os.fsync(fd.fileno())
        fd.close()
        os.replace(fd.name, str(path))
    except BaseException:
        fd.close()
        # Best-effort cleanup of the temp file on failure.
        try:
            os.unlink(fd.name)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return an ISO-8601 UTC timestamp string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _all_wave_ids(plan_data: dict) -> list[str]:
    """Return an ordered list of wave IDs from the plan."""
    ids: list[str] = []
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            ids.append(wave["id"])
    return ids


def _all_issue_numbers(plan_data: dict) -> set[int]:
    """Return a set of every issue number in the plan."""
    nums: set[int] = set()
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                nums.add(issue["number"])
    return nums


def _find_next_pending_wave(state_data: dict, wave_ids: list[str]) -> str | None:
    """Return the ID of the next pending wave after current, or None."""
    current = state_data.get("current_wave")
    waves_state = state_data.get("waves", {})

    # Find the index of the current wave.
    try:
        idx = wave_ids.index(current)
    except ValueError:
        idx = -1

    # Look for the next wave that is still pending.
    for wid in wave_ids[idx + 1:]:
        if waves_state.get(wid, {}).get("status") == "pending":
            return wid
    return None


# ---------------------------------------------------------------------------
# State-machine operations
# ---------------------------------------------------------------------------

def init_state(plan_data: dict, root: Path, *, force: bool = False) -> None:
    """Validate *plan_data*, write ``phases-waves.json``, ``state.json``,
    and ``flights.json`` under ``<root>/.claude/status/`` [R-02].

    *plan_data* must contain ``project`` (str) and ``phases`` (list).
    Raises ``ValueError`` on validation failure [R-32].

    If a plan already exists, raises ``ValueError`` unless *force* is True.
    Use ``extend_state()`` to add phases to an existing plan.
    """
    # --- validation ---
    if "project" not in plan_data:
        raise ValueError(
            "Error: plan is missing required field 'project'. "
            "Provide a plan JSON with 'project' and 'phases' keys."
        )
    if "phases" not in plan_data or not isinstance(plan_data["phases"], list):
        raise ValueError(
            "Error: plan is missing required field 'phases'. "
            "Provide a plan JSON with 'project' and 'phases' keys."
        )

    d = ensure_status_dir(root)

    # --- overwrite guard ---
    phases_path = d / "phases-waves.json"
    if phases_path.exists() and not force:
        raise ValueError(
            "Error: plan already initialized. Use 'init --extend' to add "
            "phases, or 'init --force' to overwrite the existing plan."
        )

    # --- phases-waves.json (structure, written once) ---
    save_json(phases_path, plan_data)

    # --- state.json (dynamic runtime state) ---
    wave_ids = _all_wave_ids(plan_data)
    waves_state: dict[str, dict] = {}
    for wid in wave_ids:
        waves_state[wid] = {"status": "pending", "mr_urls": {}}

    issues_state: dict[str, dict] = {}
    for phase in plan_data["phases"]:
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                issues_state[str(issue["number"])] = {"status": "open"}

    first_wave = wave_ids[0] if wave_ids else None

    state_data: dict = {
        "current_wave": first_wave,
        "current_action": {"action": "idle", "label": "idle", "detail": ""},
        "waves": waves_state,
        "issues": issues_state,
        "deferrals": [],
        "last_updated": _now_iso(),
    }
    save_json(d / "state.json", state_data)

    # --- flights.json (empty initially) ---
    save_json(d / "flights.json", {"flights": {}})


def extend_state(plan_data: dict, root: Path) -> None:
    """Append new phases from *plan_data* to an existing plan.

    Merges into ``phases-waves.json`` and ``state.json`` without disturbing
    existing phase/wave/issue state.  Raises ``ValueError`` if no existing
    plan is found or if wave IDs collide.
    """
    if "phases" not in plan_data or not isinstance(plan_data["phases"], list):
        raise ValueError(
            "Error: plan is missing required field 'phases'. "
            "Provide a plan JSON with 'project' and 'phases' keys."
        )

    d = status_dir(root)
    phases_path = d / "phases-waves.json"
    state_path = d / "state.json"

    if not phases_path.exists() or not state_path.exists():
        raise ValueError(
            "Error: no existing plan found (or state files incomplete). "
            "Use 'init' first, then 'init --extend' to add phases."
        )

    existing_plan = load_json(phases_path)
    existing_state = load_json(state_path)

    # Check for wave ID collisions
    existing_wave_ids = set(_all_wave_ids(existing_plan))
    new_wave_ids = set(_all_wave_ids(plan_data))
    wave_collisions = existing_wave_ids & new_wave_ids
    if wave_collisions:
        raise ValueError(
            f"Error: wave ID collision — {wave_collisions} already exist in the plan. "
            "Use unique wave IDs for new phases."
        )

    # Check for issue number collisions
    existing_issue_nums = _all_issue_numbers(existing_plan)
    new_issue_nums = _all_issue_numbers(plan_data)
    issue_collisions = existing_issue_nums & new_issue_nums
    if issue_collisions:
        raise ValueError(
            f"Error: issue number collision — {issue_collisions} already exist in the plan. "
            "Each issue should belong to exactly one phase."
        )

    # Merge phases into plan
    existing_plan["phases"].extend(plan_data["phases"])
    save_json(phases_path, existing_plan)

    # Add new waves and issues to state (preserve existing)
    for wid in _all_wave_ids(plan_data):
        if wid not in existing_state["waves"]:
            existing_state["waves"][wid] = {"status": "pending", "mr_urls": {}}

    for phase in plan_data["phases"]:
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                issue_key = str(issue["number"])
                if issue_key not in existing_state["issues"]:
                    existing_state["issues"][issue_key] = {"status": "open"}

    existing_state["last_updated"] = _now_iso()
    save_json(state_path, existing_state)


def store_flight_plan(flights_data: list, root: Path) -> None:
    """Store *flights_data* keyed by the current wave ID in ``flights.json`` [R-04].

    *flights_data* should be a list of flight dicts
    (e.g. ``[{"issues": [13, 1], "status": "pending"}, ...]``).
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    current_wave = state_data.get("current_wave")
    if current_wave is None:
        raise ValueError(
            "Error: no current wave is set. "
            "Run 'init' before storing a flight plan."
        )

    flights = load_json(d / "flights.json")
    flights["flights"][current_wave] = flights_data
    save_json(d / "flights.json", flights)


def _set_action(root: Path, action: str, label: str, detail: str = "") -> dict:
    """Update ``current_action`` in state.json and return the state dict."""
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    state_data["current_action"] = {
        "action": action,
        "label": label,
        "detail": detail,
    }
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def preflight(root: Path) -> dict:
    """Set current_action to ``pre-flight`` [R-05]."""
    return _set_action(root, "pre-flight", "pre-flight")


def planning(root: Path) -> dict:
    """Set current_action to ``planning`` and current wave to ``in_progress`` [R-05]."""
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    current_wave = state_data.get("current_wave")

    state_data["current_action"] = {
        "action": "planning",
        "label": "planning",
        "detail": current_wave or "",
    }

    # Also set the current wave to in_progress.
    if current_wave and current_wave in state_data.get("waves", {}):
        state_data["waves"][current_wave]["status"] = "in_progress"

    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def review(root: Path) -> dict:
    """Set current_action to ``post-wave-review`` [R-05]."""
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    current_wave = state_data.get("current_wave")
    return _set_action(root, "post-wave-review", "post-wave-review", current_wave or "")


def waiting(root: Path, msg: str = "") -> dict:
    """Set current_action to ``waiting-on-meatbag`` [R-05]."""
    return _set_action(root, "waiting-on-meatbag", "waiting-on-meatbag", msg)


def flight(n: int, root: Path) -> dict:
    """Set flight *n* to ``running`` in ``flights.json`` [R-11].

    **Strict**: for N > 1, flight N-1 must be ``completed``.
    Also sets ``current_action`` to ``in-flight``.
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    current_wave = state_data.get("current_wave")
    if current_wave is None:
        raise ValueError(
            "Error: no current wave is set. "
            "Run 'init' and 'planning' before starting a flight."
        )

    flights = load_json(d / "flights.json")
    wave_flights = flights.get("flights", {}).get(current_wave, [])

    if n < 1 or n > len(wave_flights):
        raise ValueError(
            f"Error: flight {n} does not exist for wave '{current_wave}'. "
            f"Valid flight numbers are 1 to {len(wave_flights)}."
        )

    idx = n - 1  # 0-based

    # Strict ordering: N > 1 requires N-1 completed [R-11].
    if n > 1:
        prev_status = wave_flights[idx - 1].get("status", "pending")
        if prev_status != "completed":
            raise ValueError(
                f"Error: flight {n - 1} is '{prev_status}', not 'completed'. "
                f"Complete flight {n - 1} before starting flight {n}."
            )

    wave_flights[idx]["status"] = "running"
    flights["flights"][current_wave] = wave_flights
    save_json(d / "flights.json", flights)

    # Build issue list for the flight.
    issue_nums = wave_flights[idx].get("issues", [])
    issue_str = ", ".join(f"#{num}" for num in issue_nums)
    detail = f"{current_wave} — issues: {issue_str}" if issue_str else current_wave

    state_data["current_action"] = {
        "action": "in-flight",
        "label": f"flight {n}",
        "detail": detail,
    }
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def flight_done(n: int, root: Path) -> dict:
    """Set flight *n* to ``completed`` [R-12].

    **Strict**: flight N must be ``running``.
    Also sets ``current_action`` to ``merging``.
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    current_wave = state_data.get("current_wave")
    if current_wave is None:
        raise ValueError(
            "Error: no current wave is set. "
            "Run 'init' and 'planning' before completing a flight."
        )

    flights = load_json(d / "flights.json")
    wave_flights = flights.get("flights", {}).get(current_wave, [])

    if n < 1 or n > len(wave_flights):
        raise ValueError(
            f"Error: flight {n} does not exist for wave '{current_wave}'. "
            f"Valid flight numbers are 1 to {len(wave_flights)}."
        )

    idx = n - 1
    current_status = wave_flights[idx].get("status", "pending")
    if current_status != "running":
        raise ValueError(
            f"Error: flight {n} is '{current_status}', not 'running'. "
            f"Start flight {n} before marking it done."
        )

    wave_flights[idx]["status"] = "completed"
    flights["flights"][current_wave] = wave_flights
    save_json(d / "flights.json", flights)

    state_data["current_action"] = {
        "action": "merging",
        "label": "merging",
        "detail": current_wave,
    }
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def complete(root: Path) -> dict:
    """Set current wave to ``completed`` and advance ``current_wave`` to the
    next pending wave (or ``None`` if all done) [R-13].

    Also sets ``current_action`` to ``idle``.
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    plan_data = load_json(d / "phases-waves.json")
    current_wave = state_data.get("current_wave")

    if current_wave is None:
        raise ValueError(
            "Error: no current wave is set. "
            "Run 'init' and 'planning' before completing a wave."
        )

    # Mark current wave as completed.
    if current_wave in state_data.get("waves", {}):
        state_data["waves"][current_wave]["status"] = "completed"

    # Advance to the next pending wave.
    wave_ids = _all_wave_ids(plan_data)
    next_wave = _find_next_pending_wave(state_data, wave_ids)
    state_data["current_wave"] = next_wave

    state_data["current_action"] = {
        "action": "idle",
        "label": "idle",
        "detail": "",
    }
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def close_issue(n: int, root: Path) -> dict:
    """Set issue *n* to ``closed`` in ``state.json`` [R-07, R-14].

    Raises ``ValueError`` if the issue does not exist in the plan.
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    plan_data = load_json(d / "phases-waves.json")

    valid_issues = _all_issue_numbers(plan_data)
    if n not in valid_issues:
        raise ValueError(
            f"Error: issue #{n} does not exist in the plan. "
            f"Check the issue number and try again."
        )

    issue_key = str(n)
    if issue_key not in state_data.get("issues", {}):
        state_data.setdefault("issues", {})[issue_key] = {}

    state_data["issues"][issue_key]["status"] = "closed"
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def record_mr(issue: int, mr: str, root: Path) -> dict:
    """Record an MR/PR reference for *issue* in the current wave's
    ``mr_urls`` [R-08].
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    current_wave = state_data.get("current_wave")
    if current_wave is None:
        raise ValueError(
            "Error: no current wave is set. "
            "Run 'init' before recording an MR."
        )

    waves = state_data.get("waves", {})
    if current_wave not in waves:
        raise ValueError(
            f"Error: wave '{current_wave}' not found in state. "
            "Run 'init' before recording an MR."
        )

    waves[current_wave].setdefault("mr_urls", {})[str(issue)] = mr
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def show(root: Path) -> dict:
    """Return a summary dict describing the current state [R-06].

    **Read-only** — no files are modified, no dashboard is regenerated.
    """
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    plan_data = load_json(d / "phases-waves.json")
    flights_data = load_json(d / "flights.json")

    # Determine current phase info.
    wave_ids = _all_wave_ids(plan_data)
    current_wave = state_data.get("current_wave")

    current_phase_name = ""
    current_phase_idx = 0
    total_phases = len(plan_data.get("phases", []))
    wave_in_phase = 0
    waves_in_current_phase = 0

    for pi, phase in enumerate(plan_data.get("phases", [])):
        phase_wave_ids = [w["id"] for w in phase.get("waves", [])]
        if current_wave in phase_wave_ids:
            current_phase_name = phase.get("name", "")
            current_phase_idx = pi + 1
            waves_in_current_phase = len(phase_wave_ids)
            wave_in_phase = phase_wave_ids.index(current_wave) + 1
            break

    # Flight info.
    wave_flights = flights_data.get("flights", {}).get(current_wave or "", [])
    total_flights = len(wave_flights)
    running_flight = None
    for fi, fl in enumerate(wave_flights):
        if fl.get("status") == "running":
            running_flight = fi + 1
            break

    # Issue counts.
    total_issues = 0
    closed_issues = 0
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                total_issues += 1
                istate = state_data.get("issues", {}).get(
                    str(issue["number"]), {}
                )
                if istate.get("status") == "closed":
                    closed_issues += 1
    pct = round(100 * closed_issues / total_issues) if total_issues else 0

    # Deferrals.
    deferrals = state_data.get("deferrals", [])
    pending_count = sum(1 for d in deferrals if d.get("status") == "pending")
    accepted_count = sum(1 for d in deferrals if d.get("status") == "accepted")

    # Action.
    action_obj = state_data.get("current_action", {})
    action_str = action_obj.get("action", "idle")
    detail = action_obj.get("detail", "")
    action_display = f"{action_str} — {detail}" if detail else action_str

    flight_display: str
    if total_flights == 0:
        flight_display = "\u2014"  # em dash
    elif running_flight is not None:
        flight_display = f"{running_flight}/{total_flights}"
    else:
        flight_display = f"\u2014/{total_flights}"

    return {
        "project": plan_data.get("project", "unknown"),
        "phase": f"{current_phase_idx}/{total_phases}",
        "phase_name": current_phase_name,
        "wave": f"{wave_in_phase}/{waves_in_current_phase} in phase {current_phase_idx}",
        "flight": flight_display,
        "action": action_display,
        "progress": f"{closed_issues}/{total_issues} issues ({pct}%)",
        "deferrals": f"{pending_count} pending, {accepted_count} accepted",
    }
