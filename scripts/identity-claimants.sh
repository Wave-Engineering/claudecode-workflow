#!/usr/bin/env bash
# identity-claimants.sh — is another live session using this checkout's identity? (#1366)
#
# Usage: identity-claimants.sh <root>
#
# Identity is keyed by the checkout: <root>/.claude/agent-identity.json. Two sessions in
# one checkout read the same Dev-Name and both answer the same @name. This reads the
# process table, not a lease file. A lease goes stale, needs pid-reuse logic, and can't
# see a session that started before the lease code shipped. The process table keeps no
# state and is ground truth.
#
# A live claimant of <root> is a process of this user that is `claude` (its comm, or an
# argv running claude-code/cli.js), whose cwd resolves to <root>, and that is not this
# session's own claude or a claude above it in the ancestry. The OLDER process keeps the identity. The newcomer is the one
# told, because it can move to a worktree before it does anything.
#
# Prints one line:
#   none                      no other live claimant                          exit 0
#   older <pid>[,<pid>...]    another claimant started first: don't use it    exit 3
#   younger <pid>[,<pid>...]  others exist, all started later: keep it        exit 0
#   unknown <reason>          no proc tree, or this session's claude not found exit 0
#
# Test seams: IDENTITY_PROC_ROOT (default /proc) and IDENTITY_SELF_START_PID (default
# $PPID, which for the Bash tool and for a hook is the claude process or a shell under it).

set -uo pipefail

root="${1:?usage: identity-claimants.sh <root>}"
PROC="${IDENTITY_PROC_ROOT:-/proc}"

if [[ ! -d "$PROC" ]]; then
	echo "unknown no-proc"
	exit 0
fi

is_claude() { # <pid>; builtins only, since the scan calls it for every process of this user
	local comm argv
	{ read -r comm <"$PROC/$1/comm"; } 2>/dev/null || return 1
	[[ "$comm" == claude ]] && return 0
	{ mapfile -d '' -t argv <"$PROC/$1/cmdline"; } 2>/dev/null || return 1
	[[ " ${argv[*]-} " == *claude-code/cli.js* ]]
}

start_time() { # <pid> -> field 22 of stat, read after the last ')' so a comm with spaces can't shift it
	local stat rest
	stat="$(cat "$PROC/$1/stat" 2>/dev/null)" || return 1
	rest="${stat##*)}"
	# shellcheck disable=SC2086 # word-splitting the fields is the point
	set -- $rest
	# After ')' the fields start at 3 (state), so field 22 is the 20th.
	[[ $# -ge 20 ]] || return 1
	printf '%s\n' "${20}"
}

# This session's own claude: the first claude in the ancestry. Every claude further up is
# excluded too: a nested `claude -p` run from the checkout (a headless or bench run) is
# its parent session's child, not a rival, and its parent is always older.
self=""
declare -A ancestor=()
pid="${IDENTITY_SELF_START_PID:-$PPID}"
for _ in $(seq 64); do
	[[ "$pid" =~ ^[0-9]+$ && "$pid" -gt 0 ]] || break
	if is_claude "$pid"; then
		[[ -n "$self" ]] || self="$pid"
		ancestor[$pid]=1
	fi
	pid="$(awk '/^PPid:/ {print $2}' "$PROC/$pid/status" 2>/dev/null)"
done
if [[ -z "$self" ]]; then
	echo "unknown self-not-found"
	exit 0
fi
self_start="$(start_time "$self")" || {
	echo "unknown self-start-unreadable"
	exit 0
}

want="$(readlink -f -- "$root" 2>/dev/null || printf '%s' "$root")"
older=()
younger=()
for dir in "$PROC"/[0-9]*; do
	cand="${dir##*/}"
	[[ -n "${ancestor[$cand]-}" ]] && continue
	[[ -O "$dir" ]] || continue
	is_claude "$cand" || continue
	cwd="$(readlink -f -- "$dir/cwd" 2>/dev/null)" || continue
	[[ "$cwd" == "$want" ]] || continue
	st="$(start_time "$cand")" || continue
	if [[ "$st" -lt "$self_start" ]]; then
		older+=("$cand")
	else
		younger+=("$cand")
	fi
done

join() {
	local IFS=,
	printf '%s' "$*"
}
if [[ ${#older[@]} -gt 0 ]]; then
	echo "older $(join "${older[@]}")"
	exit 3
fi
if [[ ${#younger[@]} -gt 0 ]]; then
	echo "younger $(join "${younger[@]}")"
	exit 0
fi
echo "none"
