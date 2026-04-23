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
import subprocess
import sys
from pathlib import Path

from wave_status import deferrals
from wave_status.dashboard.generator import generate_dashboard
from wave_status.state import (
    close_issue,
    complete,
    extend_state,
    flight,
    flight_done,
    get_project_root,
    init_state,
    load_json,
    load_state,
    planning,
    preflight,
    record_mr,
    review,
    save_json,
    set_current_wave,
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
    """Load all three JSON files fresh from disk and regenerate the dashboard."""
    d = status_dir(root)
    phases_data = load_json(d / "phases-waves.json")
    state_data = load_json(d / "state.json")
    flights_data = load_json(d / "flights.json")
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
    _regenerate_dashboard(root)


def _cmd_flight_plan(args: argparse.Namespace) -> None:
    """Handle ``flight-plan <file|->``."""
    root = get_project_root()
    raw = _read_json_source(args.file)
    flights_data = json.loads(raw)
    store_flight_plan(flights_data, root)
    _regenerate_dashboard(root)


def _cmd_preflight(args: argparse.Namespace) -> None:
    """Handle ``preflight``."""
    root = get_project_root()
    preflight(root)
    _regenerate_dashboard(root)


def _cmd_planning(args: argparse.Namespace) -> None:
    """Handle ``planning``."""
    root = get_project_root()
    planning(root)
    _regenerate_dashboard(root)


def _cmd_flight(args: argparse.Namespace) -> None:
    """Handle ``flight <N>``."""
    root = get_project_root()
    flight(args.n, root)
    _regenerate_dashboard(root)


def _cmd_flight_done(args: argparse.Namespace) -> None:
    """Handle ``flight-done <N>``."""
    root = get_project_root()
    flight_done(args.n, root)
    _regenerate_dashboard(root)


def _cmd_review(args: argparse.Namespace) -> None:
    """Handle ``review``."""
    root = get_project_root()
    review(root)
    _regenerate_dashboard(root)


def _cmd_complete(args: argparse.Namespace) -> None:
    """Handle ``complete``."""
    root = get_project_root()
    complete(root)
    _regenerate_dashboard(root)


def _cmd_waiting(args: argparse.Namespace) -> None:
    """Handle ``waiting [msg]``."""
    root = get_project_root()
    msg = args.msg if args.msg else ""
    waiting(root, msg=msg)
    _regenerate_dashboard(root)


def _cmd_waiting_ci(args: argparse.Namespace) -> None:
    """Handle ``waiting-ci [detail]``."""
    root = get_project_root()
    detail = args.detail if args.detail else ""
    waiting_ci(root, detail=detail)
    _regenerate_dashboard(root)


def _cmd_close_issue(args: argparse.Namespace) -> None:
    """Handle ``close-issue <N>``."""
    root = get_project_root()
    close_issue(args.n, root)
    _regenerate_dashboard(root)


def _cmd_record_mr(args: argparse.Namespace) -> None:
    """Handle ``record-mr <issue> <mr>``."""
    root = get_project_root()
    record_mr(args.issue, args.mr, root)
    _regenerate_dashboard(root)


def _cmd_defer(args: argparse.Namespace) -> None:
    """Handle ``defer <desc> <risk>``."""
    root = get_project_root()
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    if state_data.get("current_wave") is None:
        raise ValueError("no active wave — all waves are complete")
    deferrals.defer(state_data, args.desc, args.risk, state_data["current_wave"])
    save_json(d / "state.json", state_data)
    _regenerate_dashboard(root)


def _cmd_defer_accept(args: argparse.Namespace) -> None:
    """Handle ``defer-accept <index>``."""
    root = get_project_root()
    d = status_dir(root)
    state_data = load_state(d / "state.json")
    deferrals.accept(state_data, args.index)
    save_json(d / "state.json", state_data)
    _regenerate_dashboard(root)


def _cmd_set_current(args: argparse.Namespace) -> None:
    """Handle ``set-current <wave-id>``."""
    root = get_project_root()
    set_current_wave(args.wave_id, root)
    _regenerate_dashboard(root)


def _cmd_wavemachine_start(args: argparse.Namespace) -> None:
    """Handle ``wavemachine-start [--launcher <tag>]``."""
    root = get_project_root()
    wavemachine_start(root, launcher=args.launcher or "")
    _regenerate_dashboard(root)


def _cmd_wavemachine_stop(args: argparse.Namespace) -> None:
    """Handle ``wavemachine-stop``."""
    root = get_project_root()
    wavemachine_stop(root)
    _regenerate_dashboard(root)


def _cmd_show(args: argparse.Namespace) -> None:
    """Handle ``show`` — print summary, NO dashboard regen."""
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
    print("\n".join(lines))


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
    p_cp = sub.add_parser("complete", help="Complete the current wave")
    p_cp.set_defaults(func=_cmd_complete)

    # waiting
    p_wt = sub.add_parser("waiting", help="Set action to waiting-on-meatbag")
    p_wt.add_argument("msg", nargs="?", default="", help="Optional message")
    p_wt.set_defaults(func=_cmd_waiting)

    # waiting-ci
    p_wci = sub.add_parser("waiting-ci", help="Heartbeat during CI polling")
    p_wci.add_argument("detail", nargs="?", default="", help="Optional detail string")
    p_wci.set_defaults(func=_cmd_waiting_ci)

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


if __name__ == "__main__":
    main()
