#!/usr/bin/env bash
# precheck-status.sh — the `precheck` commit status: post it on a pass, read it back (#1235).
#
# /precheck is the MR gate. A pass is recorded ON THE COMMIT, as a commit status named
# `precheck` with state `success`, not in a local file:
#   - it is keyed on the SHA, so a new push moves HEAD and the mark goes stale by itself;
#   - it works across worktrees, sessions and repos (sdlc's pr_create will read it remotely);
#   - a reviewer sees it on the MR, and it can later become a required check.
# The pr-ready-gate.sh hook consumes it, and so do mcp-server-sdlc's pr_create,
# pr_ready and pr_merge from the release carrying #592. The contract — context, states, description — is docs/precheck-status.md;
# change it there first.
#
# GitLab: the status is attached to the SHA's EXISTING pipeline (pipeline_id). A bare
# status post makes GitLab create a separate "external" pipeline, which can become the
# MR's latest pipeline and hide the real CI verdict from the merge check.
# On a merged-results MR the head SHA has no pipeline (MR pipelines run on an ephemeral
# merge commit), so the post is bare by necessity. It stays on the head, because every
# reader keys on the head (pr-head + get, pr-ready-gate.sh, sdlc's pr_create/pr_ready/
# pr_merge). Each open MR's head_pipeline is read before the post, then polled after it
# (PRECHECK_HP_POLLS reads, PRECHECK_HP_STEP_SEC apart: 6 × 5 s). If one moves in that
# window, the post replaces its success with `failed` and exits 3: the hazard above,
# measured instead of assumed (#1357). A move after the window is not seen.
#
# Every read fails closed: `get` prints `success` only when the platform said so. An API
# error is exit 3, never a state.
set -euo pipefail

CONTEXT="precheck"

usage() {
	cat <<'EOF'
Usage: precheck-status.sh <command> <repo_root> [args]

Commands:
  post <repo_root> <sha> <description>
            Post `precheck` = success on <sha>, then read it back. The SHA must
            already be pushed. Description: one line, cut to 140 characters.
  get <repo_root> <sha>
            Print the `precheck` state on <sha>: success | pending | failure | none.
  last-success <repo_root> <base>
            Print the newest first-parent commit between <base> and HEAD that
            carries `precheck` = success, or `none`. What /precheck rearm diffs from.
            <base> is read as origin/<base> when that exists; fetch it first.
  pr-head <repo_root> [<number|url|branch>]
            Print "<sha> <head-branch> <base-branch>": a PR/MR as the platform sees it.
            Default: the open PR/MR from the current branch.
  branch-head <repo_root> <branch>
            Print the SHA <branch> points at on the platform. Exit 3 when it can't
            be read, including a branch that was never pushed.
  mark-ready <repo_root> <number>
            Mark PR/MR <number> ready, ONLY if its head carries `precheck` = success,
            then read it back. Prints "ready <number> <sha>". Exit 4 when the head has
            no pass. The kit's one way to make a PR/MR ready: GitHub's GraphQL
            markPullRequestReadyForReview, or GitLab's title without the draft prefix.

Exit: 0 ok; 2 usage or not a repo / unknown platform; 3 the platform API failed;
4 mark-ready refused (no pass on the head).
Platform and repository come from origin's URL (github / gitlab in the host).
Overrides, for a repository other than <repo_root>'s origin (`gh -R`, `glab -R`):
PRECHECK_SLUG=owner/repo (or group/sub/proj), PRECHECK_PLATFORM=github|gitlab,
PRECHECK_HOST=<gitlab host>. With PRECHECK_SLUG set, `get` on a full 40-hex SHA
needs no local repository or object: the platform's answer is the authority.
EOF
}

cmd="${1:-}"
repo="${2:-}"
[[ -n "$cmd" && -n "$repo" ]] || {
	usage >&2
	exit 2
}
is_repo=true
git -C "$repo" rev-parse --git-dir >/dev/null 2>&1 || is_repo=false
if ! $is_repo && [[ -z "${PRECHECK_SLUG:-}" ]]; then
	echo "not a git repository: $repo" >&2
	exit 2
fi

if [[ -n "${PRECHECK_SLUG:-}" ]]; then
	slug="${PRECHECK_SLUG%.git}"
	slug="$(printf '%s' "$slug" | sed -E 's#^[a-z+]+://[^/]+/##; s#^[^@/]*@[^:/]+[:/]##; s#/$##')"
	url="$(git -C "$repo" remote get-url origin 2>/dev/null || true)"
	host="${PRECHECK_HOST:-$(printf '%s' "$url" | sed -E 's#^[a-z+]+://##; s#^[^@/]*@##; s#[:/].*$##')}"
else
	# origin, never the CLI's own repo resolution: bare `gh` resolves `upstream` first
	# and once posted to a third party's repository.
	url="$(git -C "$repo" remote get-url origin 2>/dev/null)" || {
		echo "no origin remote in $repo" >&2
		exit 2
	}
	host="$(printf '%s' "$url" | sed -E 's#^[a-z+]+://##; s#^[^@/]*@##; s#[:/].*$##')"
	slug="$(printf '%s' "$url" | sed -E 's#^[a-z+]+://[^/]+/##; s#^[^@/]*@[^:/]+[:/]##; s#\.git$##; s#/$##')"
fi
platform="${PRECHECK_PLATFORM:-}"
if [[ -z "$platform" ]]; then
	case "$host" in
	*github*) platform=github ;;
	*gitlab*) platform=gitlab ;;
	*)
		echo "cannot tell the platform from origin host '$host'; set PRECHECK_PLATFORM" >&2
		exit 2
		;;
	esac
fi
# A -R target names its own host when it is a URL. A bare path on another forge than
# origin's gets that platform's public host (PRECHECK_HOST overrides).
if [[ -n "${PRECHECK_SLUG:-}" && -z "${PRECHECK_HOST:-}" ]]; then
	case "$PRECHECK_SLUG" in
	*://*) host="$(printf '%s' "$PRECHECK_SLUG" | sed -E 's#^[a-z+]+://##; s#^[^@/]*@##; s#[:/].*$##')" ;;
	*)
		case "$platform:$host" in
		github:*github* | gitlab:*gitlab*) ;;
		gitlab:*) host=gitlab.com ;;
		github:*) host=github.com ;;
		esac
		;;
	esac
fi
[[ "$platform" == gitlab && -z "$host" ]] && host=gitlab.com
enc="$(printf '%s' "$slug" | jq -sRr @uri)"

# gl_api <args...> — `glab api`, failing on an error BODY as well as an exit code:
# glab exits 0 on an HTTP error and prints the error (mcp-server-sdlc#502). Same rule as
# sdlc's detectGlabApiError: an object carrying message/error and none of the fields a
# real resource has.
gl_api() {
	local out
	out="$(glab api --hostname "$host" "$@" </dev/null 2>/dev/null)" || return 1
	if printf '%s' "$out" | jq -e 'type == "object" and (has("message") or has("error"))
		and ([has("id", "iid", "web_url", "sha", "name", "path")] | any | not)' >/dev/null 2>&1; then
		return 1
	fi
	printf '%s' "$out"
}

api_fail() {
	echo "precheck-status: $platform API call failed: $*" >&2
	exit 3
}

# get_state <sha> -> success | pending | failure | none
get_state() {
	local sha="$1" out
	case "$platform" in
	github)
		# The combined status holds the latest status per context.
		out="$(gh api "repos/$slug/commits/$sha/status" </dev/null 2>/dev/null)" || api_fail "read status of $sha"
		printf '%s' "$out" | jq -r --arg c "$CONTEXT" \
			'([.statuses[]? | select(.context == $c)][0].state) // "none" | if . == "error" then "failure" else . end'
		;;
	gitlab)
		out="$(gl_api "projects/$enc/repository/commits/$sha/statuses?name=$CONTEXT&all=true&per_page=100")" ||
			api_fail "read status of $sha"
		printf '%s' "$out" | jq -r \
			'(sort_by(.id) | last | .status) // "none"
			 | if . == "success" or . == "none" then .
			   elif . == "pending" or . == "running" or . == "created" then "pending"
			   else "failure" end'
		;;
	*)
		echo "unknown PRECHECK_PLATFORM '$platform'" >&2
		exit 2
		;;
	esac
}

# head_pipeline <iid> -> "<id> <source>" for GitLab MR <iid>'s head_pipeline ("" for no
# id; the source read from pipelines/<id> when the MR answer omits it). Non-zero when an
# API call fails.
head_pipeline() {
	local mr id src
	mr="$(gl_api "projects/$enc/merge_requests/$1")" || return 1
	id="$(printf '%s' "$mr" | jq -er '.head_pipeline.id // "" | tostring' 2>/dev/null)" || return 1
	src="$(printf '%s' "$mr" | jq -r '.head_pipeline.source // empty' 2>/dev/null)"
	if [[ -n "$id" && -z "$src" ]]; then
		src="$(gl_api "projects/$enc/pipelines/$id" | jq -er '.source // "unknown"' 2>/dev/null)" || return 1
	fi
	printf '%s %s\n' "$id" "${src:-none}"
}

# refuse_pass <reason>: on GitLab, put `failed` on the head's precheck context (replacing
# any success there), read it back, and exit 3 with the reason.
refuse_pass() {
	gl_api -X POST "projects/$enc/statuses/$sha" -f state=failed -f name="$CONTEXT" \
		-f description="no pass: an external pipeline hides the MR's CI verdict" >/dev/null ||
		api_fail "post the failed status on $sha (after: $1)"
	local st
	st="$(get_state "$sha")"
	[[ "$st" == failure ]] || echo "and the failed status reads back '$st', not failure" >&2
	echo "no pass on $sha: $1. Its precheck status is now failed." >&2
	exit 3
}

case "$cmd" in
post)
	sha="${3:-}"
	desc="${4:-}"
	[[ -n "$sha" && -n "$desc" ]] || {
		usage >&2
		exit 2
	}
	sha="$(git -C "$repo" rev-parse --verify --quiet "$sha^{commit}")" || {
		echo "not a commit: $3" >&2
		exit 2
	}
	desc="$(printf '%s' "$desc" | tr '\n\r' '  ' | cut -c1-140)"
	# The head_pipeline poll's seams, checked before anything is posted: a bad value must
	# never skip the guard, or die after success is already on the head.
	polls="${PRECHECK_HP_POLLS:-6}" step="${PRECHECK_HP_STEP_SEC:-5}"
	[[ "$polls" =~ ^[1-9][0-9]*$ && "$step" =~ ^[0-9]+$ ]] || {
		echo "PRECHECK_HP_POLLS must be a positive integer and PRECHECK_HP_STEP_SEC a non-negative one (got '$polls', '$step')" >&2
		exit 2
	}
	hp_before=()
	case "$platform" in
	github)
		gh api -X POST "repos/$slug/statuses/$sha" -f state=success -f context="$CONTEXT" \
			-f description="$desc" </dev/null >/dev/null 2>&1 || api_fail "post status on $sha"
		;;
	gitlab)
		# A failed lookup is a failure, never "no pipeline": a bare post is exactly the
		# external pipeline that hides the real CI verdict (header).
		# Never an external pipeline: after any earlier bare post the newest pipeline for the
		# head is our own, and attaching to it would skip the guard below (#1371 review).
		pl="$(gl_api "projects/$enc/pipelines?sha=$sha&order_by=id&sort=desc&per_page=20")" ||
			api_fail "read the pipeline of $sha"
		pid="$(printf '%s' "$pl" | jq -er 'if type == "array" then ([.[] | select(.source != "external")][0].id // "") else error end' 2>/dev/null)" ||
			api_fail "read the pipeline of $sha (unexpected answer)"
		# No pipeline for the head (a merged-results MR runs on its merge commit): the post
		# is bare by necessity. Record each open MR's head_pipeline at this head first, so
		# the post fails loudly if GitLab ever promotes the external pipeline (#1357). An MR
		# whose head_pipeline is already external is the hazard itself: no pass at all.
		if [[ -z "$pid" ]]; then
			mrs="$(gl_api "projects/$enc/repository/commits/$sha/merge_requests")" || api_fail "list MRs of $sha"
			iids="$(printf '%s' "$mrs" | jq -er --arg s "$sha" \
				'if type == "array" then ([.[] | select(.state == "opened" and .sha == $s) | .iid] | map(tostring) | join(" ")) else error end' \
				2>/dev/null)" || api_fail "list MRs of $sha (unexpected answer)"
			for iid in $iids; do
				hp="$(head_pipeline "$iid")" || api_fail "read MR !$iid"
				[[ "${hp#* }" == external ]] &&
					refuse_pass "MR !$iid's head_pipeline ${hp%% *} is already an external pipeline, which hides its CI verdict"
				hp_before+=("$iid=${hp%% *}")
			done
		fi
		args=(-X POST "projects/$enc/statuses/$sha" -f state=success -f name="$CONTEXT" -f description="$desc")
		[[ -n "$pid" ]] && args+=(-f pipeline_id="$pid")
		gl_api "${args[@]}" >/dev/null || api_fail "post status on $sha"
		;;
	esac
	# Verify the post-state, not the response code.
	state="$(get_state "$sha")"
	if [[ "$state" != success ]]; then
		echo "posted, but $sha reads back '$state', not success" >&2
		exit 3
	fi
	# GitLab moves head_pipeline in an async worker, so one immediate re-read nearly always
	# sees the old value. Poll for a bounded window (#1371 lead review), and trip on the
	# condition as well as on a change: a head_pipeline that moved, or one that is external.
	# Either way, and on a re-read that fails, the success already on the head would still
	# read as a pass, so refuse_pass replaces it with `failed` before exiting 3.
	if ((${#hp_before[@]} > 0)); then
		for ((i = 1; i <= polls; i++)); do
			sleep "$step"
			for rec in "${hp_before[@]}"; do
				iid="${rec%%=*}" before="${rec#*=}"
				hp="$(head_pipeline "$iid")" || refuse_pass "MR !$iid could not be re-read, so the guard cannot vouch for the pass"
				after="${hp%% *}"
				if [[ "$after" != "$before" ]]; then
					refuse_pass "MR !$iid's head_pipeline moved from ${before:-none} to ${after:-none}: the external pipeline the post created now hides its CI verdict"
				fi
				[[ "${hp#* }" == external ]] &&
					refuse_pass "MR !$iid's head_pipeline $after is an external pipeline, which hides its CI verdict"
			done
		done
	fi
	echo "success $sha"
	;;

get)
	sha="${3:-}"
	[[ -n "$sha" ]] || {
		usage >&2
		exit 2
	}
	# A full SHA is asked of the platform as-is: it may name a commit this clone has
	# never fetched (`gh -R other/repo pr ready N`). Anything shorter must resolve here.
	if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
		sha="$(git -C "$repo" rev-parse --verify --quiet "$sha^{commit}" 2>/dev/null)" || {
			echo "not a commit: $3" >&2
			exit 2
		}
	fi
	get_state "$sha"
	;;

pr-head)
	# The head of a PR/MR as the platform sees it: "<sha> <head-branch> <base-branch>". The selector is a
	# number, a PR/MR URL, or a branch (the open PR/MR from it); empty = the current
	# branch of <repo_root>. What pr-ready-gate.sh checks, rather than local HEAD.
	sel="${3:-}"
	if [[ -z "$sel" ]]; then
		$is_repo || {
			echo "pr-head needs a selector outside a repository" >&2
			exit 2
		}
		sel="$(git -C "$repo" rev-parse --abbrev-ref HEAD 2>/dev/null)" || {
			echo "no current branch in $repo" >&2
			exit 2
		}
	fi
	if [[ "$sel" =~ /(pull|merge_requests)/([0-9]+)/?$ ]]; then
		sel="${BASH_REMATCH[2]}"
	fi
	case "$platform" in
	github)
		if [[ "$sel" =~ ^[0-9]+$ ]]; then
			out="$(gh api "repos/$slug/pulls/$sel" </dev/null 2>/dev/null)" || api_fail "read PR $sel"
			out="$(printf '%s' "$out" | jq -r '.head.sha + " " + .head.ref + " " + .base.ref' 2>/dev/null)" || out=""
		else
			out="$(gh api "repos/$slug/pulls?state=open&head=${slug%%/*}:$sel" </dev/null 2>/dev/null)" || api_fail "list PRs from $sel"
			out="$(printf '%s' "$out" | jq -r '.[0] // empty | .head.sha + " " + .head.ref + " " + .base.ref' 2>/dev/null)" || out=""
		fi
		;;
	gitlab)
		if [[ "$sel" =~ ^[0-9]+$ ]]; then
			out="$(gl_api "projects/$enc/merge_requests/$sel")" || api_fail "read MR $sel"
			out="$(printf '%s' "$out" | jq -r '.sha + " " + .source_branch + " " + .target_branch' 2>/dev/null)" || out=""
		else
			bsel="$(printf '%s' "$sel" | jq -sRr @uri)"
			out="$(gl_api "projects/$enc/merge_requests?state=opened&source_branch=$bsel")" || api_fail "list MRs from $sel"
			out="$(printf '%s' "$out" | jq -r '.[0] // empty | .sha + " " + .source_branch + " " + .target_branch' 2>/dev/null)" || out=""
		fi
		;;
	esac
	if ! [[ "$out" =~ ^[0-9a-f]{40}\ [^\ ]+\ [^\ ]+$ ]]; then
		echo "no PR/MR head found for '$sel'" >&2
		exit 3
	fi
	echo "$out"
	;;

branch-head)
	# Where <branch> points on the platform: what a `gh pr create` from it opens with.
	# Never the local origin/<branch>, which is stale once another sandbox pushes.
	b="${3:-}"
	[[ -n "$b" ]] || {
		usage >&2
		exit 2
	}
	case "$platform" in
	github)
		out="$(gh api "repos/$slug/git/ref/heads/$b" </dev/null 2>/dev/null)" || api_fail "read branch $b (not pushed?)"
		out="$(printf '%s' "$out" | jq -r '.object.sha // empty' 2>/dev/null)" || out=""
		;;
	gitlab)
		out="$(gl_api "projects/$enc/repository/branches/$(printf '%s' "$b" | jq -sRr @uri)")" ||
			api_fail "read branch $b (not pushed?)"
		out="$(printf '%s' "$out" | jq -r '.commit.id // empty' 2>/dev/null)" || out=""
		;;
	esac
	[[ "$out" =~ ^[0-9a-f]{40}$ ]] || api_fail "no commit for branch $b"
	echo "$out"
	;;

mark-ready)
	# The kit's one path to "ready" (#1235). Not glab's porcelain: `glab mr update` rewrites
	# the title on most flags (--title, --fill, --wip …), and GitLab's draft state IS the
	# title prefix, so modelling which flags keep a draft was a losing game. This is REST,
	# self-gating, and verified by reading the PR/MR back.
	n="${3:-}"
	[[ "$n" =~ ^[0-9]+$ ]] || {
		usage >&2
		exit 2
	}
	info="$(bash "$0" pr-head "$repo" "$n")" || exit $?
	sha="${info%% *}"
	state="$(get_state "$sha")"
	if [[ "$state" != success ]]; then
		echo "refused: PR/MR $n's head ${sha:0:12} has precheck = $state; run /precheck first" >&2
		exit 4
	fi
	case "$platform" in
	github)
		pr="$(gh api "repos/$slug/pulls/$n" </dev/null 2>/dev/null)" || api_fail "read PR $n"
		if [[ "$(printf '%s' "$pr" | jq -r '.draft')" == true ]]; then
			node="$(printf '%s' "$pr" | jq -r '.node_id // empty')"
			[[ -n "$node" ]] || api_fail "PR $n has no node_id"
			# shellcheck disable=SC2016 # $id is a GraphQL variable, not a shell one
			gh api graphql -f query='mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { pullRequest { isDraft } } }' \
				-f id="$node" </dev/null >/dev/null 2>&1 || api_fail "mark PR $n ready"
		fi
		draft="$(gh api "repos/$slug/pulls/$n" </dev/null 2>/dev/null | jq -r '.draft')" || api_fail "read PR $n back"
		;;
	gitlab)
		mr="$(gl_api "projects/$enc/merge_requests/$n")" || api_fail "read MR $n"
		# Not `.draft // .work_in_progress`: jq's // skips false, so a ready MR would read null.
		if [[ "$(printf '%s' "$mr" | jq -r 'if has("draft") then .draft else .work_in_progress end')" == true ]]; then
			# Strip every leading draft prefix GitLab recognises, case-insensitively.
			title="$(printf '%s' "$mr" | jq -r '
				def undraft: if test("^\\s*(\\[draft\\]|\\(draft\\)|draft:)"; "i")
					then sub("^\\s*(\\[draft\\]|\\(draft\\)|draft:)\\s*"; ""; "i") | undraft else . end;
				.title | undraft')"
			[[ -n "$title" ]] || api_fail "MR $n's title is only a draft prefix"
			gl_api -X PUT "projects/$enc/merge_requests/$n" -f title="$title" >/dev/null || api_fail "mark MR $n ready"
		fi
		draft="$(gl_api "projects/$enc/merge_requests/$n" |
			jq -r 'if has("draft") then .draft else .work_in_progress end')" || api_fail "read MR $n back"
		;;
	esac
	# Verify the post-state, not the response code.
	[[ "$draft" == false ]] || api_fail "PR/MR $n still reads draft=$draft after marking it ready"
	echo "ready $n $sha"
	;;

last-success)
	base="${3:-}"
	[[ -n "$base" ]] || {
		usage >&2
		exit 2
	}
	# The remote base, when there is one: fleet worktrees often have no local <base>, and
	# a stale one lets rev-list reach commits already merged from another PR, whose pass
	# would then be taken as this branch's.
	bref="$base"
	git -C "$repo" rev-parse --verify --quiet "refs/remotes/origin/$base" >/dev/null 2>&1 && bref="origin/$base"
	mb="$(git -C "$repo" merge-base "$bref" HEAD 2>/dev/null)" || {
		echo "no merge-base between '$bref' and HEAD" >&2
		exit 2
	}
	# Newest first, the branch's own commits only, capped so a runaway branch cannot
	# turn into hundreds of API calls.
	# The assignment, not `[[ "$(get_state …)" == … ]]`: a failure inside [[ ]] is
	# swallowed, which would turn an API outage into a quiet `none`.
	while IFS= read -r c; do
		[[ -n "$c" ]] || continue
		s="$(get_state "$c")"
		if [[ "$s" == success ]]; then
			echo "$c"
			exit 0
		fi
	done < <(git -C "$repo" rev-list --first-parent --max-count=50 HEAD "^$mb")
	echo none
	;;

*)
	usage >&2
	exit 2
	;;
esac
