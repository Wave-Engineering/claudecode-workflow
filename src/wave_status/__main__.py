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
    flight,
    flight_done,
    get_project_root,
    init_state,
    load_json,
    planning,
    preflight,
    record_mr,
    review,
    save_json,
    show,
    status_dir,
    store_flight_plan,
    waiting,
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
    root = get_project_root()
    raw = _read_json_source(args.file)
    plan_data = json.loads(raw)
    init_state(plan_data, root)
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
    state_data = load_json(d / "state.json")
    if state_data.get("current_wave") is None:
        raise ValueError("no active wave — all waves are complete")
    deferrals.defer(state_data, args.desc, args.risk, state_data["current_wave"])
    save_json(d / "state.json", state_data)
    _regenerate_dashboard(root)


def _cmd_defer_accept(args: argparse.Namespace) -> None:
    """Handle ``defer-accept <index>``."""
    root = get_project_root()
    d = status_dir(root)
    state_data = load_json(d / "state.json")
    deferrals.accept(state_data, args.index)
    save_json(d / "state.json", state_data)
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
    """Construct the argparse parser with all 14 subcommands."""
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

    # close-issue
    p_ci = sub.add_parser("close-issue", help="Close an issue by number")
    p_ci.add_argument("n", type=int, help="Issue number")
    p_ci.set_defaults(func=_cmd_close_issue)

    # record-mr
    p_mr = sub.add_parser("record-mr", help="Record an MR/PR for an issue")
    p_mr.add_argument("issue", type=int, help="Issue number")
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
