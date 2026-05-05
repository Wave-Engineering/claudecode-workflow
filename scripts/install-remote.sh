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
#   curl ... | bash -s -- --with-logrotate
#   curl ... | bash -s -- --without-logrotate

OWNER="Wave-Engineering"
REPO="claudecode-workflow"
BASE_URL="https://github.com/${OWNER}/${REPO}/releases"

SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
CLAUDE_DIR="$HOME/.claude"
# Cellar: kit-owned scripts directory (Homebrew/Nix pattern). Wiped and
# recreated on every install — eliminates orphan rot. SCRIPTS_DIR becomes a
# symlink farm pointing into here for entries that need PATH. Ported from
# install per cc-workflow#560.
CELLAR_DIR="$HOME/.claude/scripts"

VERSION=""
NO_MCPS=false
DRY_RUN=false
# Logrotate is a tri-state: "prompt" by default, forced on/off by flag.
# Ported from install per cc-workflow#540.
LOGROTATE_MODE=prompt
TMPDIR_CLEANUP=""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

info() { printf '  \033[1;34m[+]\033[0m %s\n' "$*"; }
ok() { printf '  \033[1;32m[+]\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m[!]\033[0m %s\n' "$*"; }
fail() { printf '  \033[1;31m[!]\033[0m %s\n' "$*"; }
skip() { printf '  \033[0;37m[-]\033[0m %s\n' "$*"; }
drift() { printf '  \033[0;33m[~]\033[0m %s\n' "$*"; }
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
# Cellar + symlink-farm helpers (ported from install — see #560)
# ---------------------------------------------------------------------------
# Cellar = $CELLAR_DIR (kit-owned). Wiped and recreated each install.
# Symlink farm = $SCRIPTS_DIR — only top-level Cellar entries; subtrees like
# hooks/, vox-providers/ stay Cellar-only and are invoked by absolute path.

# Resolve a symlink's target to a normalized absolute path. Portable across
# GNU and BSD readlink (no -f).
resolve_symlink_target() {
	local link="$1" target
	target=$(readlink "$link" 2>/dev/null || true)
	[[ -z "$target" ]] && return 0
	if [[ "$target" != /* ]]; then
		target="$(cd "$(dirname "$link")" 2>/dev/null && pwd)/$target"
	fi
	target="${target/#\~/$HOME}"
	echo "$target"
}

# Enumerate the basenames that should appear in $SCRIPTS_DIR as symlinks
# pointing into $CELLAR_DIR. Top-level scripts/ entries only. Uses
# `find ... | sed` rather than GNU's `-printf '%f\n'` because BSD/macOS
# find lacks -printf and silently emits nothing — same fix-pattern as
# install. CRITICAL for macOS portability.
enumerate_farm_targets() {
	local src="$1"
	(cd "$src" && find . -maxdepth 1 -type f | sed 's|^\./||' | sort)
}

# Wipe and recreate the Cellar from the release tarball's scripts/ tree.
# Preserves directory structure and executable bits. Honors $DRY_RUN.
cellar_deploy() {
	local src_scripts="$1"
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) Would wipe and redeploy $CELLAR_DIR from tarball scripts/"
		return 0
	fi
	# Wipe — structural orphan-killer. Anything from a prior install that is
	# no longer in the release tarball dies here.
	rm -rf "$CELLAR_DIR"
	mkdir -p "$CELLAR_DIR"
	# BSD/macOS-portable: find + sed instead of -printf '%P\n'.
	while IFS= read -r rel; do
		[[ -z "$rel" ]] && continue
		[[ "$rel" == ci/* ]] && continue
		[[ "$rel" == */tests/* ]] && continue
		[[ "$rel" == */fixtures/* ]] && continue
		[[ "$rel" == */__pycache__/* ]] && continue
		[[ "$rel" == */.pytest_cache/* ]] && continue
		local s="$src_scripts/$rel"
		local d="$CELLAR_DIR/$rel"
		mkdir -p "$(dirname "$d")"
		cp "$s" "$d"
		# Preserve exec bit (top-level scripts always +x for backwards compat).
		if [[ "$rel" != */* ]]; then
			chmod +x "$d"
		elif [[ -x "$s" ]]; then
			chmod +x "$d"
		fi
	done < <(cd "$src_scripts" && find . -type f | sed 's|^\./||' | sort)
	info "Cellar redeployed: $CELLAR_DIR ($(find "$CELLAR_DIR" -type f | wc -l) files)"
}

# Drop a skill helper into a per-skill Cellar subdir at
# $CELLAR_DIR/skills/<skill_name>/<helper_name>. Preserves +x. Distinct
# from a flat Cellar drop so two skills shipping same-named helpers cannot
# silently overwrite each other.
cellar_install_skill_helper() {
	local src="$1" skill_name="$2" helper_name="$3"
	local dest="$CELLAR_DIR/skills/$skill_name/$helper_name"
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) $src → $dest (Cellar/skills)"
		return 0
	fi
	mkdir -p "$(dirname "$dest")"
	cp "$src" "$dest"
	chmod +x "$dest"
}

# If $SCRIPTS_DIR/<name> exists as a plain file (not a symlink), back it up
# before replacing with a symlink. Pre-Cellar layouts have plain files here.
safeguard_user_file() {
	local name="$1"
	local path="$SCRIPTS_DIR/$name"
	[[ -L "$path" ]] && return 0
	[[ -e "$path" ]] || return 0
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) Would back up plain file $path → ${path}.bak"
		return 0
	fi
	cp "$path" "${path}.bak"
	rm -f "$path"
	warn "Backed up user-customized $path → ${path}.bak"
}

# Create or refresh a symlink at $SCRIPTS_DIR/<name> pointing into the
# Cellar at $CELLAR_DIR/<name>. Caller must safeguard plain-file occupants
# first.
farm_symlink() {
	local name="$1"
	local target="$CELLAR_DIR/$name"
	local link="$SCRIPTS_DIR/$name"
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) symlink $link → $target"
		return 0
	fi
	mkdir -p "$(dirname "$link")"
	ln -sf "$target" "$link"
}

# Create or refresh a symlink at $SCRIPTS_DIR/<helper_name> pointing into
# the per-skill Cellar subdir. Warn loudly on cross-skill name collision.
farm_symlink_skill_helper() {
	local skill_name="$1" helper_name="$2"
	local target="$CELLAR_DIR/skills/$skill_name/$helper_name"
	local link="$SCRIPTS_DIR/$helper_name"
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) symlink $link → $target"
		return 0
	fi
	if [[ -L "$link" ]]; then
		local existing
		existing=$(resolve_symlink_target "$link")
		if [[ "$existing" == "$CELLAR_DIR/skills/"* && "$existing" != "$target" ]]; then
			warn "Helper name collision for '$helper_name': $existing already farmed; overwriting with $target"
		fi
	fi
	mkdir -p "$(dirname "$link")"
	ln -sf "$target" "$link"
}

# Walk $SCRIPTS_DIR and remove symlinks pointing into the Cellar whose
# target no longer exists. Foreign symlinks are NEVER touched.
reap_stale_cellar_symlinks() {
	[[ -d "$SCRIPTS_DIR" ]] || return 0
	local removed=0
	while IFS= read -r link; do
		[[ -L "$link" ]] || continue
		local target
		target=$(resolve_symlink_target "$link")
		[[ "$target" == "$CELLAR_DIR"/* || "$target" == "$CELLAR_DIR" ]] || continue
		[[ -e "$target" ]] && continue
		if [[ "$DRY_RUN" == true ]]; then
			info "(dry-run) Would remove stale symlink: $link → $target"
		else
			rm -f "$link"
			info "Reaped stale symlink: $link → $target"
		fi
		removed=$((removed + 1))
	done < <(find "$SCRIPTS_DIR" -maxdepth 1 -type l 2>/dev/null)
	if [[ $removed -eq 0 ]]; then
		skip "No stale symlinks under $SCRIPTS_DIR (Cellar reaper)"
	fi
}

# ---------------------------------------------------------------------------
# Settings smart-merge (ported from install — see #556 for hook union-merge)
# ---------------------------------------------------------------------------

merge_settings() {
	local template="$1" target="$2"

	cp "$target" "${target}.bak"

	# Deep merge: template into local, preserving user customizations
	# Rules:
	#   1. Top-level keys (scalars AND objects): added only if ABSENT locally
	#   2. hooks:
	#      - Event keys missing locally: added from template
	#      - Event keys present in both: matcher arrays unioned by .matcher
	#        value (template matcher entries whose .matcher is not in the
	#        local array are appended; existing local entries left untouched)
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

		# Merge hooks: add missing event keys AND union matcher arrays for shared keys
		((.[0].hooks // {}) | to_entries | map(
			select(.key != "_comment")
		)) as $tpl_hooks |
		((.[1].hooks // {}) | to_entries | map(
			select(.key != "_comment")
		)) as $local_hooks |
		((.[1].hooks // {}) | keys) as $local_hook_keys |
		# New event keys (template only) — add wholesale
		($tpl_hooks | map(select(.key | IN($local_hook_keys[]) | not))) as $new_hooks |
		# Shared event keys — union their matcher arrays by .matcher value
		($tpl_hooks | map(select(.key | IN($local_hook_keys[]))) | map({
			key: .key,
			value: (
				(.value // []) as $tpl_arr |
				(($local_hooks | from_entries)[.key] // []) as $local_arr |
				($local_arr | map(.matcher)) as $local_matchers |
				$local_arr + ($tpl_arr | map(select(.matcher as $m | $local_matchers | index($m) | not)))
			)
		}) | from_entries) as $merged_shared_hooks |

		# Merge permissions.allow: union
		((.[0].permissions.allow // []) + (.[1].permissions.allow // []) | unique) as $merged_perms |

		# Merge enabledPlugins: add missing keys
		((.[0].enabledPlugins // {}) | to_entries) as $tpl_plugins |
		((.[1].enabledPlugins // {}) | keys) as $local_plugin_keys |
		($tpl_plugins | map(select(.key | IN($local_plugin_keys[]) | not))) as $new_plugins |

		# Build result: start with local, add missing pieces
		.[1]
		| .permissions.allow = $merged_perms
		| .hooks = ((.hooks // {}) + ($new_hooks | from_entries) + $merged_shared_hooks)
		| .enabledPlugins = ((.enabledPlugins // {}) + ($new_plugins | from_entries))
		| reduce ($tpl_defaults[] | select(.key | IN($local_keys[]) | not)) as $s (.; .[$s.key] = $s.value)
		| del(._comment)
		| del(.hooks._comment)
	' "$template" "$target")

	echo "$merged" >"$target"

	# Report what changed

	# Report new hooks (and new matchers within shared event keys)
	for hook_event in $(jq -r '.hooks // {} | keys[] | select(. != "_comment")' "$template"); do
		if jq -e ".hooks.\"${hook_event}\"" "${target}.bak" &>/dev/null; then
			# Event already exists locally — diff matcher arrays and report
			# any template matchers appended by the union-merge.
			local added_matchers
			added_matchers=$(jq -r --arg ev "$hook_event" --slurpfile bak "${target}.bak" '
				(($bak[0].hooks[$ev] // []) | map(.matcher)) as $local_ms |
				(.hooks[$ev] // []) | map(.matcher) | map(select(. as $m | $local_ms | index($m) | not)) | .[]
			' "$target")
			if [[ -z "$added_matchers" ]]; then
				skip "hooks.$hook_event -- already present (skipped)"
			else
				while IFS= read -r m; do
					[[ -z "$m" ]] && continue
					info "hooks.$hook_event -- matcher \"$m\" added"
				done <<<"$added_matchers"
			fi
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
# Logrotate helpers (ported from install — see #540)
# ---------------------------------------------------------------------------
# The release tarball ships assets/logrotate/cc-mcp-logs containing a
# {{HOME}} marker which is rendered to the installing user's home before
# dropping into /etc/logrotate.d. Linux-only; macOS no-ops politely.

LOGROTATE_DEST="/etc/logrotate.d/cc-mcp-logs"
LOGROTATE_LOGS_DIR="$HOME/.claude/logs"
# LOGROTATE_SRC is set per-invocation from the release_dir.

# True iff this host has a logrotate(8) we can drive. Linux + logrotate on PATH.
logrotate_supported() {
	[[ "$(uname -s)" == "Linux" ]] && command -v logrotate &>/dev/null
}

# Render the templated config to stdout: substitute {{HOME}} with $HOME.
render_logrotate_template() {
	local src="$1"
	sed "s|{{HOME}}|$HOME|g" "$src"
}

# Install the rendered config to /etc/logrotate.d/cc-mcp-logs and run a
# dry-run validation. Returns non-zero on failure.
install_logrotate_config() {
	local src="$1"
	local tmp
	tmp="$(mktemp)"
	render_logrotate_template "$src" >"$tmp"

	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) Would install logrotate config to $LOGROTATE_DEST"
		info "(dry-run) Would run: sudo logrotate -d $LOGROTATE_DEST"
		rm -f "$tmp"
		return 0
	fi

	if sudo install -m 0644 "$tmp" "$LOGROTATE_DEST"; then
		info "Installed $LOGROTATE_DEST"
	else
		warn "Failed to install $LOGROTATE_DEST (sudo install)"
		rm -f "$tmp"
		return 1
	fi
	rm -f "$tmp"

	if sudo logrotate -d "$LOGROTATE_DEST" >/dev/null 2>&1; then
		ok "logrotate -d validation passed"
	else
		warn "logrotate -d reported errors -- re-run manually to diagnose:"
		warn "  sudo logrotate -d $LOGROTATE_DEST"
		return 1
	fi
}

# Remove the installed logrotate config (used by --uninstall).
uninstall_logrotate_config() {
	if ! logrotate_supported; then
		skip "logrotate (skipped -- non-Linux or logrotate not installed)"
		return 0
	fi
	if [[ ! -f "$LOGROTATE_DEST" ]]; then
		skip "$LOGROTATE_DEST not installed"
		return 0
	fi
	if [[ "$DRY_RUN" == true ]]; then
		info "(dry-run) Would remove $LOGROTATE_DEST"
		return 0
	fi
	if sudo rm -f "$LOGROTATE_DEST"; then
		ok "Removed $LOGROTATE_DEST"
	else
		warn "Failed to remove $LOGROTATE_DEST"
		return 1
	fi
}

# Report logrotate status for --check mode. Returns 0 if all-in-sync,
# 1 if any drift. Takes the rendered-source path as $1 (or empty string if
# the source isn't available — e.g. if the tarball didn't ship it).
check_logrotate_status() {
	local src="$1"
	if ! logrotate_supported; then
		info "logrotate (skipped -- non-Linux or logrotate not installed)"
		return 0
	fi
	if [[ -z "$src" || ! -f "$src" ]]; then
		# No source to compare against — best-effort: report install status.
		if [[ -f "$LOGROTATE_DEST" ]]; then
			info "logrotate config $LOGROTATE_DEST installed (no source available for drift check)"
		else
			drift "logrotate config $LOGROTATE_DEST -- NOT INSTALLED"
			return 1
		fi
		return 0
	fi
	local d=0
	if [[ ! -f "$LOGROTATE_DEST" ]]; then
		drift "logrotate config $LOGROTATE_DEST -- NOT INSTALLED"
		return 1
	fi
	local rendered
	rendered="$(mktemp)"
	render_logrotate_template "$src" >"$rendered"
	if ! sudo diff -q "$rendered" "$LOGROTATE_DEST" &>/dev/null; then
		drift "logrotate config $LOGROTATE_DEST -- DIFFERS from release template"
		d=1
	else
		info "logrotate config $LOGROTATE_DEST (in sync)"
	fi
	rm -f "$rendered"
	# Last-rotation mtime: any rotated mcp.jsonl.* indicates the rotation has
	# fired at least once. Use find + stat (no -printf — BSD portability).
	if [[ -d "$LOGROTATE_LOGS_DIR" ]]; then
		local newest=""
		while IFS= read -r f; do
			[[ -z "$f" ]] && continue
			if [[ -z "$newest" || "$f" -nt "$newest" ]]; then
				newest="$f"
			fi
		done < <(find "$LOGROTATE_LOGS_DIR" -maxdepth 1 \
			\( -name 'mcp.jsonl.[0-9]*' -o -name 'mcp.jsonl.[0-9]*.gz' \) \
			-type f 2>/dev/null)
		if [[ -n "$newest" ]]; then
			local newest_mtime
			newest_mtime=$(stat -c '%y' "$newest" 2>/dev/null || stat -f '%Sm' "$newest" 2>/dev/null || echo 'unknown')
			info "last rotation: $newest ($newest_mtime)"
		else
			info "no rotated files yet under $LOGROTATE_LOGS_DIR -- rotation has not fired"
		fi
	else
		info "$LOGROTATE_LOGS_DIR does not exist yet -- no rotation history"
	fi
	return $d
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

	# --- Install scripts (Cellar + symlink-farm, ported from install — #560) ---
	# Order matters: cellar_deploy wipes $CELLAR_DIR before deploying, so
	# skill helpers (which live under $CELLAR_DIR/skills/) would be obliterated
	# if skills ran first. Scripts go FIRST, then skills layer on top.
	if [[ -d "$release_dir/scripts" ]]; then
		echo "Scripts -> $CELLAR_DIR (Cellar) + $SCRIPTS_DIR (symlinks)"
		echo "--------------------------------------------"
		mkdir -p "$SCRIPTS_DIR"
		# 1. Cellar: wipe + redeploy from tarball scripts/.
		cellar_deploy "$release_dir/scripts"
		# 2. Reap stale symlinks pointing into the Cellar with missing targets.
		reap_stale_cellar_symlinks
		# 3. Symlink farm: top-level Cellar entries only.
		while IFS= read -r name; do
			[[ -z "$name" ]] && continue
			safeguard_user_file "$name"
			farm_symlink "$name"
			ok "$name (symlink -> Cellar)"
		done < <(enumerate_farm_targets "$release_dir/scripts")
		echo ""
	fi

	# --- Install skills ---
	echo "Skills -> $SKILLS_DIR (helpers go to $CELLAR_DIR/skills/<name>/ + symlink farm)"
	echo "--------------------------------------------"
	# Ensure Cellar exists (cellar_deploy may not have run if no scripts/).
	mkdir -p "$CELLAR_DIR"
	for skill_dir in "$release_dir"/skills/*/; do
		[[ -d "$skill_dir" ]] || continue
		local skill_name
		skill_name="$(basename "$skill_dir")"

		# Install SKILL.md
		if [[ -f "$skill_dir/SKILL.md" ]]; then
			mkdir -p "$SKILLS_DIR/$skill_name"
			cp "$skill_dir/SKILL.md" "$SKILLS_DIR/$skill_name/SKILL.md"
		fi

		# Install other files in the skill dir: .md files in the skill dir;
		# everything else into Cellar at $CELLAR_DIR/skills/<skill>/<helper>
		# with a top-level symlink for PATH discoverability (#560).
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			local helper_name
			helper_name="$(basename "$helper")"
			[[ "$helper_name" == "SKILL.md" ]] && continue
			if [[ "$helper_name" == *.md ]]; then
				mkdir -p "$SKILLS_DIR/$skill_name"
				cp "$helper" "$SKILLS_DIR/$skill_name/$helper_name"
			else
				cellar_install_skill_helper "$helper" "$skill_name" "$helper_name"
				safeguard_user_file "$helper_name"
				farm_symlink_skill_helper "$skill_name" "$helper_name"
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

	# --- Install pre-built packages ---
	if [[ -d "$release_dir/dist" ]]; then
		echo "Packages -> $CELLAR_DIR (Cellar) + $SCRIPTS_DIR (symlinks)"
		echo "--------------------------------------------"
		for pkg in "$release_dir"/dist/*; do
			[[ -f "$pkg" ]] || continue
			local pkg_name
			pkg_name="$(basename "$pkg")"
			# Cellar drop, then symlink farm entry (matches install — #560).
			if [[ "$DRY_RUN" != true ]]; then
				mkdir -p "$CELLAR_DIR"
				cp "$pkg" "$CELLAR_DIR/$pkg_name"
				chmod +x "$CELLAR_DIR/$pkg_name"
			fi
			safeguard_user_file "$pkg_name"
			farm_symlink "$pkg_name"
			ok "$pkg_name"
		done
		echo ""
	fi

	# --- Sanity check: prebuilt binaries present in symlink farm ---
	# If the release tarball ever ships without a dist/ tree (release-pipeline
	# regression), prebuilt binaries silently won't appear on PATH. Reuse the
	# expected_scripts list from do_check() so the two stay in lockstep.
	# Skipped on --dry-run (would always fail — nothing was actually farmed).
	if [[ "$DRY_RUN" != true ]]; then
		local expected_prebuilt=(discord-status-post slackbot-send job-fetch file-opener vox)
		local missing_prebuilt=()
		for prebuilt in "${expected_prebuilt[@]}"; do
			if [[ ! -L "$SCRIPTS_DIR/$prebuilt" && ! -x "$SCRIPTS_DIR/$prebuilt" ]]; then
				missing_prebuilt+=("$prebuilt")
			fi
		done
		if [[ ${#missing_prebuilt[@]} -gt 0 ]]; then
			warn "Expected prebuilt binaries missing from $SCRIPTS_DIR:"
			for p in "${missing_prebuilt[@]}"; do
				warn "  - $p"
			done
			warn "The release tarball may be missing its dist/ tree -- file an issue."
		fi
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

	# --- Install logrotate policy (ported from install — #540) ---
	# Linux-only; macOS no-ops politely. Tri-state: --with-logrotate forces on,
	# --without-logrotate forces off, default prompts (or skips if no tty).
	echo "Logrotate (~/.claude/logs/mcp.jsonl)"
	echo "--------------------------------------------"
	local logrotate_src="$release_dir/assets/logrotate/cc-mcp-logs"
	if ! logrotate_supported; then
		skip "Skipping -- logrotate(8) is Linux-only and not present here ($(uname -s))."
		skip "macOS users: see docs/operations/log-rotation.md for newsyslog guidance."
	elif [[ ! -f "$logrotate_src" ]]; then
		skip "Skipping -- assets/logrotate/cc-mcp-logs not found in release tarball."
	else
		local do_logrotate=false
		case "$LOGROTATE_MODE" in
		on)
			do_logrotate=true
			;;
		off)
			skip "Skipping -- --without-logrotate."
			;;
		prompt)
			if [[ "$DRY_RUN" == true ]]; then
				info "(dry-run) Would prompt to install logrotate policy."
			elif [[ -t 0 ]]; then
				read -r -p "Install logrotate policy for ~/.claude/logs/mcp.jsonl? [Y/n] " reply || reply=""
				case "$reply" in
				n | N | no | NO) skip "Skipped by user." ;;
				*) do_logrotate=true ;;
				esac
			else
				# Non-interactive (no tty, e.g. curl | bash) and no flag —
				# default to skip with a notice.
				skip "Non-interactive shell and no --with-logrotate / --without-logrotate flag -- skipping."
				info "Re-run with --with-logrotate to enable rotation."
			fi
			;;
		esac
		if [[ "$do_logrotate" == true ]]; then
			install_logrotate_config "$logrotate_src" || warn "logrotate install reported issues -- see above."
		fi
	fi
	echo ""

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

	# Scripts (Cellar + symlink farm, ported from install — #560)
	echo "Scripts (Cellar: $CELLAR_DIR)"
	echo "--------------------------------------------"
	if [[ ! -d "$CELLAR_DIR" ]]; then
		drift "Cellar -- NOT INSTALLED at $CELLAR_DIR"
		issues=$((issues + 1))
	else
		local cellar_count
		cellar_count=$(find "$CELLAR_DIR" -type f 2>/dev/null | wc -l)
		info "$cellar_count file(s) in Cellar"
	fi
	echo ""

	echo "Symlink farm ($SCRIPTS_DIR -> Cellar)"
	echo "--------------------------------------------"
	local expected_scripts=(discord-status-post slackbot-send job-fetch file-opener vox)
	for script_name in "${expected_scripts[@]}"; do
		local link="$SCRIPTS_DIR/$script_name"
		if [[ -L "$link" ]]; then
			local tgt
			tgt=$(resolve_symlink_target "$link")
			if [[ "$tgt" == "$CELLAR_DIR/$script_name" && -e "$tgt" ]]; then
				ok "$script_name (symlink -> Cellar)"
			elif [[ ! -e "$tgt" ]]; then
				drift "$script_name -- DANGLING SYMLINK ($link -> $tgt)"
				issues=$((issues + 1))
			else
				drift "$script_name -- symlink points outside Cellar ($tgt)"
				issues=$((issues + 1))
			fi
		elif [[ -x "$link" ]]; then
			drift "$script_name -- plain file (will be backed up to .bak on next install)"
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

	# Settings drift detection requires the template; run from a checkout
	# (./install --check) for full settings diff.
	echo ""

	# Logrotate (ported from install — #540)
	echo "Logrotate"
	echo "--------------------------------------------"
	# In --check we don't have the rendered template handy (no tarball
	# extraction). Pass empty src; check_logrotate_status reports install-only.
	if ! check_logrotate_status ""; then
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

	# Remove Cellar (Cellar + symlink farm — #560)
	echo "Scripts (Cellar)"
	echo "--------------------------------------------"
	if [[ -d "$CELLAR_DIR" ]]; then
		rm -rf "$CELLAR_DIR"
		ok "Removed $CELLAR_DIR"
	else
		skip "No Cellar directory found"
	fi
	# Remove symlinks from $SCRIPTS_DIR pointing into the (now-gone) Cellar.
	if [[ -d "$SCRIPTS_DIR" ]]; then
		while IFS= read -r link; do
			[[ -L "$link" ]] || continue
			local tgt
			tgt=$(resolve_symlink_target "$link")
			if [[ "$tgt" == "$CELLAR_DIR"/* || "$tgt" == "$CELLAR_DIR" ]]; then
				rm -f "$link"
				ok "Removed symlink $(basename "$link")"
			fi
		done < <(find "$SCRIPTS_DIR" -maxdepth 1 -type l 2>/dev/null)
	fi
	# Legacy plain-file uninstall: known script names from pre-Cellar layouts.
	local known_scripts=(
		discord-status-post slackbot-send job-fetch
		file-opener vox worktree-manager cc-inspector discord-lock
		generate-status-panel wave-status
	)
	for script_name in "${known_scripts[@]}"; do
		if [[ -f "$SCRIPTS_DIR/$script_name" ]]; then
			rm -f "$SCRIPTS_DIR/$script_name"
			ok "Removed legacy plain file $script_name"
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

	# Remove logrotate config (#540)
	echo "Logrotate"
	echo "--------------------------------------------"
	uninstall_logrotate_config
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
	--with-logrotate)
		LOGROTATE_MODE=on
		shift
		;;
	--without-logrotate)
		LOGROTATE_MODE=off
		shift
		;;
	--dry-run)
		DRY_RUN=true
		shift
		;;
	*)
		die "Unknown flag: $1 (use --uninstall, --check, --version <tag>, --no-mcps, --with-logrotate, --without-logrotate, --dry-run)"
		;;
	esac
done

case "${ACTION:-install}" in
install) do_install ;;
uninstall) do_uninstall ;;
check) do_check ;;
esac
