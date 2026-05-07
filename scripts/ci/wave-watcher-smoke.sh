#!/usr/bin/env bash
# Smoke test for wave-watcher.
#
# Builds (or trusts an existing) wave-watcher, points it at a fixture tree
# with three .claude/status/state.json files, and curls its endpoints to
# verify aggregation works end-to-end. Exits 0 on success, non-zero on any
# probe failure.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WW_DIR="${REPO_DIR}/scripts/wave-watcher"
PORT="${WAVE_WATCHER_SMOKE_PORT:-37777}"
TMPROOT="$(mktemp -d -t ww-smoke-XXXXXX)"
trap 'cleanup' EXIT

cleanup() {
	if [[ -n "${DAEMON_PID:-}" ]] && kill -0 "${DAEMON_PID}" 2>/dev/null; then
		kill -TERM "${DAEMON_PID}" 2>/dev/null || true
		sleep 0.2
		kill -KILL "${DAEMON_PID}" 2>/dev/null || true
	fi
	rm -rf "${TMPROOT}"
}

info() { echo "  [+] $*"; }
fail() {
	echo "  [!] $*" >&2
	exit 1
}

# Build three fixture projects with three different shapes.
mkdir -p "${TMPROOT}/projects/p1/.claude/status" \
	"${TMPROOT}/projects/p2/.claude/status" \
	"${TMPROOT}/projects/p3/.sdlc/waves" \
	"${TMPROOT}/projects/p1/.git" \
	"${TMPROOT}/projects/p2/.git" \
	"${TMPROOT}/projects/p3/.git"

cat >"${TMPROOT}/projects/p1/.claude/status/state.json" <<'JSON'
{"schema_version":3,"current_wave":"1a","current_action":{"action":"flight-1","label":"Flight 1","detail":""},"waves":{"1a":{"status":"in_progress","mr_urls":{}}},"issues":{},"deferrals":[]}
JSON
cat >"${TMPROOT}/projects/p2/.claude/status/state.json" <<'JSON'
{"schema_version":3,"current_wave":"2a","current_action":{"action":"idle","label":"idle","detail":""},"waves":{"2a":{"status":"completed","mr_urls":{}}},"issues":{},"deferrals":[{"issue":99,"status":"pending"}]}
JSON
cat >"${TMPROOT}/projects/p3/.sdlc/waves/state.json" <<'JSON'
{"schema_version":3,"current_wave":"3a","current_action":{"action":"idle","label":"idle","detail":""},"waves":{"3a":{"status":"pending","mr_urls":{}}},"issues":{},"deferrals":[]}
JSON
echo '[remote "origin"]
	url = https://github.com/x/y.git' >"${TMPROOT}/projects/p1/.git/config"
echo '[remote "origin"]
	url = git@gitlab.com:a/b.git' >"${TMPROOT}/projects/p2/.git/config"
echo '[remote "origin"]
	url = https://github.com/c/d.git' >"${TMPROOT}/projects/p3/.git/config"

cat >"${TMPROOT}/config.json" <<JSON
{"scan_roots":["${TMPROOT}/projects"],"poll_interval_ms":500,"port":${PORT},"surfaces":["statusline"],"max_depth":4}
JSON

# Pick the runtime: prefer a built binary if present, else run TS via bun.
if [[ -x "${WW_DIR}/dist/wave-watcher" ]]; then
	RUN=("${WW_DIR}/dist/wave-watcher" run)
elif command -v bun >/dev/null 2>&1; then
	RUN=(bun "${WW_DIR}/launcher.ts" run)
else
	fail "neither dist/wave-watcher nor bun is available"
fi

info "starting wave-watcher (${RUN[*]})"
WAVE_WATCHER_CONFIG="${TMPROOT}/config.json" \
	WAVE_WATCHER_STATE_DIR="${TMPROOT}/state-dir" \
	"${RUN[@]}" >"${TMPROOT}/daemon.log" 2>&1 &
DAEMON_PID=$!

# Wait for /health to come up.
deadline=$((SECONDS + 10))
until curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; do
	if [[ $SECONDS -ge $deadline ]]; then
		echo "daemon log:"
		cat "${TMPROOT}/daemon.log" >&2
		fail "wave-watcher did not become healthy within 10s"
	fi
	sleep 0.2
done
info "daemon healthy at :${PORT}"

# Wait for an aggregation cycle.
sleep 1

# Probe /api/projects.
PROJECTS_JSON="$(curl -sf "http://127.0.0.1:${PORT}/api/projects")"
COUNT="$(echo "${PROJECTS_JSON}" | jq -r '.projects | length')"
if [[ "${COUNT}" != "3" ]]; then
	fail "expected 3 projects, got ${COUNT}: ${PROJECTS_JSON}"
fi
info "/api/projects reports 3 projects"

# Probe /statusline.
STATUSLINE="$(curl -sf "http://127.0.0.1:${PORT}/statusline")"
if [[ -z "${STATUSLINE}" ]]; then
	fail "/statusline returned empty"
fi
info "/statusline returned: $(echo "${STATUSLINE}" | cat -v)"

# Probe /events — pull a single chunk.
EVENTS="$(curl -sN --max-time 2 "http://127.0.0.1:${PORT}/events" || true)"
if ! echo "${EVENTS}" | grep -q "event: snapshot"; then
	fail "/events did not emit initial snapshot frame"
fi
info "/events emitted snapshot frame"

# Probe statusline file written by the surface.
STATUSLINE_FILE="${TMPDIR:-/tmp}/wave-watcher-statusline.txt"
if [[ -f "${STATUSLINE_FILE}" ]]; then
	info "statusline file: $(cat "${STATUSLINE_FILE}")"
fi

info "all probes succeeded"
