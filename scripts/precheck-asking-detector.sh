#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# precheck-asking-detector.sh — CC Stop hook.
#
# Detects when the assistant asks permission to run /precheck instead of
# running it. Per CLAUDE.md MANDATORY: Pre-Commit Gate.
#
# Godspeed integration (cc-workflow#818):
#   - ARMED: uses the decaying-mandate decision model instead of narrow regex.
#     The mandate already covers "don't ask permission" broadly; the narrow
#     precheck pattern is superseded.
#   - UNARMED/HALTED: keeps the original narrow-regex behavior. This hook is
#     cheap and targeted enough to remain active outside a mandate.
#
# Contract (Claude Code Stop hook):
#   stdin:  JSON with .transcript_path, .session_id, .stop_hook_active
#   stdout: JSON {"decision":"block","reason":"..."} to block; empty to pass
#
# Disable: export PRECHECK_ASKING_HOOK_DISABLED=1
#
# Performance budget: <100ms.
#
# Issue: cc-workflow#542 / #545. Godspeed integration: cc-workflow#818.

set -uo pipefail

if [[ "${PRECHECK_ASKING_HOOK_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

# Source the lookback utility.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/godspeed-lookback.sh"

INPUT=$(cat 2>/dev/null || true)
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
	exit 0
fi

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

ARM_STATUS=$(godspeed_status "$TRANSCRIPT_PATH")

case "$ARM_STATUS" in

ARMED*)
	# Mandate active: stop-action-bias-detector.sh owns the full mandate
	# decision model and all notifications. Stand down here to avoid duplicate
	# blocks and double Discord/vox pings. When the mandate is in effect the
	# action-bias hook already covers "don't ask permission" broadly.
	exit 0
	;;

*)
	# UNARMED / HALTED: original narrow-regex behavior.
	# Three patterns for "asking whether to run /precheck":
	#   1. Interrogative  — trigger word within ~40 chars of "precheck", ending "?"
	#   2. Deferral       — "let me know" idiom near "precheck"
	#   3. Inverted       — "precheck" before the trigger word, same sentence, ending "?"
	PATTERN_INTERROGATIVE='(?i)\b(shall|should|can|may|do you want me to|ready (for|to))\b.{0,40}/?precheck.{0,80}\?'
	PATTERN_DEFERRAL='(?i)\blet me know\b.{0,40}/?precheck'
	PATTERN_INVERTED='(?i)/?precheck[^.?!\n]{0,40}\b(should|shall|need|ready|appropriate)\b[^.?!\n]{0,40}\?'

	if printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_INTERROGATIVE" 2>/dev/null ||
		printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_DEFERRAL" 2>/dev/null ||
		printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_INVERTED" 2>/dev/null; then
		printf '{"decision":"block","reason":"Per CLAUDE.md MANDATORY Pre-Commit Gate: do not ask whether to run /precheck — run it. The checklist that /precheck presents is the approval gate; the start of /precheck is unilateral. Continue this turn by invoking /precheck now."}\n'
	fi
	;;
esac
