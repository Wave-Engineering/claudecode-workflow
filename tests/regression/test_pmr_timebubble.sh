#!/usr/bin/env bash
# test_pmr_timebubble.sh — #1195.
#
# Drives scripts/ci/pmr-timebubble.sh against a SYNTHETIC repository, for the
# same reason test_szz_oracle.sh does: this repo's own history is the harness's
# production input, and an assertion pinned to it would need editing on every
# commit — a maintained fixture, which is the failure mode the bench exists to
# avoid.
#
# The load-bearing cases are 4 and 5. Case 4 asserts the property the whole
# harness exists for: inside a reconstructed bubble, `git diff <base>...HEAD` is
# EMPTY while the working-tree diff is not. That is the pre-commit condition,
# and it is exactly the trap that made #1194's first shape a silent no-op. Case
# 5 asserts the untracked channel survives: a file the changeset ADDED is absent
# from `git diff` at any spelling, so an arm handed only a diff cannot review it.
#
# Case 8 is a mutation test of the harness's own failure path. A guard that has
# never been watched going red is not a guard, and the gitignored-add case is
# the one documented way reconstruction can be unfaithful — so it is asserted to
# EXIT 3 LOUDLY rather than being trusted to be unreachable.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BUBBLE="$ROOT/scripts/ci/pmr-timebubble.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0
check() { # want  got  label
	if [[ "$1" == "$2" ]]; then
		echo "  [PASS] $3"
		pass=$((pass + 1))
	else
		echo "  [FAIL] $3 (want '$1', got '$2')"
		fail=$((fail + 1))
	fi
}

# --- Build the fixture history ------------------------------------------------
repo="$tmp/repo"
mkdir -p "$repo"
# Pinned so a developer's global git config cannot turn a real result into a
# confusing failure. Same convention as tests/regression/test_szz_oracle.sh —
# plus core.excludesFile, which is the setting that can actually break THIS
# test: a global gitignore matching blob.bin, added.md or secret.txt would make
# `git add -A` below silently skip the file, and Cases 3 and 8 would fail with
# no hint as to why. This suite runs on every push via scripts/ci/validate.sh,
# so "works on my machine" is not an acceptable failure mode for it.
git -C "$repo" init -q -b main 2>/dev/null || git -C "$repo" init -q
git -C "$repo" config user.name "Fixture"
git -C "$repo" config user.email "fixture@example.invalid"
git -C "$repo" config commit.gpgsign false
git -C "$repo" config core.excludesFile /dev/null

# Do not hardcode `main`: the `init -q` fallback above exists for git < 2.28,
# which names the branch `master`. Hardcoding would make the later checkout
# fail, leave the shell on `side`, turn the merge into a no-op fast-forward,
# and hand Case 7 a SINGLE-parent commit — so "a merge commit exits 2" would
# fail for a reason having nothing to do with the harness.
MAIN="$(git -C "$repo" symbolic-ref --short HEAD)"

commit() { # subject
	git -C "$repo" commit -q -m "$1"
	git -C "$repo" rev-parse HEAD
}

# R — root commit. Has no parent, so it has no pre-state to reconstruct.
printf 'alpha\nbeta\ngamma\n' >"$repo/app.sh"
printf 'doomed\n' >"$repo/legacy.txt"
printf 'secret.txt\n' >"$repo/.gitignore"
git -C "$repo" add -A
R=$(commit "feat: root")

# C — the changeset under reconstruction. Modifies one file, ADDS one, DELETES
# one, and carries a binary blob so the --binary path is exercised rather than
# assumed.
printf 'alpha\nCHANGED\ngamma\n' >"$repo/app.sh"
printf 'brand new\n' >"$repo/added.md"
printf '\x00\x01\x02\xff\xfe binary payload\n' >"$repo/blob.bin"
rm "$repo/legacy.txt"
git -C "$repo" add -A
C=$(commit "fix: the changeset")

# M — a merge commit. Two parents means two candidate diffs.
git -C "$repo" checkout -q -b side "$R"
printf 'side\n' >"$repo/side.txt"
git -C "$repo" add -A
commit "feat: side branch" >/dev/null
git -C "$repo" checkout -q "$MAIN"
git -C "$repo" merge -q --no-ff side -m "merge: side into $MAIN" >/dev/null 2>&1
M=$(git -C "$repo" rev-parse HEAD)

run() { # subcommand + args, always against the fixture repo
	bash "$BUBBLE" "$@" --repo "$repo"
}

# --- Case 1: build reconstructs faithfully ------------------------------------
echo "Case 1: build proves fidelity via tree-hash equality"
out="$(run build "$C" --into "$tmp/b1" 2>"$tmp/b1.err")"
rc=$?
check "0" "$rc" "build exits 0"
expected="$(printf '%s' "$out" | awk -F'\t' '$1=="tree_expected"{print $2}')"
actual="$(printf '%s' "$out" | awk -F'\t' '$1=="tree_actual"{print $2}')"
# The non-empty precondition is not ceremony: if `build` emitted no manifest at
# all, both awks yield "" and `check "" ""` PASSES, so the assertion would read
# green while proving nothing.
check "40" "${#actual}" "a tree hash was actually emitted (not an empty match)"
check "$expected" "$actual" "reconstructed tree equals the commit's tree"
check "$(git -C "$repo" rev-parse "$C^{tree}")" "$actual" "and equals git's own hash for that commit"

# --- Case 2: the reconstruction is UNCOMMITTED and UNSTAGED -------------------
echo "Case 2: state is dirty, not staged and not committed"
check "" "$(git -C "$tmp/b1" diff --cached --name-only)" "nothing is staged"
check "$(git -C "$repo" rev-parse "$C^")" "$(git -C "$tmp/b1" rev-parse HEAD)" "HEAD is the PARENT, not the changeset"

# --- Case 3: the working tree carries all three change kinds ------------------
echo "Case 3: modified / added / deleted all present"
check "1" "$(printf '%s' "$out" | awk -F'\t' '$1=="files_modified"{print $2}')" "one modified file counted"
check "2" "$(printf '%s' "$out" | awk -F'\t' '$1=="files_added"{print $2}')" "two added files counted (added.md, blob.bin)"
check "1" "$(printf '%s' "$out" | awk -F'\t' '$1=="files_deleted"{print $2}')" "one deleted file counted"
check "CHANGED" "$(sed -n 2p "$tmp/b1/app.sh")" "the modification is on disk"
check "NO" "$([[ -e "$tmp/b1/legacy.txt" ]] && echo YES || echo NO)" "the deletion is on disk"
check "same" "$(cmp -s "$tmp/b1/blob.bin" <(git -C "$repo" show "$C:blob.bin") && echo same || echo differs)" "the binary blob reconstructed byte-for-byte"

# --- Case 4: THE pre-commit condition — three-dot is empty here ---------------
echo "Case 4: inside the bubble, three-dot sees nothing and the working tree sees everything"
base="$(git -C "$repo" rev-parse "$C^")"
check "0" "$(git -C "$tmp/b1" diff "$base...HEAD" | wc -c | tr -d ' ')" "git diff <base>...HEAD is EMPTY — the #1194 trap, reproduced"
tracked_bytes="$(git -C "$tmp/b1" diff | wc -c | tr -d ' ')"
check "yes" "$([[ "$tracked_bytes" -gt 0 ]] && echo yes || echo no)" "git diff (working tree) is NOT empty"

# --- Case 5: the untracked channel is real and invisible to diff --------------
echo "Case 5: added files are untracked — no diff spelling reports them"
check "A" "$(printf '%s' "$out" | awk -F'\t' '$1=="file" && $3=="added.md"{print $2}')" "added.md is reported as A (untracked)"
check "0" "$(git -C "$tmp/b1" diff -- added.md | wc -c | tr -d ' ')" "git diff -- added.md is empty"
check "0" "$(git -C "$tmp/b1" diff HEAD -- added.md | wc -c | tr -d ' ')" "git diff HEAD -- added.md is empty too"
check "added.md" "$(git -C "$tmp/b1" ls-files --others --exclude-standard | grep -q 'added.md' && echo added.md)" "it IS reachable via ls-files --others (the exclusivity is proven by the two checks above)"

# --- Case 6: verify is a real post-condition ----------------------------------
echo "Case 6: verify passes clean, then catches mutation"
run verify "$tmp/b1" "$C" >/dev/null 2>&1
check "0" "$?" "verify exits 0 on an untouched bubble"
echo "MUTATION" >>"$tmp/b1/app.sh"
run verify "$tmp/b1" "$C" >/dev/null 2>&1
check "3" "$?" "verify exits 3 once the bubble is mutated"

# --- Case 7: ambiguous pre-states are refused, not guessed --------------------
echo "Case 7: merge and root commits are refused"
run build "$M" --into "$tmp/b-merge" >/dev/null 2>&1
check "2" "$?" "a merge commit exits 2"
check "NO" "$([[ -e "$tmp/b-merge" ]] && echo YES || echo NO)" "and leaves no worktree behind"
run build "$R" --into "$tmp/b-root" >/dev/null 2>&1
check "2" "$?" "a root commit exits 2"
run build "$C" --into "$tmp/b1" >/dev/null 2>&1
check "2" "$?" "an --into path that already exists exits 2"
# The header promises "exit 2 unusable input". Without ${2:-} these abort with
# an unbound-variable error and exit 1 — a different contract than the one
# documented, and one no caller can distinguish from a crash.
bash "$BUBBLE" build "$C" --repo "$repo" --into >/dev/null 2>&1
check "2" "$?" "a flag with no argument exits 2, not an unbound-variable abort"
# Both flag branches, not just one: a mutation test that only exercises --into
# leaves the --repo branch unguarded, and the suite would stay green while half
# the documented contract was gone.
bash "$BUBBLE" build "$C" --into "$tmp/b-noarg" --repo >/dev/null 2>&1
check "2" "$?" "--repo with no argument exits 2 as well"

# --- Case 8: MUTATION TEST of the fidelity guard itself -----------------------
# A changeset that adds a file the PARENT's .gitignore ignores cannot be
# reconstructed faithfully: `add -A` skips it, so the tree differs. This is the
# one documented unfaithful case, and the guard must fire LOUDLY on it. If this
# case ever passes, the exit-3 path is dead code and every fidelity claim above
# is unearned.
echo "Case 8: the fidelity guard is reachable — an unfaithful reconstruction exits 3"
printf 'ignored payload\n' >"$repo/secret.txt"
git -C "$repo" add -f secret.txt
G=$(commit "fix: commit a gitignored file")
run build "$G" --into "$tmp/b-ignored" >/dev/null 2>"$tmp/ignored.err"
check "3" "$?" "gitignored-add reconstruction exits 3"
check "yes" "$(grep -q 'NOT faithful' "$tmp/ignored.err" && echo yes || echo no)" "and says so on stderr"
check "YES" "$([[ -e "$tmp/b-ignored" ]] && echo YES || echo NO)" "worktree is left for inspection, as the header promises"

# --- Case 9: teardown ---------------------------------------------------------
echo "Case 9: teardown removes a dirty worktree"
# POSITIVE CONTROL FIRST. `grep -c` prints 0 when it matches nothing — including
# when `git worktree list` fails outright, or when no entry was ever registered.
# Asserting only the 0 afterwards would pass even if there had been nothing to
# prune, which is the "guard that passes for the wrong reason" this suite is
# written against.
check "1" "$(git -C "$repo" worktree list --porcelain | grep -cxF "worktree $tmp/b1")" "the worktree IS registered before teardown"
run teardown "$tmp/b1" >/dev/null 2>&1
check "0" "$?" "teardown exits 0 on a dirty bubble"
check "NO" "$([[ -e "$tmp/b1" ]] && echo YES || echo NO)" "the worktree directory is gone"
check "0" "$(git -C "$repo" worktree list --porcelain | grep -cxF "worktree $tmp/b1")" "and its administrative entry is pruned"
run teardown "$tmp/b-ignored" >/dev/null 2>&1

# --- Case 10: teardown never deletes something it was not handed --------------
# The rm -rf fallback exists for a worktree git declines to remove. Ungated it
# would recursively delete ANY path — a typo, a stale directory, the caller's
# home. This asserts the gate, and asserts the directory SURVIVES.
echo "Case 10: teardown refuses a path that is not a registered worktree"
mkdir -p "$tmp/not-a-worktree"
printf 'precious\n' >"$tmp/not-a-worktree/keep.txt"
run teardown "$tmp/not-a-worktree" >/dev/null 2>&1
check "2" "$?" "teardown exits 2 on a path git does not list as a worktree"
check "YES" "$([[ -f "$tmp/not-a-worktree/keep.txt" ]] && echo YES || echo NO)" "and the directory is NOT deleted"

# --- Case 11: an operator's global gitignore cannot narrow the untracked channel
# The harness pins core.excludesFile to /dev/null on every call that consults
# it. Without that pin, a global ignore rule matching a file the changeset ADDED
# would drop it from the manifest's untracked channel — silently, since the file
# is still on disk. That channel is the entire reason this harness exists, so
# the pin is asserted rather than assumed. A repo-level core.excludesFile stands
# in for the operator's global one: both are out-of-tree, and `git -c` on the
# command line outranks both identically.
echo "Case 11: an out-of-tree ignore rule cannot hide an added file"
printf 'added.md\n' >"$tmp/global-ignore"
git -C "$repo" config core.excludesFile "$tmp/global-ignore"
# The precondition must prove the ignore rule is LIVE, by showing git actually
# hiding a file because of it. Asserting "the repo has no untracked files" would
# pass whether or not the rule existed — the wrong-reason pass this whole suite
# is written to exclude.
printf 'x\n' >"$repo/added.md"
check "" "$(git -C "$repo" ls-files --others --exclude-standard)" "precondition: git DOES hide added.md because of the ignore file"
rm -f "$repo/added.md"
out11="$(run build "$C" --into "$tmp/b11" 2>/dev/null)"
check "A" "$(printf '%s' "$out11" | awk -F'\t' '$1=="file" && $3=="added.md"{print $2}')" "added.md still appears in the untracked channel"
check "2" "$(printf '%s' "$out11" | awk -F'\t' '$1=="files_added"{print $2}')" "and files_added is not silently narrowed"
check "$(git -C "$repo" rev-parse "$C^{tree}")" "$(printf '%s' "$out11" | awk -F'\t' '$1=="tree_actual"{print $2}')" "and the tree still reconstructs faithfully"
run teardown "$tmp/b11" >/dev/null 2>&1
git -C "$repo" config core.excludesFile /dev/null

# --- Result -------------------------------------------------------------------
echo ""
echo "test_pmr_timebubble: $pass passed, $fail failed"
((fail == 0))
