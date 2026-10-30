# shellcheck shell=bash
# git-detect.sh — sourced by the PreToolUse Bash hooks that act on a git subcommand
# (pre-push-test-gate.sh, secret-scan-gate.sh). One detector, so the two hooks can
# never disagree about whether a command pushes or commits (#1234), or about what a
# branch delete is (#1364: git_push_delete_target, below).
#
# git_invokes <command> <subcommand> succeeds when <command> runs `git … <subcommand>`
# anywhere: after `cd X &&`, in a subshell, behind `sudo`, inside `bash -c "…"`, past
# git's global options. It is a text match, not a parse, so it over-matches (a commit
# message that says "git push") and never under-matches the forms above; both callers
# gate on a match, which makes over-matching the safe direction.
#
# `git` as a word (bare, or a path like /usr/bin/git, or quoted as in `bash -c "git …"`),
# then any of git's GLOBAL options — `-C <dir>` / `-c <k=v>` and the value-taking long
# options with a plain, double- or single-quoted value; the `--opt=value` forms; the
# flag-only ones — then the subcommand. Only real global options, so a subcommand's
# own flags (`git log --grep push`) are not mistaken for them.
# An option value is one shell word built from adjacent segments: plain characters, a
# backslash escape, a double- or single-quoted string, an unquoted `$( … )`, or a
# backtick substitution. So `core.sshCommand="ssh -i key"` (plain + quoted), `~/my\ repo`
# (plain + escape + plain), `$(git rev-parse --show-toplevel)` and `` `pwd -P` `` are each
# one value. `"$(dirname "$f")"` is one value as quoted `"$(dirname "` + plain `$f` +
# quoted `")"` — adjacency, not the `$( … )` segment, is what holds it together.
#
# Must stay bash-3.2-safe (stock macOS).
_dq='"'
_sq="'"
_bt='`'
# shellcheck disable=SC1003 # two literal backslashes: the ERE for one literal backslash
_bs='\\'
_optval="((${_bs}.|[^[:space:]${_dq}${_sq}${_bs}${_bt}]|${_dq}[^${_dq}]*${_dq}|${_sq}[^${_sq}]*${_sq}|${_bt}[^${_bt}]*${_bt}|\\\$\\([^)]*\\))+)"
_gopt_names="git-dir|work-tree|namespace|exec-path|config-env|super-prefix|shallow-file|attr-source"
_gopt_val="-[Cc]|--(${_gopt_names})"
_gopt_eq="--(${_gopt_names})=(${_optval})?"
_gopt_flag="-[pP]|--(no-pager|paginate|bare|no-replace-objects|no-lazy-fetch|no-optional-locks|no-advice|literal-pathspecs|glob-pathspecs|noglob-pathspecs|icase-pathspecs|exec-path)"
_gitopt="([[:space:]]+((${_gopt_val})[[:space:]]+${_optval}|${_gopt_eq}|${_gopt_flag}))*"

git_invokes() {
	local re="(^|[^[:alnum:]_.-])git${_gitopt}[[:space:]]+${2}([^[:alnum:]_-]|$)"
	# Match the command as bash will run it: a backslash-newline continuation joins lines.
	local in="${1//$'\\\n'/ }"
	[[ "$in" =~ $re ]]
}

# Refs an agent never pushes to or deletes without the user: protected and release
# branches, tags (v*), and any qualified name (heads/…, tags/…, refs/…).
# shellcheck disable=SC2034 # read by the gates that source this file
GIT_PROTECTED_REF_RE='^(main|master|develop|trunk|HEAD|release/.*|v[0-9].*|(heads|tags|remotes|refs)/.*)$'
# What a delete must never name: a superset, for deletes only (#1364 review). A bare-name
# delete resolves against every remote ref, tags included, so it also covers version
# names without a v (1.2.3, 12-fix), a bare release, release-*/release_*, stable,
# production, prod and gh-pages; git_push_delete_protected adds any local tag. Pushes
# keep the narrower set, so a project's numeric-led working branches still push.
GIT_PROTECTED_DELETE_RE='^(main|master|develop|trunk|HEAD|release|release[-_/].*|stable|production|prod|gh-pages|v?[0-9].*|(heads|tags|remotes|refs)/.*)$'
# What a plain push may carry after it: one `| tail -N` / `| head -N`, then redirections.
GIT_PUSH_TAIL_RE='[[:space:]]*\|[[:space:]]*(tail|head)([[:space:]]+-n)?([[:space:]]+-?[0-9]+)?[[:space:]]*$'
GIT_PUSH_REDIR_RE='[[:space:]]+(2>&1|[12]?>[[:space:]]*/dev/null|&>[[:space:]]*/dev/null)[[:space:]]*$'

# git_push_delete_target <command> succeeds, and prints the branch, only for a PLAIN,
# single-line, delete-only push of exactly ONE ref (#1364): `git [-C <path>] push
# <remote> --delete|-d <b>` or `git [-C <path>] push <remote> :<b>`, flags anywhere
# after `push`, a leading `refs/heads/` stripped. A delete publishes no commits, so
# neither gate needs a test run or a scan for one. It prints protected targets too:
# what a protected delete means is the caller's call.
git_push_delete_target() {
	local cmd="$1" tok ref="" remote="" del=0 refs=0 first=2
	local -a toks
	if [[ "$cmd" =~ $GIT_PUSH_TAIL_RE ]]; then
		cmd="${cmd%"${BASH_REMATCH[0]}"}"
	fi
	while [[ "$cmd" =~ $GIT_PUSH_REDIR_RE ]]; do
		cmd="${cmd%"${BASH_REMATCH[0]}"}"
	done
	case "$cmd" in
	*$'\n'* | *[\;\&\|\`\$\(\)\<\>\{\}\'\"\\]*) return 1 ;;
	esac

	read -ra toks <<<"$cmd"
	if [[ "${toks[1]:-}" == "-C" ]]; then
		[[ "${toks[2]:-}" =~ ^[A-Za-z0-9._/~-]+$ ]] || return 1
		first=4
	fi
	[[ "${toks[0]:-}" == "git" && "${toks[first - 1]:-}" == "push" ]] || return 1

	for tok in "${toks[@]:first}"; do
		case "$tok" in
		-q | --quiet | -v | --verbose | --no-verify | -n | --dry-run) continue ;;
		-d | --delete)
			del=$((del + 1))
			continue
			;;
		-*) return 1 ;;
		esac
		if [[ -z "$remote" ]]; then
			[[ "$tok" =~ ^[A-Za-z0-9._-]+$ ]] || return 1 # a plain remote name, not a URL
			remote="$tok"
			continue
		fi
		ref="$tok"
		refs=$((refs + 1))
	done
	[[ $del -le 1 && $refs -eq 1 ]] || return 1
	if [[ $del -eq 0 ]]; then
		[[ "$ref" == :* ]] || return 1
		ref="${ref#:}"
	fi
	ref="${ref#refs/heads/}"
	# A letter or digit first: `@`, `+x` and the like are revisions or force pushes.
	[[ "$ref" =~ ^[A-Za-z0-9][A-Za-z0-9._/@-]*$ ]] || return 1
	printf '%s\n' "$ref"
}

# git_push_delete_protected <cwd> <command> <target> succeeds when the target that
# git_push_delete_target printed must not be deleted: it matches GIT_PROTECTED_DELETE_RE,
# or it is a tag in the repository the push runs in (<cwd>, then the command's own
# `-C <path>`). Tags are fetched by default, so a local tag stands for the remote's. A
# lookup that errors for any reason other than "no such tag" counts as protected.
git_push_delete_protected() {
	local cwd="$1" target="$3" dir rc
	local -a toks
	[[ "$target" =~ $GIT_PROTECTED_DELETE_RE ]] && return 0
	read -ra toks <<<"$2"
	dir="$cwd"
	if [[ "${toks[1]:-}" == "-C" ]]; then
		dir="${toks[2]:-}"
		[[ "$dir" == \~ || "$dir" == \~/* ]] && dir="$HOME${dir#\~}"
		[[ "$dir" == /* ]] || dir="$cwd/$dir"
	fi
	git -C "$dir" rev-parse -q --verify "refs/tags/$target" >/dev/null 2>&1
	rc=$?
	[[ $rc -ne 1 ]] # 0: a tag; 1: no such tag; anything else: unreadable, so protected
}
