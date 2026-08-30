#!/usr/bin/env bash
# precheck-review-scope.sh — decide what a /precheck Job D pass must review.
#
# WHY THIS IS A SCRIPT AND NOT PROSE IN skills/precheck/SKILL.md (#1194).
#
# The first cut of #1194 wrote this logic as a bash block inside the skill and
# had the regression test assert against a hand-typed COPY of it. Code review
# caught that the copy and the skill could drift apart silently — and, worse,
# that the logic itself was wrong in a way the copy faithfully reproduced. One
# implementation, invoked by both the skill and the test, is the fix for both.
#
# THE BUG THAT MOTIVATES THE DESIGN — read before "simplifying" this.
#
# /precheck is a PRE-COMMIT gate ("Does NOT commit/push/PR"); /scp commits
# afterwards. So the code under review lives in the WORKING TREE, and HEAD does
# NOT move between Job D passes. The obvious implementation — record
# `rev-parse HEAD`, re-review `$prev..HEAD` — therefore degrades to:
#
#     prev == HEAD  ->  `git merge-base --is-ancestor` returns 0 (ancestry is
#                       reflexive, so no guard fires)
#                   ->  `git diff $prev..HEAD` is EMPTY
#                   ->  pass 2 reviews nothing, reports success, fix ships
#
# That is not an edge case; it is every non-committing precheck cycle, i.e. all
# of them. A two-dot commit range can never contain uncommitted work.
#
# So we snapshot the reviewed STATE, not the reviewed COMMIT:
#   - `git stash create` writes a commit object for the tracked working tree
#     WITHOUT mutating the tree, index, or stash list. Empty output = clean tree.
#   - `git diff <snapshot>` then compares that snapshot against the CURRENT
#     working tree, so it picks up both new commits and uncommitted fixes.
#   - `stash create` does not capture untracked files, so those are recorded
#     separately and diffed by name.
#
# Exit status is not the channel; stdout is. `resolve` always prints exactly one
# verdict line and exits 0 unless it was called wrongly, because a non-zero exit
# inside an agent's `if` is easy to swallow, and the fail-safe must be loud:
#
#     full            -> review the whole <base>...HEAD diff (the safe default)
#     delta <ref>     -> review `git diff <ref>` plus any new-untracked list
#
# EVERY unresolvable condition resolves to `full`. Missing marker, empty marker,
# garbage marker, a snapshot object that has been gc'd, a rewritten history:
# all of them mean "we cannot prove what was reviewed", and the only safe
# response to that is to review everything again. `full` is never a failure —
# it is this script working correctly. There is no code path that yields
# "review nothing".

set -euo pipefail

usage() {
	cat <<'EOF'
Usage: precheck-review-scope.sh <command> <repo_root> <marker_dir>

Commands:
  reset     Clear any recorded state. Call ONCE at the start of every precheck
            cycle, before the first Job D pass, so pass 1 is mechanically full
            rather than full-by-convention.
  record    Record the current working-tree state as reviewed. Call ONLY after
            a Job D pass returned a parseable verdict (a findings list or the
            literal "No findings"). Never after an error, refusal, timeout, or
            empty return — on any of those, call `reset` instead.
  resolve   Print the scope for the NEXT pass: "full" or "delta <ref>".
  gather    Write the diff to disk and print how to hand it over. Takes a
            fourth arg: the diff target (a <base> branch name for a full pass,
            or the <ref> printed by `resolve` for a delta). NEVER pipes the
            diff through stdout — the Bash tool caps output at ~30k characters,
            so a 30-100KB diff was being truncated by the TRANSPORT before any
            size guard could see it. Prints either "inline <path>" (small
            enough to paste) or "split <n_lines> <path>..." (read all parts).
            Exits 2 with a reason on stderr if the target will not resolve.
  new-untracked
            Print untracked paths that appeared OR CHANGED since the recorded
            pass (all of them when there is no recorded pass). Run AFTER
            `resolve`, never before — resolve's `full` verdict is what clears
            the markers that make this re-widen. Never returns empty on error:
            it prints an UNRESOLVABLE sentinel plus every untracked path,
            because empty output reads as "there are none".
EOF
}

cmd="${1:-}"
repo="${2:-}"
marker_dir="${3:-}"

if [[ -z "$cmd" || -z "$repo" || -z "$marker_dir" ]]; then
	usage >&2
	exit 2
fi

if [[ ! -d "$repo/.git" ]] && ! git -C "$repo" rev-parse --git-dir >/dev/null 2>&1; then
	echo "not a git repository: $repo" >&2
	exit 2
fi

# Unique per invocation. Any path we cannot faithfully describe gets keyed on
# this, so it NEVER compares equal across two runs and is always surfaced. A
# constant sentinel (the first cut used a bare "UNHASHABLE") compares equal to
# itself, which silently marked such a path as reviewed — the exact inversion of
# the intent.
RUN_NONCE="$$-${EPOCHREALTIME:-$(date +%s%N 2>/dev/null || date +%s)}"

# The marker dir MUST live outside the repo. Inside it, the markers become
# untracked files that `list_untracked` reports and `record` records — so the
# reviewer is handed the marker files themselves as "new code to read in full"
# on every pass. (An earlier version of this comment blamed `/scp`'s
# `git add -A`; that is wrong — skills/scp/SKILL.md forbids `git add -A`
# explicitly. The guard is still right, the stated reason was not.)
# The rule was prose-only; enforce it where this project's own philosophy says
# logic belongs — in the tool.
mkdir -p "$marker_dir" 2>/dev/null || true
_rr="$(cd "$repo" 2>/dev/null && pwd -P)" || _rr=""
_md="$(cd "$marker_dir" 2>/dev/null && pwd -P)" || _md=""
if [[ -n "$_rr" && -n "$_md" ]]; then
	case "$_md/" in
	"$_rr"/*)
		echo "marker_dir must be OUTSIDE repo_root (got: $_md under $_rr)" >&2
		exit 2
		;;
	esac
fi

STATE="$marker_dir/precheck-reviewed-state"
UNTRACKED="$marker_dir/precheck-reviewed-untracked"

# Untracked files, as "<blob-hash> <path>" lines.
#
# The hash is load-bearing, not decoration. Recording NAMES only left a hole in
# exactly the same class as the bug this script exists to fix: an untracked file
# that exists at `record` time and is EDITED before the next pass is invisible in
# both channels — `git diff <snapshot>` never shows untracked paths, and a
# name-only set difference sees its name on both sides. Its fix would never be
# read. That is not exotic: /precheck is a pre-commit gate and /scp does the
# `git add`, so every NEW file is untracked for the whole cycle.
#
# A path that cannot be hashed (deleted mid-run, unreadable, dangling symlink)
# emits a sentinel rather than being skipped, so it reads as changed and gets
# surfaced. Failing toward "show it to the reviewer" is the only safe direction.
list_untracked() {
	(
		cd "$repo" 2>/dev/null || return 0
		git ls-files --others --exclude-standard -z |
			while IFS= read -r -d '' f; do
				# Newlines/CRs in a path would split one record across lines,
				# which breaks the line-oriented `comm` below — observed live as
				# "comm: input is not in sorted order", i.e. undefined behaviour
				# in a safety path. Escape them so every record stays exactly one
				# line. Content changes are still caught, because the key is
				# computed from the real file, not the escaped name.
				esc="${f//\\/\\\\}"
				esc="${esc//$'\n'/\\n}"
				esc="${esc//$'\r'/\\r}"

				if [[ -L "$f" ]]; then
					# git stores a symlink's TARGET STRING, but `hash-object`
					# FOLLOWS the link and hashes the target's content — so
					# repointing a link between two same-content files was
					# invisible (verified). Key on the target instead.
					#
					# The target is HASHED rather than interpolated raw: it is a
					# second variable-width field on a space-delimited line, so a
					# target containing a space made `SYMLINK:a b c` ambiguous
					# between (target "a", path "b c") and (target "a b", path
					# "c") — a real same-key/different-state collision — and
					# `cut -d' ' -f2-` then handed the reviewer a path that does
					# not exist. A target containing a newline reopened the
					# record-splitting bug the path escaping closes. Hashing
					# makes the column fixed-width; both classes become
					# impossible rather than merely unlikely.
					lnk="$(readlink -- "$f" 2>/dev/null)" || lnk=""
					lnk_key=""
					if [[ -n "$lnk" ]]; then
						lnk_key="$(printf '%s' "$lnk" | git hash-object --stdin 2>/dev/null)" || lnk_key=""
					fi
					[[ -n "$lnk_key" ]] || lnk_key="UNREADABLE-$RUN_NONCE"
					printf 'SYMLINK:%s %s\n' "$lnk_key" "$esc"
				elif [[ -f "$f" ]]; then
					h="$(git hash-object -- "$f" 2>/dev/null)" || h=""
					[[ -n "$h" ]] || h="UNHASHABLE-$RUN_NONCE"
					# The exec bit is the one mode bit git records, so `chmod +x`
					# changes what `git add` commits. Content-only keying missed
					# it — load-bearing in a repo that is mostly shell scripts.
					[[ -x "$f" ]] && h="${h}+x"
					printf '%s %s\n' "$h" "$esc"
				else
					# FIFO/socket/device. NEVER hash these: `git hash-object` on a
					# FIFO blocks until a writer appears, which would hang the
					# gate with no output at all. Nonced, so it always reads as
					# changed rather than as reviewed.
					printf 'NONREGULAR-%s %s\n' "$RUN_NONCE" "$esc"
				fi
			done
	) | LC_ALL=C sort
}

case "$cmd" in
reset)
	rm -f "$STATE" "$UNTRACKED"
	;;

record)
	mkdir -p "$marker_dir"
	# `stash create` snapshots tracked changes without touching the tree or the
	# stash list. On a clean tree it prints nothing — fall back to HEAD, which
	# is then an accurate description of "what the reviewer saw".
	snap="$(git -C "$repo" stash create 2>/dev/null || true)"
	if [[ -z "$snap" ]]; then
		snap="$(git -C "$repo" rev-parse HEAD 2>/dev/null || true)"
	fi
	if [[ -z "$snap" ]]; then
		# Unborn branch, or git refused. Record nothing rather than something
		# untrue; `resolve` will correctly say full.
		rm -f "$STATE" "$UNTRACKED"
		exit 0
	fi
	# Staged through temp files so a failed `list_untracked` cannot truncate a
	# live marker. NOT atomic across the pair — two `mv`s are two operations.
	# The untracked set is moved into place FIRST so an interruption pairs an
	# older snapshot with a newer untracked list, i.e. over-reports; the window
	# is two renames in one directory right after a completed review.
	list_untracked >"$UNTRACKED.tmp"
	printf '%s\n' "$snap" >"$STATE.tmp"
	mv -f "$UNTRACKED.tmp" "$UNTRACKED"
	mv -f "$STATE.tmp" "$STATE"
	;;

resolve)
	# Every `full` verdict CLEARS the markers before printing. `resolve` used to
	# be a pure read, so a mid-cycle fall-back to full (gc'd snapshot, rewritten
	# history, corrupt marker) left `new-untracked` still narrowing against a
	# marker the verdict had just declared untrustworthy: a full tracked diff
	# paired with a delta-scoped untracked list. The header's law is that every
	# unresolvable condition resolves to full — that has to mean full on BOTH
	# channels, or the bookkeeping again asserts coverage no pass provided.
	verdict_full() {
		rm -f "$STATE" "$UNTRACKED"
		echo full
		exit 0
	}
	prev=""
	[[ -f "$STATE" ]] && prev="$(tr -d '[:space:]' <"$STATE" 2>/dev/null || true)"

	if [[ -z "$prev" ]]; then
		verdict_full
	fi

	# The recorded object must still exist and still be a commit. A `stash
	# create` snapshot is unreferenced, so it is gc-eligible; a long gap between
	# passes can collect it. Missing object -> we cannot prove what was
	# reviewed -> full.
	if ! git -C "$repo" cat-file -e "${prev}^{commit}" 2>/dev/null; then
		verdict_full
	fi

	# A snapshot identical to the current state means nothing changed since the
	# last review. There is nothing to re-review, but "delta over an empty diff"
	# is indistinguishable from "reviewed nothing", so refuse to emit it: say
	# full and let the reviewer confirm the tree it is actually looking at.
	if git -C "$repo" diff --quiet "$prev" 2>/dev/null &&
		diff -q <(list_untracked) "$UNTRACKED" >/dev/null 2>&1; then
		verdict_full
	fi

	# Refuse a delta whose channels are BOTH empty. Deleting an untracked file
	# makes the untracked lists differ (so the equality short-circuit above does
	# not fire) while `git diff <prev>` stays empty and `comm -13` yields
	# nothing — a vacuous pass that would then be recorded as a completed
	# review. Nothing unreviewed can ship from it, but the law at the top of
	# this file says no path yields "review nothing".
	if git -C "$repo" diff --quiet "$prev" 2>/dev/null &&
		[[ -z "$("$0" new-untracked "$repo" "$marker_dir" 2>/dev/null)" ]]; then
		verdict_full
	fi

	printf 'delta %s\n' "$prev"
	;;

gather)
	# Everything here was prose-bash in the skill and was wrong twice: `split`
	# does not create its destination directory (so the anti-truncation path
	# failed 100% of the time), and the 100KB threshold sat ABOVE the Bash
	# tool's ~30k output cap, so the transport truncated the diff before the
	# guard fired. Prose-bash that nobody executes will be wrong. This is
	# executed by the regression suite.
	target="${4:-}"
	if [[ -z "$target" ]]; then
		echo "gather requires a 4th arg: <base> or the <ref> from resolve" >&2
		exit 2
	fi

	# A full pass names a branch; resolve it to the merge-base. A delta names a
	# snapshot commit already. Either way we end up with one rev to diff from.
	if git -C "$repo" rev-parse --verify --quiet "$target^{commit}" >/dev/null 2>&1; then
		from="$target"
		# Apply merge-base ONLY for a full pass (target is a branch). A delta
		# target is a `stash create` snapshot whose FIRST PARENT is HEAD — so
		# HEAD is an ancestor of it and `merge-base <snapshot> HEAD` returns
		# HEAD, not the snapshot. Applying it unconditionally silently
		# collapsed every delta into `git diff HEAD`, i.e. the whole
		# uncommitted changeset: the feature became a no-op that still cost
		# the eight minutes it exists to save, while looking like it worked.
		# Worse, it is not even a superset — a fix that REVERTS a file to its
		# committed content shows up in `git diff <snapshot>` and vanishes
		# from `git diff HEAD`, so that change escapes review entirely.
		if ! git -C "$repo" merge-base --is-ancestor HEAD "$target" 2>/dev/null; then
			if mb="$(git -C "$repo" merge-base "$target" HEAD 2>/dev/null)" && [[ -n "$mb" ]]; then
				from="$mb"
			fi
		fi
	else
		echo "cannot resolve '$target' to a commit — try origin/$target, or git fetch" >&2
		exit 2
	fi

	mkdir -p "$marker_dir/diff"
	rm -f "$marker_dir/diff/part-"* "$marker_dir/diff/full.diff"
	if ! git -C "$repo" diff "$from" >"$marker_dir/diff/full.diff" 2>"$marker_dir/diff/err"; then
		echo "git diff failed: $(head -1 "$marker_dir/diff/err" 2>/dev/null)" >&2
		exit 2
	fi

	n_lines="$(wc -l <"$marker_dir/diff/full.diff" | tr -d ' ')"
	n_bytes="$(wc -c <"$marker_dir/diff/full.diff" | tr -d ' ')"
	if [[ "$n_bytes" -eq 0 ]]; then
		# Empty is legitimate ONLY for an untracked-only changeset. Say which,
		# so the caller cannot read silence as "nothing changed".
		echo "empty 0 $marker_dir/diff/full.diff"
		exit 0
	fi

	# ALWAYS hand over paths, never content. Pasting the diff into the prompt
	# was the original design and it is wrong twice over: the Bash tool caps
	# output at ~30k characters (so gathering it truncates), and a large paste
	# burns tens of thousands of tokens the reviewer could get with one Read.
	# The reviewer HAS Read. Give it files.
	#
	# Split at 1500 lines — under Read's 2000-line-per-call cap, with headroom.
	# The caller must state the line count so the reviewer can verify its own
	# coverage; a reviewer given N paths and a total can tell when it is done,
	# one given a single path cannot.
	if [[ "$n_lines" -gt 1500 ]]; then
		split -l 1500 "$marker_dir/diff/full.diff" "$marker_dir/diff/part-"
		printf 'files %s' "$n_lines"
		for f in "$marker_dir/diff/part-"*; do printf ' %s' "$f"; done
		printf '\n'
	else
		printf 'files %s %s\n' "$n_lines" "$marker_dir/diff/full.diff"
	fi
	;;

new-untracked)
	# Files that appeared OR CHANGED since the recorded pass. `stash create` does
	# not capture untracked content, so `git diff <snap>` cannot see these — they
	# must be handed to the reviewer separately or a whole new file could be added
	# between passes and never read.
	#
	# FAIL LOUD, NEVER EMPTY. Under `set -euo pipefail` a failure in the pipeline
	# below would abort with empty stdout — and empty here reads as the
	# affirmative "no new untracked files", which is exactly backwards for a
	# safety channel. On any failure, emit a sentinel plus EVERY untracked path so
	# the caller over-reports instead of silently under-reporting.
	#
	# LC_ALL=C is on the comm as well as the sorts feeding it: comm collates with
	# strcoll under a UTF-8 locale while the inputs are byte-sorted, and a
	# non-ASCII filename makes the two disagree. Mutation-tested — the mismatch
	# MISSES a changed file, it does not merely over-report.
	if ! out="$(
		set -o pipefail
		if [[ -f "$UNTRACKED" ]]; then
			LC_ALL=C comm -13 "$UNTRACKED" <(list_untracked) | cut -d' ' -f2- | LC_ALL=C sort -u
		else
			list_untracked | cut -d' ' -f2- | LC_ALL=C sort -u
		fi
	)"; then
		echo "UNRESOLVABLE — could not compute the untracked delta; review EVERY untracked file below"
		git -C "$repo" ls-files --others --exclude-standard 2>/dev/null || true
		exit 0
	fi
	[[ -z "$out" ]] || printf '%s\n' "$out"
	;;

*)
	usage >&2
	exit 2
	;;
esac
