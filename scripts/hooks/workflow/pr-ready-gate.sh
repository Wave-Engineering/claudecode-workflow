#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# pr-ready-gate.sh — PreToolUse hook (Bash matcher): no ready PR/MR without a precheck pass.
#
# Since #1235, /precheck is the MR gate: agents commit and push working branches freely,
# and a PR/MR becomes READY (reviewable, mergeable) only on a precheck pass, recorded as
# the `precheck` commit status on its head (scripts/precheck-status.sh,
# docs/precheck-status.md). This hook is the gate for the CLI path. mcp-server-sdlc's
# pr_create / pr_ready are the same gate for the MCP path, from the release carrying #592. Gated:
#   gh pr create            unless --draft / -d
#   gh pr ready             unless --undo (that converts back to a draft)
#   glab mr create          unless --draft
#   glab mr update          EVERY form, unless --draft (and --ready always)
# Drafts are free: a draft cannot merge.
#
# WHY EVERY `glab mr update`. GitLab's draft state IS the title prefix (`Draft:`), and
# glab rewrites the title on most update flags (--title, --fill, --wip …), so a plain
# edit can make a draft ready. Modelling which flags keep the prefix failed four review
# passes running (#1235), so this gate doesn't try: an update passes only on a precheck
# pass, or with --draft, which keeps it a draft. The kit itself marks ready through REST,
# `precheck-status.sh mark-ready`, never glab's porcelain.
#
# WHAT IT IS NOT. A guard rail for the spellings agents write, not a parser of every
# argv gh and glab accept. It reads the separate, `=` and attached-value forms of the
# flags it needs; a stranger spelling, `gh api`, or a script it can't see goes past it.
# The backstops are at merge: /mmr checks the status on the head, and so does sdlc's
# pr_merge from the release carrying #592. A required `precheck` check is the platform-side end
# state. Seven review passes (#1235) each found another argv edge; past this point, a
# new one belongs at those layers, not here.
#
# WHICH REPO. The session's cwd, unless the command `cd`s first (`cd ../other && gh pr
# create`): then the last `cd`/`pushd` before the call. A target it cannot resolve
# (`cd "$X"`) blocks unless -R names the repository.
#
# WHOSE HEAD. `gh pr ready <n>` / `glab mr update <n> --ready` are checked against that
# PR/MR's real head SHA, asked of the platform (honouring -R/--repo, or the repository
# in a PR/MR URL), never the local HEAD, which may belong to another branch or repo. A
# create is checked against where the branch it opens from (--head / --source-branch,
# else the current branch) points on the platform, never the local origin/<branch>.
#
# INTEGRATION BRANCHES ARE EXEMPT. A head on kahuna/* (wave promotion) or campaign/*
# (campaign → protected), or a BASE on kahuna/* (a flight landing into its wave's
# integration branch), is governed by the wave trust gate (commutativity, merge-result
# CI, code review, trivy): nothing reaches a protected branch from kahuna/* except
# through it. Same rule as pre-push-test-gate.sh's integration refs (#724) and the
# kahuna sandbox auto-approval. The wave engine marks promotion drafts ready with
# `gh -R <repo> pr ready <n>`, and its prime node lands flights with pr_create.
#
# The match is a text match on `gh`/`glab` as a whole word (the same boundary as
# git-detect.sh), so a word in front of it never hides it: `timeout 60 gh …`,
# `env -u GH_TOKEN gh …`, `if gh …; then`, `xargs gh …`, `/usr/bin/gh …`. It tolerates
# flags before and after `pr`/`mr` (`gh -R o/r pr ready 5`). Draft flags are read with
# quoted values removed, so `--body "… -d …"` is not a draft. It over-matches a quoted
# mention rather than under-match an invocation. Fails closed: a head or a status that
# cannot be read blocks.
# Must stay bash-3.2-safe. Disable: PR_READY_GATE_DISABLED=1
set -uo pipefail

if [[ "${PR_READY_GATE_DISABLED:-0}" == "1" ]]; then
	exit 0
fi

INPUT=$(cat 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
[[ -n "$COMMAND" ]] || exit 0

case "$COMMAND" in
*gh*pr* | *glab*mr*) ;;
*) exit 0 ;;
esac

block() {
	jq -cn --arg r "$1" '{decision: "block", reason: $r}'
	exit 0
}

_lead='(^|[^[:alnum:]_.-])'
# Flags (with an optional value) between the tool, its noun and its verb.
_flags="([[:space:]]+(-[A-Za-z][^[:space:]]*|--[a-z][a-z-]*)(=[^[:space:]]*|[[:space:]]+[^-[:space:];&|][^[:space:];&|]*)?)*"
_word_end='([[:space:]]|$)'

# strip_quoted <text> — drop every "…" and '…' span, so a flag inside a value is no flag.
strip_quoted() {
	local s="$1" q="(\"[^\"]*\"|'[^']*')"
	while [[ "$s" =~ $q ]]; do
		s="${s/"${BASH_REMATCH[0]}"/ }"
	done
	printf '%s' "$s"
}

# has_flag <segment> <flag>... — any flag present as a whole word (or --flag=true),
# outside quoted values. `--draft=false` is not a draft.
has_flag() {
	local seg f
	seg=" $(strip_quoted "$1") "
	shift
	for f in "$@"; do
		case "$seg" in *" $f "* | *" $f=true "*) return 0 ;; esac
	done
	return 1
}

unquote() {
	local v="$1"
	v="${v#[\"\']}"
	v="${v%[\"\']}"
	printf '%s' "$v"
}

# Walk every gh-pr / glab-mr invocation; stop at the first that makes a PR/MR ready.
gated="" tool="" sub="" args="" prefix=""
norm="${COMMAND//$'\\\n'/ }"
rest="$norm"
re="${_lead}((gh)${_flags}[[:space:]]+pr${_flags}[[:space:]]+(create|ready)|(glab)${_flags}[[:space:]]+mr${_flags}[[:space:]]+(create|update))${_word_end}(.*)"
while [[ "$rest" =~ $re ]]; do
	m0="${BASH_REMATCH[0]}" # a suffix of $norm; has_flag's own =~ clobbers BASH_REMATCH
	whole="${BASH_REMATCH[2]}"
	tail="${BASH_REMATCH[${#BASH_REMATCH[@]} - 1]}"
	seg="${tail%%[;&|]*}"
	seg="${seg%%$'\n'*}"
	case "$whole" in
	gh*) t=gh ;;
	*) t=glab ;;
	esac
	s="${whole##*[[:space:]]}"
	# Flags written before the verb (`gh -R o/r pr ready 5`) belong to this call too.
	pre="${whole#* }"
	all="$pre $seg"
	hit=""
	case "$t:$s" in
	gh:create) has_flag "$all" --draft -d || hit=1 ;;
	gh:ready) has_flag "$all" --undo || hit=1 ;;
	glab:create) has_flag "$all" --draft || hit=1 ;;
	glab:update) { has_flag "$all" --ready -r || ! has_flag "$all" --draft; } && hit=1 ;;
	esac
	if [[ -n "$hit" ]]; then
		tool="$t" sub="$s" args="$all"
		prefix="${norm%"$m0"}"
		gated="$(printf '%s' "$whole" | tr -s '[:space:]' ' ')"
		break
	fi
	rest="$tail"
done
[[ -n "$gated" ]] || exit 0
headopt="--head" # the flag naming a create's source BRANCH, for the advice below
[[ "$tool" == glab ]] && headopt="--source-branch"

# tokenize <text> — split into toks[], keeping a '…' or "…" span as one token, so a
# quoted title's words never read as the PR/MR selector. No escapes, like the rest.
tokenize() {
	local s="$1" tok="" q="" c i have=0
	toks=()
	for ((i = 0; i < ${#s}; i++)); do
		c="${s:i:1}"
		if [[ -n "$q" ]]; then
			if [[ "$c" == "$q" ]]; then q=""; else tok+="$c"; fi
			continue
		fi
		case "$c" in
		\" | \')
			q="$c"
			have=1
			;;
		[[:space:]])
			if ((have)); then
				toks+=("$tok")
				tok="" have=0
			fi
			;;
		*)
			tok+="$c"
			have=1
			;;
		esac
	done
	if ((have)); then toks+=("$tok"); fi
}

# Parse -R/--repo, --head/--source-branch, and the first positional (the PR/MR selector).
tokenize "$args"
repo_flag="" head_flag="" base_flag="" sel=""
i=0
while ((i < ${#toks[@]})); do
	tk="${toks[$i]}"
	# glab's value-taking flags: their value is never the selector. glab's -H/--head is a
	# head REPOSITORY (gh's is a branch); glab's source branch is -s/--source-branch.
	if [[ "$tool" == glab ]]; then
		case "$tk" in
		-t | --title | -d | --description | --description-file | -l | --label | -u | --unlabel | -a | --assignee | \
			-m | --milestone | --reviewer | --state | --attach | -H | --head)
			i=$((i + 2))
			continue
			;;
		--head=* | -H?*)
			i=$((i + 1))
			continue
			;;
		esac
	fi
	case "$tk" in
	-R | --repo)
		repo_flag="${toks[$((i + 1))]:-}"
		i=$((i + 2))
		continue
		;;
	--repo=*) repo_flag="${tk#--repo=}" ;;
	-R?*)
		repo_flag="${tk:2}"
		repo_flag="${repo_flag#=}"
		;;
	-H | --head | -s | --source-branch)
		head_flag="${toks[$((i + 1))]:-}"
		i=$((i + 2))
		continue
		;;
	--head=* | --source-branch=*) head_flag="${tk#*=}" ;;
	# Shorthand with the value attached (`-Hx`, `-H=x`, `-sx`, `-s=x`): both CLIs accept it.
	-H?* | -s?*)
		head_flag="${tk:2}"
		head_flag="${head_flag#=}"
		;;
	-B | --base | -b | --target-branch)
		base_flag="${toks[$((i + 1))]:-}"
		i=$((i + 2))
		continue
		;;
	--base=* | --target-branch=*) base_flag="${tk#*=}" ;;
	pr | mr | create | ready | update) ;;
	-*) ;;
	*) [[ -z "$sel" ]] && sel="$tk" ;;
	esac
	i=$((i + 1))
done
repo_flag="$(unquote "$repo_flag")"
head_flag="$(unquote "$head_flag")"
base_flag="$(unquote "$base_flag")"
sel="$(unquote "$sel")"
# A PR/MR URL names its own repository: `gh pr ready https://github.com/o/r/pull/5`.
if [[ -z "$repo_flag" && "$sel" =~ ^(https?://[^/]+/.+)/(pull|-/merge_requests)/[0-9]+/?$ ]]; then
	repo_flag="${BASH_REMATCH[1]}"
fi

root="$(git -C "${CWD:-.}" rev-parse --show-toplevel 2>/dev/null || true)"

# A `cd` before the call moves it to another repository (see header): the last one wins.
cd_dir=""
p="$prefix"
# shellcheck disable=SC2016 # an ERE; the backtick is a literal character to match
cdre="(^|[;&|(\`{[:space:]\"'])(cd|pushd)[[:space:]]+([^;&|()<>\`[:space:]]+)" # a quote too: bash -c "cd x && …"
while [[ "$p" =~ $cdre ]]; do
	cd_dir="${BASH_REMATCH[3]}"
	p="${p#*"${BASH_REMATCH[0]}"}"
done
here="${CWD:-.}" # where the call runs, for the messages below
if [[ -n "$cd_dir" ]]; then
	d="$(unquote "$cd_dir")"
	here="the cd target '$d'"
	# shellcheck disable=SC2088 # a literal `~/` typed in the command, expanded by hand
	case "$d" in
	*'$'* | *'`'*)
		[[ -n "$repo_flag" ]] ||
			block "No ready PR/MR without a precheck pass (#1235). '$gated' runs after 'cd $d', which this gate cannot resolve, so it cannot tell which repository's head to check. Pass -R <owner/repo> (and, for a create, $headopt <branch>), or cd to a literal path."
		d=""
		;;
	"~") d="$HOME" ;;
	"~/"*) d="$HOME/${d#\~/}" ;;
	/*) ;;
	*) d="${CWD:-.}/$d" ;;
	esac
	root=""
	[[ -n "$d" ]] && root="$(git -C "$d" rev-parse --show-toplevel 2>/dev/null || true)"
fi
[[ -n "$root" || -n "$repo_flag" ]] ||
	block "No ready PR/MR without a precheck pass (#1235), and $here is not a git repository and no -R was given, so there is no head to check. Run it from the repo, or open it as a draft."

STATUS="$(dirname "$0")/../../precheck-status.sh"
[[ -x "$STATUS" ]] || block "No ready PR/MR without a precheck pass, and this gate cannot check one: precheck-status.sh is missing next to the kit's hooks. Re-run the kit's ./install, or open the PR/MR as a draft."

# A -R repository is asked about directly. `env` with no assignments is a no-op, so the
# arrays never expand empty (bash < 4.4 calls an empty "${a[@]}" unbound under set -u).
plat=github
[[ "$tool" == glab ]] && plat=gitlab
senv=(PRECHECK_NOOP=1)
[[ -n "$repo_flag" ]] && senv=(PRECHECK_SLUG="$repo_flag" PRECHECK_PLATFORM="$plat")

# exempt_if_integration — exits 0 for an integration head or base (see header).
exempt_if_integration() {
	case "$branch" in
	kahuna/* | campaign/*) exit 0 ;; # governed by the wave trust gate
	esac
	case "$base" in
	kahuna/*) exit 0 ;; # a flight into its wave's integration branch
	esac
}

# Resolve the head: sha + branch (+ base, where known).
sha="" branch="" base="$base_flag"
case "$tool:$sub" in
gh:ready | glab:update)
	if [[ -z "$sel" && -z "$root" ]]; then
		block "'$gated' names no PR/MR and $here is not a git repository, so there is no head to check (#1235)."
	fi
	info="$(env "${senv[@]}" "$STATUS" pr-head "${root:-.}" "$sel" 2>&1)" ||
		block "'$gated' makes a PR/MR ready, which needs a precheck pass on its head (#1235), and its head could not be read: $info"
	read -r sha branch base <<<"$info"
	exempt_if_integration
	;;
*)
	# With -R and --head the platform answers alone; otherwise the branch is the current one.
	if [[ -z "$root" && -z "$head_flag" ]]; then
		block "No ready PR/MR without a precheck pass (#1235): '$gated' opens from the current branch, and $here is not a git repository. Pass -R <owner/repo> and $headopt <branch>, or run it from the repo."
	fi
	[[ -n "$root" || -n "$repo_flag" ]] ||
		block "No ready PR/MR without a precheck pass (#1235): '$gated' names $headopt '$head_flag' but no -R, and $here is not a git repository."
	branch="${head_flag:-$(git -C "$root" rev-parse --abbrev-ref HEAD 2>/dev/null)}"
	exempt_if_integration
	sha="$(env "${senv[@]}" "$STATUS" branch-head "${root:-.}" "$branch" 2>&1)" ||
		block "'$gated' opens a ready PR/MR, which needs a precheck pass on its head (#1235), and where '$branch' points on the platform could not be read: $sha. Push it, or open it as a draft."
	;;
esac

[[ "$sha" =~ ^[0-9a-f]{40}$ ]] ||
	block "No ready PR/MR without a precheck pass (#1235): cannot resolve the head of '$gated' to a commit (got '${sha:-nothing}')."

state="$(env "${senv[@]}" "$STATUS" get "${root:-.}" "$sha" 2>&1)" ||
	block "No ready PR/MR without a precheck pass (#1235), and the precheck status of ${sha:0:12} could not be read: $state. Open it as a draft, or retry."
if [[ "$state" != success ]]; then
	block "'$gated' makes a PR/MR ready, which needs a precheck pass on its head (#1235), and ${sha:0:12} has precheck = $state. Open it as a draft (--draft), push freely, then run /precheck: on a pass it posts the status and marks the PR/MR ready (precheck-status.sh mark-ready). To edit a GitLab draft, add --draft to the glab mr update."
fi
exit 0
