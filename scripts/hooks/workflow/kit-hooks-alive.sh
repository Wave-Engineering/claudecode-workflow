#!/usr/bin/env bash
# kit-hooks-alive.sh — SessionStart beacon: proof the KIT'S OWN hook wiring is live.
#
# WHY THIS EXISTS (#1086).
#
# Hook wiring is supposed to be VERSIONED WITH THE RELEASE (R-06): the image digest
# IS the release, so the hooks shipped in it are the hooks that run. Under aoe that
# was not true. The CLI reads $CLAUDE_CONFIG_DIR/settings.json — aoe's own config,
# host-backed and shared by every container — and never opens the image's copy.
#
# It looked healthy, which is exactly why it survived review: that shared file had
# been seeded from a host carrying the same kit, so an EQUIVALENT hook set was
# already present and kit hooks did fire. What could not happen was version
# MOVEMENT. A hook the image added, renamed or repointed stayed on the operator's
# host timetable rather than the release's, and nothing anywhere reported the gap.
# R-06 held by coincidence, which is not the same as holding.
#
# Reading settings cannot detect that: a settings file that MENTIONS a hook proves
# nothing about whether the hook RAN. This beacon is the whole difference — it
# writes its marker only by EXECUTING, so `test -f` on the marker is a statement
# about behaviour, not about configuration. scripts/ci/aoe-preflight.sh asserts it,
# and an operator can answer "are my kit hooks live?" with one `ls`.
#
# Deliberately trivial, deliberately silent:
#   * stdout from a SessionStart hook becomes additionalContext in the agent's
#     window, so this prints NOTHING there — a beacon that spends context would be
#     a tax on every session for the life of the kit.
#   * it can never fail a session: every path exits 0.
set -uo pipefail

# No HOME means no per-user location to claim, and a fixed /tmp path would be a
# collision (and a squat target) on a multi-user host. Say nothing, do nothing.
[[ -n "${HOME:-}" ]] || exit 0

# $HOME/.claude, NOT $CLAUDE_CONFIG_DIR. Under aoe the config dir is shared by
# every container on the host, so a marker written there could not distinguish
# "this session's hooks fired" from "some other container fired them hours ago" —
# the beacon would answer a question nobody asked. $HOME/.claude is the image's
# own directory: per-container, and on a native install it is the config dir anyway.
marker_dir="$HOME/.claude"
mkdir -p "$marker_dir" 2>/dev/null || exit 0
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$marker_dir/.kit-hooks-alive" 2>/dev/null || true

exit 0
