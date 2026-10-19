#!/usr/bin/env bash
# reseed-kick.sh — type `/reseed revive` into a freshly cleared session until the
# session acknowledges it, then stop. Launched detached (setsid) by
# hooks/workflow/reseed-revive.sh. (#1225, #1244)
#
# WHY THIS EXISTS. The revive used to be `(sleep 2 && tmux send-keys … continue)
# & disown`: a fixed two-second guess at when the TUI would accept input,
# fire-and-forget, no check it landed, and a log line saying "tmux trigger sent"
# either way. A keystroke typed before the TUI is ready is silently dropped, so
# the revive missed often enough that BJ routinely found the seed by hand.
#
# THE ACK — two signals, either one counts:
#   1. The nonce. Before the first send this writes <project_root>/.claude/
#      reseed-ack. The UserPromptSubmit hook reseed-ack.sh removes it when the
#      submitted prompt is exactly `/reseed revive`.
#   2. The seed was read (#1244). The nonce alone false-paged BJ whenever a
#      session revived WITHOUT that prompt being submitted: through the Skill
#      tool, or inside a turn a peer message or task notification started right
#      after /clear (the typed sends then sit queued behind the busy turn). Every
#      revive path touches the seed, so: an assistant tool call in the session's
#      transcript (SessionStart's .transcript_path) whose input names
#      reseed-revive.md, or a Skill call for `reseed revive`. It must be the
#      agent's own tool call, not just the path appearing in the transcript: the
#      SessionStart notice names the seed too. Only entries from this kick's
#      start onward count, so a pre-clear Write of the seed cannot ack.
#
# A BUSY SESSION IS NOT A DROPPED KEYSTROKE. The transcript says whether the
# session is live (an assistant or main-thread `api-request` entry since the
# start; `api-request` lands when each request goes out, before any reply) and
# whether it is busy (the last such entry is a request, or a `tool_use` stop).
# `user` entries are not used: /clear writes its own within a second of this
# kick starting. A send into a busy session only queues behind the turn and lands
# later as a stale turn, so while busy the kicker does not type. An IDLE live
# session that has not revived (it answered a peer and stopped) gets one send per
# idle spell, which the nonce then acks. A live session is given up to
# RESEED_KICK_LIVE_WAIT past the schedule before the page.
#
# THE SCHEDULE. Wait, check for the ack, send; repeat with backoff (default
# 3 6 12 24 s); one final wait after the last send. Checking BEFORE each resend
# is what stops a landed send from being followed by a duplicate.
#
# OUTCOMES, logged as they are, never as "sent":
#   acked after <N>              — the session received the Nth send (0: a human typed it)
#   acked (seed read) after <N>  — the transcript shows the revive, whatever its path
#   FAILED …                     — no ack; BJ is paged via notify-bj.sh (vox +
#                                  #call-4-bj) naming the pane
#
# Usage: reseed-kick.sh <tmux_pane> <project_root> [<transcript_path>]
#        No transcript path → signal 2 and the live/busy checks are off; the nonce alone decides.
# Env:   RESEED_KICK_BACKOFF    space-separated delays in seconds (default "3 6 12 24")
#        RESEED_KICK_LIVE_WAIT  whole seconds to wait on a live session (default 600)
#        RESEED_KICK_POLL       whole seconds between polls during that wait (default 5)
#                               (either one not a positive integer → its default)
#        RESEED_KICK_LOG        log file (default ~/.claude/logs/reseed-kick.log)
#        RESEED_KICK_NOTIFY     notifier (default notify-bj.sh beside this script)
# Exit:  0 acked; 1 FAILED; 2 usage

set -uo pipefail

pane="${1:-}"
root="${2:-}"
transcript="${3:-}"
LOG_FILE="${RESEED_KICK_LOG:-$HOME/.claude/logs/reseed-kick.log}"
NOTIFY="${RESEED_KICK_NOTIFY:-$(dirname "$0")/notify-bj.sh}"
LIVE_WAIT="${RESEED_KICK_LIVE_WAIT:-600}"
POLL="${RESEED_KICK_POLL:-5}"
# Shell arithmetic is integer-only: `0.5` would be a syntax error and `0` a loop
# that never ends and never pages.
[[ "$LIVE_WAIT" =~ ^[1-9][0-9]*$ ]] || LIVE_WAIT=600
[[ "$POLL" =~ ^[1-9][0-9]*$ ]] || POLL=5

log() {
	mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null
	printf '%s pane=%s root=%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$pane" "$root" "$*" >>"$LOG_FILE" 2>/dev/null || true
}

if [[ -z "$pane" || ! -d "$root" ]]; then
	log "FAILED usage: reseed-kick.sh <tmux_pane> <project_root> [<transcript_path>]"
	exit 2
fi

read -r -a delays <<<"${RESEED_KICK_BACKOFF:-3 6 12 24}"
if [[ ${#delays[@]} -eq 0 ]]; then
	log "FAILED empty RESEED_KICK_BACKOFF"
	exit 2
fi

ACK="$root/.claude/reseed-ack"
# Second resolution, compared against each entry's first 19 chars: an entry in
# the same second as the start counts as after it.
START="$(date -u +%Y-%m-%dT%H:%M:%S)"

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

# transcript_has <jq-filter over one assistant entry> — any match from START on.
# Process substitution, not a pipe: the last line of a live transcript can be
# half-written, and jq's error exit must not mask a hit printed before it.
transcript_has() {
	[[ -n "$transcript" && -f "$transcript" ]] || return 1
	grep -q '^hit$' < <(jq -r --arg s "$START" \
		"select(.type == \"assistant\" and ((.timestamp // \"\")[0:19]) >= \$s) | select($1) | \"hit\"" \
		"$transcript" 2>/dev/null)
}
seed_read() {
	transcript_has 'any(.message.content[]?; .type == "tool_use" and
		((.input | tostring | test("reseed-revive\\.md")) or
		 (.name == "Skill" and (.input.skill // "") == "reseed" and ((.input.args // "") | test("revive")))))'
}
# last_activity — "<type>:<stop_reason>" of the last activity entry from START on;
# empty when there is none (or no transcript, or no jq). Activity: an assistant
# entry, or a main-thread `api-request` (written at the START of every request,
# before any reply, so a turn reads busy while it is still thinking), or an
# `api-request-shape`. A side query with another querySource is not a turn.
last_activity() {
	[[ -n "$transcript" && -f "$transcript" ]] || return 0
	jq -r --arg s "$START" \
		'select(((.timestamp // "")[0:19]) >= $s)
		 | select(.type == "assistant" or .type == "api-request-shape" or
			(.type == "api-request" and (.querySource // "repl_main_thread") == "repl_main_thread"))
		 | .type + ":" + (.message.stop_reason // "")' "$transcript" 2>/dev/null | tail -n 1
}
# state — "fresh" (no activity yet: a send may be dropped, so keep trying),
# "busy" (a request is out, or the model asked for a tool: a send would only
# queue behind the turn) or "idle" (any other end: end_turn, or a turn ended by
# an API error, which a send may well recover).
state() {
	local a
	a="$(last_activity)"
	case "$a" in
	"") echo fresh ;;
	api-request*:* | assistant:tool_use | assistant:) echo busy ;;
	*) echo idle ;;
	esac
}

send() { # returns 1 when tmux refused, so an idle spell is not marked as served
	if tmux send-keys -t "$pane" "/reseed revive" Enter 2>/dev/null; then
		sends=$((sends + 1))
	else
		log "send to pane failed (tmux exit non-zero) — will retry"
		return 1
	fi
}

acked() {
	[[ ! -e "$ACK" ]] && return 0
	if seed_read; then
		rm -f "$ACK"
		via=" (seed read)"
		return 0
	fi
	return 1
}

via=""
sends=0
idle_sent=0 # a send already made into the current idle spell
for d in "${delays[@]}"; do
	sleep "$d"
	if acked; then
		log "acked${via} after $sends"
		exit 0
	fi
	case "$(state)" in
	fresh) send ;;
	busy) idle_sent=0 ;;
	idle) ((idle_sent)) || { send && idle_sent=1; } ;;
	esac
done
sleep "${delays[${#delays[@]} - 1]}" # not ${delays[-1]}: bash 3.2 (macOS) lacks it
if acked; then
	log "acked${via} after $sends"
	exit 0
fi

# Checked AFTER the final wait, not before it: a turn whose first entry lands
# during that wait is live too, and must not be paged as "no ack".
if [[ "$(state)" != fresh ]]; then
	waited=0
	while ((waited < LIVE_WAIT)); do
		if acked; then
			log "acked${via} after $sends (session was live; waited ${waited}s)"
			exit 0
		fi
		case "$(state)" in
		busy) idle_sent=0 ;;
		idle) ((idle_sent)) || { send && idle_sent=1; } ;;
		esac
		sleep "$POLL"
		waited=$((waited + POLL))
	done
	if acked; then
		log "acked${via} after $sends (session was live; waited ${waited}s)"
		exit 0
	fi
	rm -f "$ACK"
	log "FAILED session live but no revive seen after ${waited}s (${sends} send(s))"
	page_bj "the session is running but has not read its seed after ${waited}s"
	exit 1
fi

rm -f "$ACK"
log "FAILED no ack after $sends send(s) over the schedule (${delays[*]})"
page_bj "no acknowledgement after $sends send(s)"
exit 1
