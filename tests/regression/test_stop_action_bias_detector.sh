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
pass() {
	echo "  [PASS] $*"
	PASSES=$((PASSES + 1))
}
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

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

# Transcript whose last assistant turn carries tool_use blocks (#917). The gate
# keys on these, not on the narration text that accompanies them.
make_tool_transcript() {
	local label="$1" tools="$2"
	local path="$TMPDIR_LOCAL/t-tool-$label.jsonl"
	jq -nc --argjson tools "$tools" '{
        type: "assistant",
        message: {role: "assistant", content: (
            [{type: "text", text: "Working."}] + ($tools | map({type: "tool_use", name: .name, input: .input}))
        )}
    }' >"$path"
	echo "$path"
}

# Multi-MESSAGE turn: a Claude Code turn is many assistant messages (one per
# tool round-trip). `$tool_groups` is a list of tool arrays, one per message.
# This is the fixture shape that catches turn-vs-message scoping bugs (#917).
make_multi_msg_transcript() {
	local label="$1" tool_groups="$2"
	local path="$TMPDIR_LOCAL/t-multi-$label.jsonl"
	jq -nc '{type: "user", message: {role: "user", content: [{type: "text", text: "go"}]}}' >"$path"
	jq -nc --argjson groups "$tool_groups" '
		$groups[] | {
			type: "assistant",
			message: {role: "assistant", content: (
				[{type: "text", text: "Working."}] + (. | map({type: "tool_use", name: .name, input: .input}))
			)}
		}' >>"$path"
	echo "$path"
}

# Turn whose only assistant message carries tool_use and NO text block.
make_textless_tool_transcript() {
	local label="$1" tools="$2"
	local path="$TMPDIR_LOCAL/t-textless-$label.jsonl"
	jq -nc '{type: "user", message: {role: "user", content: [{type: "text", text: "go"}]}}' >"$path"
	jq -nc --argjson tools "$tools" '{
        type: "assistant",
        message: {role: "assistant", content: ($tools | map({type: "tool_use", name: .name, input: .input}))}
    }' >>"$path"
	echo "$path"
}

# Same, but preceded by a `godspeed` user turn (ARMED d=0).
make_tool_armed_transcript() {
	local label="$1" tools="$2"
	local path="$TMPDIR_LOCAL/t-tool-armed-$label.jsonl"
	jq -nc '{type: "user", message: {role: "user", content: [{type: "text", text: "godspeed"}]}}' >"$path"
	jq -nc --argjson tools "$tools" '{
        type: "assistant",
        message: {role: "assistant", content: (
            [{type: "text", text: "Working."}] + ($tools | map({type: "tool_use", name: .name, input: .input}))
        )}
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

# ─── tool_use-based assertions (#917) ───────────────────────────────────────

assert_tool_blocks() {
	local label="$1" tools="$2" path out
	path=$(make_tool_transcript "$label" "$tools")
	out=$(run_hook "$path")
	if [[ "$out" == *'"decision":"block"'* ]]; then
		pass "blocks-action: $label"
	else
		fail "should-block-action: $label — got: ${out:-<empty>}"
	fi
}

assert_tool_passes() {
	local label="$1" tools="$2" path out
	path=$(make_tool_transcript "$label" "$tools")
	out=$(run_hook "$path")
	if [[ -z "$out" || "$out" != *'"decision":"block"'* ]]; then
		pass "passes-action: $label"
	else
		fail "should-pass-action: $label — got: $out"
	fi
}

assert_tool_armed_blocks() {
	local label="$1" tools="$2" path out
	path=$(make_tool_armed_transcript "$label" "$tools")
	out=$(run_hook "$path")
	if [[ "$out" == *'"decision":"block"'* ]]; then
		pass "blocks-action-armed: $label"
	else
		fail "should-block-action-armed: $label — got: ${out:-<empty>}"
	fi
}

# ─── UNARMED: hook stands down on all non-gated phrasings ───────────────────
# All of the following used to block under the old fuzzy-regex model (#732).
# #818 intentionally removes this enforcement in UNARMED state to eliminate
# false positives.  The precheck-asking-detector.sh retains narrow enforcement
# for the specific "shall I run /precheck?" pattern.

assert_passes "unarmed_permission_ask" "The work is complete. Want me to proceed?"
assert_passes "unarmed_should_i" "Both blockers are merged. Should I proceed?"
assert_passes "unarmed_shall_i" "Shall I go ahead and merge it?"
assert_passes "unarmed_do_you_want" "Do you want me to redeploy to the fleet?"
assert_passes "unarmed_concluded_asked" "We've converged and the team is aligned — BJ, your call?"
assert_passes "unarmed_info_question" "Which database are you using for this service?"
assert_passes "unarmed_statement" "Both blockers are merged; I'm proceeding with the redeploy now."

# ─── UNARMED: gated WORDS in prose → NO STOP (#917) ─────────────────────────
# The gate keys on tool_use, never on turn text. These all used to block, which
# is the bug #917 fixes: a turn that merely TALKS about prod is not a turn that
# TOUCHES prod. The last case is the self-referential one — documenting this
# hook's own keyword list used to trip this hook.

assert_passes "unarmed_prose_production" "I'm about to push this to production."
assert_passes "unarmed_prose_deploy" "Ready to deploy this to the cluster."
assert_passes "unarmed_prose_force_push" "I'll need to force-push to main to fix this."
assert_passes "unarmed_prose_irreversible" "This is an irreversible operation; proceeding."
assert_passes "unarmed_prose_credential" "I'll rotate the credentials now."
assert_passes "unarmed_prose_deployed_adj" "Verified against the live deployed tool schema."
assert_passes "unarmed_prose_self_ref" "Gated-axis language (prod/deploy/force-push/rotate/credentials/secrets) always STOPs."

# ─── ARMED (d=0): non-gated text → GO (mandate fresh, bar=0%) ───────────────

assert_armed_passes "armed_fresh_normal" "I'll run the tests now."
assert_armed_passes "armed_fresh_permission_ask" "Want me to proceed with the next step?"
assert_armed_passes "armed_fresh_info" "Looking at the config file."

# ─── ARMED (d=0): gated words in prose → still NO STOP (#917) ───────────────

assert_armed_passes "armed_prose_production" "I'm going to push this to production."
assert_armed_passes "armed_prose_deploy" "Deploying the new image to the cluster."
assert_armed_passes "armed_prose_force_push" "I need to force-push to main here."

# ─── Gated ACTIONS in tool_use → STOP, regardless of mandate (#917) ─────────

assert_tool_blocks "tool_force_push" \
	'[{"name":"Bash","input":{"command":"git push --force origin main"}}]'
assert_tool_blocks "tool_push_main" \
	'[{"name":"Bash","input":{"command":"git push origin main"}}]'
assert_tool_blocks "tool_terraform_apply" \
	'[{"name":"Bash","input":{"command":"terraform apply -auto-approve"}}]'
assert_tool_blocks "tool_chained_after_safe" \
	'[{"name":"Bash","input":{"command":"cd /tmp && terraform destroy"}}]'
assert_tool_blocks "tool_env_prefixed" \
	'[{"name":"Bash","input":{"command":"TF_VAR_x=1 terraform apply"}}]'
assert_tool_blocks "tool_after_pipe" \
	'[{"name":"Bash","input":{"command":"cat f | kubectl apply -f -"}}]'
assert_tool_blocks "tool_prod_desired_state_write" \
	'[{"name":"Write","input":{"file_path":"sites/aws-prod/site.yaml"}}]'
assert_tool_armed_blocks "tool_force_push_armed" \
	'[{"name":"Bash","input":{"command":"git push --force origin main"}}]'

# ─── Keywords as DATA in a tool input → NO STOP (#917) ──────────────────────
# A naive scan of tool_use.input would reproduce the text bug one layer down.
# Only the HEAD of a shell segment counts as an invoked command.

assert_tool_passes "tool_keywords_in_grep" \
	'[{"name":"Bash","input":{"command":"grep -P \"prod|deploy|rotate\" file"}}]'
assert_tool_passes "tool_keywords_in_echo" \
	'[{"name":"Bash","input":{"command":"echo \"git push --force is risky\""}}]'
assert_tool_passes "tool_read_prod_logs" \
	'[{"name":"Bash","input":{"command":"kubectl logs -n production my-pod"}}]'
assert_tool_passes "tool_push_feature_branch" \
	'[{"name":"Bash","input":{"command":"git push -u origin fix/917-foo"}}]'
assert_tool_passes "tool_doc_write_about_hook" \
	'[{"name":"Write","input":{"file_path":"docs/godspeed.md"}}]'

# ─── Turn scoping: a gated action ANYWHERE in the turn must fire (#917) ─────
# A Claude Code turn is many assistant messages. Scoping to one message and
# taking `last` failed OPEN on the normal pattern — agents almost always run a
# verification command after acting, which masked the gated one.

label="multi_msg_gated_then_verify"
path=$(make_multi_msg_transcript "$label" \
	'[[{"name":"Bash","input":{"command":"git push --force origin main"}}],[{"name":"Bash","input":{"command":"git log --oneline -3"}}]]')
out=$(run_hook "$path")
if [[ "$out" == *'"decision":"block"'* ]]; then
	pass "turn-scope: gated action in an EARLIER message still blocks"
else
	fail "turn-scope: FAIL OPEN — gated action masked by later benign tool call"
fi

label="multi_msg_benign_only"
path=$(make_multi_msg_transcript "$label" \
	'[[{"name":"Bash","input":{"command":"git status"}}],[{"name":"Bash","input":{"command":"git log --oneline -3"}}]]')
out=$(run_hook "$path")
if [[ -z "$out" ]]; then
	pass "turn-scope: all-benign multi-message turn stays silent"
else
	fail "turn-scope: benign turn should not block, got: $out"
fi

# ─── Text must not be a precondition for the ACTION gate (#917) ─────────────
label="textless_tool_only"
path=$(make_textless_tool_transcript "$label" \
	'[{"name":"Bash","input":{"command":"terraform apply -auto-approve"}}]')
out=$(run_hook "$path")
if [[ "$out" == *'"decision":"block"'* ]]; then
	pass "tool_use-only message (no text block) still reaches the gate"
else
	fail "FAIL OPEN — text-less turn short-circuited before the action gate"
fi

# ─── Prefix wrappers must not defeat segment-head anchoring (#917) ──────────
assert_tool_blocks "tool_sudo_systemctl" \
	'[{"name":"Bash","input":{"command":"sudo systemctl restart nginx"}}]'
assert_tool_blocks "tool_git_dash_C_force" \
	'[{"name":"Bash","input":{"command":"git -C /tmp/wt push --force origin main"}}]'
assert_tool_blocks "tool_timeout_terraform" \
	'[{"name":"Bash","input":{"command":"timeout 300 terraform apply"}}]'
assert_tool_blocks "tool_sh_c_terraform" \
	'[{"name":"Bash","input":{"command":"sh -c \"terraform apply\""}}]'
assert_tool_blocks "tool_subshell_force_push" \
	'[{"name":"Bash","input":{"command":"(git push --force origin main)"}}]'
assert_tool_blocks "tool_xargs_kubectl_delete" \
	'[{"name":"Bash","input":{"command":"xargs kubectl delete pod"}}]'
assert_tool_passes "tool_git_dash_C_feature_push" \
	'[{"name":"Bash","input":{"command":"git -C /tmp/wt push -u origin feature/x"}}]'

# ─── The STOP reason must grant agency, not command a halt (#917) ───────────
label="reason_grants_agency"
path=$(make_tool_transcript "$label" '[{"name":"Bash","input":{"command":"terraform apply"}}]')
out=$(run_hook "$path")
reason=$(printf '%s' "$out" | jq -r '.reason // ""' 2>/dev/null)
if [[ "$reason" == *"retain the right to proceed"* && "$reason" == *"state that assessment"* ]]; then
	pass "reason grants the agent an explicit continue path"
else
	fail "reason must grant agency, got: ${reason:0:120}"
fi
if [[ "$reason" != *"surface it to BJ before proceeding"* ]]; then
	pass "reason no longer commands an unconditional halt"
else
	fail "reason still commands an unconditional halt"
fi

# ─── Loop guard: stop_hook_active=true → always silent ───────────────────────
label="loop_guard_gated"
path=$(make_tool_transcript "$label" '[{"name":"Bash","input":{"command":"git push --force origin main"}}]')
out=$(run_hook "$path" true)
if [[ -z "$out" ]]; then
	pass "loop-guard: stop_hook_active=true on gated text → silent"
else
	fail "loop-guard: should be silent even on gated text, got: $out"
fi

# Positive control for the loop guard: the same fixture MUST block when
# stop_hook_active=false, otherwise the guard assertion above is vacuous.
label="loop_guard_positive_control"
path=$(make_tool_transcript "$label" \
	'[{"name":"Bash","input":{"command":"terraform apply"}}]')
out=$(run_hook "$path" false)
if [[ "$out" == *'"decision":"block"'* ]]; then
	pass "loop-guard positive control: blocks when stop_hook_active=false"
else
	fail "loop-guard positive control: should block, got: ${out:-<empty>}"
fi
out=$(run_hook "$path" true)
if [[ -z "$out" ]]; then
	pass "loop-guard: stop_hook_active=true on same fixture → silent"
else
	fail "loop-guard: should be silent, got: $out"
fi

# ─── Kill-switch env ─────────────────────────────────────────────────────────
# Must use a fixture that ACTUALLY blocks, plus a positive control. With the
# old gated-TEXT fixture this pair was vacuous under #917 — the text no longer
# blocks anyway, so deleting the kill-switch entirely would have left it green.
label="disabled_env_gated"
path=$(make_tool_transcript "$label" \
	'[{"name":"Bash","input":{"command":"git push --force origin main"}}]')

out=$(jq -nc --arg p "$path" '{transcript_path: $p}' | "$HOOK")
if [[ "$out" == *'"decision":"block"'* ]]; then
	pass "env-disable positive control: gated action blocks when switch is unset"
else
	fail "env-disable positive control: fixture must block, got: ${out:-<empty>}"
fi

out=$(jq -nc --arg p "$path" '{transcript_path: $p}' | STOP_ACTION_BIAS_HOOK_DISABLED=1 "$HOOK")
if [[ -z "$out" ]]; then
	pass "env-disable: gated ACTION but STOP_ACTION_BIAS_HOOK_DISABLED=1 → silent"
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
