#!/usr/bin/env bash
# sqtk-asks-sync.sh — rebuilds the statusline's asks cache from this checkout's open bj:needs
# squawks. (#1430, story 4 of #1426)
#
# The statusline lights an indicator for each open ask an agent has on `bj:needs`, by kind and
# blocking. It costs no model tokens: this script reads the squawks and writes a small file, and
# config/statusline-command.sh only renders it.
#
#   /tmp/claude-statusline-<dev_name>.asks.json
#   {"asks": [{"list": "bj:needs", "seq": 12, "kind": "approval", "blocking": true}], "synced_at": <epoch>}
#
# The file is a CACHE. The squawk text is the source of truth (an ask marker at its start,
# parsed by sqtk-answer.jq's ask_split, the contract with squawkie-talkie#163), so a lost or
# stale file is rebuilt by the next run.
#
# How it reads: .claude/sqtk-mine.json (sqtk's record of this checkout's squawks) names the
# checkout's `bj:needs` seqs; `sqtk show bj:needs --json` fetches the list once (the CLI
# handles the URL and auth); the open ones are kept and their markers parsed. The file is
# written atomically (temp file, then mv).
#
# Modes (the first argument):
#   --sync [DIR]   always sync. DIR is the checkout (default: the git toplevel of the cwd). The
#                  drain hook runs this at the end of every prompt.
#   --post-tool    PostToolUse(Bash) hook: sync only when stdin's .tool_input.command contains
#                  `sqtk add` or `sqtk set`; otherwise exit at once.
#   --stop         Stop hook: sync only when the asks file already exists, so a session with no
#                  asks pays nothing.
# The two hook modes read the checkout from stdin's .cwd.
#
# Contract: it prints nothing, never blocks, and always exits 0. A failed fetch leaves the file
# as it is; no open `bj:needs` items removes it; no identity does nothing.
#
# Config (env): SQTK_ASKS_SQTK (the sqtk to run; default `sqtk` on PATH, else the one beside the
# scripts), SQTK_ASKS_TIMEOUT (the fetch cap in seconds, default 3), SQTK_ASKS_DIR (where the
# asks file lives, default /tmp). SQUAWK_URL and SQUAWK_API_TOKEN are sqtk's own.

set -uo pipefail

MODE="${1:---sync}"
ARG_DIR="${2:-}"

LIB=$(dirname "$(readlink -f "$0")")
LIST="bj:needs"
TIMEOUT="${SQTK_ASKS_TIMEOUT:-3}"
[[ "$TIMEOUT" =~ ^[0-9]+$ ]] || TIMEOUT=3
OUT_DIR="${SQTK_ASKS_DIR:-/tmp}"

command -v jq >/dev/null 2>&1 || exit 0

INPUT=""
case "$MODE" in
--post-tool | --stop) INPUT=$(cat 2>/dev/null || true) ;;
--sync) ;;
*) exit 0 ;;
esac

# The checkout: the argument, else the hook's cwd, else the cwd; its git toplevel when it has one.
DIR="$ARG_DIR"
[[ -n "$DIR" ]] || DIR=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
[[ -n "$DIR" ]] || DIR=$(pwd)
ROOT=$(git -C "$DIR" rev-parse --show-toplevel 2>/dev/null || printf '%s' "$DIR")

# The identity names the file, as every other statusline writer resolves it. None: do nothing.
DEV=""
for f in "$DIR/.claude/agent-identity.json" "$ROOT/.claude/agent-identity.json"; do
	[[ -r "$f" ]] && DEV=$(jq -r '.dev_name // empty' "$f" 2>/dev/null || true)
	[[ -z "$DEV" ]] || break
done
[[ "$DEV" =~ ^[A-Za-z0-9._-]+$ ]] || exit 0
ASKS="$OUT_DIR/claude-statusline-${DEV}.asks.json"

case "$MODE" in
--post-tool)
	cmd=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
	[[ "$cmd" =~ sqtk[[:space:]]+(add|set)([[:space:]]|$) ]] || exit 0
	;;
--stop)
	[[ -e "$ASKS" ]] || exit 0
	;;
esac

MINE="$ROOT/.claude/sqtk-mine.json"

# Drop the cache: there is nothing open to show.
clear_asks() {
	rm -f "$ASKS" 2>/dev/null
	exit 0
}

# No record of mine, or none on bj:needs: no open ask, and no fetch.
[[ -s "$MINE" ]] || clear_asks
jq -e --arg l "$LIST" 'type == "array" and any(.[]; .list == $l)' "$MINE" >/dev/null 2>&1 || clear_asks
jq -n -L "$LIB" 'include "sqtk-answer"; 1' >/dev/null 2>&1 || exit 0

# Which sqtk: the override, else PATH, else the copy beside the scripts (the install layout).
SQTK="${SQTK_ASKS_SQTK:-}"
[[ -n "$SQTK" ]] || SQTK=$(command -v sqtk 2>/dev/null || true)
[[ -n "$SQTK" ]] || { [[ -x "$LIB/../../sqtk" ]] && SQTK="$LIB/../../sqtk"; }
[[ -n "$SQTK" ]] || exit 0

WORK=$(mktemp -d 2>/dev/null) || exit 0
trap 'rm -rf "$WORK"' EXIT

# One fetch, capped. A failure of any kind (no URL, a dead server, a bad body) leaves the file.
to=()
command -v timeout >/dev/null 2>&1 && to=(timeout "$TIMEOUT")
"${to[@]}" "$SQTK" show "$LIST" --json >"$WORK/list.json" 2>/dev/null </dev/null || exit 0
jq -e '.squawks | type == "array"' "$WORK/list.json" >/dev/null 2>&1 || exit 0

# This checkout's open items, each with its marker parsed.
jq -c -L "$LIB" --arg l "$LIST" --argjson now "$(date +%s)" --slurpfile mine "$MINE" '
	include "sqtk-answer";
	[$mine[0][] | select(.list == $l) | .seq] as $seqs
	| [.squawks[] | select(.state == "open" and (.seq as $s | $seqs | index($s)))
	   | ((.text // "") | ask_split) as $a
	   | {list: $l, seq: .seq, kind: $a.kind, blocking: $a.blocking}]
	| sort_by(.seq) as $asks
	| {asks: $asks, synced_at: $now}' "$WORK/list.json" >"$WORK/asks.json" 2>/dev/null || exit 0

jq -e '.asks | length > 0' "$WORK/asks.json" >/dev/null 2>&1 || clear_asks

# Atomic: a temp file in the same directory, then mv, so the statusline never reads half a file.
mkdir -p "$OUT_DIR" 2>/dev/null || exit 0
tmp=$(mktemp "$OUT_DIR/.claude-asks-sync.XXXXXX" 2>/dev/null) || exit 0
if cp "$WORK/asks.json" "$tmp" 2>/dev/null && mv -f "$tmp" "$ASKS" 2>/dev/null; then
	exit 0
fi
rm -f "$tmp"
exit 0
