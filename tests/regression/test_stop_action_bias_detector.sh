#!/usr/bin/env bash
# test_stop_action_bias_detector.sh — regression tests for the Godspeed
# decaying-mandate Stop hook (cc-workflow#818).
#
# Hook source: scripts/stop-action-bias-detector.sh
#
# Behavioral contract (#818, replaces #732/#776 fuzzy-regex model):
#
#   UNARMED / HALTED (no active godspeed mandate):
#     - ALL permission-ask phrasings ("Want me to?", "Should I?", etc.)  → NOOP
#       (hook stands down; no block).  This is the intentional replacement
#       for the old fuzzy-regex behavior that over-fired on legitimate gates.
#     - Gated-axis keywords (prod/deploy/force-push/irreversible/…) → STOP
#       (ABSOLUTE prod rule fires regardless of mandate state).
#
#   ARMED (godspeed typed in a recent user turn):
#     - d=0 (godspeed is the most-recent user turn), bar=0%  → GO (no block).
#     - Gated-axis keyword in last assistant turn              → STOP (block).
#
#   Loop guard: stop_hook_active=true → always silent (no re-block).
#   Kill-switch: STOP_ACTION_BIAS_HOOK_DISABLED=1 → always silent.
#   Missing transcript                             → always silent.
#
# Strategy: build minimal CC-transcript JSONL fixtures, pipe the hook input
# contract (stdin JSON with .transcript_path [, .stop_hook_active]) through
# the hook, assert on its stdout (block JSON) and exit code.
#
# Wired into CI via scripts/ci/validate.sh.

set -uo pipefail

# Mute the hook's real vox/Discord side effects — this test drives the real
# hook against gated-keyword fixtures, which otherwise fire a live "gated axis
# detected" announcement + Discord ping per case. Decision logic is unaffected.
export GODSPEED_NOTIFY_DISABLED=1

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/stop-action-bias-detector.sh"

if [[ ! -x "$HOOK" ]]; then
	echo "  [FAIL] hook missing or not executable: $HOOK"
	exit 1
fi

TMPDIR_LOCAL=$(mktemp -d)
trap 'rm -rf "$TMPDIR_LOCAL"' EXIT

PASSES=0
FAILS=0
pass() { echo "  [PASS] $*"; PASSES=$((PASSES + 1)); }
fail() { echo "  [FAIL] $*"; FAILS=$((FAILS + 1)); }

# ─── transcript builders ────────────────────────────────────────────────────

# Transcript with a single assistant turn (UNARMED state).
make_unarmed_transcript() {
	local label="$1" text="$2"
	local path="$TMPDIR_LOCAL/t-unarmed-$label.jsonl"
	jq -nc --arg t "$text" '{
        type: "assistant",
        message: {role: "assistant", content: [{type: "text", text: $t}]}
    }' >"$path"
	echo "$path"
}

# Transcript with a user "godspeed" turn followed by an assistant turn
# (ARMED d=0 state).
make_armed_transcript() {
	local label="$1" text="$2"
	local path="$TMPDIR_LOCAL/t-armed-$label.jsonl"
	jq -nc '{type: "user", message: {role: "user", content: [{type: "text", text: "godspeed"}]}}' >"$path"
	jq -nc --arg t "$text" '{
        type: "assistant",
        message: {role: "assistant", content: [{type: "text", text: $t}]}
    }' >>"$path"
	echo "$path"
}

run_hook() { # $1 transcript_path  [$2 stop_hook_active=false]
	jq -nc --arg p "$1" --argjson active "${2:-false}" \
		'{transcript_path: $p, session_id: "test", stop_hook_active: $active}' | "$HOOK"
}

assert_blocks() {
	local label="$1" text="$2" path out
	path=$(make_unarmed_transcript "$label" "$text")
	out=$(run_hook "$path")
	if [[ "$out" == *'"decision":"block"'* ]]; then
		pass "blocks: $label"
	else
		fail "should-block: $label — got: ${out:-<empty>}"
	fi
}

assert_passes() {
	local label="$1" text="$2" path out
	path=$(make_unarmed_transcript "$label" "$text")
	out=$(run_hook "$path")
	if [[ -z "$out" || "$out" != *'"decision":"block"'* ]]; then
		pass "passes: $label"
	else
		fail "should-pass: $label — got: $out"
	fi
}

assert_armed_blocks() {
	local label="$1" text="$2" path out
	path=$(make_armed_transcript "$label" "$text")
	out=$(run_hook "$path")
	if [[ "$out" == *'"decision":"block"'* ]]; then
		pass "blocks-armed: $label"
	else
		fail "should-block-armed: $label — got: ${out:-<empty>}"
	fi
}

assert_armed_passes() {
	local label="$1" text="$2" path out
	path=$(make_armed_transcript "$label" "$text")
	out=$(run_hook "$path")
	if [[ -z "$out" || "$out" != *'"decision":"block"'* ]]; then
		pass "passes-armed: $label"
	else
		fail "should-pass-armed: $label — got: $out"
	fi
}

# ─── UNARMED: hook stands down on all non-gated phrasings ───────────────────
# All of the following used to block under the old fuzzy-regex model (#732).
# #818 intentionally removes this enforcement in UNARMED state to eliminate
# false positives.  The precheck-asking-detector.sh retains narrow enforcement
# for the specific "shall I run /precheck?" pattern.

assert_passes "unarmed_permission_ask"    "The work is complete. Want me to proceed?"
assert_passes "unarmed_should_i"          "Both blockers are merged. Should I proceed?"
assert_passes "unarmed_shall_i"           "Shall I go ahead and merge it?"
assert_passes "unarmed_do_you_want"       "Do you want me to redeploy to the fleet?"
assert_passes "unarmed_concluded_asked"   "We've converged and the team is aligned — BJ, your call?"
assert_passes "unarmed_info_question"     "Which database are you using for this service?"
assert_passes "unarmed_statement"         "Both blockers are merged; I'm proceeding with the redeploy now."

# ─── UNARMED: gated-axis keywords → STOP (ABSOLUTE prod rule) ───────────────
# These must block regardless of mandate state.

assert_blocks "unarmed_gated_production"  "I'm about to push this to production."
assert_blocks "unarmed_gated_deploy"      "Ready to deploy this to the cluster."
assert_blocks "unarmed_gated_force_push"  "I'll need to force-push to main to fix this."
assert_blocks "unarmed_gated_irreversible" "This is an irreversible operation; proceeding."
assert_blocks "unarmed_gated_credential"  "I'll rotate the credentials now."
assert_blocks "unarmed_gated_destroy"     "Running terraform destroy on the staging env."
assert_blocks "unarmed_gated_migrate"     "Starting the database migration now."

# ─── ARMED (d=0): non-gated text → GO (mandate fresh, bar=0%) ───────────────

assert_armed_passes "armed_fresh_normal"         "I'll run the tests now."
assert_armed_passes "armed_fresh_permission_ask" "Want me to proceed with the next step?"
assert_armed_passes "armed_fresh_info"           "Looking at the config file."

# ─── ARMED (d=0): gated-axis text → STOP ────────────────────────────────────

assert_armed_blocks "armed_gated_production"  "I'm going to push this to production."
assert_armed_blocks "armed_gated_deploy"      "Deploying the new image to the cluster."
assert_armed_blocks "armed_gated_force_push"  "I need to force-push to main here."

# ─── Loop guard: stop_hook_active=true → always silent ───────────────────────
label="loop_guard_gated"
path=$(make_unarmed_transcript "$label" "I'm about to push to production.")
out=$(run_hook "$path" true)
if [[ -z "$out" ]]; then
	pass "loop-guard: stop_hook_active=true on gated text → silent"
else
	fail "loop-guard: should be silent even on gated text, got: $out"
fi

label="loop_guard_permission_ask"
path=$(make_unarmed_transcript "$label" "Want me to proceed?")
out=$(run_hook "$path" true)
if [[ -z "$out" ]]; then
	pass "loop-guard: stop_hook_active=true on permission-ask → silent"
else
	fail "loop-guard: should be silent, got: $out"
fi

# ─── Kill-switch env ─────────────────────────────────────────────────────────
label="disabled_env_gated"
path=$(make_unarmed_transcript "$label" "I'm about to push to production.")
out=$(jq -nc --arg p "$path" '{transcript_path: $p}' | STOP_ACTION_BIAS_HOOK_DISABLED=1 "$HOOK")
if [[ -z "$out" ]]; then
	pass "env-disable: gated text but STOP_ACTION_BIAS_HOOK_DISABLED=1 → silent"
else
	fail "env-disable: should be silent, got: $out"
fi

# ─── Missing transcript ───────────────────────────────────────────────────────
out=$(echo '{"transcript_path": "/nonexistent/xyz.jsonl"}' | "$HOOK")
if [[ -z "$out" ]]; then
	pass "missing-transcript: silent no-op"
else
	fail "missing-transcript: should be silent, got: $out"
fi

echo ""
echo "  Results: $PASSES passed, $FAILS failed"
((FAILS > 0)) && exit 1
exit 0
