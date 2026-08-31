#!/usr/bin/env bash
# pmr-timebubble.sh — reconstruct a historical changeset as UNCOMMITTED
# working-tree state, so a review protocol can be run against it exactly as
# /precheck would have seen it the day it was written.
#
# WHY THIS EXISTS (#1195). The bench compares two Job D prompt protocols over
# real changesets. Both arms must see the condition /precheck actually runs in,
# and that condition is specific: /precheck runs BEFORE /scp commits, so the
# changeset is dirty working tree, not history. Reviewing the commit instead
# would quietly change the experiment — `git diff <base>...HEAD` is EMPTY in a
# pre-commit gate (three-dot is commit-to-commit and excludes the working tree
# by construction; measured 0 bytes vs 61,193 on this repo), and the untracked
# channel — new files, which no `git diff` reports at all — would vanish
# entirely. An arm that never sees an untracked file cannot be scored on
# whether it reviews one.
#
# THE METHOD. Check out the changeset's PARENT into a throwaway worktree, then
# apply the changeset's own diff to it WITHOUT committing or staging. What is
# left on disk is the pre-commit condition, byte for byte.
#
# HOW FIDELITY IS PROVEN — an exact oracle, not a comparison. Hash the
# reconstructed working tree and require it to equal the original commit's tree
# object. Git already computed that hash; if the two 40-hex strings match, the
# reconstruction is byte-identical to the real changeset, and no heuristic,
# tolerance or model is involved. The hash is taken through a THROWAWAY index
# (`GIT_INDEX_FILE`) because the obvious `git add -A` would stage everything and
# destroy the very uncommitted condition being built.
#
# WHAT IS DELIBERATELY REJECTED, not silently repaired:
#   - Merge commits. Two parents means two possible diffs, and picking one would
#     be a policy the caller cannot see. The oracle's `fixtures` output excludes
#     merges already; this is the second line of defence.
#   - Root commits. No parent, so no pre-state to reconstruct.
#   - Any changeset whose reconstructed tree does not match. The known cause is
#     a file added by the changeset that the PARENT's .gitignore ignores: it
#     lands on disk but `add -A` skips it, so the tree differs. Such a fixture is
#     also one the real precheck would not have seen as untracked, so excluding
#     it is correct rather than merely convenient. Excluded LOUDLY (exit 3) —
#     a bench that silently drops its hard cases reports a flattering number.
#
# IGNORE SOURCES ARE PINNED, because two of the three live OUTSIDE the tree.
# `add -A` and `status` consult in-tree `.gitignore`, `core.excludesFile`, and
# `$GIT_COMMON_DIR/info/exclude`. Only the first is part of the changeset. Left
# unpinned, an operator's GLOBAL gitignore silently changes two things: which
# fixtures exit 3 (so the bench's fixture set varies by whose machine ran it),
# and — worse — whether an added file appears in the manifest's untracked
# channel at all. The untracked channel is the entire reason this harness
# exists; a manifest that quietly omits a file is worse than a loud exit 3. So
# `core.excludesFile` is pinned to /dev/null on every call that consults it.
# `info/exclude` is shared with the parent repo and CANNOT be pinned by config
# — it is the one remaining out-of-tree ignore source, and the second known
# cause of an unfaithful reconstruction. Keep it empty in any repo used as a
# bench source.
#
# Subcommands:
#   build <sha> --into <dir>   Reconstruct <sha> as dirty state in a new
#                              worktree at <dir>. Prints the manifest (TSV) on
#                              stdout. Exit 3 if fidelity is not proven.
#   verify <dir> <sha>         Re-prove fidelity of an existing bubble. Use
#                              after an arm has run, to establish that the arm
#                              did not mutate the state it was scoring.
#   teardown <dir>             Remove the worktree and prune its administrative
#                              entry.
#
# Manifest keys (TSV, `key<TAB>value`; one `file<TAB><status><TAB><path>` row
# per changed path, status M/A/D as the WORKING TREE sees it — A means
# untracked, which is the channel `git diff` cannot report):
#   culprit base worktree tree_expected tree_actual
#   files_modified files_added files_deleted diff_bytes
#
# Usage: pmr-timebubble.sh <build|verify|teardown> ... [--repo DIR]
# Exit:  0 success; 2 unusable input; 3 reconstruction not faithful (worktree is
#        LEFT in place for inspection, stderr says NOT faithful); 4 the patch did
#        not apply at all (worktree is REMOVED — there is nothing to inspect).
#        3 and 4 are separate codes on purpose: they have opposite
#        post-conditions, so a caller keying on "exit 3 means a bubble is waiting
#        for me" would be wrong half the time if they shared one.
set -euo pipefail

# Pin the diff format against the caller's global git config. A developer with
# `diff.noprefix` or an external differ set would otherwise produce a patch
# `git apply` cannot read, and the failure would look like a bad fixture rather
# than a bad environment.
DIFF_OPTS=(-c diff.noprefix=false -c diff.external= -c diff.mnemonicprefix=false)

# Pin the out-of-tree ignore sources. See "IGNORE SOURCES ARE PINNED" above: an
# operator's global gitignore must not decide what this harness can see.
IGNORE_OPTS=(-c core.excludesFile=/dev/null)

# Every mktemp registers here. The trap is installed BEFORE the first write,
# because this script runs under errexit and an abort between mktemp and a
# later cleanup would leak the file on every iteration of a bench that walks
# hundreds of fixtures. Same convention, and the same reason, as
# scripts/ci/szz-oracle.sh.
TMPFILES=()
cleanup_tmpfiles() {
	if ((${#TMPFILES[@]} > 0)); then
		rm -f "${TMPFILES[@]}"
	fi
}
trap cleanup_tmpfiles EXIT

die() { # message  exit-code
	echo "pmr-timebubble: $1" >&2
	exit "${2:-2}"
}

MODE="${1:-}"
shift || true

REPO="."
INTO=""
POSITIONAL=()

while [[ $# -gt 0 ]]; do
	case "$1" in
	--repo)
		REPO="${2:-}"
		[[ -n "$REPO" ]] || die "--repo needs a directory"
		shift 2
		;;
	--into)
		INTO="${2:-}"
		[[ -n "$INTO" ]] || die "--into needs a path"
		shift 2
		;;
	-*)
		die "unknown argument: $1"
		;;
	*)
		POSITIONAL+=("$1")
		shift
		;;
	esac
done

case "$MODE" in
build | verify | teardown) ;;
*)
	die "usage: pmr-timebubble.sh <build <sha> --into DIR|verify DIR SHA|teardown DIR> [--repo DIR]"
	;;
esac

cd "$REPO" || die "not a directory: $REPO"
git rev-parse --git-dir >/dev/null 2>&1 || die "not a git repository: $REPO"

# Hash a worktree's CURRENT on-disk state as a tree object, without touching the
# worktree's own index. Reading the base tree first means files the changeset
# deleted are staged-as-present and then removed by `add -A`, so deletions are
# reflected as faithfully as additions.
tree_of_worktree() { # worktree-dir  base-ref
	local dir="$1" base="$2" idx
	idx="$(mktemp -t pmr-timebubble-index.XXXXXX)"
	TMPFILES+=("$idx")
	GIT_INDEX_FILE="$idx" git -C "$dir" read-tree "$base"
	GIT_INDEX_FILE="$idx" git "${IGNORE_OPTS[@]}" -C "$dir" add -A
	GIT_INDEX_FILE="$idx" git -C "$dir" write-tree
}

case "$MODE" in

build)
	sha="${POSITIONAL[0]:-}"
	[[ -n "$sha" ]] || die "build needs a commit-ish"
	[[ -n "$INTO" ]] || die "build needs --into DIR"
	[[ -e "$INTO" ]] && die "--into path already exists: $INTO"

	culprit="$(git rev-parse --verify "${sha}^{commit}" 2>/dev/null)" ||
		die "not a commit: $sha"

	parents="$(git rev-list --parents -n 1 "$culprit" | wc -w)"
	((parents == 2)) ||
		die "not a single-parent commit ($((parents - 1)) parent(s)): $culprit — merges and root commits have no unambiguous pre-state"

	base="$(git rev-parse --verify "${culprit}^")"

	patch="$(mktemp -t pmr-timebubble-patch.XXXXXX)"
	TMPFILES+=("$patch")
	git "${DIFF_OPTS[@]}" diff --binary --no-textconv --no-ext-diff "$base" "$culprit" >"$patch"
	diff_bytes="$(wc -c <"$patch" | tr -d ' ')"
	((diff_bytes > 0)) || die "empty diff for $culprit — nothing to reconstruct"

	git worktree add --detach --quiet "$INTO" "$base" ||
		die "could not create worktree at $INTO"

	# Capture rather than `2>&1`: stdout is the MANIFEST stream, and apply's
	# reject/context errors interleaved into it would corrupt a caller's TSV
	# parse while still leaving the operator with only the one-line die.
	if ! apply_err="$(git -C "$INTO" apply --whitespace=nowarn "$patch" 2>&1)"; then
		[[ -n "$apply_err" ]] && echo "$apply_err" >&2
		git worktree remove --force --force "$INTO" >/dev/null 2>&1 || true
		die "patch did not apply cleanly onto $base" 4
	fi

	tree_expected="$(git rev-parse "${culprit}^{tree}")"
	tree_actual="$(tree_of_worktree "$INTO" "$base")"

	worktree_abs="$(cd "$INTO" && pwd)"
	printf 'culprit\t%s\n' "$culprit"
	printf 'base\t%s\n' "$base"
	printf 'worktree\t%s\n' "$worktree_abs"
	printf 'tree_expected\t%s\n' "$tree_expected"
	printf 'tree_actual\t%s\n' "$tree_actual"
	printf 'diff_bytes\t%s\n' "$diff_bytes"

	# Status of the reconstruction as the WORKING TREE reports it — which is what
	# a review protocol is handed. `??` is the untracked channel.
	status="$(git "${IGNORE_OPTS[@]}" -C "$INTO" status --porcelain=v1 --untracked-files=all)"
	n_mod=0
	n_add=0
	n_del=0
	rows=""
	while IFS= read -r line; do
		[[ -n "$line" ]] || continue
		code="${line:0:2}"
		path="${line:3}"
		case "$code" in
		'??')
			n_add=$((n_add + 1))
			rows+="file	A	$path"$'\n'
			;;
		*D*)
			n_del=$((n_del + 1))
			rows+="file	D	$path"$'\n'
			;;
		*)
			n_mod=$((n_mod + 1))
			rows+="file	M	$path"$'\n'
			;;
		esac
	done <<<"$status"

	printf 'files_modified\t%s\n' "$n_mod"
	printf 'files_added\t%s\n' "$n_add"
	printf 'files_deleted\t%s\n' "$n_del"
	printf '%s' "$rows"

	if [[ "$tree_expected" != "$tree_actual" ]]; then
		echo "pmr-timebubble: reconstruction is NOT faithful for $culprit" >&2
		echo "pmr-timebubble:   expected tree $tree_expected" >&2
		echo "pmr-timebubble:   actual   tree $tree_actual" >&2
		echo "pmr-timebubble: worktree left at $worktree_abs for inspection; exclude this fixture" >&2
		exit 3
	fi
	;;

verify)
	dir="${POSITIONAL[0]:-}"
	sha="${POSITIONAL[1]:-}"
	[[ -n "$dir" && -n "$sha" ]] || die "verify needs DIR and SHA"
	[[ -d "$dir" ]] || die "no such worktree: $dir"

	culprit="$(git rev-parse --verify "${sha}^{commit}" 2>/dev/null)" ||
		die "not a commit: $sha"
	base="$(git rev-parse --verify "${culprit}^")"

	tree_expected="$(git rev-parse "${culprit}^{tree}")"
	tree_actual="$(tree_of_worktree "$dir" "$base")"

	printf 'tree_expected\t%s\n' "$tree_expected"
	printf 'tree_actual\t%s\n' "$tree_actual"
	[[ "$tree_expected" == "$tree_actual" ]] ||
		die "bubble at $dir no longer matches $culprit — state was mutated" 3
	;;

teardown)
	dir="${POSITIONAL[0]:-}"
	[[ -n "$dir" ]] || die "teardown needs DIR"
	# --force twice is not redundant: the first overrides "worktree is dirty",
	# which every bubble is BY CONSTRUCTION, and the second overrides a lock left
	# by a killed run (cc-workflow#438).
	#
	# The rm -rf fallback is GATED on git agreeing the path is a registered
	# worktree. Ungated, the only validation is that $dir is non-empty, so a
	# typo, a stale path, or the repo's own main worktree (which git always
	# refuses to remove) would fall through to an unconditional recursive
	# delete. A cleanup helper must not be able to destroy something it was
	# never handed.
	if ! git worktree remove --force --force "$dir" >/dev/null 2>&1; then
		dir_abs="$(cd "$dir" 2>/dev/null && pwd)" || dir_abs=""
		if [[ -n "$dir_abs" ]] && git worktree list --porcelain | grep -qxF "worktree $dir_abs"; then
			rm -rf "$dir"
		else
			die "refusing to delete $dir — git does not list it as a worktree of $REPO"
		fi
	fi
	git worktree prune
	;;
esac
