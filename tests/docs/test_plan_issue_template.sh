#!/usr/bin/env bash
# test_plan_issue_template.sh — Asserts docs/plan-issue-template.md exists
# and contains all required sections (AC for cc-workflow#509).
#
# Exits 0 on pass, 1 on any failure.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOC="$REPO_DIR/docs/plan-issue-template.md"

fail=0
check() {
	local label="$1"
	local pattern="$2"
	if grep -Fq "$pattern" "$DOC"; then
		echo "  [+] $label"
	else
		echo "  [!] $label — missing: $pattern"
		fail=1
	fi
}

echo "test_plan_issue_template"
echo "──────────────────────────────────────────"

if [[ ! -f "$DOC" ]]; then
	echo "  [!] docs/plan-issue-template.md does not exist"
	exit 1
fi
echo "  [+] docs/plan-issue-template.md exists"

# Required top-level sections
check "Overview section" "## Overview"
check "Body Template section" "## Body Template"
check "Comment Typed-Prefix Table section" "## Comment Typed-Prefix Table"
check "Mutation Rules section" "## Mutation Rules"
check "Examples section" "## Examples"

# Body template sentinel (verbatim from §5.1.2)
check "PLAN-ISSUE v1 sentinel comment" "PLAN-ISSUE v1 — frozen content only."
check "Goal placeholder" "# Plan: <Name>"
check "Phases heading in body template" "## Phases"
check "References heading in body template" "## References"

# Cross-link to authoritative source
check "Cross-link to phase-epic-taxonomy-devspec.md" "phase-epic-taxonomy-devspec.md"

# All 9 typed prefixes from §5.1.3
check "Prefix: ledger" "\`[ledger D-NNN]\`"
check "Prefix: status" "\`[status <field>=<value>]\`"
check "Prefix: phase-start" "\`[phase-start Phase N]\`"
check "Prefix: phase-complete" "\`[phase-complete Phase N]\`"
check "Prefix: story-merge" "\`[story-merge Story X.Y #NNN]\`"
check "Prefix: drift-halt" "\`[drift-halt]\`"
check "Prefix: gate-result" "\`[gate-result <pass\\|block>]\`"
check "Prefix: plan-complete" "\`[plan-complete]\`"
check "Prefix: concern" "\`[concern]\`"

# Canonical example reference
check "Canonical example cites cc-workflow#499" "cc-workflow#499"

echo ""
if [[ $fail -ne 0 ]]; then
	echo "FAIL"
	exit 1
fi
echo "PASS"
