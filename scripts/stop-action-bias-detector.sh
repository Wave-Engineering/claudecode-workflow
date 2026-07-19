#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# stop-action-bias-detector.sh — CC Stop hook.
#
# Implements the Godspeed decaying-mandate autonomy model (cc-workflow#818),
# replacing the fuzzy-regex permission-asking detection that false-positived
# on legitimate gates and questions.
#
# Decision model:
#   1. Gated ACTION in this turn's tool_use → STOP (salience signal; the agent
#      may state an assessment and continue). No notification fires. (#917)
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

# Extract every tool_use block in the CURRENT TURN — what the turn actually
# DID. This is the gate's substrate; text is used only by the mandate model.
#
# A Claude Code turn is MANY assistant messages (one per tool round-trip), not
# one. Scoping to a single message and taking `last` fails OPEN on the normal
# pattern — agents almost always run a verification command after acting:
#
#   msg 1: Bash git push --force origin main   <- the gated action
#   msg 2: Bash git log --oneline -3           <- `last` picks this
#   msg 3: text "Force-pushed and verified."
#
# so the gate saw only the benign command. The turn boundary is the most recent
# user entry carrying real human text (the same predicate godspeed_status uses
# to avoid counting tool_result wrappers as user turns); everything after it is
# this turn. Union, never `last`. (#917)
LAST_TOOL_USES=$(
	tail -n 600 "$TRANSCRIPT_PATH" 2>/dev/null |
		jq -cs '
      . as $all
      | ([ $all
           | to_entries[]
           | select(.value.type == "user"
               and (((.value.message.content // []) | map(select(.type == "text") | .text) | join("")) | length > 0))
           | .key ] | last // -1) as $boundary
      | [ $all[($boundary + 1):][]
          | select(.type == "assistant" and (.message.role // "") == "assistant")
          | (.message.content // [])[]
          | select(.type == "tool_use")
          | {name, input} ]
    ' 2>/dev/null || echo "[]"
)
[[ -z "$LAST_TOOL_USES" || "$LAST_TOOL_USES" == "null" ]] && LAST_TOOL_USES="[]"

# Bail only when the turn has NEITHER text NOR actions. The old text-only guard
# was a leftover of the text substrate: a tool_use-only final message (no text
# block) short-circuited before the action gate could run — text presence must
# not be a precondition for an action check. (#917)
if [[ (-z "$LAST_ASSISTANT_TEXT" || "$LAST_ASSISTANT_TEXT" == "null") && "$LAST_TOOL_USES" == "[]" ]]; then
	exit 0
fi

# Get mandate status.
ARM_STATUS=$(godspeed_status "$TRANSCRIPT_PATH")

# Compute the decision.
DECISION_LINE=$(godspeed_decision "$ARM_STATUS" "$LAST_ASSISTANT_TEXT" "$SESSION_ID" "$LAST_TOOL_USES")
DECISION=$(echo "$DECISION_LINE" | awk '{print $1}')

case "$DECISION" in

STOP)
	# Loop guard: if the hook already blocked this turn, stand down so the
	# model can answer the prod-gate prompt without triggering another block.
	STOP_HOOK_ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)
	if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
		exit 0
	fi

	# NO notification here. Notifying on trigger makes the HOOK the escalator
	# and spends BJ's attention on every false positive — before the agent has
	# assessed anything. Under a mandate the AGENT decides what merits his
	# attention, and escalates with its own vox/Discord tools. (#917)

	# `paste -d` cycles its LIST, so a multi-char delimiter would join as "a;b c".
	GATED_ACTIONS=$(godspeed_gated_actions "$LAST_TOOL_USES" | head -3 | paste -sd'|' - | sed 's/|/; /g' || true)
	[[ -z "$GATED_ACTIONS" ]] && GATED_ACTIONS="(unspecified)"

	# The reason string is the real control surface. It raises salience and
	# hands the judgment back — it does not command a halt. An unconditional
	# halt defeats /godspeed entirely, and buys nothing: this hook runs AFTER
	# the tools executed, so it could never have prevented the action. (#917)
	jq -nc --arg a "$GATED_ACTIONS" '{
		decision: "block",
		reason: ("[godspeed-GATE] Gated action detected this turn: " + $a +
			". You retain the right to proceed. If this is prod-affecting and NOT already authorized by BJ in this conversation, surface it to him now and wait. If you have assessed it as within existing authorization, or as not prod-affecting, state that assessment in one line and continue — do not halt silently, and do not re-ask for approval you already have. The ABSOLUTE prod rule still binds you; this hook is a salience signal, not the gate.")
	}'
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
