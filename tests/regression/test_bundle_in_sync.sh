#!/usr/bin/env bash
# test_bundle_in_sync.sh — #699/#2: single-file Workflow bundle integrity + no-drift guard.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# A Dynamic Workflow MUST be ONE self-contained file with `export const meta` first (live-gate
# finding #2). The engine's tested halves live in separate modules; bundle.mjs inlines them into
# per-wave-workflow.bundled.js. This test pins that the committed bundle:
#   1. exists and is in sync with its source modules (bundle.mjs --check),
#   2. parses as valid JS,
#   3. contains NO import statements (self-contained),
#   4. has `export const meta` as its first statement,
#   5. exports ONLY meta (helper exports stripped).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
NW="skills/nextwave-next"
BUNDLE="$REPO_DIR/$NW/per-wave-workflow.bundled.js"
fail=0

echo "test_bundle_in_sync"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the bundle test"
	exit 1
fi

# 1. bundle exists
if [[ ! -f "$BUNDLE" ]]; then
	echo "  [FAIL] $NW/per-wave-workflow.bundled.js missing — run: node $NW/bundle.mjs"
	exit 1
fi

# 2. in sync with source modules
if node "$REPO_DIR/$NW/bundle.mjs" --check &>/dev/null; then
	echo "  [PASS] bundle in sync with source modules"
else
	echo "  [FAIL] bundle is stale — run: node $NW/bundle.mjs"
	fail=1
fi

# 3. valid JS
if node --check "$BUNDLE" 2>/dev/null; then
	echo "  [PASS] bundle parses as valid JS"
else
	echo "  [FAIL] bundle is not valid JS"
	fail=1
fi

# 4. self-contained: no import statements
if grep -qE '^import ' "$BUNDLE"; then
	echo "  [FAIL] bundle contains import statements (a Workflow must be self-contained)"
	fail=1
else
	echo "  [PASS] no import statements"
fi

# 5. export const meta is the first statement (first non-comment, non-blank line).
# awk (single process, exits on first match) avoids the grep|head SIGPIPE under `set -o pipefail`.
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
	echo "  all bundle-sync checks passed"
else
	exit 1
fi
