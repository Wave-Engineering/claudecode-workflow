#!/usr/bin/env bash
# test_pmr_bench_arm.sh — #1195.
#
# HERMETIC BY CONSTRUCTION. This suite runs on every push via validate.sh, and
# the thing under test dispatches a model call that costs ~$3 and takes ~6
# minutes. So `claude` is replaced with a PATH shim that records its argv and
# prints a canned envelope. That is not a compromise: what needs asserting is
# how the harness COMPOSES the invocation and how it handles what comes back,
# and both are exactly what the shim exposes. The model's opinion is not under
# test here.
#
# The load-bearing cases:
#
#   Case 3 — Bash must NOT be in --allowedTools. If an arm can run git itself,
#            arm A reconstructs the diff its prompt failed to hand it, both arms
#            converge, and the bench reports "no difference" between a working
#            protocol and a broken one. That is the most expensive way for this
#            instrument to be wrong, and it would look like a clean result.
#
#   Case 4 — every directory the prompt names must be on the access list. The
#            first live run named a diff under the marker dir while only the
#            bubble was allowed, so the arm was told to read a file it could not
#            open. It does not fail loudly; it reviews nothing and says so with
#            confidence — the bench's own subject matter, reproduced inside the
#            bench.
#
#   Case 6 — a killed or empty run must NOT be recorded as a review. "No
#            findings" and "produced nothing" are the same string to a careless
#            parser and opposite facts to a bench.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
ARMRUN="$ROOT/scripts/ci/pmr-bench-arm.sh"
BUBBLE_SH="$ROOT/scripts/ci/pmr-timebubble.sh"
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

# --- A synthetic repo with one reconstructable changeset ----------------------
repo="$tmp/repo"
mkdir -p "$repo"
git -C "$repo" init -q -b main 2>/dev/null || git -C "$repo" init -q
git -C "$repo" config user.name "Fixture"
git -C "$repo" config user.email "fixture@example.invalid"
git -C "$repo" config commit.gpgsign false
git -C "$repo" config core.excludesFile /dev/null

printf 'alpha\nbeta\n' >"$repo/app.sh"
git -C "$repo" add -A
git -C "$repo" commit -q -m "feat: base"

printf 'alpha\nCHANGED\n' >"$repo/app.sh"
printf 'new\n' >"$repo/added.md"
git -C "$repo" add -A
git -C "$repo" commit -q -m "feat: the changeset"
CULPRIT="$(git -C "$repo" rev-parse HEAD)"

bubble="$tmp/bubble"
bash "$BUBBLE_SH" build "$CULPRIT" --into "$bubble" --repo "$repo" >/dev/null 2>&1 ||
	echo "  [WARN] bubble build failed; downstream cases will be meaningless" >&2

# --- The claude shim ----------------------------------------------------------
# Records argv verbatim, then emits a minimal but REAL envelope shape (the
# harness parses `.result`, so a stub that omitted it would test nothing).
shimdir="$tmp/bin"
mkdir -p "$shimdir"
cat >"$shimdir/claude" <<'SHIM'
#!/usr/bin/env bash
printf '%s\n' "$@" > "$SHIM_ARGV"
if [[ "${SHIM_MODE:-ok}" == "empty" ]]; then
	exit 0                       # exits clean, writes NOTHING to stdout
elif [[ "${SHIM_MODE:-ok}" == "killed" ]]; then
	exit 143
elif [[ "${SHIM_MODE:-ok}" == "noresult" ]]; then
	echo '{"total_cost_usd":0.01,"usage":{}}'
elif [[ "${SHIM_MODE:-ok}" == "iserror" ]]; then
	# Exits 0, carries real text, and says it failed. Without an is_error check
	# this is recorded as a scoreable review.
	echo '{"result":"Error: the session ran out of context.","is_error":true,"subtype":"error_max_turns","total_cost_usd":0.05,"usage":{}}'
elif [[ "${SHIM_MODE:-ok}" == "malformed" ]]; then
	printf '{"result": "truncated'          # valid prefix, invalid JSON
else
	echo '{"result":"## Findings\n\n### Important\n\n1. A finding.","total_cost_usd":0.42,"num_turns":3,"usage":{"input_tokens":10,"output_tokens":20,"cache_read_input_tokens":30}}'
fi
SHIM
chmod +x "$shimdir/claude"

# $ROOT/scripts is prepended so the resolution ladder's FIRST rung
# (`command -v precheck-review-scope.sh`) deterministically finds the REPO copy.
# Without it, a machine with the kit installed on PATH exercises the installed
# script while CI exercises the repo one -- different code, identical
# assertions, divergence invisible. Same shape as
# lesson_live_binary_not_repo_source.
run_arm() { # <arm> <outdir> ; env: SHIM_MODE
	SHIM_ARGV="$tmp/argv.txt" PATH="$shimdir:$ROOT/scripts:$PATH" \
		bash "$ARMRUN" "$1" --bubble "$bubble" --culprit "$CULPRIT" \
		--repo "$ROOT" --out "$2" >/dev/null 2>&1
}

# --- Case 1: both arms run and record a scoreable result ----------------------
echo "Case 1: both arms produce a scoreable record"
run_arm A "$tmp/outA"
check "0" "$?" "arm A exits 0"
run_arm B "$tmp/outB"
check "0" "$?" "arm B exits 0"
check "OK" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/outA/meta.tsv")" "arm A records status OK"
check "A" "$(awk -F'\t' '$1=="arm"{print $2}' "$tmp/outA/meta.tsv")" "meta names the arm"
check "0.42" "$(awk -F'\t' '$1=="cost_usd"{print $2}' "$tmp/outB/meta.tsv")" "cost is captured from the envelope"
check "yes" "$([[ -s "$tmp/outB/findings.txt" ]] && echo yes || echo no)" "the review text is written out"

# --- Case 2: the arms differ, and differ in the RIGHT way ---------------------
# If these two prompts ever converge, the bench has no independent variable.
echo "Case 2: the two arms send genuinely different prompts"
check "no" "$(cmp -s "$tmp/outA/prompt.txt" "$tmp/outB/prompt.txt" && echo yes || echo no)" "arm A and arm B prompts are not identical"
check "1" "$(grep -c 'vs main' "$tmp/outA/prompt.txt")" "arm A carries the pre-#1194 hardcoded 'vs main'"
check "0" "$(grep -c 'vs main' "$tmp/outB/prompt.txt")" "arm B does not"
check "1" "$(grep -c '### Diff' "$tmp/outB/prompt.txt")" "arm B carries a gathered Diff section"
check "1" "$(grep -c '### Untracked files' "$tmp/outB/prompt.txt")" "arm B carries the untracked channel"
check "0" "$(grep -c '### Untracked files' "$tmp/outA/prompt.txt")" "arm A does not — that absence IS the defect under test"

# --- Case 3: the RESTRICTING flag is used, not merely a permissive one --------
# The first version of this case asserted only that "Bash" was absent from argv,
# under the heading "no arm may hold a Bash tool". Those are different claims,
# and the gap between them was a live critical defect: the script passed
# `--allowedTools`, which is a PERMISSION list that removes nothing, so the arm
# kept Bash and both arms could converge. Measured from this repo:
#   --allowedTools <read-only set>  -> the model ran `echo` and returned stdout
#   --tools        <read-only set>  -> the model replied NOBASH
# A shim cannot prove the runtime effect, so the assertion must at least name
# the mechanism that HAS the effect. Absence of a string is not restriction.
echo "Case 3: the tool set is restricted by --tools, not just permitted"
check "1" "$(grep -cx -- '--tools' "$tmp/argv.txt")" "--tools (availability) is passed"
check "0" "$(grep -cx -- '--allowedTools' "$tmp/argv.txt")" "--allowedTools (permission only) is NOT relied on"
check "0" "$(grep -cx 'Bash' "$tmp/argv.txt")" "Bash is not in the tool set"
check "0" "$(grep -cx 'BashOutput' "$tmp/argv.txt")" "nor BashOutput"
check "0" "$(grep -cx 'KillShell' "$tmp/argv.txt")" "nor KillShell"
check "1" "$(grep -cx 'Read' "$tmp/argv.txt")" "Read IS granted — a restriction that blocked reading would be equally broken"

# --- Case 4: every directory the prompt names is reachable --------------------
# Asserted structurally rather than by name: whatever path the prompt points at
# must appear under --add-dir. A future edit that relocates the gathered diff
# cannot silently reintroduce the unreadable-file bug.
echo "Case 4: paths named in the prompt are on the access list"
mapfile -t added < <(awk '/^--add-dir$/{flag=1;next} /^--/{flag=0} flag' "$tmp/argv.txt")
check "yes" "$([[ ${#added[@]} -ge 2 ]] && echo yes || echo no)" "more than one directory is granted"
diffpath="$(grep -oE '/[^[:space:]]+/full\.diff' "$tmp/outB/prompt.txt" | head -1)"
reachable=no
for d in "${added[@]}"; do
	[[ -n "$diffpath" && "$diffpath" == "$d"* ]] && reachable=yes
done
check "yes" "$reachable" "the diff path named in arm B's prompt lies under a granted directory"

# --- Case 5: the evidence outlives the temp dir -------------------------------
echo "Case 5: what the arm was shown is preserved"
check "yes" "$([[ -s "$tmp/outB/shown/full.diff" ]] && echo yes || echo no)" "the gathered diff is copied into the run record"
check "no" "$([[ -d "$(dirname "$diffpath")" ]] && echo yes || echo no)" "and the marker dir it came from is cleaned up"

# --- Case 6: a run that produced nothing is NOT a review ----------------------
echo "Case 6: failure is never recorded as 'no findings'"
SHIM_MODE=empty run_arm B "$tmp/out-empty"
check "3" "$?" "an empty envelope exits 3"
check "FAILED" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/out-empty/meta.tsv")" "and records status FAILED"
check "no" "$([[ -f "$tmp/out-empty/findings.txt" ]] && echo yes || echo no)" "and writes no findings file"

SHIM_MODE=killed run_arm B "$tmp/out-killed"
check "3" "$?" "a killed run (rc 143) exits 3"
check "FAILED" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/out-killed/meta.tsv")" "and records status FAILED"

SHIM_MODE=noresult run_arm B "$tmp/out-noresult"
check "3" "$?" "a well-formed envelope with no result text exits 3"
check "FAILED" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/out-noresult/meta.tsv")" "and still writes a FAILED record — absence of meta.tsv is never legal"

SHIM_MODE=iserror run_arm B "$tmp/out-iserror"
check "3" "$?" "an envelope with is_error=true exits 3 even though it has result text"
check "FAILED" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/out-iserror/meta.tsv")" "and records FAILED"

SHIM_MODE=malformed run_arm B "$tmp/out-malformed"
check "3" "$?" "a malformed (non-JSON) envelope exits 3, not 1 with a traceback"
check "FAILED" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/out-malformed/meta.tsv")" "and records FAILED"

# --- Case 6b: a retry must not inherit the previous attempt's success ---------
# `mkdir -p` does not clear, so without an explicit wipe a timed-out retry into
# the same out dir leaves the prior findings.txt beside the new failure, reading
# as a successful run of the current attempt.
echo "Case 6b: a failed retry does not inherit stale artifacts"
run_arm B "$tmp/out-retry"
check "yes" "$([[ -s "$tmp/out-retry/findings.txt" ]] && echo yes || echo no)" "first attempt leaves findings"
SHIM_MODE=killed run_arm B "$tmp/out-retry"
check "no" "$([[ -f "$tmp/out-retry/findings.txt" ]] && echo yes || echo no)" "the retry's failure clears the prior findings"
check "FAILED" "$(awk -F'\t' '$1=="status"{print $2}' "$tmp/out-retry/meta.tsv")" "and the record reads FAILED, not OK"

# --- Case 6c: the untracked channel is cross-checked against git --------------
# Only arm B carries an untracked section, so a silent loss there weakens the
# arm under test asymmetrically. The harness refuses to dispatch rather than
# send a prompt that under-describes the changeset.
echo "Case 6c: an under-described untracked channel is fatal, not silent"
check "1" "$(grep -c 'added.md' "$tmp/outB/prompt.txt")" "the untracked file reached arm B's prompt"

# Force the mismatch the cross-check exists for. A REPO-level core.excludesFile
# is out of reach of the GIT_CONFIG_GLOBAL/SYSTEM pin, so `new-untracked` hides
# added.md while the harness's own `-c core.excludesFile=/dev/null` probe still
# sees it. Pre-fix this dispatched a prompt whose untracked section had silently
# gone empty; the arm would then review a changeset it was never fully shown and
# report confidently on the remainder.
printf 'added.md\n' >"$tmp/repo-ignore"
git -C "$repo" config core.excludesFile "$tmp/repo-ignore"
run_arm B "$tmp/out-mismatch"
check "3" "$?" "a narrowed untracked channel exits 3 rather than dispatching"
check "untracked-channel-mismatch" "$(awk -F'\t' '$1=="reason"{print $2}' "$tmp/out-mismatch/meta.tsv")" "and names the reason in the record"
check "no" "$([[ -f "$tmp/out-mismatch/findings.txt" ]] && echo yes || echo no)" "and no review is produced"
git -C "$repo" config --unset core.excludesFile
git -C "$repo" config core.excludesFile /dev/null

# --- Case 7: usage errors are loud --------------------------------------------
echo "Case 7: unusable input exits 2"
bash "$ARMRUN" C --bubble "$bubble" --culprit "$CULPRIT" --repo "$ROOT" --out "$tmp/o" >/dev/null 2>&1
check "2" "$?" "an unknown arm name exits 2"
bash "$ARMRUN" B --bubble "$tmp/nope" --culprit "$CULPRIT" --repo "$ROOT" --out "$tmp/o" >/dev/null 2>&1
check "2" "$?" "a non-existent bubble exits 2"
bash "$ARMRUN" B --bubble "$bubble" --culprit "$CULPRIT" --repo "$ROOT" --out >/dev/null 2>&1
check "2" "$?" "a flag with no argument exits 2"

# --- Result -------------------------------------------------------------------
echo ""
echo "test_pmr_bench_arm: $pass passed, $fail failed"
((fail == 0))
