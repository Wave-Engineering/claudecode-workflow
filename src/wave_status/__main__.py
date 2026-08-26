"""CLI entry point for wave_status — argparse subcommand dispatch.

Wires subcommands to the state machine (state.py), deferral engine
(deferrals.py), and dashboard generator (dashboard/generator.py).

This is the only module that imports across package boundaries.

Usage::

    python -m wave_status <subcommand> [args]

Requires Python 3.10+ stdlib only — no external dependencies [CT-01].
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path

from wave_status import deferrals
from wave_status.dashboard.derived_state import compute_derived_state
from wave_status.dashboard.generator import generate_dashboard
from wave_status.state import (
    append_trajectory,
    awaiting_verdict,
    close_issue,
    complete,
    extend_state,
    flight,
    flight_done,
    get_project_root,
    hold,
    hold_wave,
    init_state,
    launching,
    load_json,
    load_state,
    planning,
    preflight,
    promoting,
    read_trajectory,
    record_mr,
    resolve_campaign_head_detail,
    review,
    save_json,
    set_current_wave,
    set_kahuna_branch,
    show,
    status_dir,
    store_flight_plan,
    waiting,
    waiting_ci,
    wavemachine_start,
    wavemachine_stop,
)


# ---------------------------------------------------------------------------
# Dashboard regeneration helper
# ---------------------------------------------------------------------------

def _regenerate_dashboard(root: Path) -> None:
    """Load all three JSON files fresh from disk and regenerate the dashboard.

    Before generating HTML, splice the computed ``gauges`` and ``rail``
    snapshots into ``state.json`` so the polling cycle (which only fetches
    ``state.json``) can resolve the gauge-card and progress-rail bindings
    without a full HTML regen.  See issue #447.
    """
    d = status_dir(root)
    phases_data = load_json(d / "phases-waves.json")
    state_data = load_json(d / "state.json")
    flights_data = load_json(d / "flights.json")

    # Refresh derived fields and persist back to state.json so the polling
    # cycle (the *only* path that doesn't get an HTML regen) sees them.
    derived = compute_derived_state(phases_data, state_data, flights_data)
    state_data["gauges"] = derived["gauges"]
    state_data["rail"] = derived["rail"]
    save_json(d / "state.json", state_data)

    generate_dashboard(root, phases_data, state_data, flights_data)
    # Best-effort Discord status update
    try:
        subprocess.run(
            ["discord-status-post", "--state-dir", str(d)],
            timeout=10,
            capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass  # discord-status-post not installed or timed out — skip silently


def _safe_regenerate_dashboard(root: Path) -> None:
    """Run ``_regenerate_dashboard`` but never raise to the caller [#495].

    The state mutation has already persisted by the time this is called.
    Dashboard regeneration is a derived-view refresh — if it crashes (bad
    legacy state.json, missing field, library bug, etc.), we still want
    the JSON success envelope to print so MCP wrappers and downstream
    sub-agents see ``{ok: true}`` instead of a non-zero exit.

    The exception detail is written to stderr so a human running the CLI
    interactively can still see what failed.
    """
    try:
        _regenerate_dashboard(root)
    except Exception as exc:  # noqa: BLE001 — best-effort; envelope must print
        # The mutation already persisted; a derived-view refresh failure must
        # not fail the command. Emit the full traceback (not just the message)
        # so a render bug like #<this issue> is diagnosable from the warning
        # even though the exit code stays 0.
        print(
            f"warning: dashboard regeneration failed: {exc}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)


def _print_envelope(state: dict) -> None:
    """Print the canonical ``{ok, state}`` JSON envelope to stdout [#495].

    Used by the mutation subcommands so callers (sdlc-server MCP wrappers,
    Prime sub-agents) get a parseable success payload rather than the empty
    stdout that pre-#495 mutation handlers produced.
    """
    print(json.dumps({"ok": True, "state": state}))


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``init <file|->``."""
    if args.extend and args.force:
        print(
            "Error: --extend and --force are mutually exclusive. "
            "Use --extend to add phases, or --force to overwrite.",
            file=sys.stderr,
        )
        sys.exit(1)

    root = get_project_root()
    raw = _read_json_source(args.file)
    plan_data = json.loads(raw)
    # --repo flag overrides plan-level default repo for qualified issue keys
    # (v3 schema).  Per-issue ``repo`` in the plan JSON still wins over this
    # default because _issue_repo() consults the issue's own repo first.
    if getattr(args, "repo", None):
        plan_data["repo"] = args.repo
    if args.extend:
        extend_state(plan_data, root)
    else:
        init_state(plan_data, root, force=args.force)
    _safe_regenerate_dashboard(root)


def _cmd_flight_plan(args: argparse.Namespace) -> None:
    """Handle ``flight-plan <file|->``."""
    root = get_project_root()
    raw = _read_json_source(args.file)
    flights_data = json.loads(raw)
    # #632: tolerate both the bare array (the tool's expected shape) and a
    # wrapped {"flights": [...]} object — the Prime prompt sometimes emits the
    # wrapper, which otherwise stores an inconsistent shape that crashes the
    # wave-status read path. Normalize to the bare list at this boundary.
    if isinstance(flights_data, dict) and "flights" in flights_data:
        flights_data = flights_data["flights"]
    store_flight_plan(flights_data, root)
    _safe_regenerate_dashboard(root)


def _cmd_preflight(args: argparse.Namespace) -> None:
    """Handle ``preflight``."""
    root = get_project_root()
    preflight(root)
    _safe_regenerate_dashboard(root)


def _cmd_planning(args: argparse.Namespace) -> None:
    """Handle ``planning``."""
    root = get_project_root()
    planning(root)
    _safe_regenerate_dashboard(root)


def _cmd_flight(args: argparse.Namespace) -> None:
    """Handle ``flight <N>``."""
    root = get_project_root()
    result = flight(args.n, root)
    _safe_regenerate_dashboard(root)
    _print_envelope(result)


def _cmd_flight_done(args: argparse.Namespace) -> None:
    """Handle ``flight-done <N>``."""
    root = get_project_root()
    result = flight_done(args.n, root)
    _safe_regenerate_dashboard(root)
    _print_envelope(result)


def _cmd_review(args: argparse.Namespace) -> None:
    """Handle ``review``."""
    root = get_project_root()
    review(root)
    _safe_regenerate_dashboard(root)


def _cmd_complete(args: argparse.Namespace) -> None:
    """Handle ``complete [wave-id]`` — target the run's explicit wave when given
    (ENG-1 / #846); default to ``current_wave`` when omitted."""
    root = get_project_root()
    complete(root, wave_id=getattr(args, "wave_id", None) or None)
    _safe_regenerate_dashboard(root)


def _cmd_hold_wave(args: argparse.Namespace) -> None:
    """Handle ``hold-wave <wave-id> [--detail ...]`` — mark a non-promoted wave
    ``held`` without advancing ``current_wave`` (ENG-1 / #846). Distinct from the
    coarse-state ``hold`` command (which sets ``current_action``)."""
    root = get_project_root()
    hold_wave(args.wave_id, root, detail=args.detail or "")
    _safe_regenerate_dashboard(root)


def _cmd_waiting(args: argparse.Namespace) -> None:
    """Handle ``waiting [msg]``."""
    root = get_project_root()
    msg = args.msg if args.msg else ""
    result = waiting(root, msg=msg)
    _safe_regenerate_dashboard(root)
    _print_envelope(result)


def _cmd_waiting_ci(args: argparse.Namespace) -> None:
    """Handle ``waiting-ci [detail]``."""
    root = get_project_root()
    detail = args.detail if args.detail else ""
    waiting_ci(root, detail=detail)
    _safe_regenerate_dashboard(root)


def _cmd_launching(args: argparse.Namespace) -> None:
    """Handle ``launching [wave]`` — dynamic-driver coarse state (#738)."""
    root = get_project_root()
    launching(root, wave_id=args.wave or "")
    _safe_regenerate_dashboard(root)


def _cmd_awaiting_verdict(args: argparse.Namespace) -> None:
    """Handle ``awaiting-verdict [wave]`` — coarse state (#738)."""
    root = get_project_root()
    awaiting_verdict(root, wave_id=args.wave or "")
    _safe_regenerate_dashboard(root)


def _cmd_promoting(args: argparse.Namespace) -> None:
    """Handle ``promoting [wave]`` — coarse state (#738)."""
    root = get_project_root()
    promoting(root, wave_id=args.wave or "")
    _safe_regenerate_dashboard(root)


def _cmd_hold(args: argparse.Namespace) -> None:
    """Handle ``hold [reason]`` — coarse state (#738)."""
    root = get_project_root()
    hold(root, reason=args.reason or "")
    _safe_regenerate_dashboard(root)


def _cmd_trajectory_append(args: argparse.Namespace) -> None:
    """Handle ``trajectory-append <wave> <entry-json|->`` — durable cross-wave
    campaign trajectory upsert (#748)."""
    root = get_project_root()
    entry = json.loads(_read_json_source(args.entry))
    append_trajectory(root, args.wave, entry)
    _safe_regenerate_dashboard(root)


def _cmd_trajectory_show(args: argparse.Namespace) -> None:
    """Handle ``trajectory-show`` — emit the durable cross-wave trajectory as a
    JSON array (the read path the judgment seed + dashboard consume, #748)."""
    root = get_project_root()
    print(json.dumps(read_trajectory(root)))


def _cmd_close_issue(args: argparse.Namespace) -> None:
    """Handle ``close-issue <N>``."""
    root = get_project_root()
    result = close_issue(args.n, root)
    _safe_regenerate_dashboard(root)
    _print_envelope(result)


def _cmd_record_mr(args: argparse.Namespace) -> None:
    """Handle ``record-mr <issue> <mr>``."""
    root = get_project_root()
    result = record_mr(args.issue, args.mr, root)
    _safe_regenerate_dashboard(root)
    _print_envelope(result)


def _cmd_defer(args: argparse.Namespace) -> None:
    """Handle ``defer <desc> <risk>``."""
    root = get_project_root()
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    if state_data.get("current_wave") is None:
        raise ValueError("no active wave — all waves are complete")
    deferrals.defer(state_data, args.desc, args.risk, state_data["current_wave"])
    save_json(d / "state.json", state_data)
    _safe_regenerate_dashboard(root)


def _cmd_defer_accept(args: argparse.Namespace) -> None:
    """Handle ``defer-accept <index>``."""
    root = get_project_root()
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    deferrals.accept(state_data, args.index)
    save_json(d / "state.json", state_data)
    _safe_regenerate_dashboard(root)


def _cmd_set_current(args: argparse.Namespace) -> None:
    """Handle ``set-current <wave-id>``."""
    root = get_project_root()
    set_current_wave(args.wave_id, root)
    _safe_regenerate_dashboard(root)


def _cmd_set_kahuna_branch(args: argparse.Namespace) -> None:
    """Handle ``set-kahuna-branch [<branch>]`` — empty arg clears the field."""
    root = get_project_root()
    branch = args.branch.strip() if args.branch else ""
    set_kahuna_branch(branch or None, root)
    _safe_regenerate_dashboard(root)


def _cmd_wavemachine_start(args: argparse.Namespace) -> None:
    """Handle ``wavemachine-start [--launcher <tag>]``."""
    root = get_project_root()
    wavemachine_start(root, launcher=args.launcher or "")
    _safe_regenerate_dashboard(root)


def _cmd_wavemachine_stop(args: argparse.Namespace) -> None:
    """Handle ``wavemachine-stop``."""
    root = get_project_root()
    result = wavemachine_stop(root)
    _safe_regenerate_dashboard(root)
    _print_envelope(result)


def _cmd_emit(args: argparse.Namespace) -> None:
    """Handle ``emit <kind> [opts…]`` — emit one FlightDeck event.

    Delegates verbatim to the events emit CLI (single source of truth for the
    option surface). Fire-and-forget: it buffers + non-blocking-ships and never
    regenerates the dashboard.
    """
    from wave_status.events.emit import main as emit_main

    emit_main(args.emit_args)


def _cmd_campaign_head(args: argparse.Namespace) -> None:
    """Handle ``campaign-head`` — emit the FlightDeck campaign card's head.

    Unlike ``emit`` (a generic, fire-and-forget event that never raises),
    this command computes ``planTotal``/``workItemsTotal``/``waveWorkItems``/the project title
    FROM THE PLAN (``resolve_campaign_head_detail``) rather than accepting
    them as caller-supplied literals, and lets a ``ValueError`` propagate to
    ``main()``'s handler — refusing loudly (non-zero exit, a message on
    stderr) rather than emitting a card with an unknown/guessed total
    (flightdeck#1145, cc-workflow#1146 step 4). The caller owns
    ``--activity-id`` (the plan id) — ``/wavemachine``'s launch sequence
    resolves it from its own shell's ``FLIGHTDECK_ACTIVITY_ID``;
    ``/prepwaves``'s persist step (cc-workflow#1171) resolves it by reading
    back the ``plan_id`` it just persisted to ``phases-waves.json`` — because
    ``resolve_campaign_head_detail`` cannot key the event itself the way the
    plain state mutators do.

    Delegates the actual emit to the events emit CLI (`_cmd_emit`'s own
    pattern) rather than calling ``emit()`` directly, so this call site gets
    the SAME side effects a hand-typed ``wave-status emit`` gets for free —
    most importantly the durable FlightDeck scope marker a campaign
    ``activity_start`` writes (#1148/#1150), which the per-wave tee resolves
    scope from. Reimplementing the emit here would silently lose that. Uses
    ``--detail-json`` (not ``--detail``) so the buffered event carries
    ``planTotal`` as an OBJECT, not a string — the flightdeck-side shim that
    accepts a string is explicitly a compatibility shim for the OLD shape,
    not the target (flightdeck fold.ts `asRecord`).
    """
    from wave_status.events.emit import main as emit_main

    # An empty --activity-id is the SAME defect this command exists to fix,
    # one field over: emit()'s own fallback chain reads a blank string as
    # falsy and resolves it to "unknown", which the scope-marker allowlist
    # then explicitly SKIPS (aid != "unknown") — so a card would render under
    # a bogus id AND leave no marker for the per-wave tee to resolve scope
    # from, silently, at exit 0. Refuse here instead, same as an unresolvable
    # plan.
    if not (args.activity_id or "").strip():
        raise ValueError(
            "Error: --activity-id is empty. Export FLIGHTDECK_ACTIVITY_ID=<plan_id> "
            "before emitting the campaign head."
        )

    root = get_project_root()
    resolved = resolve_campaign_head_detail(root)
    argv = [
        "activity_start",
        "--activity-id", args.activity_id,
        "--activity-type", "campaign",
        "--detail-json", json.dumps({
            "planTotal": resolved["planTotal"],
            "workItemsTotal": resolved["workItemsTotal"],
            "waveWorkItems": resolved["waveWorkItems"],
        }),
    ]
    if resolved["project"]:
        # `--flag=value` (one token), not `--flag value` (two) — a project
        # name that happens to start with "-" would otherwise be parsed as a
        # flag by the emit CLI's own argparse instance.
        argv += [f"--label={resolved['project']}"]
    if args.agent:
        argv += [f"--agent={args.agent}"]
    if args.session:
        argv += [f"--session={args.session}"]
    emit_main(argv)


def _cmd_wave_begin(args: argparse.Namespace) -> None:
    """Handle ``wave-begin <activity-id> <wave>`` — idempotently own the
    FlightDeck ``activity_start`` head row for an activity id (cc-workflow#1138
    step 2 / #1170).

    Root cause this closes: ``skills/nextwave/per-wave-workflow.js``'s
    ``AID = PLAN_ID || WAVE_ID`` degrades to a wave-scoped key whenever
    ``planId`` isn't threaded through (a bare/standalone ``/nextwave`` run),
    and nothing ever emitted an ``activity_start`` ROW for that key at all —
    flightdeck's fold.ts backfilled ``startedAt`` from whichever event
    happened to arrive first instead, an orphaned tail with no canonical
    head. Calling this unconditionally, once, at the start of every wave
    (from ``rehydrate()``) closes that regardless of whether ``AID``
    resolved via the real plan id or the fallback: a real campaign's
    already-real head gets an idempotent no-op re-fire; a bare/standalone
    run gets a real head row where none existed.

    NOT claimed: this command does not, by itself, move a headless-classified
    activity (flightdeck's fold.ts ``activityType``, per flightdeck#31/#42)
    out of the headless UI bucket — that classification latches on any
    event declaring ``activityType: campaign|float``, which this command
    deliberately never does (see the narrow-surface rationale below).
    cc-workflow#1171 closes that gap on the ``/prepwaves`` side instead:
    ``/prepwaves``'s own persist step now calls ``campaign-head`` right
    after writing the plan, so a standalone run gets a real
    ``activityType: campaign`` declaration (with real ``planTotal``/
    ``workItemsTotal``) from the moment the plan is prepped, not just under
    ``/wavemachine``. This command's own narrow surface is unchanged.

    Deliberately narrow option surface — NO ``--label``/``--detail-json``/
    ``--activity-type``, unlike ``campaign-head``. That narrowness IS the
    idempotency mechanism, not an incidental omission: flightdeck's fold.ts
    guards ``startedAt`` (a second ``activity_start`` is a no-op there), but
    ``label`` and the ``detail`` progress fields (``planTotal`` etc.) are
    last-write-wins across ``activity_start`` events specifically. A version
    of this command that could pass those fields would risk clobbering a
    real campaign's label/planTotal on a defensive re-fire; one that
    structurally cannot, cannot. If a real head is needed with a
    label/detail/type, that is ``campaign-head``'s job, not this one's.

    Delegates through the events emit CLI (`_cmd_campaign_head`'s own
    pattern), never calling ``emit()`` directly, so this gets the same
    agent/session default-injection a hand-typed ``wave-status emit`` gets
    for free. It does NOT get campaign-head's scope-marker write — that
    write is allowlisted on ``activity_type == "campaign"``
    (``events/emit.py``), which this command structurally never passes.
    """
    from wave_status.events.emit import main as emit_main

    # Same defect class campaign-head's own guard exists to close, one field
    # over (see its docstring/guard above): a blank --activity-id resolves
    # to "unknown" in emit()'s own fallback, silently mislabeling the head
    # row rather than refusing. Refuse here instead.
    if not (args.activity_id or "").strip():
        raise ValueError(
            "Error: activity-id is empty. Pass the AID the wave's tee resolved to "
            "(planId, or waveId on a bare/test run)."
        )

    argv = ["activity_start", "--activity-id", args.activity_id, "--wave", args.wave]
    if args.agent:
        argv += [f"--agent={args.agent}"]
    if args.session:
        argv += [f"--session={args.session}"]
    emit_main(argv)


def _cmd_show(args: argparse.Namespace) -> None:
    """Handle ``show`` — print summary, NO dashboard regen.

    When the state carries KAHUNA context (``kahuna_branch`` set, or
    ``kahuna_branches`` history non-empty, or ``action`` is a gate state),
    the summary is followed by a "Kahuna" section with branch + merged/
    pending flight counts, a trust-signal summary for ``gate_evaluating``,
    a failure detail block for ``gate_blocked``, and a collapsed history
    table (last 10 entries) per devspec §5.2.5.
    """
    root = get_project_root()
    summary = show(root)
    lines = [
        f"Project:   {summary['project']}",
        f"Phase:     {summary['phase']} — {summary['phase_name']}",
        f"Wave:      {summary['wave']}",
        f"Flight:    {summary['flight']}",
        f"Action:    {summary['action']}",
        f"Progress:  {summary['progress']}",
        f"Deferrals: {summary['deferrals']}",
    ]
    lines.extend(_render_kahuna_cli(summary))
    print("\n".join(lines))


def _render_kahuna_cli(summary: dict) -> list[str]:
    """Format the Kahuna CLI block from a ``state.show`` summary.

    Returns an empty list when there is no Kahuna context to report so
    legacy, non-KAHUNA output remains byte-identical.
    """
    branch = summary.get("kahuna_branch")
    history = summary.get("kahuna_branches") or []
    action_key = summary.get("action_key") or ""
    detail = summary.get("action_detail")

    has_context = bool(branch) or bool(history) or action_key in (
        "gate_evaluating",
        "gate_blocked",
    )
    if not has_context:
        return []

    out: list[str] = ["", "Kahuna:"]

    if branch:
        merged = summary.get("kahuna_flights_merged", 0)
        pending = summary.get("kahuna_flights_pending", 0)
        out.append(f"  Branch:   {branch}")
        out.append(f"  Flights:  {merged} merged, {pending} pending")
    else:
        out.append("  Branch:   (none active)")

    if action_key == "gate_evaluating":
        signals: list[str] = []
        if isinstance(detail, dict):
            raw = detail.get("signals")
            if isinstance(raw, list):
                signals = [str(s) for s in raw]
        if not signals:
            signals = [
                "commutativity_verify",
                "ci_wait_run",
                "code-reviewer",
                "trivy vuln scan",
            ]
        out.append("  Trust signals evaluating:")
        for s in signals:
            out.append(f"    - {s}")

    elif action_key == "gate_blocked":
        failures: list[str] = []
        if isinstance(detail, dict):
            raw = detail.get("failures")
            if isinstance(raw, list):
                for entry in raw:
                    if isinstance(entry, dict):
                        sig = str(entry.get("signal", ""))
                        reason = str(entry.get("reason", ""))
                        failures.append(
                            f"{sig}: {reason}" if reason else sig
                        )
                    else:
                        failures.append(str(entry))
        elif isinstance(detail, str) and detail:
            failures.append(detail)
        if not failures:
            failures.append("Gate blocked — see wave state for details.")
        out.append("  Gate blocked — failing signals:")
        for f in failures:
            out.append(f"    - {f}")

    if history:
        # Collapsible table — print a header and up to the last 10 rows.
        shown = history[-10:]
        out.append(f"  History (last {len(shown)} of {len(history)}):")
        out.append(
            "    BRANCH | EPIC | CREATED | RESOLVED | DISPOSITION | "
            "MERGE_SHA | ABORT_REASON"
        )
        for entry in shown:
            if not isinstance(entry, dict):
                continue
            b = str(entry.get("branch", ""))
            epic = str(entry.get("epic_id", ""))
            created = str(entry.get("created_at", ""))
            resolved = str(entry.get("resolved_at", ""))
            disp = str(entry.get("disposition", ""))
            sha = str(entry.get("main_merge_sha", "-") or "-")
            reason = str(entry.get("abort_reason", "-") or "-")
            out.append(
                f"    {b} | {epic} | {created} | {resolved} | {disp} | "
                f"{sha} | {reason}"
            )
    return out


# ---------------------------------------------------------------------------
# Input helper
# ---------------------------------------------------------------------------

def _read_json_source(source: str) -> str:
    """Read JSON text from a file path or stdin (``-``)."""
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser with all subcommands."""
    parser = argparse.ArgumentParser(
        prog="wave-status",
        description="Wave execution lifecycle CLI",
        epilog=(
            "Side effects: the 'flight-done' and 'complete' subcommands "
            "trigger a best-effort call to discord-status-post to update "
            "the Discord status embed."
        ),
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize state from a plan JSON file")
    p_init.add_argument("file", help="Path to plan JSON file, or '-' for stdin")
    p_init.add_argument("--extend", action="store_true",
                        help="Add phases to an existing plan instead of overwriting")
    p_init.add_argument("--force", action="store_true",
                        help="Overwrite an existing plan (default: refuse)")
    p_init.add_argument(
        "--repo",
        default=None,
        help="Default '{owner}/{repo}' for qualified issue keys (v3 schema). "
             "Per-issue 'repo' in the plan JSON still wins over this.",
    )
    p_init.set_defaults(func=_cmd_init)

    # flight-plan
    p_fp = sub.add_parser("flight-plan", help="Store flight plan for the current wave")
    p_fp.add_argument("file", help="Path to flights JSON file, or '-' for stdin")
    p_fp.set_defaults(func=_cmd_flight_plan)

    # preflight
    p_pf = sub.add_parser("preflight", help="Set action to pre-flight")
    p_pf.set_defaults(func=_cmd_preflight)

    # planning
    p_pl = sub.add_parser("planning", help="Set action to planning")
    p_pl.set_defaults(func=_cmd_planning)

    # flight
    p_fl = sub.add_parser("flight", help="Start a flight")
    p_fl.add_argument("n", type=int, help="Flight number (1-based)")
    p_fl.set_defaults(func=_cmd_flight)

    # flight-done
    p_fd = sub.add_parser("flight-done", help="Complete a flight")
    p_fd.add_argument("n", type=int, help="Flight number (1-based)")
    p_fd.set_defaults(func=_cmd_flight_done)

    # review
    p_rv = sub.add_parser("review", help="Set action to post-wave review")
    p_rv.set_defaults(func=_cmd_review)

    # complete
    p_cp = sub.add_parser("complete", help="Complete a wave (defaults to the current wave)")
    p_cp.add_argument(
        "wave_id",
        nargs="?",
        default=None,
        help="Wave id to complete (ENG-1 / #846); defaults to current_wave when omitted",
    )
    p_cp.set_defaults(func=_cmd_complete)

    # waiting
    p_wt = sub.add_parser("waiting", help="Set action to waiting-on-meatbag")
    p_wt.add_argument("msg", nargs="?", default="", help="Optional message")
    p_wt.set_defaults(func=_cmd_waiting)

    # waiting-ci
    p_wci = sub.add_parser("waiting-ci", help="Heartbeat during CI polling")
    p_wci.add_argument("detail", nargs="?", default="", help="Optional detail string")
    p_wci.set_defaults(func=_cmd_waiting_ci)

    # dynamic-driver coarse states (#738)
    p_lc = sub.add_parser("launching", help="Coarse state: about to launch the per-wave Workflow")
    p_lc.add_argument("wave", nargs="?", default="", help="Wave id")
    p_lc.set_defaults(func=_cmd_launching)

    p_av = sub.add_parser("awaiting-verdict", help="Coarse state: per-wave Workflow in flight, awaiting verdict")
    p_av.add_argument("wave", nargs="?", default="", help="Wave id")
    p_av.set_defaults(func=_cmd_awaiting_verdict)

    p_pr = sub.add_parser("promoting", help="Coarse state: promoting a PASS wave")
    p_pr.add_argument("wave", nargs="?", default="", help="Wave id")
    p_pr.set_defaults(func=_cmd_promoting)

    p_hd = sub.add_parser("hold", help="Coarse state: paused for human attention (HOLD / adjudication)")
    p_hd.add_argument("reason", nargs="?", default="", help="Hold reason")
    p_hd.set_defaults(func=_cmd_hold)

    # hold-wave — durable per-wave 'held' terminal status (ENG-1 / #846).
    # Distinct from the coarse-state 'hold' above: this sets waves[<id>].status,
    # NOT current_action, and never advances current_wave.
    p_hw = sub.add_parser(
        "hold-wave",
        help="Mark a non-promoted wave 'held' without advancing current_wave (ENG-1 / #846)",
    )
    p_hw.add_argument("wave_id", help="Wave id to hold")
    p_hw.add_argument("--detail", default="", help="Optional hold detail (why the wave held)")
    p_hw.set_defaults(func=_cmd_hold_wave)

    # durable cross-wave campaign trajectory (#748)
    p_tr = sub.add_parser("trajectory-append", help="Upsert a wave's terminal entry into the durable cross-wave trajectory (judgment seed)")
    p_tr.add_argument("wave", help="Wave id")
    p_tr.add_argument("entry", help="Path to entry JSON, or '-' for stdin")
    p_tr.set_defaults(func=_cmd_trajectory_append)

    p_ts = sub.add_parser("trajectory-show", help="Print the durable cross-wave trajectory as a JSON array (judgment-seed / dashboard read path)")
    p_ts.set_defaults(func=_cmd_trajectory_show)

    # close-issue
    p_ci = sub.add_parser("close-issue", help="Close an issue by number or qualified ref")
    p_ci.add_argument(
        "n",
        type=str,
        help="Issue number (e.g. 13) or qualified ref (e.g. owner/repo#13)",
    )
    p_ci.set_defaults(func=_cmd_close_issue)

    # record-mr
    p_mr = sub.add_parser("record-mr", help="Record an MR/PR for an issue")
    p_mr.add_argument(
        "issue",
        type=str,
        help="Issue number (e.g. 13) or qualified ref (e.g. owner/repo#13)",
    )
    p_mr.add_argument("mr", help="MR/PR reference (e.g. '#14')")
    p_mr.set_defaults(func=_cmd_record_mr)

    # defer
    p_df = sub.add_parser("defer", help="Append a pending deferral")
    p_df.add_argument("desc", help="Description of the deferred item")
    p_df.add_argument("risk", choices=["low", "medium", "high"],
                       help="Risk level: low, medium, high")
    p_df.set_defaults(func=_cmd_defer)

    # defer-accept
    p_da = sub.add_parser("defer-accept", help="Accept a pending deferral")
    p_da.add_argument("index", type=int, help="1-based deferral index")
    p_da.set_defaults(func=_cmd_defer_accept)

    # set-current
    p_sc = sub.add_parser(
        "set-current",
        help="Set current_wave to <wave-id> (must exist in the plan)",
    )
    p_sc.add_argument("wave_id", help="Wave ID (e.g. 'wave-6a')")
    p_sc.set_defaults(func=_cmd_set_current)

    # set-kahuna-branch
    p_skb = sub.add_parser(
        "set-kahuna-branch",
        help="Set or clear the active KAHUNA integration branch (devspec §5.1.4)",
    )
    p_skb.add_argument(
        "branch",
        nargs="?",
        default="",
        help="Branch name (e.g. 'kahuna/42-foo'); pass empty to clear",
    )
    p_skb.set_defaults(func=_cmd_set_kahuna_branch)

    # wavemachine-start
    p_ws = sub.add_parser(
        "wavemachine-start",
        help="Mark the plan as driven by wavemachine (sets wavemachine_active)",
    )
    p_ws.add_argument(
        "--launcher",
        default="",
        help="Optional label identifying who started the run (e.g. agent task ID)",
    )
    p_ws.set_defaults(func=_cmd_wavemachine_start)

    # wavemachine-stop
    p_wst = sub.add_parser(
        "wavemachine-stop",
        help="Clear wavemachine_active (call from worker on abort or clean exit)",
    )
    p_wst.set_defaults(func=_cmd_wavemachine_stop)

    # emit — FlightDeck event emit (buffer + fire-and-forget ingest, #863).
    # REMAINDER captures the full emit option surface so the emit CLI stays the
    # single source of truth (see: python -m wave_status.events.emit -h).
    p_em = sub.add_parser(
        "emit",
        help="Emit one FlightDeck event to the durable buffer + ingest",
    )
    p_em.add_argument(
        "emit_args",
        nargs=argparse.REMAINDER,
        help="<kind> [--wave …] [--metric …] … (see the emit CLI -h)",
    )
    p_em.set_defaults(func=_cmd_emit)

    # campaign-head (flightdeck#1145, cc-workflow#1154): computes
    # planTotal/workItemsTotal/waveWorkItems/project from the plan itself rather than
    # requiring the caller to hand-type them.
    p_ch = sub.add_parser(
        "campaign-head",
        help="Emit the FlightDeck campaign card head, deriving planTotal/workItemsTotal/waveWorkItems from the plan",
    )
    p_ch.add_argument(
        "--activity-id", dest="activity_id", required=True,
        help="the plan id (e.g. $FLIGHTDECK_ACTIVITY_ID) — only the driver's shell has this",
    )
    p_ch.add_argument(
        "--agent", default=None,
        help="Dev-Name (card title); omit to resolve it from <cwd>/.claude/agent-identity.json "
             "(cc-workflow#1163), falling back to the project label when no identity resolves",
    )
    p_ch.add_argument(
        "--session", default=None,
        help="AX-4 stable session identity, distinct from --agent (Dev-Name); omit to resolve "
             "it from FLIGHTDECK_SESSION_ID/CLAUDE_CODE_SESSION_ID (cc-workflow#1146 step 3 / #1165)",
    )
    p_ch.set_defaults(func=_cmd_campaign_head)

    # wave-begin (cc-workflow#1138 step 2, #1170): idempotently own the
    # activity_start head for a wave's activity id — no --label/--detail-json/
    # --activity-type, unlike campaign-head. See _cmd_wave_begin's docstring
    # for why that narrowness is the idempotency guarantee.
    p_wb = sub.add_parser(
        "wave-begin",
        help="Idempotently emit the FlightDeck activity_start head for a wave's activity id",
    )
    p_wb.add_argument("activity_id", help="the AID the wave's tee resolved to (planId, or waveId on a bare/test run)")
    p_wb.add_argument("wave", help="the wave id")
    p_wb.add_argument(
        "--agent", default=None,
        help="Dev-Name; omit to auto-resolve (same as emit/campaign-head, cc-workflow#1163)",
    )
    p_wb.add_argument(
        "--session", default=None,
        help="AX-4 stable session identity; omit to auto-resolve (cc-workflow#1146 step 3 / #1165)",
    )
    p_wb.set_defaults(func=_cmd_wave_begin)

    # show
    p_sh = sub.add_parser("show", help="Print status summary (read-only)")
    p_sh.set_defaults(func=_cmd_show)

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(2)

    try:
        args.func(args)
    except json.JSONDecodeError as exc:
        # Invalid JSON input is an unexpected error, not a state/deferral
        # ValueError — even though JSONDecodeError is a ValueError subclass.
        print(str(exc), file=sys.stderr)
        sys.exit(2)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"Unexpected error: {exc}", file=sys.stderr)
        sys.exit(2)


def _run_as_script() -> None:
    """The real top-level entry-point body for the ``wave-status`` CLI
    (#1149).

    This is the TRUE top-level entry point — every subcommand (`emit`,
    `campaign-head`, `close-issue`, ...) is dispatched from here, in-process,
    via `main()`. That matters because some of them can start a FlightDeck
    shipper daemon thread (`wave_status.events.emit._ship_async`) which must
    never block its caller — so the bounded join that protects against the
    daemon-thread/interpreter-shutdown segfault race belongs ONLY here,
    never inside `main()` or any `_cmd_*` handler (which are also called
    in-process by tests). See
    `wave_status.events.emit.flush_pending_ships`'s docstring for the full
    rationale — it is the same one this function exists to apply.

    Factored out of the ``if __name__ == "__main__":`` guard so tests can
    call it directly with ``os._exit`` mocked — actually invoking
    ``os._exit`` would kill the test process. This function has a SECOND
    caller beyond that guard: the zipapp shim ``scripts/ci/build.sh``
    generates for the shipped ``wave-status`` binary calls it directly
    (``getattr(_m, "_run_as_script", _m.main)()``), since that shim imports
    this module rather than running it — the ``__main__`` guard never fires
    there at all, and that gap was the original version of this fix's
    critical bug (the join existed but was unreachable in production).
    """
    from wave_status.events.emit import _flush_std_streams, flush_pending_ships

    _code = 0
    try:
        main()
    except SystemExit as exc:
        code = exc.code
        if code is None:
            _code = 0
        elif isinstance(code, int):
            _code = code
        else:
            print(str(code), file=sys.stderr)
            _code = 1
    finally:
        flush_pending_ships()
        _flush_std_streams()
    # os._exit, not a bare return: skips Py_Finalize's interpreter teardown
    # entirely, safe here specifically because flush_pending_ships() already
    # ran. See emit.py's mirrored guard for the full "why os._exit, why here
    # only" rationale — identical reasoning, same fix, the other true entry
    # point.
    os._exit(_code)


if __name__ == "__main__":
    _run_as_script()
