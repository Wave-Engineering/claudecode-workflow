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
#   ./install.sh --channels   Install channel servers only (bun install + MCP registration)
#
# Targets:
#   Skills     → ~/.claude/skills/<name>/SKILL.md
#   Scripts    → ~/.local/bin/<name>
#   Statusline → ~/.claude/statusline-command.sh
#   Channels   → user-scope MCP servers (claude mcp add --scope user)
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
INSTALL_CHANNELS=true

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
		INSTALL_CHANNELS=false
		shift
		;;
	--scripts)
		INSTALL_SKILLS=false
		INSTALL_CONFIG=false
		INSTALL_CHANNELS=false
		shift
		;;
	--config)
		INSTALL_SKILLS=false
		INSTALL_SCRIPTS=false
		INSTALL_CHANNELS=false
		shift
		;;
	--channels)
		INSTALL_SKILLS=false
		INSTALL_SCRIPTS=false
		INSTALL_CONFIG=false
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

	if [[ -d "$REPO_DIR/src" ]]; then
		echo ""
		echo "Packages"
		echo "──────────────────────────────────────────"
		# Rebuild to ensure fresh comparison
		"$REPO_DIR/scripts/ci/build.sh" >/dev/null 2>&1 || true
		for pkg_dir in "$REPO_DIR"/src/*/; do
			[[ -f "$pkg_dir/__main__.py" ]] || continue
			pkg_name="$(basename "$pkg_dir")"
			artifact_name="${pkg_name//_/-}"
			src="$REPO_DIR/dist/$artifact_name"
			dest="$SCRIPTS_DIR/$artifact_name"
			if [[ -f "$src" ]]; then
				total=$((total + 1))
				do_check "$src" "$dest" "$artifact_name" || drifted=$((drifted + 1))
			fi
		done
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
			# Merge statusLine config into existing settings.json if missing
			if [[ "$DRY_RUN" != true ]] && command -v jq &>/dev/null; then
				if ! jq -e '.statusLine' "$CLAUDE_DIR/settings.json" &>/dev/null; then
					cp "$CLAUDE_DIR/settings.json" "$CLAUDE_DIR/settings.json.bak"
					jq '.statusLine = {"type": "command", "command": "bash ~/.claude/statusline-command.sh"}' \
						"$CLAUDE_DIR/settings.json.bak" >"$CLAUDE_DIR/settings.json"
					info "Merged statusLine config into existing settings.json"
				else
					skip "statusLine already configured in settings.json"
				fi
			elif [[ "$DRY_RUN" == true ]]; then
				info "(dry-run) Would merge statusLine config into settings.json if missing"
			fi
		else
			do_copy "$REPO_DIR/config/settings.template.json" "$CLAUDE_DIR/settings.json"
		fi
	fi
fi

# --- Build and install packages -----------------------------------------------
if [[ "$INSTALL_SCRIPTS" == true && -d "$REPO_DIR/src" ]]; then
	echo ""
	echo "Packages → $SCRIPTS_DIR"
	echo "──────────────────────────────────────────"
	# Build from source
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) Would run scripts/ci/build.sh"
	else
		"$REPO_DIR/scripts/ci/build.sh"
	fi
	# Install built artifacts
	for pkg_dir in "$REPO_DIR"/src/*/; do
		[[ -f "$pkg_dir/__main__.py" ]] || continue
		pkg_name="$(basename "$pkg_dir")"
		artifact_name="${pkg_name//_/-}"
		src="$REPO_DIR/dist/$artifact_name"
		dest="$SCRIPTS_DIR/$artifact_name"
		if [[ "$DRY_RUN" == true ]]; then
			info "(dry-run) $src → $dest"
		else
			if [[ -f "$src" ]]; then
				do_copy "$src" "$dest"
				chmod +x "$dest"
			else
				warn "Expected artifact not found: $src"
			fi
		fi
	done
fi

# --- Install channel servers --------------------------------------------------
if [[ "$INSTALL_CHANNELS" == true && -d "$REPO_DIR/channels" ]]; then
	echo ""
	echo "Channel servers"
	echo "──────────────────────────────────────────"
	if ! command -v bun &>/dev/null; then
		warn "bun not found — skipping channel server setup"
		warn "Install bun (https://bun.sh) and re-run to enable channel servers"
	elif ! command -v claude &>/dev/null; then
		warn "claude CLI not found — skipping MCP registration"
	else
		for channel_dir in "$REPO_DIR"/channels/*/; do
			[[ -f "$channel_dir/package.json" ]] || continue
			channel_name="$(basename "$channel_dir")"
			entry_file="$channel_dir/index.ts"
			[[ -f "$entry_file" ]] || continue

			# Install dependencies
			if [[ "$DRY_RUN" == true ]]; then
				info "(dry-run) bun install in $channel_dir"
				info "(dry-run) claude mcp add --scope user $channel_name"
			else
				if [[ ! -d "$channel_dir/node_modules" ]]; then
					info "Installing dependencies for $channel_name..."
					(cd "$channel_dir" && bun install --silent)
				else
					skip "$channel_name dependencies (already installed)"
				fi

				# Register at user scope (idempotent — overwrites existing)
				if claude mcp add --scope user --transport stdio \
					"$channel_name" -- bun "$entry_file" 2>/dev/null; then
					info "Registered MCP server: $channel_name (user scope)"
				else
					warn "Failed to register MCP server: $channel_name"
					warn "Run manually: claude mcp add --scope user --transport stdio $channel_name -- bun $entry_file"
				fi
			fi
		done
	fi
fi

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
for cmd in curl jq bun glab gh python3 shellcheck shfmt; do
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

if [[ -f "$HOME/secrets/discord-bot-token" ]]; then
	info "discord-bot-token found"
else
	warn "$HOME/secrets/discord-bot-token — NOT FOUND (needed for /disc and discord-watcher)"
fi

if [[ ${#missing[@]} -gt 0 ]]; then
	echo ""
	warn "Missing dependencies: ${missing[*]}"
	echo "  Install them before using the skills that require them."
fi
