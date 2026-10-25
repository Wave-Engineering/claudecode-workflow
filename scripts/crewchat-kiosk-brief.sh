#!/usr/bin/env bash
# crewchat-kiosk-brief.sh — print exactly what the kiosk will see from a reseed seed. (#1336, K-2)
#
# The crewchat MCP shim reads <project_root>/.claude/reseed-revive.md, extracts ONLY its
# `## Kiosk` section, and pushes that to the daemon, which seeds the kiosk from it. The kiosk
# answers people outside the crew, so that section is the one part of a seed that outsiders
# can read through its answers (mattermost-crew R-32, §5.11). /reseed runs this after writing
# a seed, so the agent re-reads the section the way an outsider would.
#
# WHY IT RUNS THE INSTALLED EXTRACTOR AND NOT A COPY. `extract_brief` is fence-aware (a
# `## ` line inside a code fence is text) and keeps `### ` subheadings. An awk or sed copy
# would drift from it silently, and the self-check would then show the agent something other
# than what the kiosk gets. So this calls crewchat-clients' own `read_brief`, from the uv tool
# environment install-crewchat.sh installed, at the version the kit pins.
#
# No crewchat-clients on this host means no shim and no kiosk fed from here, so there is
# nothing to check. That is exit 0 with a note, not a failure: /reseed writes the section on
# every host.
#
# Usage:
#   crewchat-kiosk-brief.sh [<seed>]   default: <git toplevel>/.claude/reseed-revive.md
#
# Exit codes: 0 = printed the section (or said why there is nothing to check);
#             2 = the seed is missing, or the extractor failed.
set -euo pipefail

PACKAGE="crewchat-clients"

seed="${1:-}"
if [[ -z "$seed" ]]; then
	root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
	seed="$root/.claude/reseed-revive.md"
fi
if [[ ! -f "$seed" ]]; then
	echo "crewchat-kiosk-brief: no seed at $seed" >&2
	exit 2
fi

python=""
if command -v uv >/dev/null 2>&1; then
	python="$(uv tool dir 2>/dev/null)/$PACKAGE/bin/python"
fi
if [[ -z "$python" || ! -x "$python" ]]; then
	echo "crewchat-kiosk-brief: $PACKAGE is not installed here, so no kiosk is fed from this host; nothing to check."
	exit 0
fi

# -I: isolated mode, so nothing on the caller's cwd or PYTHONPATH can shadow the package.
if ! brief="$("$python" -I -c 'import sys
from pathlib import Path
from crewchat_clients.brief import read_brief
sys.stdout.write(read_brief(Path(sys.argv[1])))' "$seed")"; then
	echo "crewchat-kiosk-brief: the $PACKAGE extractor failed on $seed" >&2
	exit 2
fi

if [[ -z "$brief" ]]; then
	echo "crewchat-kiosk-brief: the seed has no ## Kiosk section, or it is empty. The kiosk will answer: \"I have nothing to share yet.\""
	exit 0
fi

echo "crewchat-kiosk-brief: the kiosk sees exactly this, and outsiders read its answers:"
echo "----"
printf '%s\n' "$brief"
echo "----"
