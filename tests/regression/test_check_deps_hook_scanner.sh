#!/usr/bin/env bash
# test_check_deps_hook_scanner.sh — #669: install hook-scanner must not misread an
# inline shell-assignment hook body as a missing script path.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# `_check_hook_scripts` (scripts/ci/check-deps.sh) auto-scans settings.template.json hook
# commands for referenced script paths. A hook whose `command` is an INLINE shell one-liner
# (e.g. the wavemachine Stop hook: `state="…"; [ -f "$state" ] || exit 0; …`) is NOT a path —
# scanning it as one produced a false "1 required dependency missing" on every clean install.
# This test pins:
#   1. an inline-shell hook (leading assignment) contributes ZERO missing deps (#669),
#   2. a bare path to a REAL script contributes zero,
#   3. a bare path to a GENUINELY-MISSING script is STILL reported (no over-suppression).

set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "test_check_deps_hook_scanner"
echo "──────────────────────────────────────────"

if ! command -v jq &>/dev/null; then
	echo "  [FAIL] jq not found — required for the hook scanner"
	exit 1
fi

# A real, existing hook script + a path that does NOT exist.
mkdir -p "$TMP/config"
real_hook="$TMP/real-hook.sh"
printf '#!/usr/bin/env bash\nexit 0\n' >"$real_hook"
chmod +x "$real_hook"
missing_hook="$TMP/nonexistent-hook.sh" # deliberately not created

# Template: an inline-shell Stop hook (the #669 repro), a real PreToolUse hook,
# and a genuinely-missing PreToolUse hook.
cat >"$TMP/config/settings.template.json" <<JSON
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "state=\"\${CLAUDE_PROJECT_DIR:-.}/.claude/status/state.json\"; [ -f \"\$state\" ] || exit 0; printf '{}'" } ] }
    ],
    "PreToolUse": [
      { "hooks": [ { "type": "command", "command": "$real_hook" } ] },
      { "hooks": [ { "type": "command", "command": "$missing_hook" } ] }
    ]
  }
}
JSON

# Source the library under a REPO_DIR pointed at our fixture, then run the scanner.
REPO_DIR="$TMP"
# shellcheck source=/dev/null
source "$ROOT/scripts/ci/check-deps.sh"

_check_hook_scripts >/dev/null 2>&1
missing=$?

fail=0
if [[ $missing -eq 1 ]]; then
	echo "  [PASS] exactly 1 missing dep — the genuinely-missing script, not the inline-shell hook (#669)"
else
	echo "  [FAIL] expected 1 missing dep (only the real missing script); got $missing"
	echo "         (0 ⇒ real missing script no longer detected; ≥2 ⇒ inline-shell hook still false-flagged)"
	fail=1
fi

# Focused control: a template with ONLY the inline-shell hook must report ZERO.
cat >"$TMP/config/settings.template.json" <<JSON
{
  "hooks": {
    "Stop": [
      { "hooks": [ { "type": "command", "command": "state=\"\${CLAUDE_PROJECT_DIR:-.}/.claude/status/state.json\"; [ -f \"\$state\" ] || exit 0; printf '{}'" } ] }
    ]
  }
}
JSON
_check_hook_scripts >/dev/null 2>&1
inline_only=$?
if [[ $inline_only -eq 0 ]]; then
	echo "  [PASS] inline-shell hook alone → 0 missing deps (clean-install false positive fixed)"
else
	echo "  [FAIL] inline-shell hook alone reported $inline_only missing deps (expected 0)"
	fail=1
fi

echo "──────────────────────────────────────────"
if [[ $fail -eq 0 ]]; then
	echo "  ALL PASS"
	exit 0
fi
exit 1
