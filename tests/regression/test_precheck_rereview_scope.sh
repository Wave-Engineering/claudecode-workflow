#!/usr/bin/env bash
# test_precheck_rereview_scope.sh — regression test for issue #1194.
# Picked up by scripts/ci/validate.sh's "Regression tests" loop.
#
# /precheck's Job D (code review) is the dominant wall-clock cost in the gate
# (~8 min/pass; three passes approaches 30 min). #1194 scopes RE-RUNS to what
# changed since the last completed review, so pass 2+ stops re-reading code the
# reviewer already cleared in the same cycle.
#
# WHY THIS TEST DRIVES scripts/ci/precheck-review-scope.sh DIRECTLY.
#
# The first version of this test grepped the skill for strings and separately
# executed a hand-typed COPY of the scope predicate. Code review pointed out
# that nothing connected the two: the copy could pass every assertion while the
# skill's real logic was broken — and it was. The predicate recorded
# `rev-parse HEAD` and re-reviewed `<prev>..HEAD`, which is empty in a
# PRE-commit gate because HEAD never moves between passes. Pass 2 would have
# reviewed nothing and reported success.
#
# So the logic now lives in ONE script, and this test executes THAT script. The
# doc-shape checks that remain exist only to catch the skill drifting away from
# calling it.

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SKILL="$REPO_DIR/skills/precheck/SKILL.md"
SCOPE="$REPO_DIR/scripts/precheck-review-scope.sh"

FAILS=0
fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}
pass() { echo "  [PASS] $*"; }

echo "test_precheck_rereview_scope (#1194)"
echo "──────────────────────────────────────────"

for f in "$SKILL" "$SCOPE"; do
	if [[ ! -f "$f" ]]; then
		fail "missing: $f"
		exit 1
	fi
done

# ===========================================================================
# PART 1 — the real script, executed. This is the load-bearing half.
# ===========================================================================

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
R="$TMP/repo"
M="$TMP/mark"
mkdir -p "$R" "$M"

# gpgsign/defaultBranch pinned so a developer's global git config cannot turn a
# real result into a confusing failure.
git -C "$R" init -q -b main 2>/dev/null || git -C "$R" init -q
git -C "$R" config user.email t@t.t
git -C "$R" config user.name t
git -C "$R" config commit.gpgsign false
echo v1 >"$R/f"
git -C "$R" add f
git -C "$R" commit -qm base

scope() { bash "$SCOPE" "$1" "$R" "$M" 2>/dev/null; }
verdict() { scope resolve | awk '{print $1}'; }
ref() { scope resolve | awk '{print $2}'; }

expect() { # <expected-verdict> <label>
	local got
	got="$(verdict)"
	if [[ "$got" == "$1" ]]; then
		pass "$2"
	else
		fail "$2 (expected '$1', got '$got')"
	fi
}

# --- fail-safe matrix: every unresolvable state must be `full` -------------
scope reset
expect full "no marker -> full"

: >"$M/precheck-reviewed-state"
expect full "empty marker -> full"

echo "not-a-sha" >"$M/precheck-reviewed-state"
expect full "garbage marker -> full"

echo "0000000000000000000000000000000000000000" >"$M/precheck-reviewed-state"
expect full "nonexistent object (gc'd snapshot) -> full"

# --- THE bug #1194's first implementation shipped -------------------------
# Uncommitted work, reviewed, then fixed — still uncommitted, HEAD unmoved.
# The old `<prev>..HEAD` predicate returned an EMPTY delta here.
scope reset
echo "buggy" >>"$R/f" # work under review (uncommitted, as in a real precheck)
scope record          # pass 1 completes
HEAD_BEFORE="$(git -C "$R" rev-parse HEAD)"
echo "fixed" >>"$R/f" # the fix — still uncommitted
HEAD_AFTER="$(git -C "$R" rev-parse HEAD)"

if [[ "$HEAD_BEFORE" == "$HEAD_AFTER" ]]; then
	pass "fixture is honest: HEAD does not move between passes (pre-commit gate)"
else
	fail "fixture broken: HEAD moved, so this no longer tests the pre-commit case"
fi

expect delta "uncommitted fix after a recorded pass -> delta"

DELTA_REF="$(ref)"
if [[ -n "$DELTA_REF" ]] && ! git -C "$R" diff --quiet "$DELTA_REF" 2>/dev/null; then
	pass "REGRESSION GUARD: delta diff is NON-EMPTY (the fix is actually reviewed)"
else
	fail "REGRESSION: delta diff is empty — pass 2 would review nothing and report success"
fi

# The delta must actually contain the fix, not merely be non-empty.
if git -C "$R" diff "$DELTA_REF" | grep -q '^+fixed'; then
	pass "delta contains the specific fix made after the recorded pass"
else
	fail "delta does not contain the post-review fix"
fi

# The delta must NARROW, not merely be non-empty. Regressing the snapshot from
# `stash create` back to `rev-parse HEAD` leaves every safety assertion above
# green — the diff still contains the fix — while the delta degenerates into the
# entire uncommitted diff and the feature costs the 8 minutes it exists to save.
# `buggy` was present when the pass was recorded; it must NOT reappear.
if git -C "$R" diff "$DELTA_REF" | grep -q '^+buggy'; then
	fail "delta re-includes already-reviewed content — snapshot degraded to HEAD, feature is a no-op"
else
	pass "delta EXCLUDES content the recorded pass already reviewed (it genuinely narrows)"
fi

# --- an untracked file EDITED after record must still be surfaced ---------
# Name-only tracking missed this: `git diff <snapshot>` never shows untracked
# paths, and a by-name set difference sees the name on both sides. In a
# pre-commit gate every new file is untracked for the whole cycle, so this was a
# live "fix reaches main unreviewed" hole, not a corner case.
scope reset
echo "tracked-work" >>"$R/f"
echo "untracked v1" >"$R/fresh.py"
scope record
echo "tracked-fix" >>"$R/f"
echo "untracked-FIX" >>"$R/fresh.py"
if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qx "fresh.py"; then
	pass "untracked file MODIFIED after record is surfaced to the reviewer"
else
	fail "modified untracked file invisible in both channels — its fix would never be read"
fi
rm -f "$R/fresh.py"

# --- the FULL pass's diff command must see uncommitted work ---------------
# Executed, not grepped. Reproduces the exact precheck condition: HEAD ==
# merge-base (nothing committed on the branch) with staged+unstaged edits.
scope reset
git -C "$R" checkout -q -b fullcheck 2>/dev/null || git -C "$R" checkout -q fullcheck
echo "uncommitted work" >>"$R/f"
MB="$(git -C "$R" merge-base main HEAD 2>/dev/null || git -C "$R" rev-parse HEAD)"
THREE_DOT="$(git -C "$R" diff main...HEAD 2>/dev/null | wc -c)"
MERGE_BASE="$(git -C "$R" diff "$MB" 2>/dev/null | wc -c)"
if ((MERGE_BASE > 0)); then
	pass "merge-base->worktree diff is NON-EMPTY with uncommitted work ($MERGE_BASE bytes)"
else
	fail "merge-base->worktree diff is empty — the full pass would review nothing"
fi
if ((THREE_DOT == 0)); then
	pass "[INFO] commit-range diff is EMPTY here — demonstrates why three-dot is wrong"
else
	pass "[INFO] commit-range diff non-empty in this fixture; form still wrong for precheck"
fi
git -C "$R" checkout -q - 2>/dev/null || true

# --- an unchanged tree must not produce an empty delta --------------------
scope reset
echo "x" >>"$R/f"
scope record
expect full "recorded then nothing changed -> full (never an empty delta)"

# --- untracked files are surfaced separately ------------------------------
# `git stash create` cannot capture untracked content, so a whole new file
# added between passes would otherwise be invisible to the reviewer.
scope reset
scope record
echo "brand new" >"$R/newmodule.py"
if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qx "newmodule.py"; then
	pass "new untracked file is reported to the delta reviewer"
	# A file already present at record time must NOT be re-reported.
	scope record
	if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qx "newmodule.py"; then
		fail "already-reviewed untracked file re-reported (delta is not narrowing)"
	else
		pass "untracked file recorded in a pass is not re-reported next pass"
	fi
else
	fail "new untracked file NOT reported — it would never be read"
fi

# --- hostile filenames must not corrupt the set difference ----------------
# A newline in a path split one record across two lines, and sorting the inputs
# LC_ALL=C while `comm` collated under a UTF-8 locale made the two disagree —
# both produced "comm: input is not in sorted order", i.e. undefined behaviour
# in the code path whose entire job is not missing a changed file.
#
# The fixture must RECORD the hostile names first: an earlier version created
# them after `record`, so comm's first input was empty and neither defect could
# fire. Both mutations passed a green suite until this was fixed.
scope reset
printf 'x' >"$R/ünïcödé.py"
printf 'x' >"$R/has space.py"
NL_FILE="$R/has"$'\n'"newline.py"
printf 'x' >"$NL_FILE" 2>/dev/null && HAVE_NL=1 || HAVE_NL=0
scope record # <- hostile names are now IN the recorded list

printf 'x' >"$R/later.py" # something new, so comm actually diffs two populated lists
# Run the collation-sensitive assertions under a REAL collating locale. The
# LC_ALL=C-on-comm defect only manifests where strcoll disagrees with strcmp;
# CI images default to C.UTF-8 whose collation IS codepoint order, so without
# this the guard for that defect is inert exactly where it matters most.
COLLATE_LOCALE=""
for cand in en_US.UTF-8 en_GB.UTF-8 de_DE.UTF-8; do
	if locale -a 2>/dev/null | grep -qix "${cand//UTF-8/utf8}" || locale -a 2>/dev/null | grep -qix "$cand"; then
		COLLATE_LOCALE="$cand"
		break
	fi
done
if [[ -n "$COLLATE_LOCALE" ]]; then
	pass "collating locale available for hostile-name checks ($COLLATE_LOCALE)"
else
	pass "[SKIPPED] no collating locale installed — collation guard cannot be exercised here"
fi
HOSTILE_ERR="$(LC_ALL="${COLLATE_LOCALE:-C}" LANG="${COLLATE_LOCALE:-C}" bash "$SCOPE" new-untracked "$R" "$M" 2>&1 >/dev/null)"
if [[ -z "$HOSTILE_ERR" ]]; then
	pass "new-untracked is silent on unicode/space/newline filenames"
else
	fail "new-untracked wrote to stderr (sort/collation mismatch): $HOSTILE_ERR"
fi

if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qxF "later.py"; then
	pass "genuinely-new file still reported alongside hostile names"
else
	fail "new file lost when hostile filenames are present"
fi

# An edit to the non-ASCII file must be isolated — this is what breaks when the
# LC_ALL=C/strcoll mismatch makes comm mis-pair lines.
scope record
printf 'EDITED' >>"$R/ünïcödé.py"
if LC_ALL="${COLLATE_LOCALE:-C}" LANG="${COLLATE_LOCALE:-C}" bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qxF "ünïcödé.py"; then
	pass "edit to a non-ASCII untracked file is detected (under $COLLATE_LOCALE)"
else
	fail "edit to a non-ASCII untracked file missed — content change invisible"
fi

# An edit to the newline-named file must also be caught. Without escaping, its
# record spans two lines and the set difference is garbage.
if ((HAVE_NL)); then
	scope record
	printf 'EDITED' >>"$NL_FILE"
	OUT="$(bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null)"
	if [[ "$(printf '%s' "$OUT" | wc -l)" -le 1 ]] && printf '%s' "$OUT" | grep -q 'newline'; then
		pass "edit to a newline-named untracked file is detected as ONE record"
	else
		fail "newline-named file mishandled (record split or edit missed): $(printf '%s' "$OUT" | tr '\n' '|')"
	fi
	rm -f "$NL_FILE"
else
	pass "[SKIPPED] filesystem rejects newline in filename"
fi
rm -f "$R/ünïcödé.py" "$R/has space.py" "$R/later.py"

# --- keys must describe what git will STORE, not just file content --------
# Three cases where content-only hashing marked a real change as reviewed.
scope reset
echo same >"$R/A"
echo same >"$R/B"
ln -s A "$R/mylink"
printf '#!/bin/sh\n' >"$R/s.sh"
chmod 644 "$R/s.sh"
scope record

ln -sf B "$R/mylink" # retarget between IDENTICAL-content files
if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qx "mylink"; then
	pass "symlink retargeted between same-content files is detected"
else
	fail "symlink retarget invisible — git stores the target string, not its content"
fi

scope record
chmod +x "$R/s.sh" # exec bit is the one mode bit git records
if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qx "s.sh"; then
	pass "exec-bit-only change on an untracked file is detected"
else
	fail "chmod +x invisible — changes what git add commits"
fi

# A path that cannot be hashed in EITHER pass must not compare equal to itself.
scope reset
echo secret >"$R/locked.txt"
chmod 000 "$R/locked.txt"
scope record
# root ignores the mode bits, so hash-object succeeds and the key is stable —
# the assertion below would go red on CORRECT code in any root container lane.
if [[ $EUID -eq 0 ]]; then
	pass "[SKIPPED] running as root — chmod 000 cannot make a file unreadable"
elif bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qx "locked.txt"; then
	pass "persistently unhashable path is surfaced, not silently marked reviewed"
else
	fail "constant sentinel — an unreadable file reads as reviewed on every pass"
fi
chmod 644 "$R/locked.txt"

# ...and none of this may cause false positives on a quiet tree.
scope reset
echo x >"$R/quiet.py"
ln -s quiet.py "$R/quiet.link"
scope record
NOISE="$(bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null)"
if [[ -z "$NOISE" ]]; then
	pass "unchanged tree with symlinks reports nothing (no false positives)"
else
	fail "false positives on an unchanged tree: $(printf '%s' "$NOISE" | tr '\n' ' ')"
fi
rm -f "$R/A" "$R/B" "$R/mylink" "$R/s.sh" "$R/locked.txt" "$R/quiet.py" "$R/quiet.link"

# --- non-regular files: guard is defensive, and the branch is UNREACHABLE --
# `git hash-object` on a FIFO blocks until a writer appears, which would hang
# the gate. The script guards against it — but `git ls-files --others` does NOT
# list FIFOs, so the branch cannot actually be reached today. Stated plainly
# rather than dressed up as coverage: an earlier version of this test created a
# FIFO and asserted no hang, which passed whether or not the guard existed.
if grep -q 'NONREGULAR-' "$SCOPE"; then
	pass "non-regular guard present (defensive; ls-files does not surface FIFOs today)"
else
	fail "non-regular guard removed — if ls-files ever lists a FIFO, the gate hangs"
fi

# --- symlink target must be a FIXED-WIDTH key, not raw interpolation -------
# Raw interpolation on a space-delimited line makes (target "a", path "b c")
# and (target "a b", path "c") produce the SAME record, so retargeting across
# that boundary is invisible; and `cut -d" " -f2-` then emits a path that does
# not exist.
scope reset
mkdir -p "$R/sd"
echo x >"$R/sd/a"
echo x >"$R/sd/a b"
ln -s a "$R/sd/b c"
ln -s "a b" "$R/sd/c"
scope record
ln -sf "a b" "$R/sd/b c" # retarget across the ambiguous boundary
if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qxF "sd/b c"; then
	pass "symlink retarget across a space-ambiguous boundary is detected"
else
	fail "symlink key collision — retarget invisible (target must be hashed, not interpolated)"
fi
# ...and the emitted path must be the LINK, not target+link glued together.
ln -sf "$R/sd/a" "$R/sd/spacetgt" 2>/dev/null
scope record
ln -sf "a b" "$R/sd/spacetgt"
if bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null | grep -qxF "sd/spacetgt"; then
	pass "emitted path is the symlink itself, not target-plus-path"
else
	fail "emitted path is wrong — reviewer would be handed a nonexistent file"
fi
rm -rf "$R/sd"

# --- new-untracked must FAIL LOUD, never empty ----------------------------
# Empty output reads as the affirmative "no new untracked files". Under
# `set -euo pipefail` any pipeline failure would abort with exactly that.
scope reset
echo x >"$R/present.py"
scope record
printf 'zzz-unsorted\nAAA\n' >"$M/precheck-reviewed-untracked" # corrupt the marker
CORRUPT_OUT="$(bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null)"
if [[ -n "$CORRUPT_OUT" ]]; then
	pass "new-untracked fails loud on a corrupt marker (non-empty output)"
else
	fail "new-untracked returned EMPTY on a corrupt marker — reads as 'nothing new'"
fi
rm -f "$R/present.py"

# --- `full` must clear BOTH channels, not just the tracked one ------------
# resolve used to be a pure read, so a mid-cycle fall-back to full left
# new-untracked still narrowing against the marker the verdict had just
# declared untrustworthy: full tracked diff + delta-scoped untracked list.
scope reset
echo "orphan" >"$R/orphan.py"
scope record
echo "0000000000000000000000000000000000000000" >"$M/precheck-reviewed-state"
V="$(verdict)"
U="$(bash "$SCOPE" new-untracked "$R" "$M" 2>/dev/null || true)"
if [[ "$V" == "full" ]] && printf '%s' "$U" | grep -qx "orphan.py"; then
	pass "a 'full' verdict re-lists untracked files (both channels widen together)"
else
	fail "mixed scope: verdict='$V' but untracked list did not re-list orphan.py"
fi
rm -f "$R/orphan.py"

# --- marker_dir must be rejected INSIDE the repo --------------------------
# Otherwise the markers are themselves untracked files that record records and
# /scp's `git add -A` commits.
mkdir -p "$R/inside_marker"
if bash "$SCOPE" record "$R" "$R/inside_marker" >/dev/null 2>&1; then
	fail "marker_dir inside repo_root was ACCEPTED — markers would get committed"
else
	pass "marker_dir inside repo_root is rejected"
fi
rm -rf "$R/inside_marker"

# --- `gather` is EXECUTED, not described -----------------------------------
# The two hand-written versions of this logic shipped broken (split's missing
# destination dir; a threshold above the Bash output cap). It is a subcommand
# now precisely so these are executed assertions rather than greps on prose.
scope reset
echo "gathered change" >>"$R/f"
G="$(bash "$SCOPE" gather "$R" "$M" main 2>/dev/null || true)"
if [[ "$(printf '%s' "$G" | awk '{print $1}')" == "files" ]]; then
	pass "gather returns 'files <N> <path>...' for a normal changeset"
else
	fail "gather did not return a files verdict: '$G'"
fi
GPATH="$(printf '%s' "$G" | awk '{print $3}')"
if [[ -s "$GPATH" ]] && grep -q 'gathered change' "$GPATH"; then
	pass "gather wrote a real, non-empty diff to disk containing the change"
else
	fail "gather's output file is missing, empty, or lacks the change"
fi

# unresolvable target -> exit 2, message on stderr, nothing on stdout
GOUT="$(bash "$SCOPE" gather "$R" "$M" definitely-not-a-branch 2>/dev/null)"
GRC=$?
if ((GRC != 0)) && [[ -z "$GOUT" ]]; then
	pass "gather exits non-zero with empty stdout on an unresolvable target"
else
	fail "gather returned rc=$GRC stdout='$GOUT' for an unresolvable target"
fi

# untracked-only changeset -> explicit 'empty', NEVER silence.
# Isolated fixture so the state is deterministic: an earlier version depended on
# the shared repo's tree and had an `else pass [INFO]` escape, which made it
# unable to fail — the decorative-assertion problem, in a brand-new test.
ER="$TMP/emptyrepo"
EM="$TMP/emptymark"
mkdir -p "$ER" "$EM"
git -C "$ER" init -q -b main 2>/dev/null || git -C "$ER" init -q
git -C "$ER" config user.email t@t.t
git -C "$ER" config user.name t
git -C "$ER" config commit.gpgsign false
echo base >"$ER/tracked.txt"
git -C "$ER" add -A
git -C "$ER" commit -qm base
echo "brand new" >"$ER/only_untracked.py" # nothing tracked has changed
GE="$(bash "$SCOPE" gather "$ER" "$EM" main 2>/dev/null || true)"
if [[ "$(printf '%s' "$GE" | awk '{print $1}')" == "empty" ]]; then
	pass "gather says 'empty' explicitly for an untracked-only changeset (never silence)"
else
	fail "gather returned '$GE' for an untracked-only changeset — silence reads as 'nothing changed'"
fi

# >1500 lines must SPLIT, and the parts must be lossless
python3 - "$R/big.txt" <<'PY'
import sys
open(sys.argv[1], "w").write("\n".join(f"line {i}" for i in range(4000)))
PY
git -C "$R" add big.txt 2>/dev/null || true
GS="$(bash "$SCOPE" gather "$R" "$M" main 2>/dev/null || true)"
NPARTS=$(printf '%s' "$GS" | wc -w)
TOTAL=$(printf '%s' "$GS" | awk '{print $2}')
if ((NPARTS > 3)) && [[ -n "$TOTAL" ]]; then
	SUM=$(cat "$M"/diff/part-* 2>/dev/null | wc -l)
	if [[ "$SUM" == "$TOTAL" ]]; then
		pass "gather SPLITS a >1500-line diff losslessly ($TOTAL lines across parts)"
	else
		fail "split lost lines: parts=$SUM vs reported=$TOTAL"
	fi
else
	fail "gather did not split a 4000-line diff: '$(printf '%s' "$GS" | cut -c1-60)'"
fi
git -C "$R" rm -q --cached big.txt 2>/dev/null || true
rm -f "$R/big.txt"
rm -rf "$M/diff"

# --- gather with a DELTA ref must NARROW (the pass-9 critical) ------------
# Every gather assertion above passes the literal `main`, so gather's rev
# arithmetic was only ever exercised on the full path. On the delta path it
# applied merge-base unconditionally — and since `stash create` makes HEAD the
# snapshot's first parent, merge-base(snapshot, HEAD) IS HEAD. Every delta
# collapsed to `git diff HEAD`: the whole changeset, i.e. the feature was a
# no-op that still cost the 8 minutes it exists to save.
scope reset
echo "was-reviewed" >>"$R/f"
scope record
echo "the-fix" >>"$R/f"
DREF="$(scope resolve | awk '{print $2}')"
if [[ -n "$DREF" ]]; then
	DP="$(bash "$SCOPE" gather "$R" "$M" "$DREF" 2>/dev/null | awk '{print $3}')"
	if [[ -s "$DP" ]] && grep -q '^+the-fix' "$DP" && ! grep -q '^+was-reviewed' "$DP"; then
		pass "gather on a DELTA ref narrows: contains the fix, excludes reviewed content"
	else
		fail "gather delta did NOT narrow (merge-base collapsed the snapshot to HEAD) — feature is a no-op"
	fi
	# ...and the FULL path must still widen, or the fix broke the other mode.
	FP="$(bash "$SCOPE" gather "$R" "$M" main 2>/dev/null | awk '{print $3}')"
	if [[ -s "$FP" ]] && grep -q '^+was-reviewed' "$FP"; then
		pass "gather on a BRANCH still returns the full changeset"
	else
		fail "gather full path stopped covering everything"
	fi
else
	fail "resolve did not produce a delta ref for the narrowing fixture"
fi
rm -rf "$M/diff"

# --- committed work is covered too ----------------------------------------
scope reset
scope record
echo "committed change" >>"$R/f"
git -C "$R" add -A
git -C "$R" commit -qm "later commit"
expect delta "a commit made after the recorded pass -> delta"
if git -C "$R" diff "$(ref)" | grep -q 'committed change'; then
	pass "delta covers work that was committed between passes"
else
	fail "delta misses committed work"
fi

# --- rewritten history must not yield a bogus range -----------------------
scope reset
echo "pre-rewrite" >>"$R/f"
scope record
git -C "$R" checkout -q --orphan rewritten
git -C "$R" add -A
git -C "$R" commit -qm rewritten
# The snapshot object may or may not survive. Either verdict is acceptable so
# long as it is SAFE: `full`, or a `delta` whose ref is still a real commit.
V="$(verdict)"
if [[ "$V" == "full" ]]; then
	pass "rewritten history -> full"
elif [[ "$V" == "delta" ]] && git -C "$R" cat-file -e "$(ref)^{commit}" 2>/dev/null; then
	pass "rewritten history -> delta against a still-valid snapshot (safe)"
else
	fail "rewritten history produced an unusable verdict: '$V'"
fi

# --- reset genuinely clears -----------------------------------------------
scope reset
expect full "reset clears the marker -> next pass is full"

# ===========================================================================
# PART 2 — doc-shape: the skill must still DELEGATE to that script.
# ===========================================================================

# Anchored on the FULL invocation form. An unanchored grep matched a bare
# `precheck-review-scope.sh reset` just as happily, which meant the fix for
# "invoked by bare relative path" had zero coverage: a regression there breaks
# the script lookup whenever the agent's cwd is not the repo root, and the
# likely agent response to "file not found" is to skip the scoping step rather
# than fail the gate.
# Assert the NEGATIVE: no PATH-qualified invocation anywhere. The positive
# form was unanchored — `bash <repo_root>/scripts/precheck-review-scope.sh reset`
# satisfied `grep -F "precheck-review-scope.sh reset"` identically, so the most
# likely regression (reverting to a repo-path call at the NEW path) passed green.
# That is the same unanchored-guard defect this file has now hit four times.
if grep -qE '/precheck-review-scope\.sh' "$SKILL"; then
	pass "[INFO] path-qualified references exist — expected only inside the Step 0 ladder"
fi
LADDER_LINES=$(grep -cE '/precheck-review-scope\.sh' "$SKILL")
PROMPT_PATHS=$(awk '/\*\*Job D-full\*\*/,0' "$SKILL" | grep -cE 'bash [^ ]*/precheck-review-scope\.sh')
if ((PROMPT_PATHS == 0)); then
	pass "no PATH-qualified invocation in the prompts (resolves outside a checkout)"
else
	fail "$PROMPT_PATHS prompt invocation(s) use a repo path — inert outside a cc-workflow checkout"
fi

for sub in reset record resolve new-untracked gather; do
	if grep -qF "precheck-review-scope.sh $sub" "$SKILL"; then
		pass "skill invokes '$sub'"
	else
		fail "'$sub' invocation missing or dropped"
	fi
done

# The distribution property itself — the exact predicate install's
# enumerate_farm_targets uses, so it is pinned rather than hand-verified.
if (cd "$REPO_DIR/scripts" && find . -maxdepth 1 -type f | grep -qx './precheck-review-scope.sh'); then
	pass "tool sits where install's enumerate_farm_targets will find it"
else
	fail "tool is not a top-level scripts/ file — install would NOT distribute it"
fi

if grep -qF 'command -v precheck-review-scope.sh' "$SKILL"; then
	pass "pre-flight probe present (fails loud instead of empty-channel)"
else
	fail "no command -v pre-flight — a missing tool would silently empty both channels"
fi
if [[ -x "$SCOPE" ]]; then
	pass "tool is executable (required for PATH install)"
else
	fail "tool is not executable — breaks direct execution from a checkout (install chmods +x regardless)"
fi

# Both prompts must hand over untracked files. `git diff <base>` never shows
# them, and /precheck runs before /scp's `git add`, so a new file can be
# untracked for the whole cycle. If the FULL prompt omits the channel, pass 1
# never sees the file, `record` then writes it into the reviewed set, and the
# delta correctly omits it as cleared — reviewed by nobody.
# Sliced PER PROMPT, not counted file-wide. A global `grep -c >= 2` guards a
# CRITICAL and is satisfied by deleting the channel from Job D-full and adding
# any second mention anywhere else — prose, a comment, a duplicate in the delta
# block — leaving the critical fully regressed and the suite green.
check_slice() { # <label> <slice-content>
	if printf '%s' "$2" | grep -qF 'new-untracked <repo_root> <marker_dir>'; then
		pass "Job D-$1 prompt carries the untracked-files channel"
	else
		fail "Job D-$1 prompt LOST the untracked channel — a new file can be reviewed by nobody"
	fi
}
check_slice full "$(awk '/\*\*Job D-full\*\*/,/\*\*Job D-delta\*\*/' "$SKILL" | awk '/^```$/{n++} n==1')"
check_slice delta "$(awk '/\*\*Job D-delta\*\*/,0' "$SKILL" | awk '/^```$/{n++} n==1')"

if grep -qF 'before you edit a single file' "$SKILL"; then
	pass "record is pinned to BEFORE any edit (snapshot == what the reviewer saw)"
else
	fail "record ordering unpinned — fix-then-record silently drops those fixes from the next delta"
fi

if grep -qE 'first Job D pass of a precheck cycle ALWAYS uses the full prompt' "$SKILL"; then
	pass "first pass is explicitly ALWAYS full"
else
	fail "skill no longer states the first pass is always full"
fi

if grep -qE 'Record only on a parseable verdict' "$SKILL"; then
	pass "record is gated on a real verdict (not merely 'returned')"
else
	fail "skill may record an errored/timed-out pass as reviewed"
fi

# The delta prompt must hand the reviewer `git diff <ref>` — the form that
# compares a snapshot against the WORKING TREE. A two-dot `<ref>..HEAD` is the
# original #1194 bug: in a pre-commit gate it is always empty. The script cannot
# police the skill's prompt text, so it is asserted here, at the reintroduction
# site.
# The delta must be handed over as EMBEDDED CONTENT, not as a command for the
# reviewer to run. `feature-dev:code-reviewer` has no Bash tool, and the ref is
# a dangling `stash create` SHA that Read/Grep cannot reach — a reviewer told to
# fetch it reviews nothing and reports success. An earlier version of this test
# asserted the bare command string, which actively pinned the broken shape.

# SCOPED TO THE PROMPT BLOCK. A file-wide grep is satisfied by the explanatory
# blockquote above the prompt, which quotes the same command — so deleting the
# ### Diff channel outright, or reverting it to bare `git diff <base>`, left the
# suite green. Mutation-proven, twice. Same class as the `[^>]*` blind spot and
# the file-wide untracked count: a guard on a CRITICAL must read the artifact,
# not the prose describing it.
FULL_SLICE="$(awk '/\*\*Job D-full\*\*/,/\*\*Job D-delta\*\*/' "$SKILL" | awk '/^```$/{n++} n==1')"
if printf '%s' "$FULL_SLICE" | grep -qF '### Diff' &&
	printf '%s' "$FULL_SLICE" | grep -qF 'gather <repo_root> <marker_dir> <base>' &&
	printf '%s' "$FULL_SLICE" | grep -qF 'read ALL of these files'; then
	pass "Job D-full PROMPT gathers via the tested subcommand and demands full coverage"
else
	fail "Job D-full prompt lost its gather-based diff channel"
fi

# The delta prompt's channel needs the same artifact-scoped guard.
DELTA_SLICE="$(awk '/\*\*Job D-delta\*\*/,0' "$SKILL" | awk '/^```$/{n++} n==1')"
if printf '%s' "$DELTA_SLICE" | grep -qF 'gather <repo_root> <marker_dir> <ref>' &&
	printf '%s' "$DELTA_SLICE" | grep -qF 'read ALL these files'; then
	pass "Job D-delta PROMPT gathers via the tested subcommand"
else
	fail "Job D-delta prompt lost its gather-based diff channel"
fi

# The gather contract table must keep BOTH of its non-`files` rows. Deleting
# either leaves the agent with no defined behaviour for an empty or failed
# gather, which is where every silent-empty defect in this changeset lived.
if grep -qF 'empty 0 <path>' "$SKILL" && grep -qF 'STOP, do not dispatch' "$SKILL"; then
	pass "gather contract documents BOTH the empty and the exit-2 verdicts"
else
	fail "gather contract lost its empty/exit-2 rows — undefined behaviour on a failed gather"
fi

if grep -qF 'run `resolve` BEFORE `new-untracked`' "$SKILL"; then
	pass "resolve-before-new-untracked ordering is pinned"
else
	fail "ordering unpinned — new-untracked first returns a delta-scoped list under a full verdict"
fi

# A commit-range diff CANNOT contain the working tree, which is where a
# pre-commit gate's changeset lives. Measured on the #1194 branch:
# `git diff main...HEAD` = 0 bytes, `git diff $(merge-base)` = 61193 bytes.
# Two earlier versions of this test asserted the three-dot form was PRESENT,
# i.e. they pinned the broken shape and would have failed the correct fix.
# Scoped to the SUBSTITUTION line, not the whole file: the skill legitimately
# cites the three-dot form in its trap explanation ("Not git diff <base>...HEAD
# — this diff is EMPTY"), so a file-wide grep fires on correct prose. An
# earlier attempt used `<output of:[^>]*diff` which could never match, because
# [^>] terminates at the '>' inside "<repo_root>" — mutation-proven blind.
if grep -qE '^[[:space:]]*<output of:.*diff.*\.\.\.' "$SKILL"; then
	fail "a commit-range 'diff <base>...' appears — empty in a pre-commit gate"
else
	pass "full prompt embeds no commit-range (...) diff"
fi

# No bare command left as an instruction to the reviewer.
if grep -qE '^\s+Changes to review: git diff' "$SKILL"; then
	fail "a bare 'Changes to review: git diff …' command survives — the reviewer cannot run it"
else
	pass "no bare git command is left for the reviewer to execute"
fi

# The reviewer must NOT be told to restrict itself to the embedded diff. Reading
# beyond it is how the /devspec upshift emitter was caught — that file shared
# zero lines with the change.
# PER PROMPT. A file-wide match is satisfied while ONE prompt is diff-locked,
# because the other still carries the licence — the same prose-satisfiable
# class as the merge-base guard. Found by auditing every file-wide grep in this
# file after that class recurred a third time.
for slice_name in full delta; do
	if [[ "$slice_name" == full ]]; then
		SL="$(awk '/\*\*Job D-full\*\*/,/\*\*Job D-delta\*\*/' "$SKILL" | awk '/^```$/{n++} n==1')"
	else
		SL="$(awk '/\*\*Job D-delta\*\*/,0' "$SKILL" | awk '/^```$/{n++} n==1')"
	fi
	if printf '%s' "$SL" | grep -qiE 'Do not restrict yourself to the lines above|use them freely|use them\.'; then
		pass "Job D-$slice_name reviewer keeps its licence to read wider than the diff"
	else
		fail "Job D-$slice_name is diff-locked — cross-file stakeholders become invisible"
	fi
done

# Any `<placeholder>..HEAD` in the skill or the CHANGELOG must be there to
# DOCUMENT the trap, never to describe current behaviour. Both files cite it
# deliberately in their post-mortem paragraphs, so a blanket ban would fail on
# correct text; instead require trap/refusal language within a +/-3 line window,
# the same shape as the skip-review check below. An earlier version of this
# guard anchored on "git diff|Changes to review" appearing on the SAME line and
# was proven blind by a mutation that reintroduced the range in the CHANGELOG's
# prose without either word.
twodot_bad=0
for f in "$SKILL" "$REPO_DIR/CHANGELOG.md"; do
	while IFS= read -r hit; do
		[[ -n "$hit" ]] || continue
		ln="${hit%%:*}"
		if ! sed -n "$((ln > 3 ? ln - 3 : 1)),$((ln + 3))p" "$f" |
			grep -qiE 'trap|bug|caught|empty|never|do not|cannot|defect|wrong|post-mortem'; then
			fail "two-dot <placeholder>..HEAD at $f:$ln is not marked as the documented trap"
			twodot_bad=1
		fi
	done < <(grep -nE '<[a-z_]+>\.\.HEAD' "$f" || true)
done
if ((twodot_bad == 0)); then
	pass "every two-dot <placeholder>..HEAD is inside trap documentation, not a spec"
fi

if grep -qE 'A two-dot commit range cannot contain uncommitted work' "$SKILL"; then
	pass "the <prev>..HEAD trap is documented so it is not reintroduced"
else
	fail "the documented trap is gone — the empty-review bug can silently return"
fi

if grep -qE 'Jobs A, B, and C stay unscoped' "$SKILL"; then
	pass "Jobs A/B/C explicitly stay unscoped every pass"
else
	fail "no statement that A/B/C stay unscoped"
fi

# The tool now ships on PATH with the kit, so "absent" means the kit is not
# installed rather than "you are outside cc-workflow". The fallback still has
# to exist and still has to be concrete — an agent that improvises here pastes
# a diff that cannot survive the transport cap.
if grep -qF 'delta scoping unavailable — kit not installed' "$SKILL" &&
	grep -qF 'ls-files --others --exclude-standard' "$SKILL"; then
	pass "kit-not-installed fallback is documented AND concrete (inline gather recipe)"
else
	fail "no concrete fallback — an agent would improvise, most likely by pasting an untransportable diff"
fi

if grep -qE 'never a hardcoded .main.' "$SKILL"; then
	pass "Job D base is resolved, not a literal 'main'"
else
	fail "Job D may still hardcode 'main'"
fi

if grep -q 'prompt: "Review all files changed on the current branch vs main in' "$SKILL"; then
	fail "Job D-full prompt still says literal 'vs main'"
else
	pass "Job D-full prompt no longer hardcodes 'vs main'"
fi

# The adjacent bad idea: gating review on issue type/label. #1191 was labelled
# `chore`, self-declared "no test coverage needed", and shipped a real defect.
if grep -qE 'Issue type is self-reported \*intent\*' "$SKILL"; then
	pass "skill records why label-based gate-skipping is refused"
else
	fail "the 'do not gate on issue type' rationale is gone"
fi

for forbidden in 'skip review for doc' 'skip the code review for'; do
	if grep -qi "$forbidden" "$SKILL"; then
		if grep -niC2 "$forbidden" "$SKILL" | grep -qiE 'do not|never|refus|must not'; then
			pass "'$forbidden' appears only as a refused option"
		else
			fail "skill appears to permit skipping review: '$forbidden'"
		fi
	fi
done

echo ""
if ((FAILS > 0)); then
	echo "  $FAILS check(s) failed"
	exit 1
fi
echo "  all checks passed"
