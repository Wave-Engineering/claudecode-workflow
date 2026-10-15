#!/usr/bin/env bash
# reseed-kick.sh — type `/reseed revive` into a freshly cleared session until the
# session acknowledges it, then stop. Launched detached (setsid) by
# hooks/workflow/reseed-revive.sh. (#1225)
#
# WHY THIS EXISTS. The revive used to be `(sleep 2 && tmux send-keys … continue)
# & disown`: a fixed two-second guess at when the TUI would accept input,
# fire-and-forget, no check it landed, and a log line saying "tmux trigger sent"
# either way. A keystroke typed before the TUI is ready is silently dropped, so
# the revive missed often enough that BJ routinely found the seed by hand.
#
# THE ACK. Before the first send this writes a nonce, <project_root>/.claude/
# reseed-ack. The UserPromptSubmit hook reseed-ack.sh removes it when the
# submitted prompt is exactly `/reseed revive`. A missing nonce is the only
# evidence a send landed; everything else is a guess.
#
# THE SCHEDULE. Wait, check for the ack, send; repeat with backoff (default
# 3 6 12 24 s); one final wait after the last send. Checking BEFORE each resend
# is what stops a landed send from being followed by a duplicate.
#
# OUTCOMES, logged as they are, never as "sent":
#   acked after <N>   — the session received the Nth send (0: a human typed it)
#   FAILED …          — no ack after the whole schedule; BJ is paged via
#                       notify-bj.sh (vox + #call-4-bj) naming the pane
#
# Usage: reseed-kick.sh <tmux_pane> <project_root>
# Env:   RESEED_KICK_BACKOFF  space-separated delays in seconds (default "3 6 12 24")
#        RESEED_KICK_LOG      log file (default ~/.claude/logs/reseed-kick.log)
#        RESEED_KICK_NOTIFY   notifier (default notify-bj.sh beside this script)
# Exit:  0 acked; 1 FAILED; 2 usage

set -uo pipefail

pane="${1:-}"
root="${2:-}"
LOG_FILE="${RESEED_KICK_LOG:-$HOME/.claude/logs/reseed-kick.log}"
NOTIFY="${RESEED_KICK_NOTIFY:-$(dirname "$0")/notify-bj.sh}"

log() {
	mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
	printf '%s pane=%s root=%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$pane" "$root" "$*" >>"$LOG_FILE" 2>/dev/null || true
}

if [[ -z "$pane" || ! -d "$root" ]]; then
	log "FAILED usage: reseed-kick.sh <tmux_pane> <project_root>"
	exit 2
fi

read -r -a delays <<<"${RESEED_KICK_BACKOFF:-3 6 12 24}"
if [[ ${#delays[@]} -eq 0 ]]; then
	log "FAILED empty RESEED_KICK_BACKOFF"
	exit 2
fi

ACK="$root/.claude/reseed-ack"

page_bj() { # <reason>
	"$NOTIFY" \
		"Reseed auto-revive failed in tmux pane $pane. Type slash reseed revive there." \
		"⚠️ **Reseed auto-revive FAILED** — tmux pane \`$pane\`, project \`$root\`: $1. Type \`/reseed revive\` in that pane." \
		>/dev/null 2>&1 || log "notify failed — BJ was NOT paged"
}

# The nonce MUST exist before the first check: "absent" is how an ack reads, so
# a nonce that failed to write would read as an instant success with nothing sent.
if ! { mkdir -p "$root/.claude" && printf '%s %s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >"$ACK"; } 2>/dev/null; then
	log "FAILED cannot write nonce $ACK — nothing sent"
	page_bj "could not write its acknowledgement nonce, so it sent nothing"
	exit 1
fi

acked() { [[ ! -e "$ACK" ]]; }

sends=0
for d in "${delays[@]}"; do
	sleep "$d"
	if acked; then
		log "acked after $sends"
		exit 0
	fi
	if tmux send-keys -t "$pane" "/reseed revive" Enter 2>/dev/null; then
		sends=$((sends + 1))
	else
		log "send to pane failed (tmux exit non-zero) — will retry"
	fi
done
sleep "${delays[${#delays[@]} - 1]}" # not ${delays[-1]}: bash 3.2 (macOS) lacks it
if acked; then
	log "acked after $sends"
	exit 0
fi

rm -f "$ACK"
log "FAILED no ack after $sends send(s) over the schedule (${delays[*]})"
page_bj "no acknowledgement after $sends send(s)"
exit 1
