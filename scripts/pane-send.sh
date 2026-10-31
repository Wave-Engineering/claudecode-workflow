#!/usr/bin/env bash
# pane-send.sh — clear a tmux pane's input line, type literal text, then press Enter (#1366).
#
# Usage: pane-send.sh <pane> <text>
#
# Every kit path that types into an agent pane goes through this. An agent pane often
# holds a dim ghost prompt suggestion (27 of 32 panes in one sweep, one of them an
# approval-shaped `yes prod for ...`), or BJ's own half-typed draft. A send that reaches
# Enter without first replacing the input submits whatever is there as if BJ typed it.
#
# THE INVARIANT: Enter is only ever sent after non-empty literal text, in the same tmux
# command. Typed text replaces a ghost suggestion, so Enter can never accept one.
#
#   - C-e then eight C-u clear the input first, so a draft is discarded rather than
#     submitted with the text appended. Claude Code's keybinding docs: C-u deletes from
#     the cursor to the line start, "Repeat to clear across lines in multiline input".
#     C-e moves to the end of the cursor's line first, so text right of the cursor goes
#     too. The repeats also take an empty `!` line out of shell mode, which one C-u
#     doesn't, so the text is never run as bash. If the TUI doesn't bind a key, the
#     worst case is a no-op, and the invariant still holds. Escape is NOT used: on a
#     running turn it interrupts the turn, and twice on an empty input it opens the
#     rewind picker.
#   - `-l` sends the text literally, so tmux never reads it as a key name (a caller
#     passing `Enter` or `C-m` as "text" would otherwise send a bare Enter).
#   - The three steps are one tmux invocation (a `;`-separated command list), so no
#     other client can interleave keys between them.
#   - Text ending in `;` is refused: in a command list tmux strips a trailing `;` from an
#     argument as a separator, so `;` alone would type nothing and Enter would accept the
#     ghost.
#
# Known limit: what survives the clear is the lines below the cursor's line, and the
# top lines of a draft longer than eight lines. Either is submitted with the text.
#
# Exit: tmux's exit code; 2 on a usage error (an empty pane or text, text containing
# a newline or carriage return, text starting with `-` or ending with `;`), with tmux
# never called.

set -uo pipefail

pane="${1:-}"
text="${2:-}"

usage() {
	echo "pane-send.sh: $1" >&2
	exit 2
}

[[ -n "$pane" ]] || usage "empty pane"
[[ -n "$text" ]] || usage "empty text"
[[ "$text" != *$'\n'* && "$text" != *$'\r'* ]] || usage "text contains a newline, which would submit part of it"
[[ "$text" != -* ]] || usage "text starts with '-', which tmux would parse as an option"
[[ "$text" != *';' ]] || usage "text ends with ';', which tmux would read as a command separator"

tmux send-keys -t "$pane" C-e C-u C-u C-u C-u C-u C-u C-u C-u \; send-keys -t "$pane" -l "$text" \; send-keys -t "$pane" Enter
