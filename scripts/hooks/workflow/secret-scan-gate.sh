#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# secret-scan-gate.sh — PreToolUse hook (Bash matcher) that runs gitleaks before a
# `git commit` or `git push` (#1234).
#
# Plain pushes of working branches no longer wait for a test run (#1232), so the
# secrets check sits where the risk is. Every OaW repo is public: a pushed branch is
# published even if it never merges, and a secret added then deleted is still in history.
#
#   commit → two scans: the real index as it stands, and a throwaway index holding every
#            working-tree change and untracked, non-ignored file (GIT_INDEX_FILE + `git
#            add -A`; the real index is untouched). This hook runs BEFORE the command, so
#            for `git add -A && git commit` the real index does not hold the new files yet;
#            and the throwaway index alone misses a staged blob the working tree no longer
#            matches (`git add -p`, or staged and then edited). Together they cover what
#            the commit could contain, except a file `git add -f` forces in past
#            .gitignore in the same command: the push scan catches that one.
#   push   → scan every commit reachable from HEAD and from each local branch or tag
#            whose name appears as a word in the command (every branch for --all or
#            --mirror, every tag for --tags), minus everything already on a remote. A
#            commit already on a remote is published, so it needs no scan.
#
# Both are supersets on purpose: the hook never parses a refspec or a pathspec, so there
# is nothing in the command to get wrong (the lesson of #1232). It does NOT scan every
# unpushed branch: with squash merges, a merged branch whose remote branch was deleted
# keeps its commits off every remote forever, and one clone measured 108 of them.
#
# FAIL CLOSED. No gitleaks, no repository found, or a scan that errors → block. gitleaks
# exits 0 when the git command it runs fails (it logs `stderr is not empty` and writes an
# empty report), so its exit code is not trusted alone: any error-level output, an exit
# other than 0/1, or an unreadable report is a failed scan.
#
# Allowlisting a false positive: add `<file>:<rule>:<line>` to .gitleaksignore at the repo
# root (it suppresses that finding in both the commit and the push scan), or a rule
# allowlist in .gitleaks.toml. There is deliberately no bypass flag.
#
# The secret itself is never printed: gitleaks runs with --redact, and the block message
# carries only file, line, rule and commit.
#
# Must stay bash-3.2-safe (stock macOS).
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // empty' 2>/dev/null || true)
COMMAND=$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null || true)
CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
[[ -n "$CWD" ]] || CWD="$PWD"

# A detector that fails to load must not read as "no git command": that would switch the
# gate off with exit 0 and no notice (e.g. a hook firing mid-./install, while the kit's
# files are being redeployed). Without it, any command mentioning git is blocked.
if ! source "$(dirname "$0")/git-detect.sh" 2>/dev/null || ! declare -F git_invokes >/dev/null; then
	case "$COMMAND" in *git*)
		jq -cn '{decision: "block", reason: "Secret scan cannot run: its git-detect.sh helper did not load, so this command is blocked (the scan fails closed). Re-run the kit'"'"'s ./install, then retry."}'
		;;
	esac
	exit 0
fi
scan_commit=0
scan_push=0
git_invokes "$COMMAND" commit && scan_commit=1
git_invokes "$COMMAND" push && scan_push=1
if [[ $scan_commit -eq 0 && $scan_push -eq 0 ]]; then
	exit 0
fi

block() {
	if [[ -n "$SESSION_ID" ]]; then
		source "$(dirname "$0")/metrics.sh"
		log_metric "$SESSION_ID" "hook_block" "hook=secret-scan-gate" "reason=$2"
	fi
	jq -cn --arg r "$1" '{decision: "block", reason: $r}'
	exit 0
}

_mention="(This gate matches the text \`git commit\` / \`git push\` anywhere in a command. If this command only mentions one, e.g. in a commit message or an issue body, reword it or run it from the repository.)"

# PATH first, then where ./install puts it: ~/.local/bin, or <project>/.claude/bin under
# `install --local` (deliberately off PATH; this hook runs from <project>/.claude/scripts/
# hooks/workflow/, so that bin is three levels up).
GITLEAKS="$(command -v gitleaks 2>/dev/null || true)"
for _gl in "$HOME/.local/bin/gitleaks" "$(dirname "$0")/../../../bin/gitleaks"; do
	if [[ -z "$GITLEAKS" && -x "$_gl" ]]; then
		GITLEAKS="$_gl"
	fi
done
if [[ -z "$GITLEAKS" ]]; then
	block "Secret scan cannot run: gitleaks is not installed, so this commit/push is blocked (the scan fails closed). Install the kit's pinned version with the kit's ./install, or directly: <cc-workflow checkout>/scripts/ci/install-gitleaks.sh ~/.local/bin" "no-gitleaks"
fi

_cmd="${COMMAND//$'\\\n'/ }"

# --- Which repositories? ------------------------------------------------------------
# The hook's cwd, plus every plain `cd <dir>` target and `-C <dir>` value in the command:
# `cd ../other && git commit` and `git -C repo push` commit or push somewhere else. Again
# a superset, not a parse: a candidate that is not a git work tree is simply dropped.
_candidates=("$CWD")
_collect() {
	local rest="$_cmd" w
	while [[ "$rest" =~ $1 ]]; do
		w="${BASH_REMATCH[2]}"
		rest="${rest#*"${BASH_REMATCH[0]}"}"
		w="${w#[\"\']}"
		w="${w%[\"\']}"
		# shellcheck disable=SC2088 # a literal `~/` typed in the command, expanded by hand
		case "$w" in
		"~") w="$HOME" ;;
		"~/"*) w="$HOME/${w#\~/}" ;;
		/*) ;;
		*) w="$CWD/$w" ;;
		esac
		_candidates+=("$w")
	done
}
# shellcheck disable=SC2016 # EREs; the backticks are literal characters to match
_collect '(^|[;&|(`[:space:]])cd[[:space:]]+([^;&|()<>`[:space:]]+)'
# shellcheck disable=SC2016 # same
_collect '(^|[[:space:]])-C[[:space:]]+([^;&|()<>`[:space:]]+)'

tops=()
for c in "${_candidates[@]}"; do
	[[ -d "$c" ]] || continue
	t="$(git -C "$c" rev-parse --show-toplevel 2>/dev/null)" || continue
	[[ -n "$t" ]] || continue
	dup=0
	if [[ ${#tops[@]} -gt 0 ]]; then
		for s in "${tops[@]}"; do [[ "$s" == "$t" ]] && dup=1; done
	fi
	[[ $dup -eq 1 ]] || tops+=("$t")
done
if [[ ${#tops[@]} -eq 0 ]]; then
	block "Secret scan cannot run: no git repository found from $CWD or from a plain \`cd <dir>\` / \`-C <dir>\` in the command, so this commit/push is blocked (the scan fails closed). Run it from inside the repository. $_mention" "no-repo"
fi

# --- Scan ---------------------------------------------------------------------------
work="$(mktemp -d "${TMPDIR:-/tmp}/secret-scan-gate.XXXXXX")" || block "Secret scan cannot run: mktemp failed, so this commit/push is blocked (the scan fails closed)." "mktemp"
trap 'rm -rf "$work"' EXIT

findings=""
errors=""
# gitleaks v8.19 replaced `protect --staged` / `detect` with `git --staged` / `git`.
# Probing which one is installed costs a full gitleaks start-up (~0.5s on v8.30), so run
# the current CLI and fall back only when gitleaks says it has no `git` command.
old_cli=0

# _push_revs <top>: HEAD plus the local refs the command names, one per line.
# A whole word of the command: before it start, space, quote, `:`, `+` or `(`; after it
# end, space, quote, `:` or a shell operator (`;`, `&`, `|`, `)`, `<`, `>`, backtick), so
# `git push origin fix/x; git status` still names fix/x. Unquoted in the case patterns
# below so they stay bracket expressions.
_lb='[[:space:]"'"'"':+(]'
_tb='[[:space:]"'"'"':;&|)<>`]'
_push_revs() {
	local top="$1" ref name
	git -C "$top" rev-parse -q --verify HEAD >/dev/null 2>&1 && echo HEAD
	# --branches is git 2.46's name for --all.
	case " $_cmd " in *$_lb--all$_tb* | *$_lb--branches$_tb* | *$_lb--mirror$_tb*) echo --branches ;; esac
	case " $_cmd " in *$_lb--tags$_tb* | *$_lb--mirror$_tb*) echo --tags ;; esac
	git -C "$top" for-each-ref --format='%(refname)' refs/heads refs/tags 2>/dev/null | while IFS= read -r ref; do
		name="${ref#refs/heads/}"
		name="${name#refs/tags/}"
		case " $_cmd " in
		*$_lb"$name"$_tb* | *$_lb"${ref#refs/}"$_tb* | *$_lb"$ref"$_tb*)
			echo "$ref"
			;;
		esac
	done
}

# _run_gitleaks <top> <staged|range> <arg>: one scan, into $work/report.json. <arg> is the
# index file for a staged scan, the log options for a range scan.
_run_gitleaks() {
	local top="$1" mode="$2" opts="$3" rc
	local common=(--no-banner --redact -l error -f json -r "$work/report.json" -i "$top")
	rm -f "$work/report.json" "$work/stderr"
	if [[ $old_cli -eq 0 ]]; then
		if [[ "$mode" == staged ]]; then
			(cd "$top" && GIT_INDEX_FILE="$opts" "$GITLEAKS" git --staged "${common[@]}" "$top") >/dev/null 2>"$work/stderr"
		else
			(cd "$top" && "$GITLEAKS" git --log-opts="$opts" "${common[@]}" "$top") >/dev/null 2>"$work/stderr"
		fi
		rc=$?
		grep -q 'unknown command "git"' "$work/stderr" 2>/dev/null || return $rc
		old_cli=1
		rm -f "$work/report.json" "$work/stderr"
	fi
	if [[ "$mode" == staged ]]; then
		(cd "$top" && GIT_INDEX_FILE="$opts" "$GITLEAKS" protect --staged --source "$top" "${common[@]}") >/dev/null 2>"$work/stderr"
	else
		(cd "$top" && "$GITLEAKS" detect --source "$top" --log-opts="$opts" "${common[@]}") >/dev/null 2>"$work/stderr"
	fi
}

# _scan <top> <index|worktree|range>: append to $findings or $errors. `index` is the real
# index as staged now, `worktree` the throwaway one with every change added.
_scan() {
	local top="$1" mode="$2" glmode=range idx opts="" rc out rev unpushed
	if [[ "$mode" != range ]]; then
		idx="$(git -C "$top" rev-parse --path-format=absolute --git-path index 2>/dev/null)"
		if [[ "$mode" == index ]]; then
			[[ -n "$idx" && -f "$idx" ]] || return # nothing staged yet: the worktree scan covers it
			opts="$idx"
		else
			opts="$work/index"
			rm -f "$opts"
			if [[ -n "$idx" && -f "$idx" ]] && ! cp "$idx" "$opts"; then
				errors+="  $top: could not copy the index"$'\n'
				return
			fi
			if ! GIT_INDEX_FILE="$opts" git -C "$top" add -A >/dev/null 2>"$work/stderr"; then
				errors+="  $top: git add -A into a scratch index failed: $(head -c 300 "$work/stderr" | tr '\n' ' ')"$'\n'
				return
			fi
		fi
		glmode=staged # both index scans are gitleaks staged scans; $mode still names which
	else
		while IFS= read -r rev; do
			opts+="$rev "
		done < <(_push_revs "$top")
		[[ -n "$opts" ]] || return # nothing to push from
		opts+="--not --remotes"
		# A failed rev-list is a failed scan, never "nothing unpushed" (e.g. a named tag
		# pointing at a tree).
		# shellcheck disable=SC2086 # opts is a list of ref names and fixed flags
		if ! unpushed="$(git -C "$top" rev-list -n 1 $opts 2>"$work/stderr")"; then
			errors+="  $top: git rev-list failed: $(head -c 300 "$work/stderr" | tr '\n' ' ')"$'\n'
			return
		fi
		[[ -n "$unpushed" ]] || return # nothing unpushed
	fi
	_run_gitleaks "$top" "$glmode" "$opts"
	rc=$?
	if [[ -s "$work/stderr" || ($rc -ne 0 && $rc -ne 1) ]] || ! jq -e 'type == "array"' "$work/report.json" >/dev/null 2>&1; then
		errors+="  $top ($mode scan, exit $rc): $(head -c 300 "$work/stderr" 2>/dev/null | tr '\n' ' ')"$'\n'
		return
	fi
	if [[ $rc -eq 1 && "$(jq 'length' "$work/report.json")" == "0" ]]; then
		errors+="  $top ($mode scan): gitleaks reported leaks but wrote none"$'\n'
		return
	fi
	out="$(jq -r --arg top "$top" '.[] | "  \($top)/\(.File):\(.StartLine)  rule \(.RuleID)" + (if (.Commit // "") != "" then "  commit \(.Commit[0:8])" else "" end) + "  [allowlist key \(.File):\(.RuleID):\(.StartLine)]"' "$work/report.json")"
	[[ -n "$out" ]] && findings+="$out"$'\n'
}

for top in "${tops[@]}"; do
	if [[ $scan_commit -eq 1 ]]; then
		_scan "$top" index
		_scan "$top" worktree
	fi
	[[ $scan_push -eq 1 ]] && _scan "$top" range
done

if [[ -n "$errors" ]]; then
	block "Secret scan failed, so this commit/push is blocked (the scan fails closed):
${errors}Fix the cause and retry. $_mention" "scan-error"
fi

if [[ -n "$findings" ]]; then
	findings="$(printf '%s' "$findings" | sort -u)"
	n="$(printf '%s\n' "$findings" | grep -c .)"
	list="$(printf '%s\n' "$findings" | head -20)"
	[[ $n -gt 20 ]] && list+=$'\n'"  …and $((n - 20)) more"
	block "Secret scan blocked this commit/push: gitleaks found $n possible secret(s). The values are not shown.
${list}
What was scanned: for a commit, what is staged now plus everything the commit could include if all changes were staged; for a push, every commit on HEAD or on a branch or tag the command names that is not yet on a remote. Remove the secret. If it is in a commit, rewrite that commit; a later commit that deletes it does not help, because the push carries both. If it is a false positive, add its allowlist key to .gitleaksignore at the repository root, or allowlist the rule in .gitleaks.toml." "leak"
fi
exit 0
