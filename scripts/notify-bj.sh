#!/usr/bin/env bash
# notify-bj.sh — get BJ's attention from a script: vox, then a post to #call-4-bj.
#
# For scripts that run with no agent attached (a detached kicker, a hook) and
# so cannot call an MCP tool. The post goes through `crewchat-send call-4-bj`
# first (#1348): the checkout's agent posts it on its default backend, OaW
# Mattermost. When crewchat-send is not on PATH or exits non-zero (no daemon,
# no session, no such channel), it goes to Discord #call-4-bj exactly as before.
# A page never goes quiet: if both fail, the exit is 1.
#
# crewchat-send reads the agent from the checkout's .claude/agent-identity.json:
# NOTIFY_BJ_REPO_ROOT names that checkout, else it is the working directory's.
# The text travels on its STDIN, never argv.
#
# Discord token discipline, as godspeed-lookback.sh had it: DISCORD_BOT_TOKEN
# env wins, then DISCORD_TOKEN_PATH, then ~/.secrets/discord-bot-token, then the
# deprecated ~/secrets/discord-bot-token; the token travels on STDIN, never
# argv, because /proc/<pid>/cmdline is world-readable.
#
# Usage: notify-bj.sh <vox-message> <post-message>
# Exit:  0 the post was accepted (stderr names the path: crewchat or discord);
#        1 neither path took it (vox is best-effort and does not affect the
#        exit code); 0 without sending when muted.
#
# Muted (exit 0, nothing sent) under NOTIFY_BJ_DISABLED=1 or any non-empty $CI,
# so tests and runners never page BJ.

set -uo pipefail

vox_msg="${1:-}"
post_msg="${2:-}"
[[ -n "$vox_msg" || -n "$post_msg" ]] || {
	echo "usage: notify-bj.sh <vox-message> <post-message>" >&2
	exit 2
}

if [[ "${NOTIFY_BJ_DISABLED:-0}" == "1" || -n "${CI:-}" ]]; then
	exit 0
fi

CALL_4_BJ="1518536836673310800"

if [[ -n "$vox_msg" ]] && command -v vox &>/dev/null; then
	vox "$vox_msg" >/dev/null 2>&1 || true
fi

[[ -n "$post_msg" ]] || exit 0

if command -v crewchat-send &>/dev/null; then
	root_args=()
	[[ -n "${NOTIFY_BJ_REPO_ROOT:-}" ]] && root_args=(--repo-root "$NOTIFY_BJ_REPO_ROOT")
	if printf '%s' "$post_msg" | crewchat-send call-4-bj "${root_args[@]}" >/dev/null; then
		echo "notify-bj: delivered via crewchat" >&2
		exit 0
	else
		echo "notify-bj: crewchat-send exited $?; falling back to Discord" >&2
	fi
else
	echo "notify-bj: no crewchat-send on PATH; falling back to Discord" >&2
fi

if [[ -n "${DISCORD_BOT_TOKEN:-}" ]]; then
	token=$(tr -d '[:space:]' <<<"$DISCORD_BOT_TOKEN")
else
	token_file="${DISCORD_TOKEN_PATH:-$HOME/.secrets/discord-bot-token}"
	[[ -n "${DISCORD_TOKEN_PATH:-}" || -f "$token_file" ]] || token_file="$HOME/secrets/discord-bot-token"
	[[ -f "$token_file" ]] || {
		echo "notify-bj: no Discord token (env, DISCORD_TOKEN_PATH, ~/.secrets) — Discord post not sent" >&2
		exit 1
	}
	token=$(tr -d '[:space:]' <"$token_file")
fi

printf '%s' "$token" | python3 -I -c '
import json, os, sys, urllib.request
token = sys.stdin.read().strip()
channel_id, msg = sys.argv[1], sys.argv[2]
api = os.environ.get("NOTIFY_BJ_DISCORD_API", "https://discord.com/api/v10")
req = urllib.request.Request(
    f"{api}/channels/{channel_id}/messages",
    data=json.dumps({"content": msg}).encode(),
    headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
             "User-Agent": "cc-workflow-notify-bj (https://github.com/Wave-Engineering, 1)"},
)
try:
    urllib.request.urlopen(req, timeout=15).read()
except Exception as e:
    print(f"notify-bj: Discord post failed: {e}", file=sys.stderr)
    sys.exit(1)
' "$CALL_4_BJ" "$post_msg" || exit 1
echo "notify-bj: delivered via discord" >&2
