#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# stop-action-bias-detector.sh — CC Stop hook.
#
# Implements the Godspeed decaying-mandate autonomy model (cc-workflow#818),
# replacing the fuzzy-regex permission-asking detection that false-positived
# on legitimate gates and questions.
#
# Decision model:
#   1. Gated-axis present (prod/deploy/irreversible) → STOP + notify BJ
#   2. No mandate (UNARMED/HALTED) → NOOP; hook stands down entirely
#   3. Mandate active (godspeed in last N user turns):
#      bar = d/N (d = user turns since godspeed)
#      supplied = 80% if test sentinel exists, else 40%
#      supplied >= bar → GO (continue autonomously, no block)
#      supplied <  bar → ASK (block + checkpoint prompt; model names gap for BJ)
#
# Arm:  type `godspeed` in any user turn → mandate active
# Halt: type `HALT!` (exact) → mandate cancelled until next godspeed
#
# Contract (Claude Code Stop hook):
#   stdin:  JSON with .transcript_path, .session_id, .stop_hook_active
#   stdout: JSON {"decision":"block","reason":"..."} to block; empty to pass
#
# Disable: export STOP_ACTION_BIAS_HOOK_DISABLED=1
#
# Performance budget: <100ms. jq scan + optional discord/vox on STOP/ASK.
#
# Issue: cc-workflow#818. Predecessor: cc-workflow#732/#776.

set -uo pipefail

# Kill-switch before any work.
if [[ "${STOP_ACTION_BIAS_HOOK_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

# Source the lookback utility from the same directory as this hook.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/godspeed-lookback.sh"

INPUT=$(cat 2>/dev/null || true)
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
	exit 0
fi

# Extract the last assistant turn text (skip thinking and tool_use blocks).
LAST_ASSISTANT_TEXT=$(
	tail -n 200 "$TRANSCRIPT_PATH" 2>/dev/null |
		jq -rs '
      [.[] | select(.type == "assistant" and (.message.role // "") == "assistant")]
      | last
      | (.message.content // [])
      | map(select(.type == "text") | .text)
      | join(" ")
    ' 2>/dev/null
)

if [[ -z "$LAST_ASSISTANT_TEXT" || "$LAST_ASSISTANT_TEXT" == "null" ]]; then
	exit 0
fi

# Get mandate status.
ARM_STATUS=$(godspeed_status "$TRANSCRIPT_PATH")

# Compute the decision.
DECISION_LINE=$(godspeed_decision "$ARM_STATUS" "$LAST_ASSISTANT_TEXT" "$SESSION_ID")
DECISION=$(echo "$DECISION_LINE" | awk '{print $1}')

case "$DECISION" in

STOP)
	# Loop guard: if the hook already blocked this turn, stand down so the
	# model can answer the prod-gate prompt without triggering another block.
	STOP_HOOK_ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)
	if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
		exit 0
	fi
	_godspeed_notify "STOP"
	printf '{"decision":"block","reason":"[godspeed-STOP] Gated axis detected (prod/deploy/irreversible keyword). This action requires explicit user approval — surface it to BJ before proceeding. The Godspeed mandate does not override the ABSOLUTE prod rule."}\n'
	;;

NOOP)
	# No mandate active; hook stands down. Normal call-and-response.
	exit 0
	;;

GO)
	# Mandate active and confidence meets the bar. Continue autonomously.
	exit 0
	;;

ASK)
	# Mandate active but confidence is below bar. Block and emit checkpoint.
	# The model's one-liner names its uncertainty for BJ — not re-evaluated by
	# the hook. BJ's next turn is the resolution.
	local_d=$(echo "$DECISION_LINE" | awk '{print $2}')
	local_bar=$(echo "$DECISION_LINE" | awk '{print $3}')
	local_supplied=$(echo "$DECISION_LINE" | awk '{print $4}')
	N_val="${GODSPEED_WINDOW:-200}"

	# Loop guard first: if the hook already blocked once this turn, stand down.
	# (The model answered the checkpoint; don't notify again or pile on.)
	STOP_HOOK_ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)
	if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
		exit 0
	fi

	_godspeed_notify "ASK" "$local_d" "$N_val"
	printf '{"decision":"block","reason":"[godspeed-checkpoint] Mandate at d=%s/N=%s (bar=%s%%, supplied=%s%%). State in one sentence what you are uncertain about — specifically: is it (a) execution correctness, (b) scope alignment, or (c) side-effects? If genuinely confident, say so and continue."}\n' \
		"$local_d" "$N_val" "$local_bar" "$local_supplied"
	;;

*)
	exit 0
	;;
esac
