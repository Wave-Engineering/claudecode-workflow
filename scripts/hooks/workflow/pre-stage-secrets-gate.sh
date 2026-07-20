#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# pre-stage-secrets-gate.sh — PreToolUse hook for Bash(git add*)
#
# Scans the files being staged for secret-pattern filenames.
# If a match is found, blocks and warns the agent.
# Does NOT hard-block — emits a warning that requires confirmation.
#
# Disable: SECRETS_GATE_DISABLED=1
#
# Three defects fixed in #929, all of which made this gate WORSE than absent:
#
#   1. Patterns were unanchored, so `\.key` matched the JS builtin `Object.keys`
#      and `\.env` matched `foo.environment.ts`. A gate that cries wolf on a
#      language builtin is one somebody disables — which is how a real secret
#      ships.
#   2. File extraction took everything after `git add`, so a compound command
#      (`git add x.ts && grep "Object.keys" x.ts`) dragged arguments of the
#      NEXT command into the file list. That is how a builtin became a "file".
#   3. Flag-stripping reduced `git add -A` to an EMPTY list, so the broadest
#      staging command — the one most likely to sweep in a secret nobody
#      noticed — was never scanned at all. Silent, and reported success.
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

# Secret-pattern filenames.
#
# Extension patterns are anchored to END of basename: a secret is a file NAMED
# `server.key`, not any name containing the letters ".key". Dotfile-style env
# files are matched deliberately at the START (`.env`, `.env.local`,
# `.env.production`) since that family carries the suffix after the marker.
SECRET_PATTERNS='(^\.env$|^\.env\.|\.secret$|\.key$|\.pem$|\.p12$|\.pfx$|^credentials\.json$|^service-account.*\.json$|-credentials\.|\.tfvars$)'

# Extract the file arguments.
#
# Truncate at the first shell operator so arguments belonging to a LATER
# command in the same line are never treated as files being staged.
ARGS=$(printf '%s' "$COMMAND" | sed -E 's/^[[:space:]]*git[[:space:]]+(add|stage)[[:space:]]*//')
ARGS=${ARGS%%&&*}
ARGS=${ARGS%%||*}
ARGS=${ARGS%%;*}
ARGS=${ARGS%%|*}

# Does this invocation stage broadly? `-A`, `--all`, `-u`, `--update`, or a
# bare `.` all stage files not named on the command line, so the argument list
# cannot tell us what is being staged — ask git instead.
BROAD=0
if printf '%s' "$ARGS" | grep -qE '(^|[[:space:]])(-A|--all|-u|--update|-[A-Za-z]*A[A-Za-z]*|\.)([[:space:]]|$)'; then
	BROAD=1
fi

# Drop flags, then strip surrounding quotes from each remaining token.
NAMED=$(printf '%s' "$ARGS" | tr ' ' '\n' | grep -vE '^-' | tr -d '"'"'"'' | grep -vE '^\s*$' || true)

CANDIDATES=""
if [[ "$BROAD" == "1" ]]; then
	# What WOULD be staged. Without this the broadest command scanned nothing.
	CANDIDATES=$(git status --porcelain 2>/dev/null | sed -E 's/^.{3}//' | sed -E 's/^.* -> //' || true)
fi
CANDIDATES=$(printf '%s\n%s\n' "$CANDIDATES" "$NAMED" | grep -vE '^\s*$' || true)

MATCHES=""
while IFS= read -r file; do
	[[ -z "$file" ]] && continue
	base=$(basename "$file" 2>/dev/null || printf '%s' "$file")
	if printf '%s' "$base" | grep -qEi "$SECRET_PATTERNS"; then
		MATCHES="${MATCHES}${file} "
	fi
done <<<"$CANDIDATES"

if [[ -n "$MATCHES" ]]; then
	SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || true)
	source "$(dirname "$0")/metrics.sh"
	log_metric "$SESSION_ID" "hook_block" "hook=pre-stage-secrets-gate" "files=$MATCHES"
	printf '{"decision":"block","reason":"Potential secrets detected in staged files: %s. Verify with the user before staging these files."}' "$MATCHES"
	exit 0
fi

exit 0
