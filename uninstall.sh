#!/usr/bin/env bash
# uninstall.sh — Remove Claude Code workflow environment
#
# Removes skills, scripts, config, and MCP servers installed by install.sh.
# Does NOT remove settings.json or credentials.
#
# Usage:
#   ./uninstall.sh              Remove everything (skills, scripts, config, mcps)
#   ./uninstall.sh --dry-run    Show what would be removed without doing it
#   ./uninstall.sh --skills     Remove skills only
#   ./uninstall.sh --scripts    Remove scripts and packages only
#   ./uninstall.sh --config     Remove config files only (statusline-command.sh)
#   ./uninstall.sh --mcps       Remove MCP server registrations only
#
# What full uninstall removes:
#   Skills      → ~/.claude/skills/<name>/
#   Scripts     → ~/.local/bin/<name>
#   Packages    → ~/.local/bin/<name> (built artifacts)
#   Config      → ~/.claude/statusline-command.sh
#   MCPs        → MCP server registrations (via each MCP's --uninstall)
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
REMOVE_MCPS=true

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
		REMOVE_MCPS=false
		shift
		;;
	--scripts)
		REMOVE_SKILLS=false
		REMOVE_CONFIG=false
		REMOVE_MCPS=false
		shift
		;;
	--config)
		REMOVE_SKILLS=false
		REMOVE_SCRIPTS=false
		REMOVE_MCPS=false
		shift
		;;
	--mcps)
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
		# Remove helper scripts (non-.md files) from ~/.local/bin/
		# (.md files live in the skill dir and are removed with it above)
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			[[ "$helper_name" == *.md ]] && continue
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

# --- Remove MCP servers -------------------------------------------------------
if [[ "$REMOVE_MCPS" == true ]]; then
	echo ""
	echo "Removing MCP servers"
	echo "──────────────────────────────────────────"
	if [[ -f "$REPO_DIR/mcps.json" ]] && command -v jq &>/dev/null; then
		for mcp_name in $(jq -r '.mcps | keys[]' "$REPO_DIR/mcps.json"); do
			install_url=$(jq -r ".mcps[\"$mcp_name\"].install_url" "$REPO_DIR/mcps.json")
			if [[ "$DRY_RUN" == true ]]; then
				echo "  [+] (dry-run) Would uninstall MCP server: $mcp_name"
			else
				info "Uninstalling $mcp_name..."
				if curl -fsSL "$install_url" | bash -s -- --uninstall; then
					info "$mcp_name removed"
				else
					echo "  [!] Failed to uninstall $mcp_name"
				fi
			fi
		done
	elif ! command -v jq &>/dev/null; then
		echo "  [!] jq not found — cannot read mcps.json"
	else
		echo "  [!] mcps.json not found — cannot determine MCP servers to remove"
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
