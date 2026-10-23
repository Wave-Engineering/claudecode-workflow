#!/usr/bin/env bash
# precheck-ci-source.sh — decide where /precheck Job B's lane result comes from (#1268).
#
# Job B's rule is "CI first": when CI has run on the pushed HEAD, its verdict IS the
# lane result, and running the same suites again on a shared box is waste. Before this
# script, Job B went straight to `ci_wait_run(timeout_sec: 1800)` and fell back to the
# full local suite on NO-RUN. Two routes made that fallback the every-time path:
#
#   1. GitLab: `ci_wait_run` could not see pipelines at all (mcp-server-sdlc#585, fixed
#      in 5.0.2). It waited out its whole timeout, up to 30 minutes, then ran locally.
#   2. Repos whose feature-branch pipelines start only on demand (a `web` or `api`
#      source). A push starts nothing, so no run exists for HEAD, and nothing ever will
#      unless someone triggers one.
#
# So this script answers, in code and before any long wait, "is there a run for this
# SHA, and if not, can one be started?" Only then does Job B wait, on a run that exists.
#
# Declared in the repo's .claude-project.md, under Toolchain (both optional):
#
#   - **CI on demand:** `glab ci run --branch <branch>`
#   - **CI jobs:** validate, test, integration
#
# `CI on demand` is the ONE command that starts a validation-only pipeline; `<branch>`
# is substituted. It is never guessed: a generic trigger can start publish or deploy
# jobs, and only the repo knows which on-demand run is safe. `CI jobs` names the jobs a
# run must contain, all green, to count as the lane result.
#
# stdout is the channel, one line, exit 0 (usage errors exit 2), in the style of
# precheck-review-scope.sh: a non-zero exit inside an agent's `if` is easy to swallow.
#
#   resolve  -> local no-ci                       no CI config for this platform
#               ci run=<id> ref=<ref>              a run exists for <sha>
#               ci triggered run=<id> ref=<ref>    none existed; the declared trigger
#                                                  ran once and a run for <sha> appeared
#               local NO-RUN <reason>              CI exists but cannot answer
#
#   <ref> is the run's own ref, and Job B-ci waits with it. On GitLab an MR pipeline's
#   ref is refs/merge-requests/<iid>/head, and `ci_wait_run` filters by ref AND sha, so
#   waiting with the branch name would miss the very run found here.
#   coverage -> covered                            every declared job present and green
#                                                  (or no jobs declared)
#               missing <job>[,<job>...]           declared jobs the run does not contain
#               not-green <job>=<state>[,...]      declared jobs present but not success
#               unknown <reason>                   the run's jobs could not be read
#
# Every `local` line gets "; shared host: book a slot before running lanes" appended
# when .claude-project.md declares a `Shared host`.

set -euo pipefail

# 90 s keeps the slowest path (trigger, then polls that find nothing) inside the Bash
# tool's default 120 s timeout, so the reason line is always printed.
TRIGGER_WAIT="${PRECHECK_CI_TRIGGER_WAIT:-90}"
POLL="${PRECHECK_CI_POLL:-10}"

usage() {
	cat <<'EOF'
Usage:
  precheck-ci-source.sh resolve  <repo_root> <marker_dir> <branch> <sha>
  precheck-ci-source.sh coverage <repo_root> <run_id>

resolve   Decide Job B's source for <sha>. Triggers the declared `CI on demand`
          command at most once per SHA (a marker in <marker_dir> records it).
coverage  After the run completes, check it contains every declared `CI jobs`
          entry, each green.
EOF
	exit 2
}

# The value of a `- **<key>:** ...` line in .claude-project.md, or empty.
project_field() {
	local root="$1" key="$2" cfg="$1/.claude-project.md"
	[[ -f "$cfg" ]] || return 0
	sed -n "s/^[[:space:]]*[-*][[:space:]]*\*\*${key}:\*\*[[:space:]]*//p" "$cfg" | head -n 1
}

# The first `backtick span` of a string, or empty.
first_code_span() {
	# shellcheck disable=SC2016  # the backticks are literal markdown, not expansions
	sed -n 's/^[^`]*`\([^`]*\)`.*/\1/p' <<<"$1"
}

# Sets HOST and SLUG (owner/repo or group/sub/project) from origin's configured URL.
# The raw config value, not `get-url`: an insteadOf rewrite changes the transport,
# never which project this is.
parse_origin() {
	local url
	url="$(git -C "$1" config --get remote.origin.url || true)"
	url="${url%.git}"
	case "$url" in
	*://*)
		url="${url#*://}"
		url="${url#*@}"
		HOST="${url%%/*}"
		HOST="${HOST%%:*}"
		SLUG="${url#*/}"
		;;
	*:*)
		url="${url#*@}"
		HOST="${url%%:*}"
		SLUG="${url#*:}"
		;;
	*)
		HOST="" SLUG=""
		;;
	esac
}

platform() {
	case "$HOST" in
	*github*) echo github ;;
	*) echo gitlab ;;
	esac
}

has_ci() {
	local root="$1"
	if [[ "$(platform)" == github ]]; then
		compgen -G "$root/.github/workflows/*.yml" >/dev/null ||
			compgen -G "$root/.github/workflows/*.yaml" >/dev/null
	else
		[[ -f "$root/.gitlab-ci.yml" ]]
	fi
}

# Prints "<id> <ref>" for the newest run/pipeline for <sha>, or nothing. Returns
# non-zero only when CI could not be read. By SHA alone: GitLab MR pipelines carry the
# ref refs/merge-requests/<iid>/head, so a branch-ref filter would miss them.
run_for_sha() {
	local sha="$1" out
	if [[ "$(platform)" == github ]]; then
		out="$(gh api "repos/${SLUG}/actions/runs?head_sha=${sha}&per_page=100")" || return 1
		jq -r '.workflow_runs[0] // empty | "\(.id) \(.head_branch)"' <<<"$out" 2>/dev/null || return 1
	else
		out="$(glab api --hostname "$HOST" "projects/${SLUG//\//%2F}/pipelines?sha=${sha}&per_page=20")" || return 1
		jq -r '.[0] // empty | "\(.id) \(.ref)"' <<<"$out" 2>/dev/null || return 1
	fi
}

local_line() {
	local line="local $1" shared
	shared="$(project_field "$ROOT" "Shared host")"
	[[ -n "$shared" ]] && line+="; shared host: book a slot before running lanes"
	echo "$line"
}

cmd_resolve() {
	[[ $# -eq 4 ]] || usage
	ROOT="$1"
	local marker_dir="$2" branch="$3" sha="$4" found trigger cmd rc waited marker
	parse_origin "$ROOT"

	if ! has_ci "$ROOT"; then
		local_line "no-ci"
		return 0
	fi
	if [[ -z "$SLUG" ]]; then
		local_line "NO-RUN cannot identify the project from origin"
		return 0
	fi

	if ! found="$(run_for_sha "$sha")"; then
		local_line "NO-RUN cannot read CI runs for ${sha:0:7}"
		return 0
	fi
	if [[ -n "$found" ]]; then
		echo "ci run=${found%% *} ref=${found#* }"
		return 0
	fi

	trigger="$(first_code_span "$(project_field "$ROOT" "CI on demand")")"
	if [[ -z "$trigger" ]]; then
		local_line "NO-RUN no run for ${sha:0:7}, and no \`CI on demand\` declared in .claude-project.md"
		return 0
	fi
	# The branch is substituted into a shell command, so it must be a plain ref name.
	if [[ ! "$branch" =~ ^[A-Za-z0-9._/-]+$ ]]; then
		local_line "NO-RUN branch name unsafe to substitute into \`CI on demand\`"
		return 0
	fi
	mkdir -p "$marker_dir"
	marker="$marker_dir/ci-triggered-$sha"
	if [[ -e "$marker" ]]; then
		local_line "NO-RUN \`CI on demand\` already ran once for ${sha:0:7} (exit $(cat "$marker" 2>/dev/null || echo '?')), and no run appeared"
		return 0
	fi

	# The marker is written BEFORE the trigger, so a killed or crashed run still counts
	# as the one attempt; the exit code is filled in once the command returns.
	cmd="${trigger//<branch>/$branch}"
	echo "?" >"$marker"
	rc=0
	(cd "$ROOT" && bash -c "$cmd") >"$marker_dir/ci-trigger.log" 2>&1 || rc=$?
	echo "$rc" >"$marker"
	if [[ $rc -ne 0 ]]; then
		local_line "NO-RUN \`CI on demand\` exited $rc (log: $marker_dir/ci-trigger.log)"
		return 0
	fi

	waited=0
	while :; do
		found="$(run_for_sha "$sha" || true)"
		if [[ -n "$found" ]]; then
			echo "ci triggered run=${found%% *} ref=${found#* }"
			return 0
		fi
		((waited >= TRIGGER_WAIT)) && break
		sleep "$POLL"
		waited=$((waited + POLL))
	done
	local_line "NO-RUN \`CI on demand\` ran, but no run for ${sha:0:7} appeared within ${TRIGGER_WAIT}s"
}

cmd_coverage() {
	[[ $# -eq 2 ]] || usage
	ROOT="$1"
	local run_id="$2" declared out filter jobs job state missing="" notgreen=""
	declared="$(project_field "$ROOT" "CI jobs" | tr -d '`')"
	if [[ -z "${declared//[[:space:],]/}" ]]; then
		echo "covered"
		return 0
	fi
	parse_origin "$ROOT"

	# GitHub's --paginate concatenates one JSON object per page, so jq reads each in turn.
	if [[ "$(platform)" == github ]]; then
		filter='.jobs[]? | "\(.name)\t\(.conclusion // .status)"'
		out="$(gh api --paginate "repos/${SLUG}/actions/runs/${run_id}/jobs?per_page=100")" || out=""
	else
		filter='.[]? | "\(.name)\t\(.status)"'
		out="$(glab api --hostname "$HOST" "projects/${SLUG//\//%2F}/pipelines/${run_id}/jobs?per_page=100")" || out=""
	fi
	if [[ -z "$out" ]] || ! jobs="$(jq -r "$filter" <<<"$out" 2>/dev/null)"; then
		echo "unknown cannot read the jobs of run $run_id"
		return 0
	fi

	IFS=',' read -ra wanted <<<"$declared"
	for job in "${wanted[@]}"; do
		job="${job#"${job%%[![:space:]]*}"}"
		job="${job%"${job##*[![:space:]]}"}"
		[[ -n "$job" ]] || continue
		state="$(awk -F'\t' -v j="$job" '$1 == j { print $2; exit }' <<<"$jobs")"
		if [[ -z "$state" ]]; then
			missing+="${missing:+,}$job"
		elif [[ "$state" != success ]]; then
			notgreen+="${notgreen:+,}$job=$state"
		fi
	done

	if [[ -n "$missing" ]]; then
		echo "missing $missing"
	elif [[ -n "$notgreen" ]]; then
		echo "not-green $notgreen"
	else
		echo "covered"
	fi
}

[[ $# -ge 1 ]] || usage
command="$1"
shift
case "$command" in
resolve) cmd_resolve "$@" ;;
coverage) cmd_coverage "$@" ;;
*) usage ;;
esac
