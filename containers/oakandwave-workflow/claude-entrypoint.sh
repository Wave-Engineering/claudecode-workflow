#!/usr/bin/env bash
# claude-entrypoint.sh — run bootstrap in the agent's OWN process, then become it.
#
# WHY THIS FILE EXISTS (#1076).
#
# bootstrap.sh was written to be the agent's parent — its last act is "refusing to
# hand off to the agent" — but nothing ever invoked it. The Dockerfile set no
# ENTRYPOINT INTO THE AGENT ("aoe manages the container lifecycle"), and aoe
# `docker exec`s `claude` into the running container as a SEPARATE process — never
# through this file's own PID-1 process. Measured on a live container: claude = PID
# 13 with PPID 0. There was no process path from bootstrap to the agent, so every
# bootstrap responsibility — skills-sync, settings merge, secret projection, R-14
# env validation — was shipped, unit-tested, documented, and inert.
#
# PID 1 itself (cc-workflow#1179): the Dockerfile DOES now declare an ENTRYPOINT —
# `tini`, wrapping `sleep infinity` — but that's an unrelated fix (fleet-wide zombie
# reaping: aoe's `docker exec`'d agent process is parentless from birth in this
# container's PID namespace, and when IT forks work that outlives it, those
# children reparent to PID 1 on exit — which needs to actually reap them). It
# exists solely to keep the container alive with a process that reaps; it has
# no bearing on the bootstrap-never-runs gap this file closes, because aoe
# still never routes `claude` through PID 1 to get here.
#
# It went unnoticed because tests/contained-workflow/test_bootstrap.py drives
# bootstrap.sh directly by subprocess. That proves the script WORKS; it never asks
# whether anything CALLS it. Same shape as the inert R-14 check (#1061), trivy
# parsing zero manifests (#1056), and `extra_volumes = [0 items]` (#1069): the
# manifest declares it, the runtime does not have it, and the gap is silent.
#
# WHY A WRAPPER AND NOT `sandbox.extra_env`.
#
# aoe does support `sandbox.extra_env` (it sits beside extra_volumes in the same
# config struct), and it would carry the token into `docker exec`. It was rejected:
#   - it fixes ONLY auth, leaving every other bootstrap phase inert;
#   - it takes KEY=VALUE with no passthrough form, so the live credential would sit
#     in plaintext in each profile's config.toml — a file that is MANUALLY copied
#     per profile, i.e. exactly the drift surface check-mount-drift.sh (#1069)
#     exists to police, now holding a secret;
#   - it makes correct behaviour depend on host-side config we do not ship.
# The wrapper is a seam we own, inside the image, identical for every profile.
#
# WHICH PATH IT REPLACES — all of them, and that is not paranoia.
#
# The first cut installed this at /usr/local/bin/claude only, and it was INERT:
#
#   docker exec <c> claude --version       -> wrapper bypassed
#   docker exec <c> /usr/local/bin/claude  -> wrapper runs
#
# `docker exec` resolves against the IMAGE's configured PATH, not a shell's, and
# that PATH reaches /root/.local/bin/claude (shipped by the base image) BEFORE
# /usr/local/bin. So the fix for "bootstrap is declared but never wired" shipped
# declared-but-never-wired. Confirmed by hiding the wrapper: bare `claude` still ran.
#
# Every reachable `claude` is therefore replaced with this wrapper, all of them
# exec'ing one canonical real binary, and scripts/ci/assert-no-claude-bypass.sh
# fails the BUILD if any reachable `claude` is not this file. The marker below is
# what that check greps for — do not remove it.
#
#   OAW-CLAUDE-BOOTSTRAP-WRAPPER
#
# WHY BOOTSTRAP IS SOURCED, NOT EXECUTED  <-- do not "simplify" this
#
# Environment flows DOWN, never up. bootstrap's whole job includes `export`ing
# CLAUDE_CODE_OAUTH_TOKEN; run as a child it would export into a process that then
# exits, and the agent would see nothing — the identical end state to the bug this
# file fixes, with all the logs looking healthy. Sourcing puts the assignments in
# THIS shell, which then `exec`s the agent and passes them on.
#
# Sourcing also preserves the fail-loud contract for free: bootstrap.sh ends in
# `main "$@"` and exits 1 when FATAL_COUNT > 0, so a fatal aborts this script and
# the agent is never started — which is what "refusing to hand off" always meant.
set -euo pipefail

BOOTSTRAP="${OAW_BOOTSTRAP:-${KIT_SRC:-/opt/oakandwave-workflow}/containers/oakandwave-workflow/bootstrap.sh}"
REAL_CLAUDE="${OAW_REAL_CLAUDE:-/usr/local/bin/claude-real}"

if [[ ! -x "$REAL_CLAUDE" ]]; then
	echo "[claude-entrypoint] FATAL: real CLI not found at $REAL_CLAUDE" >&2
	echo "  The image build moves the base CLI aside and installs this wrapper in" >&2
	echo "  its place. If that step did not run, this container has a wrapper and" >&2
	echo "  no agent. Rebuild the image." >&2
	exit 127
fi

# OAW_SKIP_BOOTSTRAP is a deliberate escape hatch: a container whose bootstrap is
# broken must still be reachable to be repaired, otherwise the fail-loud design
# locks you out of the box you need a shell on.
if [[ -n "${OAW_SKIP_BOOTSTRAP:-}" ]]; then
	echo "[claude-entrypoint] WARN: OAW_SKIP_BOOTSTRAP set — starting agent UNBOOTSTRAPPED." >&2
	echo "  No skills-sync, no settings merge, no secret projection, no env validation." >&2
	exec "$REAL_CLAUDE" "$@"
fi

if [[ ! -f "$BOOTSTRAP" ]]; then
	# Refuse rather than start. An agent that boots without bootstrap is the exact
	# silent-inert failure this issue was filed for; starting it "helpfully" would
	# reproduce the bug while looking fine.
	echo "[claude-entrypoint] FATAL: bootstrap not found at $BOOTSTRAP" >&2
	echo "  Refusing to start an unbootstrapped agent. Set OAW_SKIP_BOOTSTRAP=1 to" >&2
	echo "  override for repair work." >&2
	exit 1
fi

# shellcheck source=/dev/null
. "$BOOTSTRAP"

exec "$REAL_CLAUDE" "$@"
