#!/usr/bin/env bash
# szz-oracle.sh — deterministic bug-origin oracle over git history (SZZ).
#
# WHY THIS EXISTS (#1195). /precheck's Job D prompts cannot be hand-verified:
# a prompt is an interface with no type system and no execution, and its only
# failure signal is the reviewer replying "No findings" — indistinguishable from
# success. #1194 needed NINE adversarial review passes because of that. The only
# way to measure a review protocol is against real changesets with known
# outcomes, which means we need ground truth about which changeset introduced
# which defect. This produces that ground truth WITHOUT a model in the loop.
#
# THE METHOD (Śliwerski–Zimmermann–Zeller 2005). A bug-FIXING commit deletes the
# lines that were wrong. Blame those deleted lines in the fix's PARENT and you
# get the commit that wrote them — the bug-INTRODUCING commit. History labels
# itself; nobody hand-authors a rubric, so the labels cannot be argued with and
# cannot drift.
#
# WHY NO MODEL, DELIBERATELY. The consumer is a benchmark that grades model
# output. An oracle that itself asked a model would be grading a model with a
# model, and every result would inherit the grader's blind spots — precisely the
# self-grading failure the bench exists to avoid. It is also the standing
# constraint on this class of tooling: deterministic and CI-bakeable, never a
# prompt an agent may or may not follow.
#
# KNOWN LIMITS, MEASURED NOT ASSUMED (see docs, and `summary` output):
#   - A fix that only ADDS lines (a missing guard, a forgotten branch) deletes
#     nothing, so it has no blame trail and yields no culprit. This is inherent
#     to SZZ, not a bug here. `summary` reports the share it loses this way.
#   - Blame attributes a line to whoever last TOUCHED it, so a cosmetic reformat
#     between introduction and fix steals the attribution. `-w -M` suppresses
#     the whitespace and move cases; a genuine rewrite still shadows the origin.
#   - Blame attribution is stolen by a PROSE edit when a fix touches both code
#     and its documentation and the doc block is longer. Do NOT "fix" this by
#     excluding Markdown: in this repo skills/*/SKILL.md IS the artifact under
#     review, and a known-CORRECT attribution here is itself doc-dominated.
#
# CALIBRATED ACCURACY ON THIS REPO (docs/szz-oracle-calibration.md, 2026-08-30):
# yield 86%, raw precision 50%, and 67% after `fixtures` drops compound
# changesets — which is the number a consumer should plan against. Compound
# changesets are the largest single error source, and the only one that is
# mechanically removable. Recalibrate before trusting these numbers on any other
# repository; nothing here is portable except the method.
#
# Subcommands:
#   edges      TSV `fix<TAB>culprit<TAB>blamed_lines`, one row per attribution.
#              The raw primitive: no FIXTURE-SELECTION policy. It still applies
#              the four filters SZZ is defined by — non-merge commits, `fix`
#              subjects, modified files, and the excluded-path list — and reports
#              its denominators on stderr so none of them is a silent narrowing.
#   fixtures   TSV `fix<TAB>culprit<TAB>lines<TAB>age_days` — the pairs a bench
#              can actually use. This is where policy lives; exclusions are
#              counted on stderr, never silently dropped.
#   summary    Aggregate: oracle yield, culprit base rate, defect lifetime.
#   worksheet  Human-adjudication worksheet for a deterministic sample.
#
# Usage: szz-oracle.sh <edges|fixtures|summary|worksheet> [--since D] [--until D]
#                      [--repo DIR] [--limit N] [--stride K]
# Exit:  0 success; 2 unusable input.
set -euo pipefail

MODE="${1:-}"
shift || true

REPO="."
SINCE="12 months ago"
UNTIL=""
LIMIT=0
STRIDE=1

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo)
		REPO="$2"
		shift 2
		;;
	--since)
		SINCE="$2"
		shift 2
		;;
	--until)
		UNTIL="$2"
		shift 2
		;;
	--limit)
		LIMIT="$2"
		shift 2
		;;
	--stride)
		STRIDE="$2"
		shift 2
		;;
	*)
		echo "szz-oracle: unknown argument: $1" >&2
		exit 2
		;;
	esac
done

# Validate here rather than letting the value reach python's int() and surface as
# a traceback: the header promises "exit 2 unusable input", and a traceback is a
# different contract.
for numeric in "$LIMIT" "$STRIDE"; do
	if [[ ! "$numeric" =~ ^[0-9]+$ ]]; then
		echo "szz-oracle: --limit and --stride take a non-negative integer, got: $numeric" >&2
		exit 2
	fi
done

case "$MODE" in
edges | fixtures | summary | worksheet) ;;
*)
	echo "szz-oracle: usage: szz-oracle.sh <edges|fixtures|summary|worksheet> [--since D] [--repo DIR]" >&2
	exit 2
	;;
esac

cd "$REPO" || exit 2
git rev-parse --git-dir >/dev/null 2>&1 || {
	echo "szz-oracle: not a git repository: $REPO" >&2
	exit 2
}

log_args=(--no-merges --since="$SINCE")
[[ -n "$UNTIL" ]] && log_args+=(--until="$UNTIL")

# Bug-fixing commits, by SUBJECT.
#
# NOT `git log --grep='^fix'`. git matches the pattern line-by-line against the
# WHOLE message, body included — which is exactly why `--grep='^Signed-off-by'`
# is a standard idiom. This repo writes long prose bodies that reference other
# commits by their conventional-commit subject, so `^fix` enrols them: measured
# on this repo, it pulled in a `docs(harness):` commit whose body happened to
# carry a line beginning "fix". One wrong label in 144 is still a wrong label in
# an artifact whose entire value is that its labels cannot be argued with.
fix_commits() {
	git log "${log_args[@]}" --format='%H %s' |
		awk '$2 ~ /^fix[(:]/ { print $1 }'
}

# Files whose deleted lines carry no design intent — a blame hit here says
# nothing about who introduced a defect.
EXCLUDES=(':!*.lock' ':!*.svg' ':!*.png' ':!*.jpg' ':!*.ico' ':!*.min.js' ':!*.bundled.js')

# Emit `culprit_sha` once per deleted line of $1, by blaming the parent.
#
# Per-FILE, deliberately. Parsing a multi-file diff for `--- a/<path>` headers
# misreads a deleted line whose own content begins `-- ` (it renders as
# `--- ...` and captures the file cursor). Naming the file out of band makes
# that class impossible, and lets us skip everything before the first hunk.
blame_deleted_lines() {
	local fix="$1" f lines
	# `awk NF`, not `grep -v '^$'`: an add-only fix modifies no files, and grep
	# reports "no lines selected" as exit 1, which pipefail turns into a silent
	# whole-run abort. awk returns 0 on empty input.
	git show --format='' --name-only --diff-filter=M "$fix" -- "${EXCLUDES[@]}" |
		awk 'NF' | sort -u |
		while IFS= read -r f; do
			lines=$(
				git show --unified=0 --no-color --format='' --diff-filter=M "$fix" -- "$f" |
					awk '
						/^@@/ {
							inhunk = 1
							match($0, /-[0-9]+(,[0-9]+)?/)
							split(substr($0, RSTART + 1, RLENGTH - 1), a, ",")
							ln = a[1] + 0
							next
						}
						inhunk == 1 && /^-/ { print ln; ln++ }
					'
			)
			[[ -n "$lines" ]] || continue

			# One blame per file with many -L ranges, not one per line: on this
			# repo that is ~500 subprocesses instead of ~1500.
			local ranges=()
			while IFS= read -r l; do
				[[ "$l" -gt 0 ]] 2>/dev/null && ranges+=(-L "$l,$l")
			done <<<"$lines"
			[[ ${#ranges[@]} -gt 0 ]] || continue

			# A single out-of-range -L fails the whole batch and would silently
			# drop every line in the file, so fall back to per-line on failure
			# rather than accept a quiet under-count.
			if ! git blame -w -M --line-porcelain "${ranges[@]}" "$fix^" -- "$f" 2>/dev/null |
				grep -oE '^[0-9a-f]{40}'; then
				while IFS= read -r l; do
					git blame -w -M --line-porcelain -L "$l,$l" "$fix^" -- "$f" 2>/dev/null |
						grep -oE '^[0-9a-f]{40}' | head -1 || true
				done <<<"$lines"
			fi
		done
}

emit_edges() {
	local fix n_fix=0
	while IFS= read -r fix; do
		n_fix=$((n_fix + 1))
		blame_deleted_lines "$fix" |
			sort | uniq -c | sort -rn |
			awk -v fix="$fix" '{ print fix "\t" $2 "\t" $1 }'
	done < <(fix_commits)

	# Report the denominator even when it is zero. An empty stdout with exit 0
	# is indistinguishable from "scanned everything, found nothing" — the same
	# empty-denominator pass this repo removed from its dependency gate.
	if [[ "$n_fix" -eq 0 ]]; then
		echo "szz-oracle: no fix commits in window (since=$SINCE until=${UNTIL:-now}) — nothing scanned" >&2
	else
		echo "szz-oracle edges: scanned $n_fix fix commit(s)" >&2
	fi
}

case "$MODE" in
edges)
	emit_edges
	;;
summary | worksheet | fixtures)
	# mktemp, and the trap installed BEFORE the first write: `emit_edges` runs
	# under errexit, so an abort between the redirects and a later trap would
	# leak every file. A predictable $$-suffixed name in a shared /tmp is also
	# a collision another user can create ahead of us.
	work="$(mktemp -d)" || exit 2
	trap 'rm -rf "$work"' EXIT
	emit_edges >"$work/edges"
	git log "${log_args[@]}" --format='%H %ct %s' >"$work/universe"
	fix_commits >"$work/fixes"
	python3 "$(dirname "$0")/szz_report.py" "$MODE" \
		"$work/edges" "$work/universe" "$work/fixes" \
		"$LIMIT" "$STRIDE"
	;;
esac
