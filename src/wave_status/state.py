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
    """Return the wave status directory path.

    Prefers ``<root>/.sdlc/waves/`` if the ``.sdlc/`` directory exists,
    otherwise falls back to ``<root>/.claude/status/`` for backward
    compatibility.  Uses the same predicate (``.sdlc/`` existence) as
    ``html_path()`` and ``ensure_status_dir()`` so all three functions
    agree on which path family to use.
    """
    sdlc_dir = root / ".sdlc"
    if sdlc_dir.exists():
        return sdlc_dir / "waves"
    return root / ".claude" / "status"


def html_path(root: Path) -> Path:
    """Return the path to the generated HTML dashboard.

    If ``.sdlc/`` exists, writes to ``.sdlc/waves/dashboard.html``,
    otherwise falls back to ``.status-panel.html``.
    """
    sdlc_dir = root / ".sdlc"
    if sdlc_dir.exists():
        return sdlc_dir / "waves" / "dashboard.html"
    return root / ".status-panel.html"


def ensure_status_dir(root: Path) -> Path:
    """Create the wave status directory if absent and return its path.

    If ``.sdlc/`` exists, creates ``.sdlc/waves/``, otherwise creates
    ``.claude/status/`` [R-35].
    """
    sdlc_dir = root / ".sdlc"
    if sdlc_dir.exists():
        d = sdlc_dir / "waves"
    else:
        d = root / ".claude" / "status"
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
# Schema versioning and migration
# ---------------------------------------------------------------------------

CURRENT_SCHEMA_VERSION = 3


def migrate_state(data: dict) -> dict:
    """Migrate *data* to the current schema version in place and return it.

    Detects the schema version:
    - **v0**: has ``completed_waves`` (Phase 1 list-based layout).
      Structural migration: lists to dicts, attach ``mr_urls`` to the
      last completed wave.
    - **v1**: has ``waves`` but no ``schema_version`` (Phase 2 dict-based).
      Stamp only — no structural changes.
    - **v2**: has ``schema_version: 2``.  Bump to v3 stamp only — v3 is a
      lazy-migration schema that adds support for ``{owner}/{repo}#N`` issue
      keys alongside bare ``N`` keys (see ``close_issue``/``record_mr``
      dual-read logic).  No batch rewrite of existing keys — they're
      upgraded opportunistically when next written.
    - **v3**: has ``schema_version: 3``.  No-op.

    Unknown keys (e.g. ``wavemachine_active``) are always preserved.
    """
    version = data.get("schema_version", 0)

    # Forward-compat guard: refuse to operate on state from a newer schema.
    # Silently returning would let the rest of the tool mutate data it doesn't
    # understand, risking corruption. Raise so the user knows to upgrade.
    if version > CURRENT_SCHEMA_VERSION:
        raise ValueError(
            f"Error: state.json has schema_version {version}, "
            f"but this tool only supports up to {CURRENT_SCHEMA_VERSION}. "
            "Upgrade wave-status to read this state file."
        )

    # Already current — no-op.
    if version == CURRENT_SCHEMA_VERSION:
        return data

    # v0 → v2: structural migration from Phase 1 list-based layout.
    if "completed_waves" in data and "waves" not in data:
        completed_waves = data.pop("completed_waves", [])
        completed_issues = data.pop("completed_issues", [])
        merge_requests = data.pop("merge_requests", {})

        waves: dict[str, dict] = {}
        for wid in completed_waves:
            waves[wid] = {"status": "completed", "mr_urls": {}}
        # Attach merge_requests to the last completed wave.
        if completed_waves and merge_requests:
            waves[completed_waves[-1]]["mr_urls"] = merge_requests

        issues: dict[str, dict] = {}
        for n in completed_issues:
            issues[str(n)] = {"status": "closed"}

        data["waves"] = waves
        data["issues"] = issues

    # Stamp the version (covers both v0→v2 and v1→v2).
    data["schema_version"] = CURRENT_SCHEMA_VERSION
    return data


def load_state(path: Path, *, write_back: bool = True) -> dict:
    """Load ``state.json``, auto-migrate, and optionally write back.

    This is the canonical way to read ``state.json``.  Every call site
    that previously used ``load_json(d / "state.json")`` should use this
    instead.
    """
    data = load_json(path)
    before_version = data.get("schema_version", 0)
    data = migrate_state(data)
    if write_back and data.get("schema_version", 0) != before_version:
        save_json(path, data)
    return data


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
    """Return a set of every issue number in the plan.

    Kept for back-compat with callers that only need the bare numeric set.
    For cross-repo collision checks, prefer :func:`_all_issue_refs`.
    """
    nums: set[int] = set()
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                nums.add(issue["number"])
    return nums


def _plan_default_repo(plan_data: dict) -> str | None:
    """Return the plan-level default ``repo`` (``owner/name``) or None."""
    repo = plan_data.get("repo")
    if isinstance(repo, str) and repo:
        return repo
    return None


def _issue_repo(plan_data: dict, issue: dict) -> str | None:
    """Resolve the effective repo for *issue* — per-issue overrides plan-level."""
    per_issue = issue.get("repo")
    if isinstance(per_issue, str) and per_issue:
        return per_issue
    return _plan_default_repo(plan_data)


def _compose_issue_key(n: int | str, repo: str | None) -> str:
    """Compose a state-dict issue key.

    When *repo* is set, returns ``f"{repo}#{n}"``.  Otherwise returns
    ``str(n)`` — bare numeric form, back-compat with pre-v3 state.
    """
    if repo:
        return f"{repo}#{n}"
    return str(n)


def _parse_issue_key(key: str) -> tuple[str | None, int | None]:
    """Parse a state-dict issue key into ``(repo, number)``.

    - ``"13"`` → ``(None, 13)``
    - ``"owner/repo#13"`` → ``("owner/repo", 13)``
    - anything else → ``(None, None)``
    """
    if "#" in key:
        repo_part, _, num_part = key.rpartition("#")
        try:
            return (repo_part or None, int(num_part))
        except ValueError:
            return (None, None)
    try:
        return (None, int(key))
    except ValueError:
        return (None, None)


def _all_issue_refs(plan_data: dict, default_repo: str | None = None) -> set[str]:
    """Return a set of every issue ref in the plan.

    Refs are qualified as ``{owner}/{repo}#N`` when the issue has a
    resolvable repo (per-issue override, else plan-level ``repo``, else
    *default_repo* argument).  Otherwise bare ``str(N)``.
    """
    refs: set[str] = set()
    plan_default = default_repo or _plan_default_repo(plan_data)
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                repo = issue.get("repo") if isinstance(issue.get("repo"), str) and issue.get("repo") else plan_default
                refs.add(_compose_issue_key(issue["number"], repo))
    return refs


def _resolve_issue_key(
    state_data: dict,
    ref: int | str,
    *,
    container: str = "issues",
    wave_id: str | None = None,
) -> str | None:
    """Dual-read: resolve *ref* to an existing key in *state_data*.

    *container* selects the dict to search:
    - ``"issues"``: ``state_data["issues"]``
    - ``"mr_urls"``: ``state_data["waves"][wave_id]["mr_urls"]`` (requires
      *wave_id*).

    Resolution order:
    1. If *ref* is a ``str`` containing ``#``, treat as qualified — return
       as-is when present in the container, else None.
    2. Otherwise try ``str(ref)`` (bare form).
    3. Otherwise iterate container keys, returning any whose numeric
       portion (after ``#`` or the whole bare integer) equals ``int(ref)``.
       Prefers qualified keys on tie.

    Returns the key string if found, else None.
    """
    if container == "issues":
        bag = state_data.get("issues", {})
    elif container == "mr_urls":
        if wave_id is None:
            return None
        bag = state_data.get("waves", {}).get(wave_id, {}).get("mr_urls", {})
    else:
        return None

    # Form 1: qualified ref passed directly.
    if isinstance(ref, str) and "#" in ref:
        return ref if ref in bag else None

    # Normalize to numeric.
    try:
        n = int(ref)
    except (TypeError, ValueError):
        return None

    # Form 2: bare key direct lookup.
    bare = str(n)
    bare_hit = bare in bag

    # Form 3: scan ALL qualified suffix matches. If more than one repo's
    # qualified key matches the bare number, the input is ambiguous — raise
    # instead of silently picking whichever Python dict-iteration yields
    # first. Caller must supply a qualified ref to disambiguate.
    qualified_hits: list[str] = []
    for key in bag:
        if "#" not in key:
            continue
        _, _, num_part = key.rpartition("#")
        try:
            if int(num_part) == n:
                qualified_hits.append(key)
        except ValueError:
            continue

    if len(qualified_hits) > 1:
        raise ValueError(
            f"Error: bare issue #{n} is ambiguous — found in multiple repos: "
            f"{', '.join(sorted(qualified_hits))}. "
            "Pass a qualified ref (owner/repo#N) to disambiguate."
        )

    # Prefer qualified on conflict (v3 semantics).
    if qualified_hits:
        return qualified_hits[0]
    if bare_hit:
        return bare
    return None


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


def current_phase_info(plan_data: dict, state_data: dict) -> dict:
    """Return phase/wave position info, handling ``current_wave=None``.

    When ``current_wave`` is set, locates it in the plan.  When it is
    ``None``, infers position from wave completion status: finds the
    first pending wave (next up) or reports all phases complete.

    Returns::

        {
            "phase_idx": int,        # 1-based, 0 only if plan is empty
            "total_phases": int,
            "phase_name": str,
            "wave_in_phase": int,    # 1-based
            "waves_in_phase": int,
        }
    """
    phases = plan_data.get("phases", [])
    total_phases = len(phases)
    current_wave = state_data.get("current_wave")
    waves_state = state_data.get("waves", {})

    # --- Active wave: locate it directly ---
    if current_wave is not None:
        for pi, phase in enumerate(phases):
            phase_wave_ids = [w["id"] for w in phase.get("waves", [])]
            if current_wave in phase_wave_ids:
                return {
                    "phase_idx": pi + 1,
                    "total_phases": total_phases,
                    "phase_name": phase.get("name", ""),
                    "wave_in_phase": phase_wave_ids.index(current_wave) + 1,
                    "waves_in_phase": len(phase_wave_ids),
                }

    # --- No active wave: infer from wave completion status ---
    # Find the first phase with a pending wave — that's the next phase.
    for pi, phase in enumerate(phases):
        phase_wave_ids = [w["id"] for w in phase.get("waves", [])]
        for wi, wid in enumerate(phase_wave_ids):
            if waves_state.get(wid, {}).get("status") == "pending":
                return {
                    "phase_idx": pi + 1,
                    "total_phases": total_phases,
                    "phase_name": phase.get("name", ""),
                    "wave_in_phase": wi + 1,
                    "waves_in_phase": len(phase_wave_ids),
                }

    # All waves completed (or empty plan).
    last_phase = phases[-1] if phases else None
    return {
        "phase_idx": total_phases,
        "total_phases": total_phases,
        "phase_name": last_phase.get("name", "Complete") if last_phase else "Complete",
        "wave_in_phase": len(last_phase.get("waves", [])) if last_phase else 0,
        "waves_in_phase": len(last_phase.get("waves", [])) if last_phase else 0,
    }


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
                repo = _issue_repo(plan_data, issue)
                key = _compose_issue_key(issue["number"], repo)
                issues_state[key] = {"status": "open"}

    first_wave = wave_ids[0] if wave_ids else None

    state_data: dict = {
        "schema_version": CURRENT_SCHEMA_VERSION,
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

    # Check for issue ref collisions — use qualified refs when a repo is
    # resolvable so two different repos with the same bare number don't
    # falsely collide.  Fall back to bare numeric compare when neither
    # side has a repo.
    existing_refs = _all_issue_refs(existing_plan)
    new_refs = _all_issue_refs(plan_data)
    issue_collisions = existing_refs & new_refs
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

    # For issue keys, prefer qualified form when we have a repo — but
    # dedup against the bare form too so a pre-v3 state doesn't grow a
    # duplicate entry.
    existing_issues = existing_state.setdefault("issues", {})
    for phase in plan_data["phases"]:
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                repo = _issue_repo(plan_data, issue)
                qualified = _compose_issue_key(issue["number"], repo)
                bare = str(issue["number"])
                if qualified in existing_issues or bare in existing_issues:
                    continue
                existing_issues[qualified] = {"status": "open"}

    # Auto-advance current_wave when the prior plan has been fully worked off
    # and new pending waves now exist. Without this, running `init --extend`
    # on top of a completed plan leaves `current_wave` stuck at None (or at
    # the last-completed wave), and every subsequent subcommand that asserts
    # "a current wave is set" (planning, flight, flight_plan, …) refuses
    # because it can't tell the plan was extended.
    waves_state = existing_state.get("waves", {})
    current = existing_state.get("current_wave")
    current_is_done = (
        current is None
        or waves_state.get(current, {}).get("status") == "completed"
    )
    if current_is_done:
        for wid in _all_wave_ids(existing_plan):
            if waves_state.get(wid, {}).get("status") == "pending":
                existing_state["current_wave"] = wid
                break

    existing_state["last_updated"] = _now_iso()
    save_json(state_path, existing_state)


def store_flight_plan(flights_data: list, root: Path) -> None:
    """Store *flights_data* keyed by the current wave ID in ``flights.json`` [R-04].

    *flights_data* should be a list of flight dicts
    (e.g. ``[{"issues": [13, 1], "status": "pending"}, ...]``).
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
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
    state_data = load_state(d / "state.json")
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
    state_data = load_state(d / "state.json")
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
    state_data = load_state(d / "state.json")
    current_wave = state_data.get("current_wave")
    return _set_action(root, "post-wave-review", "post-wave-review", current_wave or "")


def waiting(root: Path, msg: str = "") -> dict:
    """Set current_action to ``waiting-on-meatbag`` [R-05]."""
    return _set_action(root, "waiting-on-meatbag", "waiting-on-meatbag", msg)


def waiting_ci(root: Path, detail: str = "") -> dict:
    """Set current_action to ``waiting-ci`` — heartbeat during CI polling."""
    return _set_action(root, "waiting-ci", "waiting-ci", detail)


def set_current_wave(wave_id: str, root: Path) -> dict:
    """Set ``current_wave`` to *wave_id* in ``state.json``.

    Validates *wave_id* exists in the plan and is not already ``completed``.
    Intended as the CLI-accessible path to advance ``current_wave`` outside
    of the normal ``complete`` flow (e.g. after ``init --extend`` on an
    already-completed plan, or when a human needs to jump the pointer during
    recovery).  Raises ``ValueError`` if the wave ID is unknown or already
    completed — pointing at a completed wave would let ``planning`` flip its
    status back to ``in_progress``, corrupting the completion record.
    """
    d = status_dir(root)
    plan_data = load_json(d / "phases-waves.json")
    valid_ids = _all_wave_ids(plan_data)
    if wave_id not in valid_ids:
        raise ValueError(
            f"Error: wave '{wave_id}' does not exist in the plan. "
            f"Valid wave IDs: {', '.join(valid_ids) if valid_ids else '(none)'}."
        )

    state_data = load_state(d / "state.json")
    target_status = state_data.get("waves", {}).get(wave_id, {}).get("status")
    if target_status == "completed":
        raise ValueError(
            f"Error: wave '{wave_id}' is already completed. "
            "Pass a pending or in_progress wave ID instead."
        )

    state_data["current_wave"] = wave_id
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def set_kahuna_branch(branch: str | None, root: Path) -> dict:
    """Set or clear ``kahuna_branch`` in ``state.json``.

    Used by the sdlc-server ``wave_init`` handler (mcp-server-sdlc#206) when
    the optional ``kahuna`` argument is passed — the handler creates the
    integration branch via the platform API and then calls this CLI to record
    the branch name in wave state. See devspec §5.1.4 for the schema.

    Pass an empty string or ``None`` to clear the field (sets ``kahuna_branch``
    to ``None`` in the JSON, which serializes as ``null``). Idempotent:
    re-setting the same value is a no-op aside from ``last_updated``.
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    state_data["kahuna_branch"] = branch if branch else None
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def wavemachine_start(root: Path, launcher: str = "") -> dict:
    """Mark the plan as actively driven by wavemachine.

    Sets ``wavemachine_active: true`` in ``state.json`` along with
    ``wavemachine_started_at`` and ``wavemachine_launcher`` metadata.
    Raises ``ValueError`` if a wavemachine run is already active (one plan
    at a time — matches the SKILL.md non-negotiable).
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    if state_data.get("wavemachine_active"):
        raise ValueError(
            "Error: wavemachine is already active for this plan. "
            "Run 'wavemachine-stop' first, or wait for the current run to exit."
        )

    state_data["wavemachine_active"] = True
    state_data["wavemachine_started_at"] = _now_iso()
    if launcher:
        state_data["wavemachine_launcher"] = launcher
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def wavemachine_stop(root: Path) -> dict:
    """Clear wavemachine ownership from ``state.json``.

    Deletes ``wavemachine_active``, ``wavemachine_started_at``, and
    ``wavemachine_launcher``.  Idempotent — succeeds even if no wavemachine
    run is active (worker abort paths need this to be safe on re-entry).
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    state_data.pop("wavemachine_active", None)
    state_data.pop("wavemachine_started_at", None)
    state_data.pop("wavemachine_launcher", None)
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def flight(n: int, root: Path) -> dict:
    """Set flight *n* to ``running`` in ``flights.json`` [R-11].

    **Strict**: for N > 1, flight N-1 must be ``completed``.
    Also sets ``current_action`` to ``in-flight``.
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
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
    state_data = load_state(d / "state.json")
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
    state_data = load_state(d / "state.json")
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


def close_issue(n: int | str, root: Path) -> dict:
    """Set issue *n* to ``closed`` in ``state.json`` [R-07, R-14].

    Accepts either a bare integer/digit-string (e.g. ``13`` or ``"13"``)
    or a qualified ref (``"owner/repo#13"``).  Dual-read lookup: tries
    the direct key first, then scans for a qualified suffix match.

    Raises ``ValueError`` if the issue does not exist in the plan.
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    plan_data = load_json(d / "phases-waves.json")

    # Normalize the incoming ref to (repo, number) for plan validation.
    if isinstance(n, str) and "#" in n:
        ref_repo, ref_num = _parse_issue_key(n)
        if ref_num is None:
            raise ValueError(
                f"Error: '{n}' is not a valid issue reference. "
                "Use an integer or 'owner/repo#N' form."
            )
    else:
        ref_repo = None
        try:
            ref_num = int(n)
        except (TypeError, ValueError):
            raise ValueError(
                f"Error: '{n}' is not a valid issue reference. "
                "Use an integer or 'owner/repo#N' form."
            )

    # Validate against the plan. When the caller supplied a qualified ref,
    # check the FULL ref (so `other-org/other-repo#13` is rejected even if the
    # plan has `Wave-Engineering/sdlc#13`). When bare, fall back to the
    # number-set check (preserves pre-v3 behavior for single-repo plans).
    if ref_repo:
        all_refs = _all_issue_refs(plan_data)
        qualified_ref = f"{ref_repo}#{ref_num}"
        if qualified_ref not in all_refs:
            raise ValueError(
                f"Error: issue {qualified_ref} does not exist in the plan. "
                "Check the qualified ref and try again."
            )
    else:
        valid_nums = _all_issue_numbers(plan_data)
        if ref_num not in valid_nums:
            raise ValueError(
                f"Error: issue #{ref_num} does not exist in the plan. "
                f"Check the issue number and try again."
            )

    # Resolve to an existing key (dual-read), else compose one.
    resolved = _resolve_issue_key(state_data, n, container="issues")
    if resolved is None:
        # Not yet in state — compose the preferred key shape.
        if ref_repo:
            resolved = _compose_issue_key(ref_num, ref_repo)
        else:
            # Infer from the plan if possible.
            plan_repo = _plan_default_repo(plan_data)
            for phase in plan_data.get("phases", []):
                for wave in phase.get("waves", []):
                    for issue in wave.get("issues", []):
                        if issue["number"] == ref_num:
                            plan_repo = _issue_repo(plan_data, issue) or plan_repo
                            break
            resolved = _compose_issue_key(ref_num, plan_repo)
        state_data.setdefault("issues", {})[resolved] = {}

    state_data["issues"][resolved]["status"] = "closed"
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def record_mr(issue: int | str, mr: str, root: Path) -> dict:
    """Record an MR/PR reference for *issue* in the current wave's
    ``mr_urls`` [R-08].

    Accepts either a bare integer/digit-string or a qualified ref
    (``"owner/repo#N"``).  Dual-read lookup on existing ``mr_urls`` keys.
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json")
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

    # Normalize to (repo, number).
    if isinstance(issue, str) and "#" in issue:
        ref_repo, ref_num = _parse_issue_key(issue)
        if ref_num is None:
            raise ValueError(
                f"Error: '{issue}' is not a valid issue reference. "
                "Use an integer or 'owner/repo#N' form."
            )
    else:
        ref_repo = None
        try:
            ref_num = int(issue)
        except (TypeError, ValueError):
            raise ValueError(
                f"Error: '{issue}' is not a valid issue reference. "
                "Use an integer or 'owner/repo#N' form."
            )

    resolved = _resolve_issue_key(
        state_data, issue, container="mr_urls", wave_id=current_wave
    )
    if resolved is None:
        if ref_repo:
            resolved = _compose_issue_key(ref_num, ref_repo)
        else:
            # Infer repo from plan for the preferred key shape.
            try:
                plan_data = load_json(d / "phases-waves.json")
                plan_repo = _plan_default_repo(plan_data)
                for phase in plan_data.get("phases", []):
                    for wave in phase.get("waves", []):
                        for iss in wave.get("issues", []):
                            if iss["number"] == ref_num:
                                plan_repo = _issue_repo(plan_data, iss) or plan_repo
                                break
                resolved = _compose_issue_key(ref_num, plan_repo)
            except FileNotFoundError:
                resolved = str(ref_num)

    waves[current_wave].setdefault("mr_urls", {})[resolved] = mr
    state_data["last_updated"] = _now_iso()
    save_json(d / "state.json", state_data)
    return state_data


def show(root: Path) -> dict:
    """Return a summary dict describing the current state [R-06].

    **Read-only** — no files are modified, no dashboard is regenerated.
    """
    d = status_dir(root)
    state_data = load_state(d / "state.json", write_back=False)
    plan_data = load_json(d / "phases-waves.json")
    flights_data = load_json(d / "flights.json")

    # Determine current phase info.
    current_wave = state_data.get("current_wave")
    phase_info = current_phase_info(plan_data, state_data)
    current_phase_name = phase_info["phase_name"]
    current_phase_idx = phase_info["phase_idx"]
    total_phases = phase_info["total_phases"]
    wave_in_phase = phase_info["wave_in_phase"]
    waves_in_current_phase = phase_info["waves_in_phase"]

    # Flight info.
    wave_flights = flights_data.get("flights", {}).get(current_wave or "", [])
    total_flights = len(wave_flights)
    running_flight = None
    for fi, fl in enumerate(wave_flights):
        if fl.get("status") == "running":
            running_flight = fi + 1
            break

    # Issue counts — dual-read: try qualified key first (composed from the
    # issue's resolved repo), then fall back to bare numeric.
    total_issues = 0
    closed_issues = 0
    issues_bag = state_data.get("issues", {})
    for phase in plan_data.get("phases", []):
        for wave in phase.get("waves", []):
            for issue in wave.get("issues", []):
                total_issues += 1
                repo = _issue_repo(plan_data, issue)
                istate: dict = {}
                if repo:
                    istate = issues_bag.get(
                        _compose_issue_key(issue["number"], repo), {}
                    )
                if not istate:
                    istate = issues_bag.get(str(issue["number"]), {})
                if not istate:
                    # Last-ditch scan — state may carry a different repo
                    # prefix (e.g. imported from another plan variant).
                    resolved = _resolve_issue_key(
                        state_data, issue["number"], container="issues"
                    )
                    if resolved is not None:
                        istate = issues_bag.get(resolved, {})
                if istate.get("status") == "closed":
                    closed_issues += 1
    pct = round(100 * closed_issues / total_issues) if total_issues else 0

    # Deferrals.
    deferrals = state_data.get("deferrals", [])
    pending_count = sum(1 for d in deferrals if d.get("status") == "pending")
    accepted_count = sum(1 for d in deferrals if d.get("status") == "accepted")

    # Action.
    action_obj = state_data.get("current_action", {}) or {}
    action_str = action_obj.get("action", "idle")
    label_str = action_obj.get("label", "")
    detail = action_obj.get("detail", "")
    # The action display used to be a bare "action - detail" string, but
    # the KAHUNA gate actions carry structured detail payloads (dict with
    # "failures" / "signals") that render as gibberish when stringified.
    # Fall back to the plain action when detail isn't a scalar.
    if isinstance(detail, str) and detail:
        action_display = f"{action_str} — {detail}"
    else:
        action_display = action_str

    flight_display: str
    if total_flights == 0:
        flight_display = "\u2014"  # em dash
    elif running_flight is not None:
        flight_display = f"{running_flight}/{total_flights}"
    else:
        flight_display = f"\u2014/{total_flights}"

    # Flight counts restricted to the current wave - used by the Kahuna
    # section to report "merged / pending" per devspec 5.2.5.
    kahuna_merged = sum(
        1 for fl in wave_flights if fl.get("status") == "completed"
    )
    kahuna_pending = sum(
        1 for fl in wave_flights if fl.get("status") != "completed"
    )

    return {
        "project": plan_data.get("project", "unknown"),
        "phase": f"{current_phase_idx}/{total_phases}",
        "phase_name": current_phase_name,
        "wave": f"{wave_in_phase}/{waves_in_current_phase} in phase {current_phase_idx}",
        "flight": flight_display,
        "action": action_display,
        "action_key": action_str,
        "action_label": label_str or action_str,
        "action_detail": detail,
        "progress": f"{closed_issues}/{total_issues} issues ({pct}%)",
        "deferrals": f"{pending_count} pending, {accepted_count} accepted",
        # Optional Kahuna fields - tolerate absence for legacy state files.
        "kahuna_branch": state_data.get("kahuna_branch"),
        "kahuna_branches": state_data.get("kahuna_branches", []) or [],
        "kahuna_flights_merged": kahuna_merged,
        "kahuna_flights_pending": kahuna_pending,
    }
