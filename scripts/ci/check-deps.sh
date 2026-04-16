#!/usr/bin/env bash
# check-deps.sh — Verify external dependencies for the Claude Code workflow
#
# Sourceable library exporting check_deps(). Designed to be sourced by
# install and sync.sh — not executed directly.
#
# Three verification layers:
#   1. Auto-scan settings.template.json hooks for referenced file paths
#   2. Read deps.json manifest for declared file/repo/config dependencies
#   3. Check CLI commands and secrets from deps.json
#
# Expects REPO_DIR to be set by the sourcing script. Uses info/warn/ok/skip
# helpers if defined, otherwise defines minimal versions.

# Guard: define output helpers if the sourcing script hasn't already
type info &>/dev/null || info() { echo "  [+] $*"; }
type warn &>/dev/null || warn() { echo "  [!] $*"; }
type ok &>/dev/null || ok() { echo "  [✓] $*"; }
type skip &>/dev/null || skip() { echo "  [-] $*"; }
type drift &>/dev/null || drift() { echo "  [~] $*"; }

# Expand ~ to $HOME in a path string
_expand_home() {
	local p="$1"
	echo "${p/#\~/$HOME}"
}

# ---------------------------------------------------------------------------
# Layer 1: Auto-scan settings.template.json hook commands
# ---------------------------------------------------------------------------
_check_hook_scripts() {
	local template="$REPO_DIR/config/settings.template.json"
	if [[ ! -f "$template" ]]; then
		skip "settings.template.json not found — skipping hook scan"
		return 0
	fi

	if ! command -v jq &>/dev/null; then
		warn "jq not found — cannot scan settings.template.json hooks"
		return 1
	fi

	local missing=0
	# Extract all command strings from hooks (ignoring _comment keys)
	local commands
	commands=$(jq -r '
		.hooks // {} | to_entries[]
		| select(.key != "_comment")
		| .value[]
		| .hooks[]
		| select(.type == "command")
		| .command
	' "$template" 2>/dev/null)

	while IFS= read -r cmd; do
		[[ -z "$cmd" ]] && continue
		# Extract the executable path — first token (e.g. "bash script.sh" → "bash",
		# but bare paths like "~/.claude/hook.sh" → the path itself).
		# For "interpreter script" patterns, check the second token if the first
		# is a known interpreter.
		local script_path first_token
		first_token=$(echo "$cmd" | awk '{print $1}')
		case "$first_token" in
		bash | sh | zsh | env)
			# Interpreter prefix — the actual script is the last non-flag token
			script_path=$(echo "$cmd" | awk '{for(i=NF;i>=1;i--) if($i !~ /^-/) {print $i; exit}}')
			;;
		*)
			script_path="$first_token"
			;;
		esac
		script_path=$(_expand_home "$script_path")

		if [[ -f "$script_path" ]]; then
			ok "hook: $script_path"
		else
			warn "hook: $script_path — NOT FOUND"
			warn "  Referenced in settings.template.json hooks"
			missing=$((missing + 1))
		fi
	done <<<"$commands"

	return $missing
}

# ---------------------------------------------------------------------------
# Layer 2: deps.json manifest — file/repo/config dependencies
# ---------------------------------------------------------------------------
_check_manifest_deps() {
	local manifest="$REPO_DIR/deps.json"
	if [[ ! -f "$manifest" ]]; then
		skip "deps.json not found — skipping manifest check"
		return 0
	fi

	if ! command -v jq &>/dev/null; then
		warn "jq not found — cannot read deps.json"
		return 1
	fi

	local missing=0

	while IFS= read -r dep_name; do
		[[ -z "$dep_name" ]] && continue
		local dep_type dep_optional dep_required_by
		dep_type=$(jq -r ".deps[\"$dep_name\"].type" "$manifest")
		dep_optional=$(jq -r ".deps[\"$dep_name\"].optional // false" "$manifest")
		dep_required_by=$(jq -r ".deps[\"$dep_name\"].required_by // empty" "$manifest")

		local all_present=true
		while IFS= read -r file_path; do
			[[ -z "$file_path" ]] && continue
			local expanded
			expanded=$(_expand_home "$file_path")
			if [[ ! -e "$expanded" ]]; then
				all_present=false
				break
			fi
		done < <(jq -r ".deps[\"$dep_name\"].files[]" "$manifest")

		if [[ "$all_present" == true ]]; then
			ok "$dep_name ($dep_type)"
		else
			if [[ "$dep_optional" == "true" ]]; then
				skip "$dep_name ($dep_type) — not installed (optional)"
			else
				warn "$dep_name ($dep_type) — NOT FOUND"
				missing=$((missing + 1))
			fi
			[[ -n "$dep_required_by" ]] && warn "  Required by: $dep_required_by"
			# Show install hint: structured clone for repos, freeform hint for others
			local clone_url clone_dest install_hint
			clone_url=$(jq -r ".deps[\"$dep_name\"].clone_url // empty" "$manifest")
			clone_dest=$(jq -r ".deps[\"$dep_name\"].clone_dest // empty" "$manifest")
			install_hint=$(jq -r ".deps[\"$dep_name\"].install // empty" "$manifest")
			if [[ -n "$clone_url" && -n "$clone_dest" ]]; then
				warn "  Install: git clone $clone_url $clone_dest"
			elif [[ -n "$install_hint" ]]; then
				warn "  Install: $install_hint"
			fi
		fi
	done < <(jq -r '.deps | keys[]' "$manifest")

	return $missing
}

# ---------------------------------------------------------------------------
# Layer 3: CLI commands from deps.json
# ---------------------------------------------------------------------------
_check_commands() {
	local manifest="$REPO_DIR/deps.json"
	if [[ ! -f "$manifest" ]] || ! command -v jq &>/dev/null; then
		return 0
	fi

	local missing=0
	local count
	count=$(jq '.commands | length' "$manifest")

	for ((i = 0; i < count; i++)); do
		local cmd_name cmd_required_by cmd_optional
		cmd_name=$(jq -r ".commands[$i].name" "$manifest")
		cmd_required_by=$(jq -r ".commands[$i].required_by // empty" "$manifest")
		cmd_optional=$(jq -r ".commands[$i].optional // false" "$manifest")

		if command -v "$cmd_name" &>/dev/null; then
			ok "$cmd_name ($(command -v "$cmd_name"))"
		elif [[ "$cmd_optional" == "true" ]]; then
			skip "$cmd_name — not installed (optional, needed for: $cmd_required_by)"
		else
			warn "$cmd_name — NOT FOUND (needed for: $cmd_required_by)"
			missing=$((missing + 1))
		fi
	done

	return $missing
}

# ---------------------------------------------------------------------------
# Layer 4: Secrets from deps.json
# ---------------------------------------------------------------------------
_check_secrets() {
	local manifest="$REPO_DIR/deps.json"
	if [[ ! -f "$manifest" ]] || ! command -v jq &>/dev/null; then
		return 0
	fi

	local missing=0
	local count
	count=$(jq '.secrets | length' "$manifest")

	for ((i = 0; i < count; i++)); do
		local secret_path secret_required_by
		secret_path=$(jq -r ".secrets[$i].path" "$manifest")
		secret_required_by=$(jq -r ".secrets[$i].required_by // empty" "$manifest")
		secret_path=$(_expand_home "$secret_path")

		if [[ -f "$secret_path" ]]; then
			ok "$(basename "$secret_path")"
		else
			warn "$(basename "$secret_path") — NOT FOUND ($secret_path)"
			[[ -n "$secret_required_by" ]] && warn "  Needed for: $secret_required_by"
			missing=$((missing + 1))
		fi
	done

	return $missing
}

# ---------------------------------------------------------------------------
# Public API: check_deps [--install]
#
#   --install  Attempt to install missing repo-type deps (used by install.sh)
#
# Returns: number of missing required dependencies
# ---------------------------------------------------------------------------
# shellcheck disable=SC2120  # $1 is optional --install flag
check_deps() {
	local do_install=false
	[[ "${1:-}" == "--install" ]] && do_install=true

	local total_missing=0

	echo ""
	echo "External Dependencies"
	echo "══════════════════════════════════════════"

	echo ""
	echo "Hook Scripts (auto-scanned from settings.template.json)"
	echo "──────────────────────────────────────────"
	_check_hook_scripts || total_missing=$((total_missing + $?))

	echo ""
	echo "Declared Dependencies (deps.json)"
	echo "──────────────────────────────────────────"
	_check_manifest_deps || total_missing=$((total_missing + $?))

	# Attempt install for repo-type deps if requested
	if [[ "$do_install" == true ]] && command -v jq &>/dev/null && [[ -f "$REPO_DIR/deps.json" ]]; then
		while IFS= read -r dep_name; do
			[[ -z "$dep_name" ]] && continue
			local dep_type dep_optional clone_url clone_dest
			dep_type=$(jq -r ".deps[\"$dep_name\"].type" "$REPO_DIR/deps.json")
			dep_optional=$(jq -r ".deps[\"$dep_name\"].optional // false" "$REPO_DIR/deps.json")

			[[ "$dep_type" != "repo" ]] && continue
			[[ "$dep_optional" == "true" ]] && continue

			clone_url=$(jq -r ".deps[\"$dep_name\"].clone_url // empty" "$REPO_DIR/deps.json")
			clone_dest=$(jq -r ".deps[\"$dep_name\"].clone_dest // empty" "$REPO_DIR/deps.json")
			[[ -z "$clone_url" || -z "$clone_dest" ]] && continue

			clone_dest=$(_expand_home "$clone_dest")

			# Check if already installed
			local all_present=true
			while IFS= read -r file_path; do
				[[ -z "$file_path" ]] && continue
				local expanded
				expanded=$(_expand_home "$file_path")
				if [[ ! -e "$expanded" ]]; then
					all_present=false
					break
				fi
			done < <(jq -r ".deps[\"$dep_name\"].files[]" "$REPO_DIR/deps.json")

			if [[ "$all_present" == false ]]; then
				echo ""
				info "Installing $dep_name..."
				if git clone "$clone_url" "$clone_dest"; then
					ok "$dep_name installed"
				else
					warn "$dep_name install failed — run manually:"
					warn "  git clone $clone_url $clone_dest"
				fi
			fi
		done < <(jq -r '.deps | keys[]' "$REPO_DIR/deps.json")
	fi

	echo ""
	echo "CLI Tools"
	echo "──────────────────────────────────────────"
	_check_commands || total_missing=$((total_missing + $?))

	echo ""
	echo "Secrets"
	echo "──────────────────────────────────────────"
	_check_secrets || total_missing=$((total_missing + $?))

	echo ""
	echo "══════════════════════════════════════════"
	if [[ $total_missing -eq 0 ]]; then
		echo "All external dependencies satisfied."
	else
		echo "$total_missing required dependency/dependencies missing."
	fi

	return $total_missing
}
