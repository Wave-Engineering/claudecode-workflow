#!/usr/bin/env bash
# test_stop_action_bias_detector.sh — regression tests for the Stop hook that
# detects permission-ask / decision-handback phrasings ("want me to proceed?",
# "should I…?") and blocks the stop with a default-to-action reminder.
#
# Hook source: scripts/stop-action-bias-detector.sh
# Issue: cc-workflow#732 (general sibling of #542 precheck-asking-detector)
#
# Strategy: build minimal CC-transcript JSONL fixtures, pipe the hook input
# contract (stdin JSON with .transcript_path [, .stop_hook_active]) through
# the hook, assert on its stdout (block JSON) and exit code.
#
# Wired into CI via scripts/ci/validate.sh.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$REPO_DIR/scripts/stop-action-bias-detector.sh"

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

make_transcript() {
	local label="$1" text="$2"
	local path="$TMPDIR/transcript-$label.jsonl"
	jq -nc --arg text "$text" '{
        type: "assistant",
        message: { role: "assistant", content: [ { type: "text", text: $text } ] }
    }' >"$path"
	echo "$path"
}

run_hook() { # $1 transcript_path  [$2 stop_hook_active]
	jq -nc --arg p "$1" --argjson active "${2:-false}" \
		'{transcript_path: $p, session_id: "test", stop_hook_active: $active}' | "$HOOK"
}

assert_blocks() {
	local label="$1" text="$2" path out
	path=$(make_transcript "$label" "$text")
	out=$(run_hook "$path")
	if [[ "$out" == *'"decision":"block"'* ]]; then pass "blocks: $label"; else fail "should-block: $label — got: ${out:-<empty>}"; fi
}

assert_passes() {
	local label="$1" text="$2" path out
	path=$(make_transcript "$label" "$text")
	out=$(run_hook "$path")
	if [[ -z "$out" || "$out" != *'"decision":"block"'* ]]; then pass "passes:  $label"; else fail "should-pass: $label — got: $out"; fi
}

# --- Positive cases — permission-asks the hook MUST block --------------------
assert_blocks "want_me_to" "The deploy is ready. Want me to proceed?"
assert_blocks "should_i" "Both blockers are merged. Should I proceed?"
assert_blocks "shall_i" "Shall I go ahead and merge it?"
assert_blocks "do_you_want" "Do you want me to redeploy to the fleet?"
assert_blocks "ready_for_me" "Ready for me to start #722?"
assert_blocks "would_you_like" "Would you like me to take the next one?"
assert_blocks "say_the_word" "It's all staged — just say the word."
assert_blocks "let_me_know_defer" "Let me know whether you want me to continue."

# --- Negative cases — the hook MUST NOT block -------------------------------
# Information-seeking questions (asking about a FACT, not permission to act).
assert_passes "info_which_db" "Which database are you using for this service?"
assert_passes "info_budget" "What token budget should this campaign target?"
assert_passes "info_fork" "Two viable approaches here — per-wave or per-plan kahuna. Which do you want?"
# #732 review C1: architectural forks / clarifications phrased with "should I" are
# LEGITIMATE stops the rule protects — the verb-gating on PATTERN_PERMIT must let
# them pass (bare "should I <non-action-verb>" never fires).
assert_passes "should_i_fork" "Should I use Postgres or MySQL for this service?"
assert_passes "should_i_which_file" "Which file should I edit — the template or the generated copy?"
assert_passes "should_i_assume" "Should I assume us-east-1 as the region here?"
assert_passes "should_i_target" "Which schema should I target for the migration?"
# Statements / no question mark.
assert_passes "statement_proceeding" "Both blockers are merged; I'm proceeding with the redeploy now."
assert_passes "no_qmark" "I can start #722 next."
# A legitimate gate stated AS a gate (no permission phrasing) is allowed.
assert_passes "gate_stated" "This is a prod deploy you haven't agreed to in this conversation; I'm holding for your explicit go on prod specifically."
# Distance / unrelated.
assert_passes "distant" "I want this done right, so the details matter and I checked them all carefully."

# --- concluded-and-asked (cc-workflow#776) — conclusion + ratify-ask conjunction
# A team-converged conclusion AND a ratify-ask in the same turn is the over-pause.
assert_blocks "concluded_asked" "We've converged and the team is aligned — this is the right move. BJ, your call?"
assert_blocks "concluded_asked_schwifty" "Consensus reached on the approach. @schwifty7759, your go-ahead to ratify?"
# Conjunction is required: conclusion-only or ratify-only must NOT fire.
assert_passes "conclusion_only" "The team converged on the approach and we're fully aligned."
assert_passes "ratify_only" "BJ, your call on this one?"
# SAFETY: concluded + ratify-ask on a GATED axis (prod/deploy/release/secrets/migration)
# must NOT fire — the block pushes the agent to ACT, and pushing an unapproved prod
# action violates the ABSOLUTE prod rule. A false-negative here is the safe direction.
assert_passes "concluded_asked_prod" "We converged on the rollout approach — BJ, your call on the prod deploy?"
assert_passes "concluded_asked_release" "Team is aligned on the cut. @schwifty7759, approve the release?"
assert_passes "concluded_asked_secrets" "We agreed on the secret-rotation plan — BJ, your go-ahead?"
# Extended gated-axis (code-review #2): ship / go-live / force-push are prod-shaped.
assert_passes "concluded_asked_ship" "We converged — this is the right move. BJ, your go-ahead to ship it?"
assert_passes "concluded_asked_golive" "Team is aligned on the cut. @schwifty7759, your call to go live?"
assert_passes "concluded_asked_forcepush" "We agreed on the rebase plan. BJ, approve the force-push to main?"

# --- Loop guard: stop_hook_active=true → allow the stop even on positive input
label="loop_guard"
path=$(make_transcript "$label" "Want me to proceed?")
out=$(run_hook "$path" true)
if [[ -z "$out" ]]; then pass "loop-guard: stop_hook_active=true → silent (no double-block)"; else fail "loop-guard: should be silent, got: $out"; fi

# --- Kill-switch env --------------------------------------------------------
label="disabled_env"
path=$(make_transcript "$label" "Want me to proceed?")
out=$(jq -nc --arg p "$path" '{transcript_path: $p}' | STOP_ACTION_BIAS_HOOK_DISABLED=1 "$HOOK")
if [[ -z "$out" ]]; then pass "env-disable: positive input but STOP_ACTION_BIAS_HOOK_DISABLED=1 — silent"; else fail "env-disable: should be silent, got: $out"; fi

# --- Missing transcript -----------------------------------------------------
out=$(echo '{"transcript_path": "/nonexistent/xyz.jsonl"}' | "$HOOK")
if [[ -z "$out" ]]; then pass "missing-transcript: silent no-op"; else fail "missing-transcript: should be silent, got: $out"; fi

echo ""
echo "  Results: $PASSES passed, $FAILS failed"
((FAILS > 0)) && exit 1
exit 0
