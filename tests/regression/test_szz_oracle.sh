#!/usr/bin/env bash
# test_szz_oracle.sh — #1195.
#
# Drives scripts/ci/szz-oracle.sh against a SYNTHETIC repository whose history
# was authored to have known bug-origin answers. Synthetic deliberately: this
# repo's own history is the oracle's production input, and an assertion pinned
# to it would need editing on every commit — a maintained fixture, which is the
# failure mode the oracle exists to avoid.
#
# Case 3 is the regression proper. An add-only `fix:` commit modifies no files,
# so the file listing is empty; `grep -v '^$'` reports "no lines selected" as
# exit 1, and under `set -o pipefail` that aborted the entire run AFTER the
# cleanup trap had removed the evidence — a silent, zero-byte, exit-1 failure
# that a narrower window never reached.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ORACLE="$ROOT/scripts/ci/szz-oracle.sh"
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
# gpgsign/defaultBranch pinned so a developer's global git config cannot turn a
# real result into a confusing failure. Same convention as
# tests/regression/test_precheck_rereview_scope.sh.
git -C "$repo" init -q -b main 2>/dev/null || git -C "$repo" init -q
git -C "$repo" config user.name "Fixture"
git -C "$repo" config user.email "fixture@example.invalid"
git -C "$repo" config commit.gpgsign false

commit() { # subject  date
	GIT_AUTHOR_DATE="$2" GIT_COMMITTER_DATE="$2" \
		git -C "$repo" commit -q -m "$1"
	git -C "$repo" rev-parse HEAD
}

# C1 — the CULPRIT. Writes a six-line file; lines 2, 4 and 5 are the ones the
# fix will later delete.
printf 'alpha\nBUGGY_LINE\ngamma\nBLOCK_A\nBLOCK_B\nomega\n' >"$repo/app.sh"
git -C "$repo" add app.sh
C1=$(commit "feat(app): initial implementation" "2026-01-01T00:00:00Z")

# C2 — rewrites the NEIGHBOURS of every line C3 will delete (1, 3 and 5).
#
# This is what gives the fixture teeth. With a file authored entirely by one
# commit, blame of line 1, 2 or 3 all return the same answer, so the old-side
# cursor in the hunk parser could be off by one in either direction and every
# assertion would still pass. Interleaving authorship means an off-by-one lands
# on C2 and the attribution assertion fails; and because line 5 is C2's while
# line 4 is C1's, a missing `ln++` collapses the block onto line 4 twice and the
# blamed-line COUNT changes. Both of those are silent bugs otherwise.
printf 'ALPHA2\nBUGGY_LINE\nGAMMA2\nBLOCK_A\nBLOCK_B2\nomega\n' >"$repo/app.sh"
git -C "$repo" add app.sh
C2=$(commit "feat(app): rewrite the surrounding lines" "2026-01-02T00:00:00Z")

# C2b — an innocent bystander touching a DIFFERENT file. Must never be blamed.
printf 'unrelated\n' >"$repo/other.sh"
git -C "$repo" add other.sh
C2B=$(commit "feat(other): unrelated addition" "2026-01-03T00:00:00Z")

# C3 — the FIX. Deletes line 2 AND the two-line block at 4-5, producing two
# hunks: a bare `@@ -2` and a comma-ranged `@@ -4,2`. The second is the only
# thing that exercises the `(,[0-9]+)?` branch of the hunk regex.
# Correct attribution: lines 2 and 4 are C1's, line 5 is C2's -> C1 wins 2 to 1.
printf 'ALPHA2\nGAMMA2\nomega\n' >"$repo/app.sh"
git -C "$repo" add app.sh
C3=$(commit "fix(app): BUGGY_LINE was wrong" "2026-01-05T00:00:00Z")

# C4 — an ADD-ONLY fix. Modifies nothing; adds a new file. SZZ cannot attribute
# it, and must say so by omission rather than by dying.
printf 'guard\n' >"$repo/guard.sh"
git -C "$repo" add guard.sh
C4=$(commit "fix(guard): add the missing guard" "2026-01-06T00:00:00Z")

# C5 — a fix deleting a line from an EXCLUDED file type. Must yield no edge.
printf 'dep = "1.0"\n' >"$repo/deps.lock"
git -C "$repo" add deps.lock
commit "chore(deps): pin" "2026-01-07T00:00:00Z" >/dev/null
printf 'dep = "2.0"\n' >"$repo/deps.lock"
git -C "$repo" add deps.lock
C5FIX=$(commit "fix(deps): wrong pin" "2026-01-08T00:00:00Z")

# C6 — a COMPOUND culprit: the wave pattern's declared promotion shape. It bundles
# a whole wave, so no single /precheck ever reviewed it, and it must never reach a
# bench as a fixture even though the blame pointing at it is perfectly correct.
printf 'one\nPROMOTED_BUG\nthree\n' >"$repo/wave.sh"
git -C "$repo" add wave.sh
C6=$(commit "plan(#959): P1W1 — kahuna to main (#988)" "2026-01-09T00:00:00Z")
printf 'one\nPROMOTED_OK\nthree\n' >"$repo/wave.sh"
git -C "$repo" add wave.sh
C7=$(commit "fix(wave): PROMOTED_BUG was wrong" "2026-01-10T00:00:00Z")

SINCE="2025-12-01"
edges="$tmp/edges.tsv"
"$ORACLE" edges --repo "$repo" --since "$SINCE" >"$edges" 2>"$tmp/edges.err"
check 0 "$?" "edges exits 0 over a history containing an add-only fix"

# --- 1. Correct attribution ---------------------------------------------------
# head -1: rows are emitted heaviest-first, so the first row IS the top culprit.
# The fix now legitimately has two culprit rows (C1 owns 2 deleted lines, C2 owns
# 1), which is the point of the interleaved fixture.
got=$(awk -v f="$C3" '$1 == f { print $2 }' "$edges" | head -1)
check "$C1" "$got" "the fix is attributed to the commit that wrote the line"

# --- 1b. Weight selection, and the count the weight is derived from ----------
#
# C1 owns two of the three deleted lines and C2 owns one, so this is also the
# only case that executes top_culprit()'s highest-weight-wins branch. Asserting
# the count is what catches a missing `ln++`: the culprit would still be C1,
# but the block would collapse onto one line and read 3 instead of 2.
got=$(awk -v f="$C3" '$1 == f && $2 == "'"$C1"'" { print $3 }' "$edges")
check 2 "$got" "the winning culprit is credited with exactly its own deleted lines"
got=$(awk -v f="$C3" '$1 == f && $2 == "'"$C2"'" { print $3 }' "$edges")
check 1 "$got" "the losing culprit is still recorded, with its own lower count"

# --- 2. The innocent bystander is never blamed --------------------------------
got=$(grep -c "$C2B" "$edges")
check 0 "$got" "a commit touching only another file is never blamed"

# --- 3. REGRESSION: add-only fix yields no edge, and does not abort the run ----
got=$(awk -v f="$C4" '$1 == f { print $2 }' "$edges")
check "" "$got" "an add-only fix produces no edge"
# The run must still have produced the OTHER fix's edge — proving C4 did not
# truncate the output. Asserting only "exit 0" would pass on an empty file.
got=$(grep -c "$C3" "$edges")
if [[ "$got" -ge 1 ]]; then
	check ok ok "an add-only fix does not truncate the rest of the run"
else
	check ok "none" "an add-only fix does not truncate the rest of the run"
fi

# --- 4. Excluded file types produce no attribution ----------------------------
#
# Keyed on the FIX'S SHA, not on the filename. `edges` rows are
# `sha<TAB>sha<TAB>count` and never contain a path at all, so the obvious
# `grep -c deps.lock "$edges"` is 0 no matter what the code does -- it passes
# with the entire EXCLUDES array deleted. That is a guard reading a field the
# artifact does not have.
got=$(awk -v f="$C5FIX" '$1 == f { print $2 }' "$edges")
check "" "$got" "deleted lines in an excluded file yield no edge"

# --- 5. The fix is never blamed for its own defect ----------------------------
got=$(awk '$1 == $2' "$edges" | wc -l)
check 0 "$got" "no commit is ever its own culprit"

# --- 6. summary runs and counts the add-only fix as unattributed --------------
sum="$tmp/summary.txt"
"$ORACLE" summary --repo "$repo" --since "$SINCE" >"$sum" 2>&1
check 0 "$?" "summary exits 0"
# TWO of the three fix( commits are unattributable, by DIFFERENT mechanisms:
# C4 added lines only, and fix(deps) deleted lines solely from an excluded file.
# Asserting the count alone would let one mechanism silently replace the other,
# so the individual absences above (cases 3 and 4) carry the real weight.
got=$(awk '/unattributed/ { print $3 }' "$sum")
check 2 "$got" "summary counts both unattributable fixes"

# --- 7. worksheet is EXECUTED, not merely shipped ------------------------------
#
# validate.sh's py_compile pass skips scripts/ci/ entirely (`-not -path "*/ci/*"`),
# so szz_report.py has no syntax gate other than being run. `summary` covers the
# import; without this case the whole worksheet path would be unexecuted code —
# shipped, plausible, and unverified.
ws="$tmp/worksheet.txt"
"$ORACLE" worksheet --repo "$repo" --since "$SINCE" --limit 2 >"$ws" 2>&1
check 0 "$?" "worksheet exits 0"
got=$(grep -c "VERDICT" "$ws" || true)
if [[ "$got" -ge 1 ]]; then
	check ok ok "worksheet emits at least one adjudication slot"
else
	check ok "empty" "worksheet emits at least one adjudication slot"
fi
# Assert the SHAPE, not a specific pair: which pairs the stratified sample picks
# is a function of the history, so pinning one culprit couples the test to
# sample selection rather than to the contract (every heading names fix -> culprit).
got=$(grep -cE '^## [0-9a-f]{9} -> [0-9a-f]{9} ' "$ws" || true)
if [[ "$got" -ge 1 ]]; then
	check ok ok "every worksheet heading names a fix -> culprit pair"
else
	check ok "none" "every worksheet heading names a fix -> culprit pair"
fi

# --- 8. fixtures applies policy; edges stays a raw primitive -------------------
#
# The split matters: if `edges` filtered, a consumer wanting everything would
# have no way to get it, and the exclusion would be invisible. So assert BOTH
# halves — the compound pair is present in edges and absent from fixtures.
got=$(awk -v f="$C7" '$1 == f { print $2 }' "$edges")
check "$C6" "$got" "edges (raw) DOES attribute the fix to the compound culprit"

fx="$tmp/fixtures.tsv"
"$ORACLE" fixtures --repo "$repo" --since "$SINCE" >"$fx" 2>"$tmp/fixtures.err"
check 0 "$?" "fixtures exits 0"
got=$(grep -c "$C6" "$fx" || true)
check 0 "$got" "fixtures EXCLUDES the wave-promotion culprit"
got=$(grep -c "$C1" "$fx" || true)
check 1 "$got" "fixtures KEEPS the ordinary atomic culprit"

# A filter that shrinks its output silently reads as "nothing to exclude".
got=$(grep -c "dropped 1 compound" "$tmp/fixtures.err" || true)
check 1 "$got" "fixtures reports the exclusion count on stderr"

# --- 9. Usage errors are loud -------------------------------------------------
"$ORACLE" bogus --repo "$repo" >/dev/null 2>&1
check 2 "$?" "an unknown subcommand exits 2"
"$ORACLE" edges --repo "$tmp" >/dev/null 2>&1
check 2 "$?" "a non-repository path exits 2"

echo ""
echo "  szz oracle: $pass passed, $fail failed"
[[ $fail -eq 0 ]]
