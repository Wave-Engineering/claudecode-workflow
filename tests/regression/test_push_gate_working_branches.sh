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

# The repo every push runs in (the hook's cwd): hermetic, with one tag, `foo`, so a
# delete of a tag is refused however it is named (#1364 review).
RREPO=$(mktemp -d)
GIT_CONFIG_GLOBAL=/dev/null git -C "$RREPO" init -q
GIT_CONFIG_GLOBAL=/dev/null git -C "$RREPO" -c user.name=t -c user.email=t@example.invalid commit -q --allow-empty -m init
GIT_CONFIG_GLOBAL=/dev/null git -C "$RREPO" tag foo

cleanup() { rm -f "$SENTINEL"; }
trap 'cleanup; rm -rf "$RREPO"' EXIT
cleanup # no sentinel: every PASS below is the exemption (or not a push), not a test run

# check <PASS|BLOCK> <command> [extra-branch-regex]
check() {
	local want="$1" cmd="$2" extra="${3:-}" out got
	out=$(jq -n --arg s "$SID" --arg c "$cmd" --arg d "$RREPO" '{session_id: $s, cwd: $d, tool_input: {command: $c}}' |
		env -u WAVE_FLIGHT_ID PUSH_GATE_EXTRA_BRANCH_RE="$extra" bash "$GATE")
	if printf '%s' "$out" | grep -q '"decision":"block"'; then got=BLOCK; else got=PASS; fi
	if [[ "$got" == "$want" ]]; then
		printf '  ok    %-5s %s%s\n' "$got" "$cmd" "${extra:+  [extra=$extra]}"
	else
		printf '  WRONG %-5s (want %s) %s%s\n' "$got" "$want" "$cmd" "${extra:+  [extra=$extra]}"
		fail=1
	fi
}

# check_reason <command> <text>...: the command is blocked and its reason carries each text.
check_reason() {
	local cmd="$1" out want
	shift
	out=$(jq -n --arg s "$SID" --arg c "$cmd" --arg d "$RREPO" '{session_id: $s, cwd: $d, tool_input: {command: $c}}' |
		env -u WAVE_FLIGHT_ID PUSH_GATE_EXTRA_BRANCH_RE= bash "$GATE")
	for want in "$@"; do
		if ! printf '%s' "$out" | jq -e --arg w "$want" '.decision == "block" and (.reason | contains($w))' >/dev/null; then
			printf '  WRONG reason of %s lacks: %s\n' "$cmd" "$want"
			fail=1
			return
		fi
	done
	printf '  ok    reason %s\n' "$cmd"
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
# #1364 review: the widened names are for deletes only, so numeric-led branches still push
check PASS "git push origin 12-fix" '^[0-9]+-.+'
check PASS "git push -u origin 12-fix" '^[0-9]+-.+'
check BLOCK "git push origin --delete 12-fix" '^[0-9]+-.+' # numeric-led: may be a tag-like name
check BLOCK "git push origin :12-fix"
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

# --- #1364: a plain delete of ONE non-protected branch needs no sentinel and no prefix ---
check PASS "git push origin --delete fix/18-mutant-bad-unit"
check PASS "git push lanebox --delete scratch-run-3"
check PASS "git push lanebox :scratch-run-3"
check PASS "git push -d origin chore/x"
check PASS "git push --delete origin scratch-1"
check PASS "git push origin --delete refs/heads/scratch-1"
check PASS "git -C $RREPO push lanebox :scratch-1"
check BLOCK "git -C $RREPO push lanebox :foo"                  # foo is a tag in the -C repo
check BLOCK "git -C /nonexistent-1364 push lanebox :scratch-1" # the tag lookup cannot run: fail closed
check PASS "git push origin --delete scratch-1 2>&1 | tail -3"
check PASS "git push -q origin --delete kahuna/4-campaign"
# protected, release, qualified and revision targets stay refused
check BLOCK "git push origin --delete main"
check BLOCK "git push origin :master"
check BLOCK "git push origin --delete release/1.2"
check BLOCK "git push origin --delete v1.0.0"
check BLOCK "git push origin --delete tags/v1"
check BLOCK "git push origin :refs/tags/v1"
check BLOCK "git push origin :refs/heads/main"
check BLOCK "git push origin --delete HEAD"
check BLOCK "git push origin --delete @"
# only a single-ref delete is exempt without a prefix
check BLOCK "git push origin --delete a b"
check BLOCK "git push origin :scratch-1 :scratch-2"
check BLOCK "git push origin :scratch-1 feature/2-x"
check BLOCK "git push origin -d --delete scratch-1"
# #1364 review: a bare name resolves against every remote ref, tags included
check BLOCK "git push origin --delete 1.2.3"
check BLOCK "git push origin :release"
check BLOCK "git push origin --delete release-2.x"
check BLOCK "git push origin --delete release_3"
check BLOCK "git push origin :stable"
check BLOCK "git push origin --delete production"
check BLOCK "git push origin --delete prod"
check BLOCK "git push origin :gh-pages"
check BLOCK "git push origin --delete foo" # a local tag
check PASS "git push origin --delete foo-bar"
check PASS "git push origin --delete releases-notes"
# malformed deletes and disallowed flags
check BLOCK "git push origin --delete"
check BLOCK "git push --delete origin"
check BLOCK "git push origin --delete +x"
check BLOCK "git push origin --delete scratch-1 --force"
check BLOCK "git push origin --delete :scratch-1"
check BLOCK "git push https://example.com/r.git --delete scratch-1"
# non-plain deletes are still gated
check BLOCK "cd /tmp && git push origin --delete scratch-1"
check BLOCK "GIT_SSH_COMMAND=x git push lanebox :scratch-1"
check BLOCK "bash -c \"git push origin :scratch-1\""
# a refused delete names the approved path
check_reason "git push origin --delete main" "git push <remote> --delete <branch>" "core.sshCommand" "ask the user" "its own Bash call"
check_reason "cd /tmp && git push origin --delete x" "git push <remote> --delete <branch>" "core.sshCommand" "ask the user" "its own Bash call"
check_reason "git push origin main" "Cannot push untested code" # a non-delete keeps the test reason

# a git-detect.sh older than the gate (mid-./install) blocks; it must not fail open
old_dir=$(mktemp -d)
cp "$GATE" "$old_dir/"
sed '/^# Refs an agent never pushes/,$d' "$REPO_DIR/scripts/hooks/workflow/git-detect.sh" >"$old_dir/git-detect.sh"
out=$(jq -n --arg s "$SID" --arg c "git push origin main" '{session_id: $s, tool_input: {command: $c}}' |
	bash "$old_dir/pre-push-test-gate.sh")
if printf '%s' "$out" | grep -q 'git-detect.sh helper did not load'; then
	printf '  ok    BLOCK git push origin main  [old git-detect.sh]\n'
else
	printf '  WRONG (want the load-failure block) git push origin main  [old git-detect.sh]: %s\n' "$out"
	fail=1
fi
rm -rf "$old_dir"

# --- the sentinel still lets any push through, as before ---
touch "$SENTINEL"
check PASS "git push origin main"
check PASS "git commit -m x && git push origin feature/1-a"
check PASS "cd /tmp && git push origin --delete scratch-1"
check PASS "cd /tmp && git push origin --delete scratch-1 2>&1 | tail -3"
# #1364 review: a PLAIN delete of a protected name or a tag is refused, test run or not.
# Other delete shapes fall back to the test-run rule, so the sentinel lets them through.
check PASS "git push origin --delete main --no-progress"
check PASS "cd . && git push origin :main"
check BLOCK "git push origin --delete 1.2.3"
check BLOCK "git push origin --delete foo"
# #1364: except a plain delete of a protected ref, which a test run does not license
check BLOCK "git push origin --delete main"
check BLOCK "git push origin :release/1.0"
cleanup

echo "──────────────────────────────────────────"
if [[ $fail -eq 0 ]]; then
	echo "PASS"
else
	echo "FAIL"
fi
exit "$fail"
