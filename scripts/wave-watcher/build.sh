#!/usr/bin/env bash
# Build wave-watcher into a single standalone binary.
# Usage: build.sh [bun-target]
#   With no argument: builds for the host platform.
#   With a target argument (used by release CI matrix): builds that target.
#
# Mirrors mcp-server-sdlc's build.sh shape so the same release pipeline can
# pick this up: outputs into dist/wave-watcher-<suffix>.
set -euo pipefail

cd "$(dirname "$0")"

mkdir -p dist

TARGETS=("${1:-}")
if [[ -z "${1:-}" ]]; then
	TARGETS=("$(bun --version >/dev/null && echo bun)") # placeholder; bun build w/o --target uses host
fi

for TARGET in "${TARGETS[@]}"; do
	if [[ "$TARGET" == "bun" ]]; then
		bun build --compile launcher.ts --outfile "dist/wave-watcher"
		echo "Built dist/wave-watcher (host)"
	else
		SUFFIX="${TARGET#bun-}"
		bun build --compile --target="$TARGET" launcher.ts --outfile "dist/wave-watcher-${SUFFIX}"
		echo "Built dist/wave-watcher-${SUFFIX}"
	fi
done
