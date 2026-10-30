#!/usr/bin/env bash
# test_wf_syntax_check.sh — #1350: the Workflow syntax checker passes good scripts and fails bad ones.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Every Workflow syntax check in tests/regression/ runs through scripts/ci/wf-syntax-check.mjs, so a
# checker that passes everything would silently disarm all of them. This pins both directions:
#   1. a Workflow-shaped fixture (imports, `export const meta`, top-level await + return) PASSES —
#      the shape `node --check` rejects on Node 24 with "Illegal return statement";
#   2. the same fixture with an unbalanced brace FAILS, and the error names the file;
#   3. every committed Workflow script (sources + bundles) PASSES.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
CHECK="$REPO_DIR/scripts/ci/wf-syntax-check.mjs"
fail=0

echo "test_wf_syntax_check"
echo "──────────────────────────────────────────"

if ! command -v node &>/dev/null; then
	echo "  [FAIL] node not found — required for the #1350 syntax-checker test"
	exit 1
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cat >"$TMP/good.js" <<'EOF'
export const meta = { name: 'fixture', description: 'a Workflow-shaped fixture' }
import { helper } from './helper.js'
import {
  other,
} from './other.js'
export function local() { return 1 }
const r = await agent('x')
if (!r) return { ok: false }
return { ok: true, n: local() }
EOF

# Drop the closing brace of the `if` body: a real syntax error.
sed 's/^if (!r) return { ok: false }$/if (!r) { return { ok: false }/' "$TMP/good.js" >"$TMP/bad.js"

# 1. the Workflow shape passes
if node "$CHECK" "$TMP/good.js" 2>/dev/null; then
	echo "  [PASS] a Workflow-shaped script (export meta, imports, top-level await + return) passes"
else
	echo "  [FAIL] a Workflow-shaped script was rejected"
	fail=1
fi

# 2. a real syntax error fails, naming the file
if out="$(node "$CHECK" "$TMP/bad.js" 2>&1)"; then
	echo "  [FAIL] a script with an unbalanced brace passed"
	fail=1
elif grep -qF "$TMP/bad.js" <<<"$out"; then
	echo "  [PASS] a script with an unbalanced brace fails, naming the file"
else
	echo "  [FAIL] the syntax error did not name the file: $out"
	fail=1
fi

# 3. every committed Workflow script passes
for f in skills/nextwave/per-wave-workflow.js skills/nextwave/per-wave-workflow.bundled.js \
	skills/nextwave/campaign-workflow.js skills/nextwave/campaign-workflow.bundled.js \
	skills/lazyriver/lazyriver-workflow.js skills/lazyriver/lazyriver-workflow.bundled.js; do
	if node "$CHECK" "$REPO_DIR/$f" 2>/dev/null; then
		echo "  [PASS] $(basename "$f") syntax (wf-syntax-check)"
	else
		echo "  [FAIL] $(basename "$f") syntax (wf-syntax-check)"
		fail=1
	fi
done

exit "$fail"
