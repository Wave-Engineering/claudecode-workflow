#!/usr/bin/env bash
# precheck-asking-detector.sh — CC Stop hook.
#
# Detects when the assistant has just written a "shall I run /precheck?"
# style question and forces the turn to continue with corrective context,
# per CLAUDE.md MANDATORY: Pre-Commit Gate.
#
# Contract (Claude Code Stop hook):
#   stdin:  JSON with .transcript_path, .session_id, .stop_hook_active
#   stdout: JSON with {"decision":"block","reason":"..."} to force the
#           assistant to continue this turn; empty stdout (exit 0) to no-op.
#
# Disable: export PRECHECK_ASKING_HOOK_DISABLED=1
#
# Performance budget: <50ms. Single jq pass over the tail of the transcript;
# no MCP calls, no network, no file writes.
#
# Issue: cc-workflow#542 — paired with #541 prose tightening.

set -uo pipefail

# Honor the kill-switch env var before any work.
if [[ "${PRECHECK_ASKING_HOOK_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

# Read hook stdin.
INPUT=$(cat 2>/dev/null || true)
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
	exit 0
fi

# Pull the last assistant text content. The transcript is JSONL where each
# line is an event. Reverse-iterate, take the first event of type=assistant
# with role=assistant, concat all blocks where .type == "text" (skipping
# thinking and tool_use blocks — thinking is not user-visible and tool_use
# has no .text). Limit to the last 200 lines for performance; an asking
# message will always be the most recent assistant turn.
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

# Two alternations:
#   1. Interrogative — trigger word (shall/should/can/may/do you want me to/
#      ready for|to) within ~40 chars of "precheck", ending with "?" within
#      ~80 chars. Catches direct asking like "Shall I run /precheck?".
#   2. Deferral — "let me know" idiom near "precheck", no "?" required.
#      Catches "Let me know when I should run precheck." which is asking by
#      deferral.
# Both case-insensitive. Negative cases the regex must NOT match: past-tense
# precheck mentions, different-command questions ("Shall I run /scp?"),
# distant trigger-and-precheck pairs, and ordinary checklist text.
#
# Falsy edge: an assistant message documenting the rule by quoting a
# forbidden phrase will trigger the hook. The PRECHECK_ASKING_HOOK_DISABLED
# kill-switch exists for those cases.
PATTERN_INTERROGATIVE='(?i)\b(shall|should|can|may|do you want me to|ready (for|to))\b.{0,40}/?precheck.{0,80}\?'
PATTERN_DEFERRAL='(?i)\blet me know\b.{0,40}/?precheck'

if printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_INTERROGATIVE" 2>/dev/null ||
	printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_DEFERRAL" 2>/dev/null; then
	cat <<'JSON'
{"decision":"block","reason":"Per CLAUDE.md MANDATORY Pre-Commit Gate: don't ask whether to run /precheck — run it. The checklist that /precheck presents is the approval gate; the start of /precheck is unilateral. Continue this turn by invoking /precheck now."}
JSON
	exit 0
fi

exit 0
