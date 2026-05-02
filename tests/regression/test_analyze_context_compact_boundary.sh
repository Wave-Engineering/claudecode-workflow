#!/usr/bin/env bash
# test_analyze_context_compact_boundary.sh — regression test for issue #567.
#
# After a `/compact`, Claude Code writes a `{"type":"system",
# "subtype":"compact_boundary", ...}` entry to the transcript. Entries before
# the boundary describe context that is no longer live; the analyzer must
# ignore them when computing current token usage.
#
# Three scenarios covered:
#   1. Compact boundary present + a post-boundary claude-* assistant turn:
#      the analyzer uses the post-boundary turn's usage, NOT the last
#      pre-boundary turn's usage.
#   2. Compact boundary present + NO post-boundary turn yet:
#      the analyzer falls back to `compactMetadata.postTokens` from the
#      boundary entry.
#   3. No compact boundary:
#      behaviour is unchanged — last claude-* usage in the file wins.
#
# No jq/python/node deps — bash + the analyzer library only.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
ANALYZER="$REPO_DIR/context-crystallizer/lib/context-analyzer.sh"

FAILS=0
TMPDIR_TEST=$(mktemp -d)
trap 'rm -rf "$TMPDIR_TEST"' EXIT

fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_analyze_context_compact_boundary (#567)"
echo "──────────────────────────────────────────"

if [[ ! -f "$ANALYZER" ]]; then
	fail "analyzer not found at $ANALYZER"
	exit 1
fi

# shellcheck source=/dev/null
source "$ANALYZER"

# A synthetic assistant-turn line with a specific cache_read value.
# The analyzer sums input + cache_create + cache_read → TOTAL, so cache_read
# dominates for these fixtures.
make_usage_line() {
	local cache_read="$1"
	printf '{"type":"assistant","message":{"model":"claude-opus-4-7","usage":{"input_tokens":1,"cache_creation_input_tokens":0,"cache_read_input_tokens":%s,"output_tokens":10}}}\n' "$cache_read"
}

make_boundary_line() {
	local post_tokens="$1"
	printf '{"type":"system","subtype":"compact_boundary","compactMetadata":{"trigger":"manual","preTokens":250000,"postTokens":%s,"durationMs":1000}}\n' "$post_tokens"
}

# --- Scenario 1: boundary + post-boundary turn -------------------------------
# Pre-boundary turn at 219k cache_read (the "stale" value); post-boundary turn
# at 115k. Analyzer MUST return ~115k, not ~219k.
T1="$TMPDIR_TEST/boundary_with_post_turn.jsonl"
{
	make_usage_line 219000
	make_boundary_line 21000
	make_usage_line 115000
} >"$T1"

RESULT=$(analyze_context "$T1" 200000 2>/dev/null | grep -o '"total": *[0-9]*' | head -n1 | tr -d ' ' | cut -d: -f2)
if [[ "$RESULT" -ge 110000 && "$RESULT" -le 120000 ]]; then
	pass "boundary + post-turn → TOTAL=$RESULT (expected ~115k)"
else
	fail "boundary + post-turn → TOTAL=$RESULT (expected ~115k; pre-boundary leak would be ~219k)"
fi

# --- Scenario 2: boundary + no post-boundary turn ----------------------------
# Pre-boundary turn at 219k, boundary's postTokens=21946, no turn after.
# Analyzer MUST fall back to postTokens (21946), not use the pre-boundary value.
T2="$TMPDIR_TEST/boundary_no_post_turn.jsonl"
{
	make_usage_line 219000
	make_boundary_line 21946
} >"$T2"

RESULT=$(analyze_context "$T2" 200000 2>/dev/null | grep -o '"total": *[0-9]*' | head -n1 | tr -d ' ' | cut -d: -f2)
if [[ "$RESULT" == "21946" ]]; then
	pass "boundary + no post-turn → TOTAL=$RESULT (expected 21946 from postTokens)"
else
	fail "boundary + no post-turn → TOTAL=$RESULT (expected 21946 from postTokens)"
fi

# --- Scenario 3: no boundary ------------------------------------------------
# No boundary entry — analyzer uses last claude-* usage in the file.
T3="$TMPDIR_TEST/no_boundary.jsonl"
{
	make_usage_line 50000
	make_usage_line 95000
} >"$T3"

RESULT=$(analyze_context "$T3" 200000 2>/dev/null | grep -o '"total": *[0-9]*' | head -n1 | tr -d ' ' | cut -d: -f2)
if [[ "$RESULT" -ge 90000 && "$RESULT" -le 100000 ]]; then
	pass "no boundary → TOTAL=$RESULT (expected ~95k, last turn in file)"
else
	fail "no boundary → TOTAL=$RESULT (expected ~95k)"
fi

# --- Scenario 4: boundary + no post-turn + missing postTokens ----------------
# Defensive: if postTokens is missing or 0, analyzer returns no-usage error
# rather than silently under-reporting.
T4="$TMPDIR_TEST/boundary_missing_posttokens.jsonl"
{
	make_usage_line 150000
	printf '{"type":"system","subtype":"compact_boundary","compactMetadata":{"trigger":"manual","preTokens":150000,"durationMs":1000}}\n'
} >"$T4"

OUT=$(analyze_context "$T4" 200000 2>/dev/null)
if echo "$OUT" | grep -q '"error": *"no usage data"'; then
	pass "boundary + no post-turn + missing postTokens → returns no-usage error"
else
	fail "boundary + no post-turn + missing postTokens → unexpected: $OUT"
fi

echo ""
if [[ "$FAILS" -gt 0 ]]; then
	echo "  $FAILS failure(s)"
	exit 1
fi
echo "  all scenarios passed"
exit 0
