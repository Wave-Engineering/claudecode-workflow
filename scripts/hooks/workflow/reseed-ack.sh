#!/usr/bin/env bash
# reseed-ack.sh — CC UserPromptSubmit hook. Acknowledges an auto-revive. (#1225)
#
# reseed-kick.sh types `/reseed revive` into a freshly cleared session and
# retries until it sees an acknowledgement: the nonce <cwd>/.claude/reseed-ack
# disappearing. This hook is that acknowledgement — it removes the nonce when,
# and only when, the submitted prompt is exactly `/reseed revive`. Any other
# prompt (`continue`, a human typing something else) leaves it alone, so the
# kicker keeps trying rather than mistaking unrelated input for success.
#
# Contract (CC UserPromptSubmit hook):
#   stdin:  JSON with .prompt, .cwd
#   stdout: nothing (anything printed would be injected into the prompt context)
#   exit:   always 0 — never block a prompt

INPUT=$(cat 2>/dev/null || true)
PROMPT=$(printf '%s' "$INPUT" | jq -r '.prompt // empty' 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
HOOK_CWD="${HOOK_CWD:-$(pwd)}"

# Trim surrounding whitespace only; the command itself must match exactly.
PROMPT="${PROMPT#"${PROMPT%%[![:space:]]*}"}"
PROMPT="${PROMPT%"${PROMPT##*[![:space:]]}"}"

if [[ "$PROMPT" == "/reseed revive" ]]; then
	rm -f "$HOOK_CWD/.claude/reseed-ack" 2>/dev/null
fi
exit 0
