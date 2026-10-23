#!/usr/bin/env bash
# test_push_gate_working_branches.sh — #1232: a PLAIN push to an agent's own working
# branch goes through with no test sentinel; /precheck gates the MR, not the push.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Drives the REAL hook. The contract (BJ, 2026-10-18: "love the simplification"):
#   - EXEMPT only a plain single-line `git push` with allowlisted flags, a plain remote
#     and plain refspecs (plus an optional trailing redirection or `| tail`/`| head`),
#     whose every destination is a working or integration branch. No shell parsing.
#   - GATED (needs the test sentinel, as before #1232) is every other `git … push`,
#     detected anywhere in the command — including compound pushes to working branches.
#   - NOT A PUSH (passes untouched) is everything else.
# The rows include every bypass shape three review passes found against the earlier
# shell-parsing design; under this design they gate because they are not plain.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
GATE="$REPO_DIR/scripts/hooks/workflow/pre-push-test-gate.sh"
SID="test-1232-pushgate-$$"
SENTINEL="/tmp/claude-tests-ran-${SID}"
fail=0

echo "test_push_gate_working_branches"
echo "──────────────────────────────────────────"

cleanup() { rm -f "$SENTINEL"; }
trap cleanup EXIT
cleanup # no sentinel: every PASS below is the exemption (or not a push), not a test run

# check <PASS|BLOCK> <command> [extra-branch-regex]
check() {
	local want="$1" cmd="$2" extra="${3:-}" out got
	out=$(jq -n --arg s "$SID" --arg c "$cmd" '{session_id: $s, tool_input: {command: $c}}' |
		env -u WAVE_FLIGHT_ID PUSH_GATE_EXTRA_BRANCH_RE="$extra" bash "$GATE")
	if printf '%s' "$out" | grep -q '"decision":"block"'; then got=BLOCK; else got=PASS; fi
	if [[ "$got" == "$want" ]]; then
		printf '  ok    %-5s %s%s\n' "$got" "$cmd" "${extra:+  [extra=$extra]}"
	else
		printf '  WRONG %-5s (want %s) %s%s\n' "$got" "$want" "$cmd" "${extra:+  [extra=$extra]}"
		fail=1
	fi
}

DEVOPS='^DEVOPS-[0-9]+-.+'

# --- EXEMPT: plain pushes to working / integration branches ---
check PASS "git push -u origin feature/58-x"
check PASS "git push origin doc/30-precheck-gates-mr"
check PASS "git push origin fix/3-a chore/4-b"
check PASS "git push lanebox HEAD:fix/12-y"
check PASS "git push origin HEAD:refs/heads/feature/7-z"
check PASS "git push origin :chore/9-old"
check PASS "git push origin +feature/x"
check PASS "git push --force-with-lease origin doc/9-y"
check PASS "git push --force-with-lease=doc/9-y:abc123 origin doc/9-y"
check PASS "git push -o ci.skip -u origin feature/58-x"
check PASS "git push --push-option=ci.skip origin fix/3-a"
check PASS "git push origin kahuna/4-campaign"
check PASS "git push origin wave-9101/issue-8"
check PASS "git push -q -u origin doc/30-precheck-gates-mr 2>&1 | tail -3"
check PASS "git push origin feature/x 2>&1 | tail -n 5"
check PASS "git push -u origin fix/3-a > /dev/null"
check PASS "git push origin feature/x &>/dev/null"
check PASS "git push origin DEVOPS-2069-record-image-digests" "$DEVOPS"
check PASS "git push -o ci.skip -u origin DEVOPS-2069-record-image-digests" "$DEVOPS"
# #1287: an agent in a second repo pushes with -C (its cwd resets after each Bash call).
check PASS "git -C /tmp/x push origin chore/x"
check PASS "git -C ../repo push -u origin fix/3-a"
check PASS "git -C ~/sandbox/github/other-repo push -q -u origin feature/9-y 2>&1 | tail -3"
check BLOCK "git -C /tmp/x push origin release/0.2"
check BLOCK "git -C /tmp/x push origin main"
check BLOCK "git -C \$P push origin fix/x"
check BLOCK "git -C /a -C /b push origin fix/x"
check BLOCK "git -C /tmp/x push"
check PASS "git -C /tmp/x commit -m push" # not a push at all

# --- GATED: plain pushes to protected refs, tags and qualified names ---
check BLOCK "git push origin main"
check BLOCK "git push origin main > /dev/null"
check BLOCK "git push origin main 2>&1 | tail -3"
check BLOCK "git push origin release/0.1"
check BLOCK "git push origin v0.1.4"
check BLOCK "git push origin feature/x main"
check BLOCK "git push origin HEAD"
check BLOCK "git push origin feature/x:main"
check BLOCK "git push origin +feature/x:tags/v1.0"
check BLOCK "git push origin feature/x:refs/tags/v1"
check BLOCK "git push origin feature/x:heads/main" ".*"
check BLOCK "git push origin :main"
check BLOCK "git push origin :"
check BLOCK "git push origin main" ".*"
check BLOCK "git push origin v2.0.0" ".*"
check BLOCK "git push origin @" ".*"
check BLOCK "git push origin feature/x:@" ".*"
check PASS "git push origin @:feature/x"
check BLOCK "git push origin docs/x"
check BLOCK "git push origin docsx/y"
check BLOCK "git push origin feature/"
check BLOCK "git push origin DEVOPS-2069-record-image-digests"
check BLOCK "git push origin DEVOPS-2069" "$DEVOPS"

# --- GATED: not plain (flags beyond the allowlist, bare or remote-only pushes) ---
check BLOCK "git push"
check BLOCK "git push origin"
check BLOCK "git push --tags origin feature/1-a"
check BLOCK "git push --tag origin feature/1-a"
check BLOCK "git push --follow-tags origin feature/1-a"
check BLOCK "git push --all origin"
check BLOCK "git push --mirror origin"
check BLOCK "git push --delete origin main"
check BLOCK "git push -o feature/a origin main"
check BLOCK "git push -o feature/a feature/b"
check BLOCK "git push --repo origin main"
check BLOCK "git push https://example.com/r.git feature/x"
check BLOCK "git push origin feature/x 2> /tmp/err.log"

# --- GATED: compound or unusual shapes, even to working branches (no shell parsing) ---
check BLOCK "cd /tmp/x && git push origin main"
check BLOCK "cd /tmp/x && git push origin feature/1-a"
check BLOCK "git commit -m \"fix push gate\" && git push -u origin feature/1-a"
check BLOCK "git push origin feature/1-a && git push origin main"
check BLOCK "git push origin feature/x && echo push"
check BLOCK $'git push origin feature/1-a\ngit push origin main'
check BLOCK $'git -C /tmp/repo \\\n  push origin main'
check BLOCK "git push origin feature/1-a && (git push origin main)"
check BLOCK "git push origin feature/1-a; git -c a=b push origin main"
check BLOCK "git --no-pager push origin main"
check BLOCK "/usr/bin/git push origin main"
check BLOCK "echo \$(git push origin main)"
check BLOCK "FOO=1 git push origin main"
check BLOCK "env X=1 git push origin feature/1-a"
check BLOCK "sudo git push origin main"
check BLOCK "{ git push origin main; }"
check BLOCK "if true; then git push origin main; fi"
check BLOCK "bash -c \"git push origin main\""
check BLOCK "echo \`git push origin main\`"
check BLOCK "git --git-dir=.git push origin main"
check BLOCK "git -C \"/tmp/my repo\" push origin main"
check BLOCK "git -c \"core.sshCommand=ssh -i key\" push origin main"
check BLOCK "git --attr-source HEAD push origin main"
check BLOCK "git submodule foreach git push origin main"
check BLOCK "git rebase -x \"git push origin HEAD:main\" main"
check BLOCK "git -c core.sshCommand=\"ssh -i ~/.ssh/key\" push origin main"
check BLOCK "git -c user.name=\"BJ Baker\" push origin feature/1-a"
check BLOCK "git -C ~/my\\ repo push origin main"
check BLOCK "git -C \"\$(dirname \"\$f\")\" push origin main"
check BLOCK "git -C \$(git rev-parse --show-toplevel) push origin main"
check BLOCK "git -C \`git rev-parse --show-toplevel\` push origin main"
check BLOCK "git --git-dir=\"/tmp/my repo/.git\" push origin main"
check BLOCK "git --work-tree=~/my\\ repo push origin main"
check BLOCK "git --git-dir=\"\$(git rev-parse --git-common-dir)\" push origin main"
check BLOCK "git --git-dir= push origin main"
check BLOCK "git push origin \"feature/x\""
check BLOCK "git push origin feature/x\$(echo :main)"

# --- NOT A PUSH: passes untouched ---
check PASS "echo hi"
check PASS "git status && echo push"
check PASS "git commit -m \"push the fix\""
check PASS "git log --grep push"
check PASS "git stash push -m wip"
check PASS "grep -n push scripts/hooks/workflow/pre-push-test-gate.sh"

# --- PINNED TRADEOFF: a command that only MENTIONS "git push" is gated too. Ignoring quoted
# text would reopen `bash -c "git push origin main"`; a false block costs one test run, and
# the block reason says so. ---
check BLOCK "grep -rn \"git push\" scripts/"
check BLOCK "git commit -m \"doc: explain the git push gate\""
check BLOCK "gh issue create --body \"then run git push\""

# --- the sentinel still lets any push through, as before ---
touch "$SENTINEL"
check PASS "git push origin main"
check PASS "git commit -m x && git push origin feature/1-a"
cleanup

echo "──────────────────────────────────────────"
if [[ $fail -eq 0 ]]; then
	echo "PASS"
else
	echo "FAIL"
fi
exit "$fail"
