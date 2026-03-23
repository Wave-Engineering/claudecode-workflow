#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code workflow environment
#
# Removes skills and scripts installed by install.sh.
# Does NOT remove settings.json or credentials.
#
# Usage:
#   ./uninstall.sh              Remove everything
#   ./uninstall.sh --dry-run    Show what would be removed without doing it
#   ./uninstall.sh --skills     Remove skills only
#   ./uninstall.sh --scripts    Remove scripts only

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
CLAUDE_DIR="$HOME/.claude"
DRY_RUN=false
REMOVE_SKILLS=true
REMOVE_SCRIPTS=true
REMOVE_CONFIG=true

# --- Parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
	case "$1" in
	--dry-run)
		DRY_RUN=true
		shift
		;;
	--skills)
		REMOVE_SCRIPTS=false
		REMOVE_CONFIG=false
		shift
		;;
	--scripts)
		REMOVE_SKILLS=false
		REMOVE_CONFIG=false
		shift
		;;
	--help | -h)
		grep '^#' "$0" | sed 's/^# \?//' | tail -n +2
		exit 0
		;;
	*)
		echo "Unknown option: $1" >&2
		exit 1
		;;
	esac
done

# --- Helpers ------------------------------------------------------------------
info() { echo "  [+] Removed: $*"; }
skip() { echo "  [-] Not found: $*"; }

do_remove() {
	local path="$1"
	if [[ ! -e "$path" ]]; then
		skip "$path"
		return
	fi
	if [[ "$DRY_RUN" == true ]]; then
		echo "  [+] (dry-run) Would remove: $path"
		return
	fi
	rm -rf "$path"
	info "$path"
}

# --- Remove skills ------------------------------------------------------------
if [[ "$REMOVE_SKILLS" == true ]]; then
	echo ""
	echo "Removing skills from $SKILLS_DIR"
	echo "──────────────────────────────────────────"
	for skill_dir in "$REPO_DIR"/skills/*/; do
		skill_name="$(basename "$skill_dir")"
		do_remove "$SKILLS_DIR/$skill_name"
	done
fi

# --- Remove scripts -----------------------------------------------------------
if [[ "$REMOVE_SCRIPTS" == true ]]; then
	echo ""
	echo "Removing scripts from $SCRIPTS_DIR"
	echo "──────────────────────────────────────────"
	for script in "$REPO_DIR"/scripts/*; do
		[[ -f "$script" ]] || continue
		[[ -d "$script" ]] && continue
		script_name="$(basename "$script")"
		do_remove "$SCRIPTS_DIR/$script_name"
	done
fi

# --- Remove config ------------------------------------------------------------
if [[ "$REMOVE_CONFIG" == true ]]; then
	echo ""
	echo "Removing config from $CLAUDE_DIR"
	echo "──────────────────────────────────────────"
	do_remove "$CLAUDE_DIR/statusline-command.sh"
	echo "  [-] settings.json — preserved (not managed by uninstall)"
fi

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
	echo "Dry run complete. No files were removed."
else
	echo "Uninstall complete."
fi
