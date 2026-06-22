#!/usr/bin/env bash
# stop-action-bias-detector.sh — CC Stop hook.
#
# Detects when the assistant ends a turn by handing a decision back to the
# user ("want me to proceed?", "should I…?", "shall I…?") instead of acting
# on something it already knows how to do. Forces the turn to continue with
# a default-to-action reminder, per CLAUDE.md MANDATORY: Default to Action.
#
# This is the GENERAL sibling of precheck-asking-detector.sh (#542), which
# catches the precheck-specific case. Same Stop-hook contract and budget.
#
# Contract (Claude Code Stop hook):
#   stdin:  JSON with .transcript_path, .session_id, .stop_hook_active
#   stdout: JSON with {"decision":"block","reason":"..."} to force the
#           assistant to continue this turn; empty stdout (exit 0) to no-op.
#
# Disable: export STOP_ACTION_BIAS_HOOK_DISABLED=1
#
# Performance budget: <50ms. Single jq pass over the tail of the transcript;
# no MCP calls, no network, no file writes.
#
# Issue: cc-workflow#732 — paired with the CLAUDE.md prose rule (same issue).

set -uo pipefail

# Kill-switch before any work.
if [[ "${STOP_ACTION_BIAS_HOOK_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

INPUT=$(cat 2>/dev/null || true)
TRANSCRIPT_PATH=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)

# Loop guard: if this Stop hook already fired this turn (the assistant was
# already nudged and still chose to end on a permission-ask), allow the stop.
# A genuine gate re-affirmed after one reminder is respected — the hook kills
# the REFLEXIVE ask, not the deliberate one.
STOP_HOOK_ACTIVE=$(printf '%s' "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null || true)
if [[ "$STOP_HOOK_ACTIVE" == "true" ]]; then
	exit 0
fi

if [[ -z "$TRANSCRIPT_PATH" || ! -f "$TRANSCRIPT_PATH" ]]; then
	exit 0
fi

# Last assistant text (concat text blocks of the most recent assistant turn;
# skip thinking + tool_use). Last 200 lines is plenty — a permission-ask is
# always the most recent assistant message.
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

# Permission-ask / decision-handback tells — scoped DELIBERATELY to
# permission-seeking phrasings, NOT to all questions. A genuine information-
# seeking question or an architectural fork ("Should I use Postgres or MySQL?",
# "Which schema should I target?") asks the user to CHOOSE or to supply a FACT —
# those are legitimate stops the rule protects, and must NOT fire. The failure
# class is asking PERMISSION TO ACT on something already known.
#   - PATTERN_PROCEED: "want me to … ?" forms — inherently permission-to-act.
#   - PATTERN_PERMIT:  "should/shall I" ONLY when followed by an action/permission
#     verb (proceed, merge, deploy, …). This is the load-bearing guard (#732
#     review C1): bare "should I" introduces just as many forks/clarifications as
#     permission-asks, so it is excluded — only the verb-gated form matches, so
#     "should I use X or Y?" / "which X should I target?" correctly pass through.
# Each requires a "?" within proximity (no sentence terminator [^.?!\n] between)
# so a mid-sentence mention doesn't fire. Case-insensitive.
PATTERN_PROCEED='(?i)\b(want me to|do you want me to|would you like me to|ready (for me to|to proceed))\b[^.?!\n]{0,60}\?'
PATTERN_PERMIT='(?i)\b(should|shall) i\s+(go ahead|proceed|continue|start|begin|merge|deploy|push|run|commit|create|land|ship|kick off|move on|do (it|that|this|so))\b[^.?!\n]{0,40}\?'
PATTERN_WORD='(?i)\b(just )?say the word\b' # unanchored like the sibling's edge; kill-switch covers quoted-rule prose
PATTERN_DEFER='(?i)\blet me know\b[^.?!\n]{0,30}\b(if|whether|when)\b[^.?!\n]{0,30}\b(you want|i should|to proceed|go ahead)\b'

if printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_PROCEED" 2>/dev/null ||
	printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_PERMIT" 2>/dev/null ||
	printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_WORD" 2>/dev/null ||
	printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_DEFER" 2>/dev/null; then
	cat <<'JSON'
{"decision":"block","reason":"Per CLAUDE.md MANDATORY: Default to Action — you ended by asking permission to do something. If you already know what to do and it is safe, understood, and in your lane, DO IT now instead of asking; stopping blocks everyone downstream and spends the user's attention. Stop ONLY for a genuinely new irreversible/prod action the user has NOT already agreed to, or a real architectural fork. Agreement persists — completing work the user already directed is not a new gate. If this IS a legitimate gate, continue the turn and state it plainly as a gate with the specific reason; otherwise continue by taking the action."}
JSON
	exit 0
fi

# --- concluded ∧ asked (cc-workflow#776 / fleet incident 2026-06-21) ---------
# A subtler over-pause than the bare permission-ask above: the turn STATES a
# team-converged conclusion AND asks the user to ratify it in the SAME message
# ("we converged … BJ, your call?"). For an already-converged decision in the
# agent's delegated lane, the converging IS the green light; routing it back to
# the user for ratify is the over-pause. Requires the CONJUNCTION (conclusion
# marker AND ratify-ask) so a bare prod gate ("BJ — your call on the prod
# push?"), which has no conclusion marker, does NOT fire and stays surfaced.
PATTERN_CONCLUSION='(?i)\b(converged|convergence|agreed|aligned|endorsed|locked in|the right move|only logical|consensus|we (all )?agree|team[\- ]converged)\b'
PATTERN_RATIFY='(?i)\b(BJ|@?schwifty7759)\b[^.?!\n]{0,40}\b(ratify|approve|your (call|nod|go|go-ahead|read|move|sign[\- ]?off|concur))\b[^.?!\n]{0,10}\?'
# SAFETY negative-guard (cc-workflow#776): never fire when a genuinely-gated axis
# (prod / deploy / release / ship / go-live / force-push / irreversible / secrets /
# migration / …) appears ANYWHERE in the turn. NOTE: this matches the whole
# message, not only the ratify-ask clause — an unrelated mention of a gated term
# also suppresses. That is deliberately the SAFE direction: this hook's "block"
# PUSHES the agent to act, so firing on a real prod gate would push an unapproved
# prod action, violating CLAUDE.md's ABSOLUTE prod rule. A missed nudge
# (false-negative) is cheap; pushing prod (false-positive) is not — so the axis
# list is intentionally over-broad. Applied ONLY to this new case — the
# permission-ask patterns above legitimately catch "should I merge/push?".
PATTERN_GATED_AXIS='(?i)\b(prod|production|deploy|release|rollout|ship|cut[\- ]?over|go[\- ]?live|force[\- ]?push|publish|promote|rotate|tear[\- ]?down|irreversible|destroy|destructive|drop|wipe|delete|secret|credential|migrat|tag|merge to (main|master|prod)|fleet[\- ]wide)\b'

if printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_CONCLUSION" 2>/dev/null &&
	printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_RATIFY" 2>/dev/null &&
	! printf '%s' "$LAST_ASSISTANT_TEXT" | grep -Pq "$PATTERN_GATED_AXIS" 2>/dev/null; then
	cat <<'JSON'
{"decision":"block","reason":"Per CLAUDE.md MANDATORY: Default to Action + standing authority — you stated a team-converged conclusion AND asked the user to ratify it in the same turn (the concluded-and-asked over-pause). For an already-converged decision in your delegated lane (non-prod, team-aligned, within your standing authority), the converging IS the green light; surfacing it for ratify is the over-pause. Stop ONLY for: (a) a genuinely new irreversible/prod action the user has NOT already agreed to; (b) a real fork where the user's choice changes what gets built; (c) novel risk requiring user-judgment they hold. Otherwise continue by taking the action."}
JSON
	exit 0
fi

exit 0
