# shellcheck shell=bash
# git-detect.sh — sourced by the PreToolUse Bash hooks that act on a git subcommand
# (pre-push-test-gate.sh, secret-scan-gate.sh). One detector, so the two hooks can
# never disagree about whether a command pushes or commits (#1234).
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
