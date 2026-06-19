#!/usr/bin/env bash
# test_wavemachine_preflight_tools_check.sh — regression test for issue #569.
#
# /wavemachine SKILL.md must instruct the agent to run a pre-flight existence
# check on its supporting CLIs (wave-status, generate-status-panel, mcp-log)
# and refuse to start if any is missing. This is the encoded form of BJ's
# principle: "any script or binary that an MCP needs should be installable
# somewhere any project can find and execute it."
#
# This test is intentionally a doc-shape check, not a runtime test — the
# pre-flight is behavioural instruction the agent follows, not Bash code we
# can directly execute. The check verifies the skill body still tells the
# agent to do the right thing. If a future edit silently drops the check,
# this test fails before merge.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/wavemachine/SKILL.md"

FAILS=0
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_wavemachine_preflight_tools_check (#569)"
echo "──────────────────────────────────────────"

if [[ ! -f "$SKILL" ]]; then
	fail "skill body not found: $SKILL"
	exit 1
fi

# 1. The pre-flight section must contain a `command -v` probe for ALL THREE
#    supporting CLIs in a single invocation (single command-v line — so a
#    partial probe missing one tool wouldn't slip past).
if grep -qE "command -v[^\"]*\bwave-status\b[^\"]*\bgenerate-status-panel\b[^\"]*\bmcp-log\b" "$SKILL"; then
	pass "pre-flight has 'command -v wave-status generate-status-panel mcp-log' probe"
else
	fail "pre-flight missing combined 'command -v wave-status generate-status-panel mcp-log' probe"
fi

# 2. The pre-flight must explicitly mention refusing/aborting on missing CLIs.
#    Tolerant phrasing: any of "refuse", "abort", "do not enter the loop", or
#    similar in the same paragraph as the command-v line.
if awk '
	/^## Pre-flight/,/^## /{
		# Capture the section block
		print
	}
' "$SKILL" | grep -qiE "refuse|abort|do not enter the loop"; then
	pass "pre-flight section uses refuse/abort wording"
else
	fail "pre-flight section missing refuse/abort wording — agent may not know to halt"
fi

# 3. The refusal message template must reference the cc-workflow installer,
#    so the agent's error output points the operator at the fix.
if grep -qE "claudecode-workflow.*install|\./install" "$SKILL"; then
	pass "refusal references the installer remediation path"
else
	fail "no installer-remediation pointer — refusal won't tell operator how to fix"
fi

# 4. Defensive: the skill must NOT advise PYTHONPATH hacks or 'pip install -e'
#    as an alternative to using the installed binaries. The whole point of
#    the fix is that the binaries on PATH are the contract.
if grep -qiE "PYTHONPATH=src|pip install -e.*wave_status" "$SKILL"; then
	fail "skill suggests PYTHONPATH/pip-install-e workarounds — defeats the portable-CLI contract"
else
	pass "skill does not suggest PYTHONPATH/pip-install-e workarounds"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all checks passed"
exit 0
