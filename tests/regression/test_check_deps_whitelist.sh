#!/usr/bin/env bash
# test_check_deps_whitelist.sh — #1016: the oakandwave-workflow image build gate.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
#
# The image build tolerates check-deps' expected-missing items (the discord bot
# token + the runtime-installed wtf-server hook) but must FAIL on any OTHER
# missing required dependency. Two failure shapes are covered:
#   - a normal missing dep prints "  [!] <item> — NOT FOUND …" (e.g. gh);
#   - jq itself missing bails check-deps' jq-guarded scans early: NO "NOT FOUND"
#     line, but the SUMMARY count is still nonzero (the count cross-check catches it).
# The gate is invoked exactly as the Dockerfile invokes it — directly (./…), NOT
# via `bash …` — so this also guards the script's executable bit.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE="$REPO_DIR/scripts/ci/assert-only-expected-deps-missing.sh"

pass=0
fail=0
check() { # <description> <expected-rc> <actual-rc>
	if [[ "$2" -eq "$3" ]]; then
		echo "  [PASS] $1"
		pass=$((pass + 1))
	else
		echo "  [FAIL] $1 (expected rc=$2, got rc=$3)"
		fail=$((fail + 1))
	fi
}

# The exact expected-missing set from a real container build (#1014 build log),
# less slack-bot-token which went with Slack support (#1062): the wtf hook + the
# discord token — 2 missing, all whitelisted.
expected_only='  [✓] gh (/usr/bin/gh)
  [!] hook: /home/ubuntu/.local/share/wtf-server/hooks/wtf-post-tool-use.sh — NOT FOUND
  [!]   Referenced in settings.template.json hooks
  [!] discord-bot-token — NOT FOUND (/home/ubuntu/.secrets/discord-bot-token)
2 required dependency/dependencies missing.'

# An UNEXPECTED regression: gh has gone missing (3 missing, one not whitelisted).
with_unexpected='  [!] hook: /home/ubuntu/.local/share/wtf-server/hooks/wtf-post-tool-use.sh — NOT FOUND
  [!] discord-bot-token — NOT FOUND (/home/ubuntu/.secrets/discord-bot-token)
  [!] gh — NOT FOUND (needed for: GitHub CLI)
3 required dependency/dependencies missing.'

# A clean build: nothing missing.
none_missing='  [✓] gh (/usr/bin/gh)
  [✓] jq (/usr/bin/jq)
All required dependencies present.'

# jq itself missing: check-deps' jq-guarded scans bail early, so NO "NOT FOUND"
# line is emitted, but the summary count is still nonzero. The count cross-check
# must catch this (the exact regression class #1016 targets).
jq_missing='  [!] jq not found — cannot scan settings.template.json hooks
  [!] jq not found — cannot read deps.json
2 required dependency/dependencies missing.'

rc=0
printf '%s\n' "$expected_only" | "$GATE" >/dev/null 2>&1 || rc=$?
check "tolerates ONLY the expected-missing items (secrets + wtf hook)" 0 "$rc"

rc=0
printf '%s\n' "$with_unexpected" | "$GATE" >/dev/null 2>&1 || rc=$?
check "FAILS when an unexpected dep (gh) is missing" 1 "$rc"

rc=0
printf '%s\n' "$none_missing" | "$GATE" >/dev/null 2>&1 || rc=$?
check "passes when nothing is missing" 0 "$rc"

rc=0
printf '%s\n' "$jq_missing" | "$GATE" >/dev/null 2>&1 || rc=$?
check "FAILS on a jq regression (count > NOT-FOUND lines, no NOT FOUND emitted)" 1 "$rc"

# The wtf hook whitelist is by basename — must hold for any home prefix.
rc=0
printf '%s\n' '  [!] hook: /home/bakerb/.local/share/wtf-server/hooks/wtf-post-tool-use.sh — NOT FOUND
1 required dependency/dependencies missing.' | "$GATE" >/dev/null 2>&1 || rc=$?
check "wtf-hook whitelist holds regardless of home prefix" 0 "$rc"

echo "  ${pass} passed, ${fail} failed"
[[ "$fail" -eq 0 ]]
