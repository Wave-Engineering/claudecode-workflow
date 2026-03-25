#!/usr/bin/env bash
# build.sh — Build zipapp executables from src/ packages
#
# Discovers src/*/ directories containing __main__.py and builds each
# into a standalone executable using python3 -m zipapp.
#
# Output: dist/<package-name>  (underscores replaced with hyphens)
#
# Usage:
#   ./scripts/ci/build.sh          Build all packages
#
# Exit codes:
#   0  All packages built successfully
#   1  One or more builds failed

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DIST_DIR="$REPO_DIR/dist"

info() { echo "  [+] $*"; }
err() { echo "  [!] $*"; }

# --- Discover packages --------------------------------------------------------
echo ""
echo "Building zipapp packages"
echo "══════════════════════════════════════════"

packages=()
for pkg_dir in "$REPO_DIR"/src/*/; do
	[[ -f "$pkg_dir/__main__.py" ]] || continue
	packages+=("$pkg_dir")
done

if [[ ${#packages[@]} -eq 0 ]]; then
	err "No packages found in src/ with __main__.py"
	exit 1
fi

# --- Build --------------------------------------------------------------------
mkdir -p "$DIST_DIR"
built=0
failed=0

for pkg_dir in "${packages[@]}"; do
	pkg_name="$(basename "$pkg_dir")"
	# Convert underscores to hyphens for the output name
	artifact_name="${pkg_name//_/-}"
	output="$DIST_DIR/$artifact_name"

	echo ""
	echo "Building: $pkg_name → dist/$artifact_name"
	echo "──────────────────────────────────────────"

	# Stage a temporary directory with the package as a subdirectory
	# and a top-level __main__.py that imports it. This ensures
	# intra-package imports (e.g. "from wave_status import ...") work.
	staging="$(mktemp -d)"
	trap 'rm -rf "$staging"' EXIT
	cp -r "$pkg_dir" "$staging/$pkg_name"
	cat >"$staging/__main__.py" <<ENTRY
from ${pkg_name}.__main__ import main
main()
ENTRY

	if python3 -m zipapp "$staging" -o "$output" -p '/usr/bin/env python3'; then
		chmod +x "$output"
		size=$(wc -c <"$output")
		info "$artifact_name ($size bytes)"
		built=$((built + 1))
	else
		err "Failed to build $pkg_name"
		failed=$((failed + 1))
	fi
	rm -rf "$staging"
done

# --- Summary ------------------------------------------------------------------
echo ""
echo "══════════════════════════════════════════"
echo "Built: $built, Failed: $failed"

if [[ $failed -gt 0 ]]; then
	exit 1
fi
