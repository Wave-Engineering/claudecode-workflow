#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# pre-stage-secrets-gate.sh — PreToolUse hook for Bash(git add*)
#
# Scans the files being staged for secret-pattern filenames.
# If a match is found, blocks and warns the agent.
# Does NOT hard-block — emits a warning that requires confirmation.
#
# Disable: SECRETS_GATE_DISABLED=1
set -uo pipefail

if [[ "${SECRETS_GATE_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

INPUT=$(cat 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)

if [[ -z "$COMMAND" ]]; then
	exit 0
fi

# Only gate git add / git stage commands
if ! printf '%s' "$COMMAND" | grep -qE '^\s*git\s+(add|stage)'; then
	exit 0
fi

# Extract filenames from the command (everything after git add/stage and flags)
FILES=$(printf '%s' "$COMMAND" | sed -E 's/^\s*git\s+(add|stage)\s+//' | sed -E 's/\s*-[^ ]+\s*//g')

# Secret-pattern filenames
SECRET_PATTERNS='(\.env|\.env\.|\.secret|\.key|\.pem|\.p12|\.pfx|credentials\.json|service-account.*\.json|.*-credentials\.|.*\.tfvars)'

MATCHES=""
for file in $FILES; do
	base=$(basename "$file" 2>/dev/null || echo "$file")
	if printf '%s' "$base" | grep -qEi "$SECRET_PATTERNS"; then
		MATCHES="${MATCHES}${file} "
	fi
done

if [[ -n "$MATCHES" ]]; then
	SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || true)
	source "$(dirname "$0")/metrics.sh"
	log_metric "$SESSION_ID" "hook_block" "hook=pre-stage-secrets-gate" "files=$MATCHES"
	printf '{"decision":"block","reason":"Potential secrets detected in staged files: %s. Verify with the user before staging these files."}' "$MATCHES"
	exit 0
fi

exit 0
