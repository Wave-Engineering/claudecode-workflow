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
#   ./install.sh --scripts    Install scripts only (also builds packages from src/)
#   ./install.sh --config     Install config files only (smart-merges settings.json)
#   ./install.sh --channels   Install channel servers only (bun install + MCP registration)
#
# Targets:
#   Skills     → ~/.claude/skills/<name>/SKILL.md
#   Scripts    → ~/.local/bin/<name>
#   Packages   → ~/.local/bin/<name> (built from src/ via scripts/ci/build.sh)
#   Statusline → ~/.claude/statusline-command.sh
#   Settings   → ~/.claude/settings.json (smart-merged: missing keys added, your
#                 customizations preserved — see merge_settings() for rules)
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

merge_settings() {
	local template="$1" target="$2"

	# Requires jq
	if ! command -v jq &>/dev/null; then
		warn "jq not found — cannot merge settings.json"
		return 1
	fi

	cp "$target" "${target}.bak"

	# Deep merge: template into local, preserving user customizations
	# Rules:
	#   1. Top-level keys (scalars AND objects like statusLine): added only if ABSENT locally
	#   2. hooks: add missing event keys from template; leave existing alone
	#   3. permissions.allow: union of both arrays (deduplicated)
	#   4. enabledPlugins: add missing keys from template; leave existing alone
	#   5. _comment keys: stripped from result (template-only documentation)
	#   6. Any key present locally but not in template: preserve as-is
	local merged
	merged=$(jq -s '
		# .[0] = template, .[1] = local

		# Top-level keys from template (excluding special-merge keys)
		(.[0] | to_entries | map(
			select(.key | IN("hooks", "permissions", "enabledPlugins", "_comment") | not)
		)) as $tpl_defaults |

		# Capture local keys before entering reduce
		(.[1] | keys) as $local_keys |

		# Merge hooks: add missing event keys
		((.[0].hooks // {}) | to_entries | map(
			select(.key != "_comment")
		)) as $tpl_hooks |
		((.[1].hooks // {}) | keys) as $local_hook_keys |
		($tpl_hooks | map(select(.key | IN($local_hook_keys[]) | not))) as $new_hooks |

		# Merge permissions.allow: union
		((.[0].permissions.allow // []) + (.[1].permissions.allow // []) | unique) as $merged_perms |

		# Merge enabledPlugins: add missing keys
		((.[0].enabledPlugins // {}) | to_entries) as $tpl_plugins |
		((.[1].enabledPlugins // {}) | keys) as $local_plugin_keys |
		($tpl_plugins | map(select(.key | IN($local_plugin_keys[]) | not))) as $new_plugins |

		# Build result: start with local, add missing pieces
		.[1]
		| .permissions.allow = $merged_perms
		| .hooks = ((.hooks // {}) + ($new_hooks | from_entries))
		| .enabledPlugins = ((.enabledPlugins // {}) + ($new_plugins | from_entries))
		| reduce ($tpl_defaults[] | select(.key | IN($local_keys[]) | not)) as $s (.; .[$s.key] = $s.value)
		| del(._comment)
		| del(.hooks._comment)
	' "$template" "$target")

	echo "$merged" >"$target"

	# Report what changed

	# Report new hooks
	for hook_event in $(jq -r '.hooks // {} | keys[] | select(. != "_comment")' "$template"); do
		if jq -e ".hooks.\"${hook_event}\"" "${target}.bak" &>/dev/null; then
			skip "hooks.$hook_event — already present (skipped)"
		else
			info "hooks.$hook_event — added"
		fi
	done

	# Report new plugins
	for plugin in $(jq -r '.enabledPlugins // {} | keys[]' "$template"); do
		if jq -e ".enabledPlugins.\"${plugin}\"" "${target}.bak" &>/dev/null; then
			skip "enabledPlugins.$plugin — already present (skipped)"
		else
			info "enabledPlugins.$plugin — added"
		fi
	done

	# Report permissions
	local old_perm_count new_perm_total
	old_perm_count=$(jq '.permissions.allow | length' "${target}.bak")
	new_perm_total=$(jq '.permissions.allow | length' "$target")
	local perm_diff=$((new_perm_total - old_perm_count))
	if [[ $perm_diff -gt 0 ]]; then
		info "permissions — $perm_diff new entries merged"
	else
		skip "permissions — no new entries"
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
		# Check non-SKILL.md files: .md files in skill dir, others in scripts dir
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			total=$((total + 1))
			if [[ "$helper_name" == *.md ]]; then
				do_check "$helper" "$SKILLS_DIR/$skill_name/$helper_name" "$skill_name/$helper_name" || drifted=$((drifted + 1))
			else
				do_check "$helper" "$SCRIPTS_DIR/$helper_name" "$skill_name/$helper_name" || drifted=$((drifted + 1))
			fi
		done
		# Check content subdirectories (e.g., tours/)
		for subdir in "$skill_dir"*/; do
			[[ -d "$subdir" ]] || continue
			subdir_name="$(basename "$subdir")"
			for content_file in "$subdir"*; do
				[[ -f "$content_file" ]] || continue
				content_name="$(basename "$content_file")"
				total=$((total + 1))
				do_check "$content_file" "$SKILLS_DIR/$skill_name/$subdir_name/$content_name" "$skill_name/$subdir_name/$content_name" || drifted=$((drifted + 1))
			done
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

	# Settings.json drift: missing hooks and plugins
	if [[ -f "$REPO_DIR/config/settings.template.json" && -f "$CLAUDE_DIR/settings.json" ]]; then
		echo ""
		echo "Settings"
		echo "──────────────────────────────────────────"
		# Check for missing hooks
		for hook_event in $(jq -r '.hooks // {} | keys[] | select(. != "_comment")' "$REPO_DIR/config/settings.template.json"); do
			total=$((total + 1))
			if ! jq -e ".hooks.\"${hook_event}\"" "$CLAUDE_DIR/settings.json" &>/dev/null; then
				drift "settings.json — missing hook: $hook_event"
				drifted=$((drifted + 1))
			else
				info "settings.json hook $hook_event (present)"
			fi
		done
		# Check for missing plugins
		for plugin in $(jq -r '.enabledPlugins // {} | keys[]' "$REPO_DIR/config/settings.template.json"); do
			total=$((total + 1))
			if ! jq -e ".enabledPlugins.\"${plugin}\"" "$CLAUDE_DIR/settings.json" &>/dev/null; then
				drift "settings.json — missing plugin: $plugin"
				drifted=$((drifted + 1))
			else
				info "settings.json plugin $plugin (present)"
			fi
		done
	fi

	# Channels: MCP registration drift
	if [[ -d "$REPO_DIR/channels" ]] && command -v claude &>/dev/null; then
		echo ""
		echo "Channels"
		echo "──────────────────────────────────────────"
		mcp_list=$(claude mcp list 2>/dev/null || true)
		for channel_dir in "$REPO_DIR"/channels/*/; do
			[[ -f "$channel_dir/package.json" ]] || continue
			channel_name="$(basename "$channel_dir")"
			total=$((total + 1))
			if echo "$mcp_list" | grep -q "$channel_name"; then
				info "MCP server $channel_name (registered)"
			else
				drift "MCP server $channel_name — NOT REGISTERED"
				drifted=$((drifted + 1))
			fi
		done
	fi

	if [[ -d "$REPO_DIR/src" ]]; then
		echo ""
		echo "Packages"
		echo "──────────────────────────────────────────"
		if [[ ! -d "$REPO_DIR/dist" ]] || [[ -z "$(ls -A "$REPO_DIR/dist" 2>/dev/null)" ]]; then
			warn "dist/ is empty — run 'install.sh --scripts' to build packages before checking drift"
		else
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
		# Install non-SKILL.md files: .md files stay in the skill dir,
		# everything else goes to ~/.local/bin/ as executable scripts
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			if [[ "$helper_name" == *.md ]]; then
				do_copy "$helper" "$SKILLS_DIR/$skill_name/$helper_name"
			else
				do_copy "$helper" "$SCRIPTS_DIR/$helper_name"
				if [[ "$DRY_RUN" != true ]]; then
					chmod +x "$SCRIPTS_DIR/$helper_name"
				fi
			fi
		done
		# Install content subdirectories (e.g., tours/) into the skill dir
		for subdir in "$skill_dir"*/; do
			[[ -d "$subdir" ]] || continue
			subdir_name="$(basename "$subdir")"
			for content_file in "$subdir"*; do
				[[ -f "$content_file" ]] || continue
				content_name="$(basename "$content_file")"
				do_copy "$content_file" "$SKILLS_DIR/$skill_name/$subdir_name/$content_name"
			done
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
			if [[ "$DRY_RUN" == true ]]; then
				info "(dry-run) Would merge missing config from settings.template.json into settings.json"
			else
				merge_settings "$REPO_DIR/config/settings.template.json" "$CLAUDE_DIR/settings.json"
			fi
		else
			# Fresh install: copy template and strip _comment keys
			if [[ "$DRY_RUN" == true ]]; then
				info "(dry-run) $REPO_DIR/config/settings.template.json → $CLAUDE_DIR/settings.json"
			else
				mkdir -p "$(dirname "$CLAUDE_DIR/settings.json")"
				jq 'del(._comment) | del(.hooks._comment)' \
					"$REPO_DIR/config/settings.template.json" >"$CLAUDE_DIR/settings.json"
				info "Installed settings.json (stripped _comment keys)"
			fi
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
				needs_install=false
				stamp_file="$channel_dir/.install-stamp"
				if [[ ! -d "$channel_dir/node_modules" ]]; then
					needs_install=true
				elif [[ -f "$stamp_file" ]]; then
					# Reinstall if package.json or bun.lock is newer than stamp
					for src_file in "$channel_dir/package.json" "$channel_dir/bun.lock" "$channel_dir/bun.lockb"; do
						if [[ -f "$src_file" && "$src_file" -nt "$stamp_file" ]]; then
							needs_install=true
							break
						fi
					done
				fi
				if [[ "$needs_install" == true ]]; then
					info "Installing dependencies for $channel_name..."
					(cd "$channel_dir" && bun install --silent)
					touch "$stamp_file"
				else
					skip "$channel_name dependencies (up to date)"
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
