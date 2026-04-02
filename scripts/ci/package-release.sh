#!/usr/bin/env bash
# package-release.sh — Assemble the release tarball for cc-workflow
#
# Collects skills, scripts, config, pre-built packages, and the MCP
# manifest into a single tarball suitable for the remote installer.
#
# Usage:
#   ./scripts/ci/package-release.sh <version>
#
# Output:
#   cc-workflow.tar.gz (in the current directory)
#
# The tarball contains:
#   skills/       — All SKILL.md files, helper files, and content subdirs
#   scripts/      — All bin scripts (top-level files in scripts/, no ci/)
#   config/       — statusline-command.sh, settings.template.json
#   dist/         — Pre-built Python zipapp packages
#   mcps.json     — MCP manifest

set -euo pipefail

VERSION="${1:?Usage: package-release.sh <version>}"
REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

info() { echo "  [+] $*"; }
err() { echo "  [!] $*"; }

echo ""
echo "Packaging cc-workflow $VERSION"
echo "============================================"

# Create staging directory
STAGING=$(mktemp -d)
trap 'rm -rf "$STAGING"' EXIT

# --- Skills ---
info "Collecting skills..."
for skill_dir in "$REPO_DIR"/skills/*/; do
	[[ -d "$skill_dir" ]] || continue
	skill_name="$(basename "$skill_dir")"
	mkdir -p "$STAGING/skills/$skill_name"
	# Copy all files
	for f in "$skill_dir"/*; do
		[[ -f "$f" ]] && cp "$f" "$STAGING/skills/$skill_name/"
	done
	# Copy subdirectories (tours/, lib/, etc.)
	for subdir in "$skill_dir"*/; do
		[[ -d "$subdir" ]] || continue
		subdir_name="$(basename "$subdir")"
		mkdir -p "$STAGING/skills/$skill_name/$subdir_name"
		for f in "$subdir"*; do
			[[ -f "$f" ]] && cp "$f" "$STAGING/skills/$skill_name/$subdir_name/"
		done
	done
done

# --- Scripts (top-level files only, not ci/) ---
info "Collecting scripts..."
mkdir -p "$STAGING/scripts"
for script in "$REPO_DIR"/scripts/*; do
	[[ -f "$script" ]] || continue
	cp "$script" "$STAGING/scripts/"
done

# --- Config ---
info "Collecting config..."
mkdir -p "$STAGING/config"
for f in "$REPO_DIR"/config/*; do
	[[ -f "$f" ]] && cp "$f" "$STAGING/config/"
done

# --- Pre-built packages ---
if [[ -d "$REPO_DIR/dist" ]] && [[ -n "$(ls -A "$REPO_DIR/dist" 2>/dev/null)" ]]; then
	info "Collecting pre-built packages..."
	mkdir -p "$STAGING/dist"
	cp "$REPO_DIR"/dist/* "$STAGING/dist/"
fi

# --- MCP manifest ---
if [[ -f "$REPO_DIR/mcps.json" ]]; then
	info "Including mcps.json..."
	cp "$REPO_DIR/mcps.json" "$STAGING/"
fi

# --- Build tarball ---
info "Creating tarball..."
tar -czf "cc-workflow.tar.gz" -C "$STAGING" .

size=$(wc -c <"cc-workflow.tar.gz")
echo ""
echo "============================================"
info "cc-workflow.tar.gz ($size bytes)"
echo ""
