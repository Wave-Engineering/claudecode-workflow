#!/usr/bin/env bash
# test_precheck_asking_detector.sh — regression tests for the Stop hook
# that detects "shall I run /precheck?" style asking phrasings.
#
# Hook source: scripts/precheck-asking-detector.sh
# Issue: cc-workflow#542
#
# Strategy: build minimal CC-transcript JSONL fixtures in a tmpdir, pipe
# the hook input contract (stdin JSON with .transcript_path) through the
# hook, and assert on its stdout (block JSON) and exit code.
#
# Wired into CI via scripts/ci/validate.sh.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/precheck-asking-detector.sh"

if [[ ! -x "$HOOK" ]]; then
	echo "  [FAIL] hook missing or not executable: $HOOK"
	exit 1
fi

TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

PASSES=0
FAILS=0

pass() {
	echo "  [PASS] $*"
	PASSES=$((PASSES + 1))
}
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

# Build a minimal transcript JSONL with one assistant message containing
# the given text. Returns the path.
make_transcript() {
	local label="$1"
	local text="$2"
	local path="$TMPDIR/transcript-$label.jsonl"
	# Use jq to safely encode the text into a JSON string — handles quotes,
	# newlines, backslashes correctly.
	jq -nc --arg text "$text" '{
        type: "assistant",
        message: {
            role: "assistant",
            content: [
                { type: "text", text: $text }
            ]
        }
    }' >"$path"
	echo "$path"
}

run_hook() {
	local transcript_path="$1"
	jq -nc --arg p "$transcript_path" '{transcript_path: $p, session_id: "test"}' |
		"$HOOK"
}

# ---------------------------------------------------------------------------
# Positive cases — hook MUST emit block JSON
# ---------------------------------------------------------------------------

assert_blocks() {
	local label="$1"
	local text="$2"
	local path
	path=$(make_transcript "$label" "$text")
	local out
	out=$(run_hook "$path")
	if [[ "$out" == *'"decision":"block"'* ]]; then
		pass "blocks: $label"
	else
		fail "should-block: $label — got: ${out:-<empty>}"
	fi
}

assert_blocks "shall_i_run" "Shall I run /precheck?"
assert_blocks "should_i_run" "Should I run precheck now?"
assert_blocks "ready_for_precheck" "Ready for /precheck?"
assert_blocks "let_me_know_when" "Let me know when I should run precheck."
assert_blocks "do_you_want" "Do you want me to run /precheck?"
assert_blocks "may_i_run" "May I run /precheck?"

# ---------------------------------------------------------------------------
# Negative cases — hook MUST NOT block
# ---------------------------------------------------------------------------

assert_passes() {
	local label="$1"
	local text="$2"
	local path
	path=$(make_transcript "$label" "$text")
	local out
	out=$(run_hook "$path")
	if [[ -z "$out" || "$out" != *'"decision":"block"'* ]]; then
		pass "passes:  $label"
	else
		fail "should-pass: $label — got: $out"
	fi
}

assert_passes "past_tense_completed" "/precheck completed cleanly. Ready for your call."
assert_passes "no_question_mark" "I would run /precheck next."
assert_passes "different_command" "Shall I run /scp?"
assert_passes "checklist_text" "Validation green, trivy 0, reviewer clean. Ready for /scp / /scpmr / /scpmmr."

# Distance test: trigger word and "precheck" >40 chars apart.
assert_passes "distant_words" \
	"Should we, given everything that has happened in this very long sentence with lots of detail, also do a precheck?"

# ---------------------------------------------------------------------------
# Disable env var
# ---------------------------------------------------------------------------

label="disabled_via_env"
path=$(make_transcript "$label" "Shall I run /precheck?")
out=$(jq -nc --arg p "$path" '{transcript_path: $p, session_id: "test"}' |
	PRECHECK_ASKING_HOOK_DISABLED=1 "$HOOK")
if [[ -z "$out" ]]; then
	pass "env-disable: positive input but PRECHECK_ASKING_HOOK_DISABLED=1 — silent"
else
	fail "env-disable: should be silent, got: $out"
fi

# ---------------------------------------------------------------------------
# Missing transcript path
# ---------------------------------------------------------------------------

label="missing_transcript"
out=$(echo '{"transcript_path": "/nonexistent/path/xyz.jsonl"}' | "$HOOK")
if [[ -z "$out" ]]; then
	pass "missing-transcript: silent no-op"
else
	fail "missing-transcript: should be silent, got: $out"
fi

# ---------------------------------------------------------------------------
# Performance: hook must complete <500ms wall-clock on a realistic transcript
# size. (Budget-spec is <50ms; using 500ms here as a soft CI ceiling that
# tolerates VM variance.)
# ---------------------------------------------------------------------------

label="perf"
path=$(make_transcript "$label" "Shall I run /precheck?")
# Pad transcript with 200 noise events to simulate a real session.
for i in $(seq 1 200); do
	jq -nc --arg t "noise message $i with no asking phrasing in it." '{
        type: "assistant",
        message: { role: "assistant", content: [{type:"text", text:$t}] }
    }' >>"$path"
done
# The asking message is now early in the file; append it again at the end so
# it's the LAST assistant turn (matching real-world ordering).
jq -nc --arg t "Shall I run /precheck?" '{
    type:"assistant",
    message:{ role:"assistant", content:[{type:"text", text:$t}] }
}' >>"$path"

start_ms=$(($(date +%s%N) / 1000000))
out=$(run_hook "$path")
end_ms=$(($(date +%s%N) / 1000000))
elapsed=$((end_ms - start_ms))

if [[ "$out" == *'"decision":"block"'* ]] && ((elapsed < 500)); then
	pass "perf: 200-event transcript handled in ${elapsed}ms (budget <500ms CI / <50ms target)"
elif [[ "$out" != *'"decision":"block"'* ]]; then
	fail "perf: did not block on positive input — got: $out"
else
	fail "perf: ${elapsed}ms exceeds 500ms budget"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

echo ""
echo "  Results: $PASSES passed, $FAILS failed"

if ((FAILS > 0)); then
	exit 1
fi
exit 0
