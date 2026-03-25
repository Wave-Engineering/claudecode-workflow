#!/usr/bin/env bash
# install.sh — Deploy Claude Code workflow environment
#
# Installs skills, scripts, and config from this repo
# into the correct locations on the local machine.
#
# Usage:
#   ./install.sh              Install everything
#   ./install.sh --dry-run    Show what would be done without doing it
#   ./install.sh --check      Show drift between repo and installed versions
#   ./install.sh --skills     Install skills only
#   ./install.sh --scripts    Install scripts only
#   ./install.sh --config     Install config files only (statusline, settings template)
#
# Targets:
#   Skills     → ~/.claude/skills/<name>/SKILL.md
#   Scripts    → ~/.local/bin/<name>
#   Statusline → ~/.claude/statusline-command.sh
#
# Existing files are backed up to <file>.bak before overwriting.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
CLAUDE_DIR="$HOME/.claude"
DRY_RUN=false
CHECK_MODE=false
INSTALL_SKILLS=true
INSTALL_SCRIPTS=true
INSTALL_CONFIG=true

# --- Parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
	case "$1" in
	--dry-run)
		DRY_RUN=true
		shift
		;;
	--check)
		CHECK_MODE=true
		shift
		;;
	--skills)
		INSTALL_SCRIPTS=false
		INSTALL_CONFIG=false
		shift
		;;
	--scripts)
		INSTALL_SKILLS=false
		INSTALL_CONFIG=false
		shift
		;;
	--config)
		INSTALL_SKILLS=false
		INSTALL_SCRIPTS=false
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
info() { echo "  [+] $*"; }
warn() { echo "  [!] $*"; }
skip() { echo "  [-] $*"; }
drift() { echo "  [~] $*"; }

do_copy() {
	local src="$1" dest="$2"
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) $src → $dest"
		return
	fi
	if [[ -f "$dest" ]]; then
		if diff -q "$src" "$dest" &>/dev/null; then
			skip "$dest (unchanged)"
			return
		fi
		cp "$dest" "${dest}.bak"
		warn "Backed up existing: ${dest}.bak"
	fi
	mkdir -p "$(dirname "$dest")"
	cp "$src" "$dest"
	info "$src → $dest"
}

do_check() {
	local src="$1" dest="$2" label="$3"
	if [[ ! -f "$dest" ]]; then
		drift "$label — NOT INSTALLED"
		return 1
	elif ! diff -q "$src" "$dest" &>/dev/null; then
		drift "$label — DIFFERS"
		return 1
	else
		info "$label (in sync)"
		return 0
	fi
}

# --- Check mode ---------------------------------------------------------------
if [[ "$CHECK_MODE" == true ]]; then
	echo ""
	echo "Sync check: repo vs installed"
	echo "══════════════════════════════════════════"
	total=0
	drifted=0

	echo ""
	echo "Skills"
	echo "──────────────────────────────────────────"
	for skill_dir in "$REPO_DIR"/skills/*/; do
		skill_name="$(basename "$skill_dir")"
		# Check SKILL.md
		src="$skill_dir/SKILL.md"
		dest="$SKILLS_DIR/$skill_name/SKILL.md"
		if [[ -f "$src" ]]; then
			total=$((total + 1))
			do_check "$src" "$dest" "$skill_name" || drifted=$((drifted + 1))
		fi
		# Check helper scripts (non-SKILL.md files)
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			total=$((total + 1))
			do_check "$helper" "$SCRIPTS_DIR/$helper_name" "$skill_name/$helper_name" || drifted=$((drifted + 1))
		done
	done

	echo ""
	echo "Scripts"
	echo "──────────────────────────────────────────"
	for script in "$REPO_DIR"/scripts/*; do
		[[ -f "$script" ]] || continue
		[[ -d "$script" ]] && continue
		script_name="$(basename "$script")"
		dest="$SCRIPTS_DIR/$script_name"
		total=$((total + 1))
		do_check "$script" "$dest" "$script_name" || drifted=$((drifted + 1))
	done

	echo ""
	echo "Config"
	echo "──────────────────────────────────────────"
	if [[ -f "$REPO_DIR/config/statusline-command.sh" ]]; then
		total=$((total + 1))
		do_check "$REPO_DIR/config/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh" "statusline-command.sh" || drifted=$((drifted + 1))
	fi

	echo ""
	echo "══════════════════════════════════════════"
	if [[ $drifted -eq 0 ]]; then
		echo "All $total items in sync."
	else
		echo "$drifted of $total items out of sync."
		echo "Run ./install.sh to update."
	fi
	exit 0
fi

# --- Install skills -----------------------------------------------------------
if [[ "$INSTALL_SKILLS" == true ]]; then
	echo ""
	echo "Skills → $SKILLS_DIR"
	echo "──────────────────────────────────────────"
	for skill_dir in "$REPO_DIR"/skills/*/; do
		skill_name="$(basename "$skill_dir")"
		# Install SKILL.md
		src="$skill_dir/SKILL.md"
		dest="$SKILLS_DIR/$skill_name/SKILL.md"
		[[ -f "$src" ]] && do_copy "$src" "$dest"
		# Install helper scripts (non-SKILL.md files) to ~/.local/bin/
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			do_copy "$helper" "$SCRIPTS_DIR/$helper_name"
			if [[ "$DRY_RUN" != true ]]; then
				chmod +x "$SCRIPTS_DIR/$helper_name"
			fi
		done
	done
fi

# --- Install scripts ----------------------------------------------------------
if [[ "$INSTALL_SCRIPTS" == true ]]; then
	echo ""
	echo "Scripts → $SCRIPTS_DIR"
	echo "──────────────────────────────────────────"
	for script in "$REPO_DIR"/scripts/*; do
		[[ -f "$script" ]] || continue
		[[ -d "$script" ]] && continue
		script_name="$(basename "$script")"
		dest="$SCRIPTS_DIR/$script_name"
		do_copy "$script" "$dest"
		if [[ "$DRY_RUN" != true ]]; then
			chmod +x "$dest"
		fi
	done
fi

# --- Install config -----------------------------------------------------------
if [[ "$INSTALL_CONFIG" == true ]]; then
	echo ""
	echo "Config → $CLAUDE_DIR"
	echo "──────────────────────────────────────────"
	if [[ -f "$REPO_DIR/config/statusline-command.sh" ]]; then
		do_copy "$REPO_DIR/config/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"
		if [[ "$DRY_RUN" != true ]]; then
			chmod +x "$CLAUDE_DIR/statusline-command.sh"
		fi
	fi

	if [[ -f "$REPO_DIR/config/settings.template.json" ]]; then
		if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
			skip "settings.json already exists (won't overwrite — use settings.template.json as reference)"
		else
			do_copy "$REPO_DIR/config/settings.template.json" "$CLAUDE_DIR/settings.json"
		fi
	fi
fi

# Package builds added by Story 4.1

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
	echo "Dry run complete. No files were modified."
else
	echo "Installation complete."
fi

# --- Dependency check ---------------------------------------------------------
echo ""
echo "Dependency check:"
missing=()
for cmd in curl jq glab gh python3 shellcheck shfmt; do
	if command -v "$cmd" &>/dev/null; then
		info "$cmd $(command -v "$cmd")"
	else
		warn "$cmd — NOT FOUND"
		missing+=("$cmd")
	fi
done

if [[ -f "$HOME/secrets/slack-bot-token" ]]; then
	info "slack-bot-token found"
else
	warn "$HOME/secrets/slack-bot-token — NOT FOUND (needed for /ping)"
fi

if [[ ${#missing[@]} -gt 0 ]]; then
	echo ""
	warn "Missing dependencies: ${missing[*]}"
	echo "  Install them before using the skills that require them."
fi
