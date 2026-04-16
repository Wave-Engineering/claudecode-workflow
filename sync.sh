#!/usr/bin/env bash
# sync.sh — Pull local changes back into the claudecode-workflow repo
#
# Compares installed skills, scripts, and config against the repo versions.
# For files that differ, offers to copy the local version into the repo
# so you can review and commit the changes.
#
# Usage:
#   ./sync.sh            Interactive — prompt per changed file
#   ./sync.sh --all      Pull all changed files without prompting
#   ./sync.sh --check    Show drift summary only (no changes)
#
# Direction:
#   install.sh  = repo → local  (deploy)
#   sync.sh     = local → repo  (capture)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
CLAUDE_DIR="$HOME/.claude"
CHECK_ONLY=false
PULL_ALL=false

# --- Parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
	case "$1" in
	--check)
		CHECK_ONLY=true
		shift
		;;
	--all)
		PULL_ALL=true
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
skip() { echo "  [-] $*"; }
drift() { echo "  [~] $*"; }

# Compare a local (installed) file against the repo version.
# Returns: 0 if different, 1 if same or local missing.
check_pair() {
	local installed="$1" repo_file="$2" label="$3"

	if [[ ! -f "$installed" ]]; then
		skip "$label — not installed locally"
		return 1
	fi

	if [[ ! -f "$repo_file" ]]; then
		drift "$label — exists locally but NOT in repo (new file)"
		return 0
	fi

	if diff -q "$installed" "$repo_file" &>/dev/null; then
		info "$label (in sync)"
		return 1
	else
		drift "$label — local differs from repo"
		return 0
	fi
}

# Prompt user and optionally copy local → repo.
sync_pair() {
	local installed="$1" repo_file="$2" label="$3"

	if [[ "$CHECK_ONLY" == true ]]; then
		return
	fi

	echo ""
	echo "──── $label ────"
	if [[ -f "$repo_file" ]]; then
		diff --color=auto -u "$repo_file" "$installed" || true
	else
		echo "  (new file — not yet in repo)"
		head -20 "$installed"
		echo "  ..."
	fi

	if [[ "$PULL_ALL" == true ]]; then
		do_pull "$installed" "$repo_file" "$label"
		return
	fi

	echo ""
	while true; do
		read -rp "  Pull into repo? [y]es / [n]o / [a]ll / [q]uit: " answer
		case "$answer" in
		y | Y | yes)
			do_pull "$installed" "$repo_file" "$label"
			break
			;;
		n | N | no)
			skip "skipped $label"
			break
			;;
		a | A | all)
			PULL_ALL=true
			do_pull "$installed" "$repo_file" "$label"
			break
			;;
		q | Q | quit)
			echo "Aborted."
			exit 0
			;;
		*) echo "  Please enter y, n, a, or q." ;;
		esac
	done
}

do_pull() {
	local src="$1" dest="$2" label="$3"
	mkdir -p "$(dirname "$dest")"
	cp "$src" "$dest"
	info "Pulled: $label"
}

# --- Collect drifted files ----------------------------------------------------
echo ""
echo "Sync: local → repo"
echo "══════════════════════════════════════════"

changed_installed=()
changed_repo=()
changed_labels=()

# Skills
echo ""
echo "Skills"
echo "──────────────────────────────────────────"
for skill_dir in "$REPO_DIR"/skills/*/; do
	skill_name="$(basename "$skill_dir")"
	# Check SKILL.md
	installed="$SKILLS_DIR/$skill_name/SKILL.md"
	repo_file="$skill_dir/SKILL.md"
	if check_pair "$installed" "$repo_file" "$skill_name"; then
		changed_installed+=("$installed")
		changed_repo+=("$repo_file")
		changed_labels+=("$skill_name")
	fi
	# Check helper scripts (non-SKILL.md files)
	for helper in "$skill_dir"/*; do
		[[ -f "$helper" ]] || continue
		helper_name="$(basename "$helper")"
		[[ "$helper_name" == "SKILL.md" ]] && continue
		installed_helper="$SCRIPTS_DIR/$helper_name"
		if check_pair "$installed_helper" "$helper" "$skill_name/$helper_name"; then
			changed_installed+=("$installed_helper")
			changed_repo+=("$helper")
			changed_labels+=("$skill_name/$helper_name")
		fi
	done
done

# Check for locally installed skills NOT in the repo
if [[ -d "$SKILLS_DIR" ]]; then
	for local_skill_dir in "$SKILLS_DIR"/*/; do
		[[ -d "$local_skill_dir" ]] || continue
		skill_name="$(basename "$local_skill_dir")"
		if [[ ! -d "$REPO_DIR/skills/$skill_name" ]]; then
			installed="$local_skill_dir/SKILL.md"
			repo_file="$REPO_DIR/skills/$skill_name/SKILL.md"
			if [[ -f "$installed" ]]; then
				drift "$skill_name — exists locally but NOT in repo (new skill)"
				changed_installed+=("$installed")
				changed_repo+=("$repo_file")
				changed_labels+=("$skill_name (new)")
			fi
		fi
	done
fi

# Scripts
echo ""
echo "Scripts"
echo "──────────────────────────────────────────"
for script in "$REPO_DIR"/scripts/*; do
	[[ -f "$script" ]] || continue
	[[ -d "$script" ]] && continue
	script_name="$(basename "$script")"
	installed="$SCRIPTS_DIR/$script_name"
	if check_pair "$installed" "$script" "$script_name"; then
		changed_installed+=("$installed")
		changed_repo+=("$script")
		changed_labels+=("$script_name")
	fi
done

# Config (statusline)
echo ""
echo "Config"
echo "──────────────────────────────────────────"
if [[ -f "$REPO_DIR/config/statusline-command.sh" ]]; then
	installed="$CLAUDE_DIR/statusline-command.sh"
	repo_file="$REPO_DIR/config/statusline-command.sh"
	if check_pair "$installed" "$repo_file" "statusline-command.sh"; then
		changed_installed+=("$installed")
		changed_repo+=("$repo_file")
		changed_labels+=("statusline-command.sh")
	fi
fi

# --- Summary / Interactive sync ----------------------------------------------
echo ""
echo "══════════════════════════════════════════"

if [[ ${#changed_installed[@]} -eq 0 ]]; then
	echo "All files in sync."
else
	echo "${#changed_installed[@]} file(s) differ."
fi

# External dependency check (always runs in --check mode)
if [[ "$CHECK_ONLY" == true ]]; then
	# shellcheck source=scripts/ci/check-deps.sh
	source "$REPO_DIR/scripts/ci/check-deps.sh"
	# shellcheck disable=SC2119  # intentionally no --install arg
	check_deps || true
fi

if [[ ${#changed_installed[@]} -eq 0 ]]; then
	exit 0
fi

if [[ "$CHECK_ONLY" == true ]]; then
	echo "Run ./sync.sh to pull changes into the repo."
	exit 0
fi

echo ""
for i in "${!changed_installed[@]}"; do
	sync_pair "${changed_installed[$i]}" "${changed_repo[$i]}" "${changed_labels[$i]}"
done

# --- Done ---------------------------------------------------------------------
echo ""
echo "══════════════════════════════════════════"
echo "Sync complete. Review changes with 'git diff', then commit."
