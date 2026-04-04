"""CLI entry point for campaign_status -- argparse subcommand dispatch.

Wires subcommands to the state machine (state.py) and dashboard
generator (dashboard/generator.py).

Usage::

    python -m campaign_status <subcommand> [args]

Requires Python 3.10+ stdlib only -- no external dependencies.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from campaign_status.dashboard.generator import generate_dashboard
from campaign_status.state import (
    STAGES,
    campaign_dir,
    defer_item,
    get_project_root,
    init_campaign,
    load_json,
    show_campaign,
    stage_complete,
    stage_review,
    stage_start,
)


# ---------------------------------------------------------------------------
# Dashboard regeneration helper
# ---------------------------------------------------------------------------

def _regenerate_dashboard(root: Path) -> None:
    """Load all JSON files fresh from disk and regenerate the dashboard."""
    d = campaign_dir(root)
    campaign_data = load_json(d / "campaign.json")
    state_data = load_json(d / "campaign-state.json")
    items_data = load_json(d / "campaign-items.json")
    generate_dashboard(root, campaign_data, state_data, items_data)


# ---------------------------------------------------------------------------
# Git integration helper
# ---------------------------------------------------------------------------

def _git_commit(root: Path, message: str) -> None:
    """Stage ``.sdlc/`` and commit with *message*.

    Best-effort: if git fails (not in a repo, nothing to commit, etc.),
    print a warning but do not crash.  Does NOT push.
    """
    sdlc_path = str(campaign_dir(root))
    try:
        subprocess.run(
            ["git", "add", sdlc_path],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"sdlc: {message}"],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Warning: git commit failed: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def _cmd_init(args: argparse.Namespace) -> None:
    """Handle ``init <project-name>``."""
    root = get_project_root()
    init_campaign(args.project_name, root)
    _regenerate_dashboard(root)
    _git_commit(root, f"init campaign '{args.project_name}'")
    print(f"Campaign '{args.project_name}' initialized in .sdlc/")


def _cmd_stage_start(args: argparse.Namespace) -> None:
    """Handle ``stage-start <stage>``."""
    root = get_project_root()
    stage_start(args.stage, root)
    _regenerate_dashboard(root)
    _git_commit(root, f"start stage '{args.stage}'")
    print(f"Stage '{args.stage}' is now active.")


def _cmd_stage_review(args: argparse.Namespace) -> None:
    """Handle ``stage-review <stage>``."""
    root = get_project_root()
    stage_review(args.stage, root)
    _regenerate_dashboard(root)
    _git_commit(root, f"stage '{args.stage}' moved to review")
    print(f"Stage '{args.stage}' is now in review.")


def _cmd_stage_complete(args: argparse.Namespace) -> None:
    """Handle ``stage-complete <stage>``."""
    root = get_project_root()
    stage_complete(args.stage, root)
    _regenerate_dashboard(root)
    _git_commit(root, f"stage '{args.stage}' complete")
    print(f"Stage '{args.stage}' is now complete.")


def _cmd_defer(args: argparse.Namespace) -> None:
    """Handle ``defer <item> --reason <text>``."""
    root = get_project_root()
    defer_item(args.item, args.reason, root)
    _regenerate_dashboard(root)
    _git_commit(root, f"defer '{args.item}'")
    print(f"Deferred: {args.item}")


def _cmd_show(args: argparse.Namespace) -> None:
    """Handle ``show`` -- print summary, NO dashboard regen, NO git commit."""
    root = get_project_root()
    summary = show_campaign(root)
    lines = [
        f"Project:      {summary['project']}",
        f"Active Stage: {summary['active_stage']}",
        "Stages:",
    ]
    lines.extend(summary["stage_lines"])
    lines.append(f"Deferrals:    {summary['deferrals_count']}")
    if summary["deferrals"]:
        for d in summary["deferrals"]:
            lines.append(f"  - {d['item']}: {d['reason']} (stage: {d.get('stage', 'unknown')})")
    print("\n".join(lines))


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Construct the argparse parser with all 6 subcommands."""
    parser = argparse.ArgumentParser(
        prog="campaign-status",
        description="SDLC campaign lifecycle CLI -- stage tracking, gates, deferrals",
    )
    sub = parser.add_subparsers(dest="command")

    # init
    p_init = sub.add_parser("init", help="Initialize campaign with project name")
    p_init.add_argument("project_name", help="Name of the project/campaign")
    p_init.set_defaults(func=_cmd_init)

    # stage-start
    p_ss = sub.add_parser("stage-start", help="Start a campaign stage")
    p_ss.add_argument("stage", choices=STAGES, help="Stage to start")
    p_ss.set_defaults(func=_cmd_stage_start)

    # stage-review
    p_sr = sub.add_parser("stage-review", help="Move a stage to review")
    p_sr.add_argument("stage", choices=STAGES, help="Stage to review")
    p_sr.set_defaults(func=_cmd_stage_review)

    # stage-complete
    p_sc = sub.add_parser("stage-complete", help="Mark a stage as complete")
    p_sc.add_argument("stage", choices=STAGES, help="Stage to complete")
    p_sc.set_defaults(func=_cmd_stage_complete)

    # defer
    p_df = sub.add_parser("defer", help="Defer a deliverable or work item")
    p_df.add_argument("item", help="Description of the deferred item")
    p_df.add_argument("--reason", required=True, help="Reason for deferral")
    p_df.set_defaults(func=_cmd_defer)

    # show
    p_sh = sub.add_parser("show", help="Print current campaign state (read-only)")
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
