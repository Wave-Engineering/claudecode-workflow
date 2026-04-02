#!/usr/bin/env bash
set -euo pipefail

# cc-workflow — Remote Installer
#
# Install the Claude Code workflow environment from GitHub Releases
# without cloning the repo. Downloads a release tarball containing
# skills, scripts, config, and pre-built packages, then installs
# them into the correct locations on the local machine.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/Wave-Engineering/claudecode-workflow/main/scripts/install-remote.sh | bash
#   curl ... | bash -s -- --uninstall
#   curl ... | bash -s -- --check
#   curl ... | bash -s -- --version v1.0.0
#   curl ... | bash -s -- --no-mcps

OWNER="Wave-Engineering"
REPO="claudecode-workflow"
BASE_URL="https://github.com/${OWNER}/${REPO}/releases"

SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
CLAUDE_DIR="$HOME/.claude"

VERSION=""
NO_MCPS=false
TMPDIR_CLEANUP=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info() { printf '  \033[1;34m[+]\033[0m %s\n' "$*"; }
ok() { printf '  \033[1;32m[+]\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m[!]\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m[!]\033[0m %s\n' "$*"; }
skip() { printf '  \033[0;37m[-]\033[0m %s\n' "$*"; }
die() {
	fail "$*"
	exit 1
}

# ---------------------------------------------------------------------------
# Download helper (curl with wget fallback, atomic tmp+mv)
# ---------------------------------------------------------------------------

fetch() {
	local url="$1" dest="$2"
	local tmp="${dest}.tmp.$$"
	if command -v curl &>/dev/null; then
		curl -fsSL "$url" -o "$tmp"
	elif command -v wget &>/dev/null; then
		wget -q "$url" -O "$tmp"
	else
		die "Neither curl nor wget found"
	fi
	mv -f "$tmp" "$dest"
}

# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

check_prereqs() {
	local missing=0
	for cmd in claude jq; do
		if command -v "$cmd" &>/dev/null; then
			ok "$cmd available"
		else
			fail "$cmd not found"
			missing=1
		fi
	done
	if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
		fail "Neither curl nor wget found"
		missing=1
	else
		ok "$(command -v curl &>/dev/null && echo curl || echo wget) available"
	fi
	if [[ $missing -ne 0 ]]; then
		die "Install missing prerequisites and try again."
	fi
}

# ---------------------------------------------------------------------------
# Resolve download URL for a release asset
# ---------------------------------------------------------------------------

resolve_url() {
	local file="$1"
	if [[ -n "$VERSION" ]]; then
		echo "${BASE_URL}/download/${VERSION}/${file}"
	else
		echo "${BASE_URL}/latest/download/${file}"
	fi
}

# ---------------------------------------------------------------------------
# Settings smart-merge (ported from install.sh)
# ---------------------------------------------------------------------------

merge_settings() {
	local template="$1" target="$2"

	cp "$target" "${target}.bak"

	# Deep merge: template into local, preserving user customizations
	# Rules:
	#   1. Top-level keys (scalars AND objects): added only if ABSENT locally
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
	for hook_event in $(jq -r '.hooks // {} | keys[] | select(. != "_comment")' "$template"); do
		if jq -e ".hooks.\"${hook_event}\"" "${target}.bak" &>/dev/null; then
			skip "hooks.$hook_event -- already present (skipped)"
		else
			info "hooks.$hook_event -- added"
		fi
	done

	for plugin in $(jq -r '.enabledPlugins // {} | keys[]' "$template"); do
		if jq -e ".enabledPlugins.\"${plugin}\"" "${target}.bak" &>/dev/null; then
			skip "enabledPlugins.$plugin -- already present (skipped)"
		else
			info "enabledPlugins.$plugin -- added"
		fi
	done

	local old_perm_count new_perm_total
	old_perm_count=$(jq '.permissions.allow | length' "${target}.bak")
	new_perm_total=$(jq '.permissions.allow | length' "$target")
	local perm_diff=$((new_perm_total - old_perm_count))
	if [[ $perm_diff -gt 0 ]]; then
		info "permissions -- $perm_diff new entries merged"
	else
		skip "permissions -- no new entries"
	fi
}

# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

do_install() {
	echo ""
	echo "cc-workflow -- Remote Installer"
	echo "===================================="
	echo ""

	echo "Checking prerequisites..."
	check_prereqs
	echo ""

	# Create temp dir for extraction
	TMPDIR_CLEANUP=$(mktemp -d)
	trap 'rm -rf "$TMPDIR_CLEANUP"' EXIT
	local tmpdir="$TMPDIR_CLEANUP"

	# Download and extract tarball
	local tarball="$tmpdir/cc-workflow.tar.gz"
	info "Downloading cc-workflow release tarball..."
	fetch "$(resolve_url "cc-workflow.tar.gz")" "$tarball"
	tar -xzf "$tarball" -C "$tmpdir"
	ok "Release tarball extracted"
	echo ""

	local release_dir="$tmpdir"

	# --- Install skills ---
	echo "Skills -> $SKILLS_DIR"
	echo "--------------------------------------------"
	for skill_dir in "$release_dir"/skills/*/; do
		[[ -d "$skill_dir" ]] || continue
		local skill_name
		skill_name="$(basename "$skill_dir")"

		# Install SKILL.md
		if [[ -f "$skill_dir/SKILL.md" ]]; then
			mkdir -p "$SKILLS_DIR/$skill_name"
			cp "$skill_dir/SKILL.md" "$SKILLS_DIR/$skill_name/SKILL.md"
		fi

		# Install other files in the skill dir
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			local helper_name
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			if [[ "$helper_name" == *.md ]]; then
				mkdir -p "$SKILLS_DIR/$skill_name"
				cp "$helper" "$SKILLS_DIR/$skill_name/$helper_name"
			else
				mkdir -p "$SCRIPTS_DIR"
				cp "$helper" "$SCRIPTS_DIR/$helper_name"
				chmod +x "$SCRIPTS_DIR/$helper_name"
			fi
		done

		# Install content subdirectories (e.g., tours/)
		for subdir in "$skill_dir"*/; do
			[[ -d "$subdir" ]] || continue
			local subdir_name
			subdir_name="$(basename "$subdir")"
			for content_file in "$subdir"*; do
				[[ -f "$content_file" ]] || continue
				local content_name
				content_name="$(basename "$content_file")"
				mkdir -p "$SKILLS_DIR/$skill_name/$subdir_name"
				cp "$content_file" "$SKILLS_DIR/$skill_name/$subdir_name/$content_name"
			done
		done

		ok "$skill_name"
	done
	echo ""

	# --- Install scripts ---
	echo "Scripts -> $SCRIPTS_DIR"
	echo "--------------------------------------------"
	mkdir -p "$SCRIPTS_DIR"
	for script in "$release_dir"/scripts/*; do
		[[ -f "$script" ]] || continue
		local script_name
		script_name="$(basename "$script")"
		cp "$script" "$SCRIPTS_DIR/$script_name"
		chmod +x "$SCRIPTS_DIR/$script_name"
		ok "$script_name"
	done
	echo ""

	# --- Install pre-built packages ---
	if [[ -d "$release_dir/dist" ]]; then
		echo "Packages -> $SCRIPTS_DIR"
		echo "--------------------------------------------"
		for pkg in "$release_dir"/dist/*; do
			[[ -f "$pkg" ]] || continue
			local pkg_name
			pkg_name="$(basename "$pkg")"
			cp "$pkg" "$SCRIPTS_DIR/$pkg_name"
			chmod +x "$SCRIPTS_DIR/$pkg_name"
			ok "$pkg_name"
		done
		echo ""
	fi

	# --- Install config ---
	echo "Config -> $CLAUDE_DIR"
	echo "--------------------------------------------"
	mkdir -p "$CLAUDE_DIR"

	# statusline-command.sh
	if [[ -f "$release_dir/config/statusline-command.sh" ]]; then
		cp "$release_dir/config/statusline-command.sh" "$CLAUDE_DIR/statusline-command.sh"
		chmod +x "$CLAUDE_DIR/statusline-command.sh"
		ok "statusline-command.sh"
	fi

	# settings.json smart-merge
	if [[ -f "$release_dir/config/settings.template.json" ]]; then
		if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
			info "Smart-merging settings.template.json into settings.json..."
			merge_settings "$release_dir/config/settings.template.json" "$CLAUDE_DIR/settings.json"
			ok "settings.json merged (backup at settings.json.bak)"
		else
			# Fresh install: copy template and strip _comment keys
			jq 'del(._comment) | del(.hooks._comment)' \
				"$release_dir/config/settings.template.json" >"$CLAUDE_DIR/settings.json"
			ok "settings.json installed (fresh)"
		fi
	fi
	echo ""

	# --- Install MCPs via manifest ---
	if [[ "$NO_MCPS" == false && -f "$release_dir/mcps.json" ]]; then
		echo "MCP servers (via mcps.json)"
		echo "--------------------------------------------"
		for mcp_name in $(jq -r '.mcps | keys[]' "$release_dir/mcps.json"); do
			local install_url description
			install_url=$(jq -r ".mcps[\"$mcp_name\"].install_url" "$release_dir/mcps.json")
			description=$(jq -r ".mcps[\"$mcp_name\"].description" "$release_dir/mcps.json")
			info "Installing $mcp_name -- $description"
			if command -v curl &>/dev/null; then
				if curl -fsSL "$install_url" | bash; then
					ok "$mcp_name installed"
				else
					warn "Failed to install $mcp_name -- run manually:"
					warn "  curl -fsSL $install_url | bash"
				fi
			elif command -v wget &>/dev/null; then
				if wget -qO- "$install_url" | bash; then
					ok "$mcp_name installed"
				else
					warn "Failed to install $mcp_name -- run manually:"
					warn "  wget -qO- $install_url | bash"
				fi
			fi
			echo ""
		done
	elif [[ "$NO_MCPS" == true ]]; then
		skip "MCP installation skipped (--no-mcps)"
		echo ""
	fi

	# Verify install dir is on PATH
	if ! echo "$PATH" | tr ':' '\n' | grep -qx "$SCRIPTS_DIR"; then
		warn "${SCRIPTS_DIR} is not on your PATH"
		info "Add it: export PATH=\"${SCRIPTS_DIR}:\$PATH\""
	fi

	echo ""
	echo "===================================="
	ok "Installation complete"
	echo ""
}

# ---------------------------------------------------------------------------
# Check
# ---------------------------------------------------------------------------

do_check() {
	echo ""
	echo "cc-workflow -- Installation Check"
	echo "===================================="
	echo ""
	local issues=0

	# Prerequisites
	echo "Prerequisites"
	echo "--------------------------------------------"
	for cmd in claude jq; do
		if command -v "$cmd" &>/dev/null; then
			ok "$cmd available"
		else
			fail "$cmd not found"
			issues=$((issues + 1))
		fi
	done
	if ! command -v curl &>/dev/null && ! command -v wget &>/dev/null; then
		fail "Neither curl nor wget found"
		issues=$((issues + 1))
	else
		ok "$(command -v curl &>/dev/null && echo curl || echo wget) available"
	fi
	echo ""

	# Skills
	echo "Skills"
	echo "--------------------------------------------"
	# We check what's installed without downloading
	local skill_count=0
	if [[ -d "$SKILLS_DIR" ]]; then
		for skill_dir in "$SKILLS_DIR"/*/; do
			[[ -d "$skill_dir" ]] || continue
			[[ -f "$skill_dir/SKILL.md" ]] || continue
			local sname
			sname="$(basename "$skill_dir")"
			ok "$sname"
			skill_count=$((skill_count + 1))
		done
	fi
	if [[ $skill_count -eq 0 ]]; then
		fail "No skills found in $SKILLS_DIR"
		issues=$((issues + 1))
	else
		info "$skill_count skill(s) installed"
	fi
	echo ""

	# Scripts
	echo "Scripts"
	echo "--------------------------------------------"
	local expected_scripts=(discord-bot discord-status-post slackbot-send job-fetch file-opener vox)
	for script_name in "${expected_scripts[@]}"; do
		if [[ -x "$SCRIPTS_DIR/$script_name" ]]; then
			ok "$script_name"
		else
			fail "$script_name not found"
			issues=$((issues + 1))
		fi
	done
	echo ""

	# Config
	echo "Config"
	echo "--------------------------------------------"
	if [[ -f "$CLAUDE_DIR/statusline-command.sh" ]]; then
		ok "statusline-command.sh"
	else
		fail "statusline-command.sh not found"
		issues=$((issues + 1))
	fi

	if [[ -f "$CLAUDE_DIR/settings.json" ]]; then
		ok "settings.json"
	else
		fail "settings.json not found"
		issues=$((issues + 1))
	fi
	echo ""

	# MCPs
	if [[ "$NO_MCPS" == false ]]; then
		echo "MCPs"
		echo "--------------------------------------------"
		if command -v claude &>/dev/null; then
			local mcp_list
			mcp_list=$(claude mcp list 2>/dev/null || true)
			for mcp_name in wtf-server discord-watcher; do
				if echo "$mcp_list" | grep -qw "$mcp_name"; then
					ok "MCP server $mcp_name registered"
				else
					fail "MCP server $mcp_name not registered"
					issues=$((issues + 1))
				fi
			done
		else
			warn "claude not found -- cannot check MCP registrations"
		fi
		echo ""
	fi

	echo "===================================="
	if [[ $issues -eq 0 ]]; then
		ok "All checks passed"
	else
		fail "$issues issue(s) found"
		info "Run the installer to fix:"
		info "  curl -fsSL https://raw.githubusercontent.com/${OWNER}/${REPO}/main/scripts/install-remote.sh | bash"
		exit 1
	fi
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

do_uninstall() {
	echo ""
	echo "cc-workflow -- Remote Uninstaller"
	echo "===================================="
	echo ""

	# Remove skills
	echo "Skills"
	echo "--------------------------------------------"
	if [[ -d "$SKILLS_DIR" ]]; then
		for skill_dir in "$SKILLS_DIR"/*/; do
			[[ -d "$skill_dir" ]] || continue
			local sname
			sname="$(basename "$skill_dir")"
			rm -rf "$skill_dir"
			ok "Removed $sname"
		done
	else
		skip "No skills directory found"
	fi
	echo ""

	# Remove scripts (known script names from skills)
	echo "Scripts"
	echo "--------------------------------------------"
	local known_scripts=(
		discord-bot discord-status-post slackbot-send job-fetch
		file-opener vox worktree-manager cc-inspector discord-lock
		generate-status-panel wave-status
	)
	for script_name in "${known_scripts[@]}"; do
		if [[ -f "$SCRIPTS_DIR/$script_name" ]]; then
			rm -f "$SCRIPTS_DIR/$script_name"
			ok "Removed $script_name"
		fi
	done
	echo ""

	# Remove config (statusline only -- settings.json is preserved)
	echo "Config"
	echo "--------------------------------------------"
	if [[ -f "$CLAUDE_DIR/statusline-command.sh" ]]; then
		rm -f "$CLAUDE_DIR/statusline-command.sh"
		ok "Removed statusline-command.sh"
	else
		skip "statusline-command.sh not found"
	fi
	info "settings.json preserved (not removed)"
	echo ""

	# Uninstall MCPs
	if [[ "$NO_MCPS" == false ]]; then
		echo "MCPs"
		echo "--------------------------------------------"
		for mcp_name in wtf-server discord-watcher; do
			# Try calling each MCP's own uninstaller
			local install_url
			case "$mcp_name" in
			wtf-server)
				install_url="https://raw.githubusercontent.com/Wave-Engineering/mcp-server-wtf/main/scripts/install-remote.sh"
				;;
			discord-watcher)
				install_url="https://raw.githubusercontent.com/Wave-Engineering/mcp-server-discord-watcher/main/scripts/install-remote.sh"
				;;
			esac
			info "Uninstalling $mcp_name..."
			if command -v curl &>/dev/null; then
				if curl -fsSL "$install_url" | bash -s -- --uninstall; then
					ok "$mcp_name uninstalled"
				else
					warn "Failed to uninstall $mcp_name"
				fi
			elif command -v wget &>/dev/null; then
				if wget -qO- "$install_url" | bash -s -- --uninstall; then
					ok "$mcp_name uninstalled"
				else
					warn "Failed to uninstall $mcp_name"
				fi
			fi
		done
		echo ""
	fi

	echo "===================================="
	ok "Uninstall complete"
	echo ""
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

ACTION=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--uninstall)
		ACTION="uninstall"
		shift
		;;
	--check)
		ACTION="check"
		shift
		;;
	--version)
		VERSION="${2:?--version requires a tag}"
		shift 2
		;;
	--no-mcps)
		NO_MCPS=true
		shift
		;;
	*)
		die "Unknown flag: $1 (use --uninstall, --check, --version <tag>, or --no-mcps)"
		;;
	esac
done

case "${ACTION:-install}" in
install) do_install ;;
uninstall) do_uninstall ;;
check) do_check ;;
esac
