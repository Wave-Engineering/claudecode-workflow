#!/usr/bin/env bash
# aoe-preflight.sh — rehearse a container the way it is ACTUALLY launched.
#
# WHY THIS EXISTS (#1085). Three separate fixes (#1076 bootstrap wiring, #1079
# onboarding state, #1082 GitHub access) were each verified green and each turned
# out to be partially bypassed in production. Every one of those verifications
# used `docker run` with the profile's extra_volumes — which reproduces the MOUNTS
# but not the LAUNCHER. Only `aoe` sets
#
#     CLAUDE_CONFIG_DIR=/root/.claude
#
# and mounts its own config there, and that single environment variable is what
# redirected settings, MCP registrations, onboarding state, workspace trust and
# credential lookup away from everything the image and bootstrap had prepared.
# Five distinct production symptoms, one unobserved variable.
#
# The lesson is not "add another assertion". It is that a harness which
# reproduces the inputs but not the INVOKER is not a rehearsal. This script
# launches through aoe and asserts behaviour from inside the resulting container.
#
# Usage:  scripts/ci/aoe-preflight.sh [profile] [--keep]
# Exit:   0 all checks pass; 1 a check failed; 2 usage/environment problem.
set -uo pipefail

PROFILE="${1:-dogfood}"
[[ "${1:-}" == --* ]] && PROFILE="dogfood"
KEEP=0
for a in "$@"; do [[ "$a" == "--keep" ]] && KEEP=1; done

command -v aoe >/dev/null 2>&1 || {
	echo "aoe-preflight: aoe not installed — cannot rehearse the real launch path" >&2
	exit 2
}
command -v docker >/dev/null 2>&1 || {
	echo "aoe-preflight: docker not available" >&2
	exit 2
}

WS="$(mktemp -d -t aoe-preflight-XXXXXX)"
SESSION_ID=""
CONTAINER=""

cleanup() {
	((KEEP)) && {
		echo "  --keep: leaving session $SESSION_ID / container $CONTAINER / $WS"
		return 0
	}
	[[ -n "$CONTAINER" ]] && docker rm -f "$CONTAINER" >/dev/null 2>&1
	[[ -n "$SESSION_ID" ]] && aoe -p "$PROFILE" remove "$SESSION_ID" >/dev/null 2>&1
	rm -rf "$WS"
	return 0
}
trap cleanup EXIT

FAILED=0
pass() { printf '  [PASS] %s\n' "$1"; }
fail() {
	printf '  [FAIL] %s\n' "$1" >&2
	[[ -n "${2:-}" ]] && printf '         %s\n' "$2" >&2
	FAILED=$((FAILED + 1))
}

echo "==> launching via aoe (profile: $PROFILE, workspace: $WS)"
SESSION_ID="$(timeout 180 aoe -p "$PROFILE" add --sandbox --launch "$WS" 2>&1 |
	grep -oE 'ID:[[:space:]]+[0-9a-f]+' | awk '{print $2}' | head -1)"
if [[ -z "$SESSION_ID" ]]; then
	echo "aoe-preflight: aoe did not report a session id — cannot continue" >&2
	exit 2
fi

# Resolve the container by the workspace we asked for, not by "the newest one" —
# other agents may be starting concurrently on this host.
for _ in $(seq 1 30); do
	for c in $(docker ps -q --filter 'name=aoe-sandbox'); do
		if docker inspect "$c" --format '{{range .Mounts}}{{println .Source}}{{end}}' 2>/dev/null | grep -qxF "$WS"; then
			CONTAINER="$c"
			break 2
		fi
	done
	sleep 2
done
[[ -n "$CONTAINER" ]] || {
	echo "aoe-preflight: no container found mounting $WS" >&2
	exit 2
}
echo "==> container ${CONTAINER:0:12}"

x() { docker exec -u ubuntu "$CONTAINER" "$@" 2>&1; }

# --- 1. the launcher's own environment ---------------------------------------
# shellcheck disable=SC2016  # deliberate: expand INSIDE the container, not here
CFGDIR="$(x sh -c 'echo "${CLAUDE_CONFIG_DIR:-<unset>}"' | tr -d '\r')"
echo "  (CLAUDE_CONFIG_DIR=$CFGDIR — the variable no docker-run harness ever saw)"

# ASSERT it, never assume it. If aoe injects this per-exec rather than at container
# creation, a plain `docker exec` will not see it — and then every check below
# silently degrades to the docker-run harness this script exists to replace, and
# reports all-green while rehearsing the wrong thing.
if [[ "$CFGDIR" == "<unset>" ]]; then
	echo "aoe-preflight: CLAUDE_CONFIG_DIR is not visible to docker exec." >&2
	echo "  This is NOT a rehearsal — it is the docker-run harness that missed" >&2
	echo "  #1076/#1079/#1082. Refusing to report a result." >&2
	exit 2
fi

# --- 2. settings must be READABLE, or the CLI skips them ENTIRELY -------------
if [[ "$CFGDIR" != "<unset>" ]] && ! x test -r "$CFGDIR/settings.json"; then
	fail "settings unreadable at $CFGDIR/settings.json" \
		"the CLI skips files with errors ENTIRELY — all hooks and permissions are lost"
else
	pass "settings readable by the runtime user"
fi

# --- 3. kit MCP servers present in the config the CLI ACTUALLY reads ----------
# NO FALLBACK. os.path.exists() returns False on EACCES as well as on absence, so
# a fallback to ~/.claude.json reads the IMAGE config — which the build guarantees
# carries all five kit servers — and reports PASS on precisely the unfixed image
# whose symptom was zero MCP servers. Confirmed against the control run: this
# check passed while settings and onboarding both failed.
MCP="$(x python3 -c "
import json, os
p = os.environ['CLAUDE_CONFIG_DIR'].rstrip('/') + '/.claude.json'
try:
    with open(p) as fh:
        print(len(json.load(fh).get('mcpServers', {})), p)
except Exception as e:
    print('UNREADABLE', p, type(e).__name__)
" | tr -d '\r')"
MCP_N="${MCP%% *}"
MCP_WHERE="${MCP#* }"
if [[ "$MCP_N" =~ ^[0-9]+$ ]] && ((MCP_N >= 5)); then
	pass "kit MCP servers registered where the CLI reads ($MCP_N in $MCP_WHERE)"
else
	fail "kit MCP servers not readable in the CLI's config ($MCP)" \
		"the image registers them at build time into \$HOME — under aoe the CLI reads elsewhere"
fi

# --- 4. auth, and NOT via a leaked env credential ------------------------------
# Strip bootstrap's own stderr BEFORE matching. x() folds stderr into stdout, and
# bootstrap's credential diagnostic contains the word "revoked" (by design — it
# tells the operator what to suspect). The first cut grepped the merged stream and
# so reported FAIL by matching its own advice text, against a container that
# authenticated perfectly. An instrument must not read its own output as evidence.
AUTH="$(x claude -p 'reply with exactly: AUTH_OK' |
	grep -vE '^\[bootstrap\]|^bootstrap:' |
	grep -oE 'AUTH_OK|has been revoked|Please run /login' | head -1)"
if [[ "$AUTH" == "AUTH_OK" ]]; then
	pass "agent authenticates"
else
	fail "agent did not authenticate (saw: ${AUTH:-nothing})" \
		"if this says 'revoked', check \$CLAUDE_CONFIG_DIR/.credentials.json BEFORE the mounted token"
fi

# Ask for the COUNT rather than relying on exec exit status: an exec failure
# would otherwise read as "absent" and pass, the opposite polarity to every
# other check here.
GHTOK="$(x sh -c 'env | grep -c "^GH_TOKEN=" || true' | tr -d '\r')"
if [[ ! "$GHTOK" =~ ^[0-9]+$ ]]; then
	fail "could not read the agent environment (got: $GHTOK)"
elif ((GHTOK > 0)); then
	fail "GH_TOKEN present in agent env" \
		"an org-admin PAT must never be inherited by every child process"
else
	pass "GH_TOKEN absent from agent env (file modality held)"
fi

# --- 5. git can actually LAND work, not merely call the API -------------------
if x sh -c 'command -v gh >/dev/null && gh api user --jq .login >/dev/null 2>&1'; then
	pass "gh authenticated"
else
	fail "gh not authenticated" "no push, no PR, no merge, no /scpmmr"
fi
if x sh -c 'git config --global --get-regexp "credential.*github" >/dev/null 2>&1'; then
	pass "git credential helper configured (gh auth alone does NOT let git push)"
else
	fail "git has no credential helper" "gh pr create shells out to git push and will fail"
fi

# --- 6. reaches a usable prompt with ZERO keystrokes ---------------------------
OUT="$(timeout 20 docker exec -t -u ubuntu -w /workspace/"$(basename "$WS")" \
	"$CONTAINER" claude 2>&1 || true)"
CLEAN="$(printf '%s' "$OUT" | sed -E 's/\x1b\[[0-9;?]*[a-zA-Z]//g; s/\x1b[()][A-Z]//g; s/\x1b[=>]//g' | tr -d '\r\n \t')"
if [[ ${#CLEAN} -lt 50 ]]; then
	fail "could not read the agent's screen (${#CLEAN} bytes)" "instrument saw nothing — not a pass"
elif printf '%s' "$CLEAN" | grep -q 'Selectloginmethod'; then
	fail "login menu appeared"
elif printf '%s' "$CLEAN" | grep -q 'Choosethetextstyle'; then
	fail "theme picker appeared" "onboarding state is not in the config the CLI reads"
elif printf '%s' "$CLEAN" | grep -q 'trustthisfolder'; then
	fail "trust dialog appeared" "trust must be recorded for the ACTUAL workspace path"
elif printf '%s' "$CLEAN" | grep -qi 'SettingsError'; then
	fail "Settings Error panel appeared"
elif ! printf '%s' "$CLEAN" | grep -qiE 'shortcuts|bypasspermissions|ctxremaining|forshortcuts'; then
	# A denylist alone passes on anything unrecognised — a crash trace, an API
	# error panel, a rate-limit notice, or a reworded wizard in a future CLI.
	# Require positive evidence of prompt chrome.
	fail "no recognisable prompt chrome on screen" \
		"matched no known failure AND no known prompt — treat as unknown, not pass"
else
	pass "reaches a prompt with zero keystrokes"
fi

# --- 7. every configured hook resolves IN THIS NAMESPACE ----------------------
# POSITIVE CONTROL FIRST. A zero here is only meaningful if bootstrap actually
# ran: an exec failure yields non-numeric, and a container where the agent never
# started yields 0 — both of which would read as "no bad hooks". That is the
# empty-denominator shape the rest of this repo is written against.
HOOKOUT="$(x sh -c 'claude -p ok 2>&1' || true)"
BOOTLINES="$(printf '%s' "$HOOKOUT" | grep -c '^\[bootstrap\]' || true)"
BADHOOKS="$(printf '%s' "$HOOKOUT" | grep -c 'does not exist in this container' || true)"
if [[ ! "$BOOTLINES" =~ ^[0-9]+$ ]] || ((BOOTLINES == 0)); then
	fail "no bootstrap output — cannot judge hook paths" \
		"a zero from an instrument that saw nothing is not a pass"
elif ((BADHOOKS > 0)); then
	fail "$BADHOOKS configured hook(s) do not resolve in the container" \
		"host absolute paths cannot resolve here — they fail at first tool use"
else
	pass "all configured hook paths resolve ($BOOTLINES bootstrap lines seen)"
fi

echo
if ((FAILED)); then
	echo "aoe-preflight: $FAILED check(s) FAILED" >&2
	exit 1
fi
echo "aoe-preflight: all checks passed (profile: $PROFILE)"
