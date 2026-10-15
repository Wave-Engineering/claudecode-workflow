#!/usr/bin/env bash
# notify-bj.sh — get BJ's attention from a script: vox, then a post to #call-4-bj.
#
# For scripts that run with no agent attached (a detached kicker, a hook) and
# so cannot call the disc-server MCP tool. Same token discipline as
# godspeed-lookback.sh's _godspeed_notify: DISCORD_BOT_TOKEN env wins, then
# DISCORD_TOKEN_PATH, then ~/.secrets/discord-bot-token, then the deprecated
# ~/secrets/discord-bot-token; the token travels on STDIN, never argv, because
# /proc/<pid>/cmdline is world-readable.
#
# Usage: notify-bj.sh <vox-message> <discord-message>
# Exit:  0 the Discord post was accepted; 1 it was not (vox is best-effort and
#        does not affect the exit code); 0 without sending when muted.
#
# Muted (exit 0, nothing sent) under NOTIFY_BJ_DISABLED=1 or any non-empty $CI,
# so tests and runners never page BJ.

set -uo pipefail

vox_msg="${1:-}"
discord_msg="${2:-}"
[[ -n "$vox_msg" || -n "$discord_msg" ]] || {
	echo "usage: notify-bj.sh <vox-message> <discord-message>" >&2
	exit 2
}

if [[ "${NOTIFY_BJ_DISABLED:-0}" == "1" || -n "${CI:-}" ]]; then
	exit 0
fi

CALL_4_BJ="1518536836673310800"

if [[ -n "$vox_msg" ]] && command -v vox &>/dev/null; then
	vox "$vox_msg" >/dev/null 2>&1 || true
fi

[[ -n "$discord_msg" ]] || exit 0

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
import json, sys, urllib.request
token = sys.stdin.read().strip()
channel_id, msg = sys.argv[1], sys.argv[2]
req = urllib.request.Request(
    f"https://discord.com/api/v10/channels/{channel_id}/messages",
    data=json.dumps({"content": msg}).encode(),
    headers={"Authorization": f"Bot {token}", "Content-Type": "application/json",
             "User-Agent": "cc-workflow-notify-bj (https://github.com/Wave-Engineering, 1)"},
)
try:
    urllib.request.urlopen(req, timeout=15).read()
except Exception as e:
    print(f"notify-bj: Discord post failed: {e}", file=sys.stderr)
    sys.exit(1)
' "$CALL_4_BJ" "$discord_msg"
