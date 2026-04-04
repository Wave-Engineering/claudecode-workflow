"""State machine, JSON I/O, atomic writes, and path helpers for campaign lifecycle.

All business logic for the SDLC campaign state machine.  No presentation,
no CLI, no HTML.  Functions operate on Python dicts (loaded JSON) and
use load_json / save_json for persistence.

Requires Python 3.10+ stdlib only -- no external dependencies.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STAGES = ("concept", "prd", "backlog", "implementation", "dod")

# Stages that have a review gate before completion.
STAGES_WITH_REVIEW = ("concept", "prd", "dod")

VALID_STATUSES = ("not_started", "active", "review", "complete")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def get_project_root() -> Path:
    """Discover the git repository root from the current working directory.

    Raises ``ValueError`` when not inside a git repository.
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


def campaign_dir(root: Path) -> Path:
    """Return the path to ``<root>/.sdlc/``."""
    return root / ".sdlc"


def ensure_campaign_dir(root: Path) -> Path:
    """Create ``.sdlc/`` if absent and return its path."""
    d = campaign_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Atomic JSON I/O
# ---------------------------------------------------------------------------

def load_json(path: Path) -> dict:
    """Read and parse a JSON file, returning a dict."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: dict | list) -> None:
    """Atomically write *data* as JSON to *path*.

    Writes to a ``tempfile.NamedTemporaryFile`` in the **same directory**
    as *path* (guaranteeing same-filesystem rename), then calls
    ``os.replace()`` for an atomic swap.
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


def _validate_stage(stage: str) -> None:
    """Raise ``ValueError`` if *stage* is not a valid stage name."""
    if stage not in STAGES:
        raise ValueError(
            f"Error: '{stage}' is not a valid stage. "
            f"Valid stages are: {', '.join(STAGES)}."
        )


def _stage_index(stage: str) -> int:
    """Return the 0-based index of *stage* in the STAGES tuple."""
    return STAGES.index(stage)


def _previous_stage(stage: str) -> str | None:
    """Return the stage before *stage*, or None if it is the first."""
    idx = _stage_index(stage)
    if idx == 0:
        return None
    return STAGES[idx - 1]


# ---------------------------------------------------------------------------
# State-machine operations
# ---------------------------------------------------------------------------

def init_campaign(project_name: str, root: Path) -> dict:
    """Initialize the ``.sdlc/`` directory with campaign definition files.

    Creates:
    - ``campaign.json`` — project metadata and stage definitions
    - ``campaign-state.json`` — current state (all stages not_started)
    - ``campaign-items.json`` — empty items/deferrals list

    Returns the campaign-state dict.
    Raises ``ValueError`` if ``.sdlc/campaign.json`` already exists.
    """
    if not project_name or not project_name.strip():
        raise ValueError(
            "Error: project name must not be empty. "
            "Provide a project name as the first argument."
        )

    d = ensure_campaign_dir(root)

    campaign_path = d / "campaign.json"
    if campaign_path.exists():
        raise ValueError(
            "Error: campaign already initialized. "
            "Remove .sdlc/ to reinitialize."
        )

    # campaign.json — definition
    campaign_data = {
        "project": project_name.strip(),
        "stages": list(STAGES),
        "created": _now_iso(),
    }
    save_json(campaign_path, campaign_data)

    # campaign-state.json — runtime state
    stages_state: dict[str, str] = {}
    for stage in STAGES:
        stages_state[stage] = "not_started"

    state_data = {
        "active_stage": None,
        "stages": stages_state,
        "last_updated": _now_iso(),
    }
    save_json(d / "campaign-state.json", state_data)

    # campaign-items.json — deliverables and deferrals
    items_data: dict = {
        "deferrals": [],
    }
    save_json(d / "campaign-items.json", items_data)

    return state_data


def stage_start(stage: str, root: Path) -> dict:
    """Transition a stage to ``active``.

    Rules:
    - Stage must be valid.
    - Stage must currently be ``not_started``.
    - If this is not the first stage (concept), the previous stage must be
      ``complete``.

    Returns the updated campaign-state dict.
    """
    _validate_stage(stage)
    d = campaign_dir(root)
    state_data = load_json(d / "campaign-state.json")

    current_status = state_data["stages"].get(stage)
    if current_status != "not_started":
        raise ValueError(
            f"Error: stage '{stage}' is '{current_status}', expected 'not_started'. "
            f"Only stages in 'not_started' state can be started."
        )

    prev = _previous_stage(stage)
    if prev is not None:
        prev_status = state_data["stages"].get(prev)
        if prev_status != "complete":
            raise ValueError(
                f"Error: previous stage '{prev}' is '{prev_status}', not 'complete'. "
                f"Complete '{prev}' before starting '{stage}'."
            )

    state_data["stages"][stage] = "active"
    state_data["active_stage"] = stage
    state_data["last_updated"] = _now_iso()
    save_json(d / "campaign-state.json", state_data)
    return state_data


def stage_review(stage: str, root: Path) -> dict:
    """Transition a stage to ``review`` (waiting for human approval).

    Rules:
    - Stage must be valid.
    - Stage must be one of the stages that have a review gate
      (concept, prd, dod).
    - Stage must currently be ``active``.

    Returns the updated campaign-state dict.
    """
    _validate_stage(stage)

    if stage not in STAGES_WITH_REVIEW:
        raise ValueError(
            f"Error: stage '{stage}' does not have a review gate. "
            f"Only {', '.join(STAGES_WITH_REVIEW)} stages support review."
        )

    d = campaign_dir(root)
    state_data = load_json(d / "campaign-state.json")

    current_status = state_data["stages"].get(stage)
    if current_status != "active":
        raise ValueError(
            f"Error: stage '{stage}' is '{current_status}', expected 'active'. "
            f"Only active stages can be moved to review."
        )

    state_data["stages"][stage] = "review"
    if state_data.get("active_stage") == stage:
        state_data["active_stage"] = None
    state_data["last_updated"] = _now_iso()
    save_json(d / "campaign-state.json", state_data)
    return state_data


def stage_complete(stage: str, root: Path) -> dict:
    """Mark a stage as ``complete`` (gate passed).

    Rules:
    - Stage must be valid.
    - For stages with review gates (concept, prd, dod): must be in ``review``.
    - For stages without review gates (backlog, implementation): must be
      ``active``.

    Returns the updated campaign-state dict.
    """
    _validate_stage(stage)
    d = campaign_dir(root)
    state_data = load_json(d / "campaign-state.json")

    current_status = state_data["stages"].get(stage)

    if stage in STAGES_WITH_REVIEW:
        if current_status != "review":
            raise ValueError(
                f"Error: stage '{stage}' is '{current_status}', expected 'review'. "
                f"Move '{stage}' to review before completing it."
            )
    else:
        if current_status != "active":
            raise ValueError(
                f"Error: stage '{stage}' is '{current_status}', expected 'active'. "
                f"Start '{stage}' before completing it."
            )

    state_data["stages"][stage] = "complete"

    # Clear active_stage if this was the active one.
    if state_data.get("active_stage") == stage:
        state_data["active_stage"] = None

    state_data["last_updated"] = _now_iso()
    save_json(d / "campaign-state.json", state_data)
    return state_data


def defer_item(item: str, reason: str, root: Path) -> dict:
    """Defer a deliverable or work item with rationale.

    Appends to the deferrals list in ``campaign-items.json`` with a
    timestamp and the current active stage.

    Returns the updated campaign-items dict.
    """
    if not item or not item.strip():
        raise ValueError(
            "Error: item description must not be empty. "
            "Provide the item name as the first argument."
        )
    if not reason or not reason.strip():
        raise ValueError(
            "Error: reason must not be empty. "
            "Provide a reason with --reason."
        )

    d = campaign_dir(root)
    state_data = load_json(d / "campaign-state.json")
    items_data = load_json(d / "campaign-items.json")

    active_stage = state_data.get("active_stage")

    deferral = {
        "item": item.strip(),
        "reason": reason.strip(),
        "stage": active_stage,
        "timestamp": _now_iso(),
    }
    items_data["deferrals"].append(deferral)
    save_json(d / "campaign-items.json", items_data)
    return items_data


def show_campaign(root: Path) -> dict:
    """Return a summary dict describing the current campaign state.

    **Read-only** -- no files are modified.
    """
    d = campaign_dir(root)
    campaign_data = load_json(d / "campaign.json")
    state_data = load_json(d / "campaign-state.json")
    items_data = load_json(d / "campaign-items.json")

    project = campaign_data.get("project", "unknown")
    active_stage = state_data.get("active_stage")
    stages = state_data.get("stages", {})

    # Build per-stage status list.
    stage_lines: list[str] = []
    for s in STAGES:
        status = stages.get(s, "not_started")
        stage_lines.append(f"  {s}: {status}")

    deferrals = items_data.get("deferrals", [])

    return {
        "project": project,
        "active_stage": active_stage or "none",
        "stages": stages,
        "stage_lines": stage_lines,
        "deferrals_count": len(deferrals),
        "deferrals": deferrals,
    }
