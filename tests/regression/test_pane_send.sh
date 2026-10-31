#!/usr/bin/env bash
# test_pane_send.sh — #1366 regression test for scripts/pane-send.sh.
#
# Every kit keystroke into an agent pane goes through pane-send.sh, so a ghost
# suggestion or a half-typed draft is never submitted. Drives it against a fake
# tmux that logs its argv:
#   - one tmux call: clear (C-e, then 32 C-u), type literally (-l), then Enter;
#   - empty text, a newline, a leading dash, a trailing ';' or an empty pane: exit 2,
#     tmux never called;
#   - a tmux failure is the helper's exit code;
#   - no other tracked file calls send-keys or tmux's `send` alias (tests, docs, the
#     changelog and Markdown outside skills/ excepted).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SEND="$REPO_DIR/scripts/pane-send.sh"

echo "test_pane_send"
echo "──────────────────────────────────────────"

FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1"
	FAILS=$((FAILS + 1))
}

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

SHIM="$WORK/shim"
mkdir -p "$SHIM"
cat >"$SHIM/tmux" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$TMUX_CALLS"
exit "${TMUX_RC:-0}"
SH
chmod +x "$SHIM/tmux"

run() { # <case> <pane> <text> [tmux rc]; sets rc and calls
	local d="$WORK/$1"
	mkdir -p "$d"
	env PATH="$SHIM:$PATH" TMUX_CALLS="$d/calls" TMUX_RC="${4:-0}" bash "$SEND" "$2" "$3" 2>"$d/err"
	rc=$?
	calls="$d/calls"
}

run ok %1 "hello there"
CLEAR="C-e$(printf ' C-u%.0s' $(seq 32))"
want="send-keys -t %1 $CLEAR ; send-keys -t %1 -l hello there ; send-keys -t %1 Enter"
if [[ $rc -eq 0 && -f "$calls" && "$(wc -l <"$calls")" -eq 1 ]] && grep -qxF -- "$want" "$calls"; then
	pass "clears, types literally, then Enter in one tmux call"
else
	fail "rc=$rc calls: $(cat "$calls" 2>/dev/null)"
fi

refuse() { # <case> <label> <pane> <text>
	run "$1" "$3" "$4"
	if [[ $rc -eq 2 && ! -e "$calls" ]]; then
		pass "$2"
	else
		fail "$2: rc=$rc calls: $(cat "$calls" 2>/dev/null)"
	fi
}
refuse empty "refuses empty text" %1 ""
refuse newline "refuses text with a newline" %1 $'a\nb'
refuse cr "refuses text with a carriage return" %1 $'a\rb'
refuse dash "refuses text starting with a dash" %1 "-x"
refuse nopane "refuses an empty pane" "" "hello"
refuse semi "refuses text that is only ';'" %1 ";"
refuse semitail "refuses text ending in ';'" %1 'foo\;'

run tmuxfail %1 "hello" 1
if [[ $rc -eq 1 ]]; then pass "propagates a tmux failure"; else fail "tmux exit 1 became $rc"; fi

# Every tracked file that runs or tells an agent to run something: not tests, docs, the
# changelog or prose Markdown, but skills' Markdown is instructions and stays in. The
# pattern also catches tmux's `send` alias and a `tmux -L x send-keys` with options between.
hits="$(git -C "$REPO_DIR" ls-files |
	awk '!/^(tests|docs)\// && !/^CHANGELOG/ && (!/\.md$/ || /^skills\//)' |
	(cd "$REPO_DIR" && xargs -d '\n' grep -lE -- 'send-keys|tmux[^|;&]*\bsend(-keys)?\b' 2>/dev/null) | sort)"
if [[ "$hits" == "scripts/pane-send.sh" ]]; then
	pass "no send-keys outside the helper"
else
	fail "send-keys outside scripts/pane-send.sh: $hits"
fi

echo
if [[ $FAILS -eq 0 ]]; then
	echo "test_pane_send: all passed"
	exit 0
fi
echo "test_pane_send: $FAILS failed"
exit 1
