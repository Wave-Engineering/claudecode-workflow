#!/usr/bin/env bash
# test_kahuna_presync_runbook.sh — #851/ENG-8: the kahuna↔release pre-sync RUNBOOK.
#
# Picked up by scripts/ci/validate.sh's "Regression tests" loop (tests/regression/*.sh).
# Doc-only deliverable, so this pins the runbook's CONTRACT, not engine behavior:
#   1. the runbook exists and carries the load-bearing content (pre-sync + safety check +
#      reactive-unblock variant + the explicit "engine fix tracked elsewhere — hands-off" note),
#   2. it is cross-linked from the wave operator guide,
#   3. its bash example snippets PARSE (bash -n) after substituting the <release>/<kahuna>
#      placeholders — so the documented commands can't rot into syntax errors,
#   4. the engine was NOT patched for ENG-8 in this repo (the hands-off constraint).

set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
DOC="$REPO_DIR/docs/operations/kahuna-release-presync.md"
GUIDE="$REPO_DIR/docs/kahuna-guide.md"
fail=0

echo "test_kahuna_presync_runbook"
echo "──────────────────────────────────────────"

check() { # $1=description $2=condition-already-evaluated (0 pass / nonzero fail)
	if [[ "$2" -eq 0 ]]; then echo "  [PASS] $1"; else echo "  [FAIL] $1"; fail=1; fi
}

# 1. exists
[[ -f "$DOC" ]]; check "runbook exists (docs/operations/kahuna-release-presync.md)" $?

if [[ -f "$DOC" ]]; then
	# content: pre-sync + the -X ours merge + the safety check + reactive-unblock variant
	grep -qiE "pre-?sync" "$DOC"; check "documents the pre-sync workaround" $?
	grep -qE "merge -X ours" "$DOC"; check "shows the 'git merge -X ours' superset merge" $?
	grep -qiE "safety check" "$DOC"; check "documents the safety check (kahuna ⊇ release)" $?
	grep -qE 'HEAD\.\.origin/<release>' "$DOC"; check "safety check verifies no release commits are missing" $?
	grep -qiE "reactive" "$DOC"; check "documents the reactive-unblock variant" $?
	grep -qiE "no_merge_result_pr" "$DOC"; check "names the observed symptom (no_merge_result_pr)" $?
	# the load-bearing hands-off note: engine fix tracked elsewhere, do NOT patch the engine here
	grep -qiE "tracked (elsewhere|separately)" "$DOC" && grep -qiE "do ?not.*(patch|engine)" "$DOC"
	check "explicit 'engine fix tracked elsewhere — do NOT patch the engine here' note" $?

	# 3. every ```bash fenced block parses under bash -n (with placeholders substituted).
	block_err=0 nblocks=0
	while IFS= read -r block; do
		:
	done < <(true)
	# Extract fenced bash blocks and bash -n each. awk emits blocks separated by a NUL-ish marker.
	tmpdir="$(mktemp -d)"
	awk '
		/^```bash$/ {inblk=1; n++; fn=sprintf("blk%03d.sh", n); next}
		/^```$/     {if (inblk){inblk=0}; next}
		inblk {print > (dir "/" fn)}
	' dir="$tmpdir" "$DOC"
	shopt -s nullglob
	for f in "$tmpdir"/blk*.sh; do
		nblocks=$((nblocks + 1))
		# Substitute the doc placeholders so the snippet is valid shell to parse.
		sed -e 's/<release>/release/g' -e 's/<kahuna>/kahuna/g' -e 's/<sha>/deadbee/g' "$f" >"$f.subst"
		if ! bash -n "$f.subst" 2>/dev/null; then
			echo "      bash -n failed on extracted block: $f"
			block_err=1
		fi
	done
	rm -rf "$tmpdir"
	[[ $nblocks -gt 0 && $block_err -eq 0 ]]
	check "all $nblocks bash example blocks parse (bash -n, placeholders substituted)" $?
fi

# 2. cross-linked from the operator guide
grep -qE "operations/kahuna-release-presync\.md" "$GUIDE"; check "cross-linked from docs/kahuna-guide.md" $?

# 4. hands-off: no ENG-8 engine patch landed in the per-wave engine source.
#    (Guard the constraint: the runbook is the ONLY thing that should reference this workaround
#    in an engine file. The engine JS must not gain a presync/ENG-8 code path in this repo.)
if grep -rniE "presync|pre-sync .*kahuna" "$REPO_DIR/skills/nextwave"/*.js 2>/dev/null | grep -viE "runbook|docs/operations"; then
	echo "  [FAIL] an ENG-8 pre-sync code path appears in the engine — the fix is HANDS-OFF here"
	fail=1
else
	echo "  [PASS] no ENG-8 pre-sync engine patch in skills/nextwave/*.js (hands-off honored)"
fi

echo "──────────────────────────────────────────"
if [[ $fail -eq 0 ]]; then
	echo "  ALL PASS"
	exit 0
fi
echo "  FAILURES"
exit 1
