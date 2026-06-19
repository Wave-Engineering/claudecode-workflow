#!/usr/bin/env bash
# test_skill_uses_installed_binaries.sh — regression test for issue #569.
#
# /wavemachine and /nextwave SKILL.md must invoke their supporting tooling
# via PATH-resolvable names of the installed binaries:
#
#   wave-status               (zipapp at ~/.local/bin/wave-status)
#   generate-status-panel     (script at ~/.local/bin/generate-status-panel)
#   mcp-log                   (script at ~/.local/bin/mcp-log)
#
# Forbidden patterns — these only resolve from inside the cc-workflow source
# tree and break the skill on every other project (regression introduced by
# PR #383, fixed by #569):
#
#   python3 -m wave_status            (Python module form — needs src/ on PYTHONPATH)
#   ./scripts/generate-status-panel   (relative path — needs cwd=cc-workflow root)
#   scripts/generate-status-panel     (same, no leading ./)
#   scripts/mcp-log                   (relative path)
#   scripts/wavebus/<name>            (relative path into the bus scripts; use wavebus-<name>)
#   wave_status <subcommand>          (orphan: dropped python3 -m prefix)
#
# This test scans both skill bodies and fails if any forbidden pattern is
# present. It is the locked-in invariant that prevents the regression from
# coming back via a future "convenience" edit.
#
# Pattern 5 (wavebus, #709): the bus scripts were flattened from
# scripts/wavebus/<name> to scripts/wavebus-<name>, so ./install now mirrors
# them to ~/.local/bin/wavebus-<name> (directly on PATH). nextwave must invoke
# them by bare name (wavebus-<name>), never by the old relative scripts/wavebus
# path. This is the "fifth pattern" the earlier out-of-scope note deferred.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
WAVEMACHINE="$REPO_DIR/skills/wavemachine/SKILL.md"
NEXTWAVE="$REPO_DIR/skills/nextwave/SKILL.md"

FAILS=0
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_skill_uses_installed_binaries (#569)"
echo "──────────────────────────────────────────"

for f in "$WAVEMACHINE" "$NEXTWAVE"; do
	if [[ ! -f "$f" ]]; then
		fail "skill body not found: $f"
		continue
	fi
done
[[ "$FAILS" -gt 0 ]] && exit 1

# Pattern 1: python3 -m wave_status — both files
for f in "$WAVEMACHINE" "$NEXTWAVE"; do
	if grep -q "python3 -m wave_status" "$f"; then
		fail "$(basename "$f"): contains forbidden 'python3 -m wave_status' (use 'wave-status' instead)"
		grep -n "python3 -m wave_status" "$f" | sed 's/^/    /'
	else
		pass "$(basename "$f"): no 'python3 -m wave_status'"
	fi
done

# Pattern 2: ./scripts/generate-status-panel and scripts/generate-status-panel
for f in "$WAVEMACHINE" "$NEXTWAVE"; do
	# Match scripts/generate-status-panel with or without leading ./
	if grep -qE "(\./)?scripts/generate-status-panel" "$f"; then
		fail "$(basename "$f"): contains forbidden 'scripts/generate-status-panel' path (use 'generate-status-panel' instead)"
		grep -nE "(\./)?scripts/generate-status-panel" "$f" | sed 's/^/    /'
	else
		pass "$(basename "$f"): no relative-path generate-status-panel"
	fi
done

# Pattern 3: scripts/mcp-log
for f in "$WAVEMACHINE" "$NEXTWAVE"; do
	if grep -q "scripts/mcp-log" "$f"; then
		fail "$(basename "$f"): contains forbidden 'scripts/mcp-log' path (use 'mcp-log' instead)"
		grep -n "scripts/mcp-log" "$f" | sed 's/^/    /'
	else
		pass "$(basename "$f"): no 'scripts/mcp-log'"
	fi
done

# Pattern 4: orphan wave_status (underscore, used as a command — no python3 -m
# prefix, no surrounding identifier characters). Match the substring inside
# backticks where the skill bodies present commands, since plain prose like
# "the wave_status CLI" would false-positive otherwise.
#
# We look for two call-site forms:
#   (a) backtick-inline: `wave_status <subcommand>` (most common)
#   (b) fenced-code-block: a line starting with `wave_status <subcommand>`
#       inside a ``` ... ``` block (escape route #1 noticed in code review)
for f in "$WAVEMACHINE" "$NEXTWAVE"; do
	# (a) `wave_status <word>` inside backticks
	if grep -qE '`wave_status [a-z]' "$f"; then
		fail "$(basename "$f"): contains backtick-bounded 'wave_status <subcommand>' (use 'wave-status' with hyphen)"
		grep -nE '`wave_status [a-z]' "$f" | sed 's/^/    /'
	# (b) line starting with `wave_status <word>` (fenced code block content)
	elif grep -qE '^wave_status [a-z]' "$f"; then
		fail "$(basename "$f"): contains fenced-block 'wave_status <subcommand>' (use 'wave-status' with hyphen)"
		grep -nE '^wave_status [a-z]' "$f" | sed 's/^/    /'
	else
		pass "$(basename "$f"): no orphan wave_status command form"
	fi
done

# Pattern 5: scripts/wavebus/<name> — relative path into the (now-removed)
# bus subdir. The scripts were flattened to scripts/wavebus-<name> and install
# puts them on PATH by bare name, so any relative scripts/wavebus/ reference is
# a regression (#709).
for f in "$WAVEMACHINE" "$NEXTWAVE"; do
	if grep -qE "scripts/wavebus/" "$f"; then
		fail "$(basename "$f"): contains forbidden 'scripts/wavebus/<name>' path (use bare 'wavebus-<name>')"
		grep -nE "scripts/wavebus/" "$f" | sed 's/^/    /'
	else
		pass "$(basename "$f"): no relative-path scripts/wavebus/ invocations"
	fi
done

# Positive checks — confirm the installed-binary names ARE present where
# expected. (Defensive: catches a "mass deletion" regression.)
if ! grep -qE '\bwave-status\b' "$WAVEMACHINE"; then
	fail "wavemachine: no 'wave-status' references — did the skill lose its CLI calls entirely?"
fi
if ! grep -qE '\bgenerate-status-panel\b' "$WAVEMACHINE"; then
	fail "wavemachine: no 'generate-status-panel' references"
fi
if ! grep -qE '\bmcp-log\b' "$WAVEMACHINE"; then
	fail "wavemachine: no 'mcp-log' references"
fi
if ! grep -qE '\bmcp-log\b' "$NEXTWAVE"; then
	fail "nextwave: no 'mcp-log' references"
fi
# nextwave must still reference the bus scripts — by bare name (#709).
if ! grep -qE '\bwavebus-(wave-init|flight-finalize|wave-cleanup|changelog-aggregate)\b' "$NEXTWAVE"; then
	fail "nextwave: no bare 'wavebus-<name>' references — did the bus call sites get lost?"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all checks passed"
exit 0
