#!/usr/bin/env bash
# test_campaign_bundle_in_sync.sh — #749: campaign Workflow bundle integrity + no-drift guard.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Mirrors test_bundle_in_sync.sh for the campaign engine: a Dynamic Workflow MUST be ONE
# self-contained file with `export const meta` first. campaign-bundle.mjs inlines campaign-loop.js
# (the unit-tested pure core) into campaign-workflow.bundled.js. This pins that the committed bundle:
#   1. exists and is in sync with its source modules (campaign-bundle.mjs --check),
#   2. parses as valid JS,
#   3. contains NO import statements (self-contained),
#   4. has `export const meta` as its first statement,
#   5. exports ONLY meta (helper exports stripped).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NW="skills/nextwave"
BUNDLE="$REPO_DIR/$NW/campaign-workflow.bundled.js"
fail=0

echo "test_campaign_bundle_in_sync"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the campaign bundle test"
	exit 1
fi

# 1. bundle exists
if [[ ! -f "$BUNDLE" ]]; then
	echo "  [FAIL] $NW/campaign-workflow.bundled.js missing — run: node $NW/campaign-bundle.mjs"
	exit 1
fi

# 2. in sync with source modules
if node "$REPO_DIR/$NW/campaign-bundle.mjs" --check &>/dev/null; then
	echo "  [PASS] campaign bundle in sync with source modules"
else
	echo "  [FAIL] campaign bundle is stale — run: node $NW/campaign-bundle.mjs"
	fail=1
fi

# 3. valid JS
if node --check "$BUNDLE" 2>/dev/null; then
	echo "  [PASS] campaign bundle parses as valid JS"
else
	echo "  [FAIL] campaign bundle is not valid JS"
	fail=1
fi

# 4. self-contained: no import statements
if grep -qE '^import ' "$BUNDLE"; then
	echo "  [FAIL] campaign bundle contains import statements (a Workflow must be self-contained)"
	fail=1
else
	echo "  [PASS] no import statements"
fi

# 5. export const meta is the first statement (first non-comment, non-blank line).
first="$(awk 'NF && $0 !~ /^[[:space:]]*\/\// { print; exit }' "$BUNDLE")"
if [[ "$first" == "export const meta = {"* ]]; then
	echo "  [PASS] export const meta is the first statement"
else
	echo "  [FAIL] first statement is not 'export const meta' (got: ${first})"
	fail=1
fi

# 6. only meta is exported (helpers stripped to plain declarations)
nexports="$(grep -cE '^export ' "$BUNDLE" || true)"
if [[ "$nexports" == "1" ]]; then
	echo "  [PASS] exactly one export (meta)"
else
	echo "  [FAIL] expected exactly 1 export (meta), found ${nexports}"
	fail=1
fi

if [[ $fail -eq 0 ]]; then
	echo "  all campaign bundle-sync checks passed"
else
	exit 1
fi
