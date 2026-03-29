#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code workflow environment
#
# Removes skills, scripts, config, and channel servers installed by install.sh.
# Does NOT remove settings.json or credentials.
#
# Usage:
#   ./uninstall.sh              Remove everything (skills, scripts, config, channels)
#   ./uninstall.sh --dry-run    Show what would be removed without doing it
#   ./uninstall.sh --skills     Remove skills only
#   ./uninstall.sh --scripts    Remove scripts and packages only
#   ./uninstall.sh --config     Remove config files only (statusline-command.sh)
#   ./uninstall.sh --channels   Remove MCP server registrations only
#
# What full uninstall removes:
#   Skills      → ~/.claude/skills/<name>/
#   Scripts     → ~/.local/bin/<name>
#   Packages    → ~/.local/bin/<name> (built artifacts)
#   Config      → ~/.claude/statusline-command.sh
#   Channels    → MCP server registrations (claude mcp remove)
#
# What full uninstall preserves:
#   Settings    → ~/.claude/settings.json (user-customized)
#   Credentials → ~/secrets/ (not managed by install.sh)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
CLAUDE_DIR="$HOME/.claude"
DRY_RUN=false
REMOVE_SKILLS=true
REMOVE_SCRIPTS=true
REMOVE_CONFIG=true
REMOVE_CHANNELS=true

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
		REMOVE_CHANNELS=false
		shift
		;;
	--scripts)
		REMOVE_SKILLS=false
		REMOVE_CONFIG=false
		REMOVE_CHANNELS=false
		shift
		;;
	--config)
		REMOVE_SKILLS=false
		REMOVE_SCRIPTS=false
		REMOVE_CHANNELS=false
		shift
		;;
	--channels)
		REMOVE_SKILLS=false
		REMOVE_SCRIPTS=false
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
		# Remove helper scripts (non-SKILL.md files) from ~/.local/bin/
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			do_remove "$SCRIPTS_DIR/$helper_name"
		done
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

# --- Remove packages ----------------------------------------------------------
if [[ "$REMOVE_SCRIPTS" == true && -d "$REPO_DIR/src" ]]; then
	echo ""
	echo "Removing packages from $SCRIPTS_DIR"
	echo "──────────────────────────────────────────"
	for pkg_dir in "$REPO_DIR"/src/*/; do
		[[ -f "$pkg_dir/__main__.py" ]] || continue
		pkg_name="$(basename "$pkg_dir")"
		artifact_name="${pkg_name//_/-}"
		do_remove "$SCRIPTS_DIR/$artifact_name"
	done
fi

# --- Remove config ------------------------------------------------------------
if [[ "$REMOVE_CONFIG" == true ]]; then
	echo ""
	echo "Removing config from $CLAUDE_DIR"
	echo "──────────────────────────────────────────"
	# Discover config files from config/ directory
	if [[ -f "$REPO_DIR/config/statusline-command.sh" ]]; then
		do_remove "$CLAUDE_DIR/statusline-command.sh"
	fi
	echo "  [-] settings.json — preserved (not managed by uninstall)"
fi

# --- Remove channel servers ---------------------------------------------------
if [[ "$REMOVE_CHANNELS" == true ]]; then
	echo ""
	echo "Removing channel servers"
	echo "──────────────────────────────────────────"
	if command -v claude &>/dev/null; then
		mcp_list=$(claude mcp list 2>/dev/null || true)
		for channel_dir in "$REPO_DIR"/channels/*/; do
			[[ -f "$channel_dir/package.json" ]] || continue
			channel_name="$(basename "$channel_dir")"
			if echo "$mcp_list" | grep -q "$channel_name"; then
				if [[ "$DRY_RUN" == true ]]; then
					echo "  [+] (dry-run) Would remove MCP server: $channel_name"
				else
					if claude mcp remove --scope user "$channel_name" 2>/dev/null; then
						info "$channel_name (MCP server)"
					else
						echo "  [!] Failed to remove MCP server: $channel_name"
					fi
				fi
			else
				skip "$channel_name (MCP server not registered)"
			fi
		done
	else
		echo "  [!] claude CLI not found — cannot remove MCP servers"
	fi
fi

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
	echo "Dry run complete. No files were removed."
else
	echo "Uninstall complete."
fi
