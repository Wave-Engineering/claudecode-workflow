#!/usr/bin/env bash
# autochain-gate.sh — the mechanical gate behind CLAUDE.md's "Exception: Approved
# Autochain". Decides whether /precheck may skip its human STOP for one issue.
#
# WHY THIS IS A SCRIPT AND NOT PROSE IN skills/autochain/SKILL.md (#1224).
#
# Autochain originally granted the approval in its own text: "A passing /precheck
# is automatic approval for /scpmmr." That is policy, it lived in a skill, and it
# contradicted /precheck Step 5, which STOPs on every non-kahuna branch. An agent
# following both skills held two opposite instructions and chose between them
# turn by turn. The approval BJ actually gives is real — approving a chain's
# order IS a pre-approval for the issues in it — so it is honoured, but by a
# check /precheck runs, not by whichever skill the agent read last.
#
# FAIL CLOSED. `check` answers "approved" in exactly one case: the state file
# exists, parses, is younger than the TTL, and lists the issue. Absent, unreadable,
# malformed, expired, a non-integer issue, an issue not in the list, a missing
# approval quote, an interpreter that will not start — every one of those is
# "not-approved", which leaves /precheck's human STOP exactly where it always was.
# A gate that can fail open is the wrong direction to be wrong in: the cost of a
# spurious STOP is a wait, the cost of a spurious approval is an unreviewed merge.
#
# THE APPROVAL NARROWS AS THE CHAIN RUNS. Approval attaches to a chain that is
# running, so it must not outlive it:
#   - `consume` removes each issue once it has merged, so a landed issue cannot be
#     re-approved by a later branch reusing its number; the last consume disarms.
#   - a TTL (AUTOCHAIN_TTL_HOURS, default 12) expires a chain whose agent died or
#     stopped without disarming. A chain that legitimately runs longer re-arms on
#     a fresh approval — the cheap side of the trade.
#
# The approval quote is REQUIRED at arm time and is read from a FILE. It is not
# verified — nothing here can prove BJ said it — but it puts his words on disk
# next to the issue list, so a merge made under this gate can always be traced to
# the approval it claimed. It is a file, not an argument, because a quote passed
# as a double-quoted shell argument has its backticks and $(...) EXECUTED by the
# caller's shell before this script ever sees it; write the file with a tool that
# never invokes a shell.
#
# Usage:
#   autochain-gate.sh arm     <repo_root> <epic> --approval-file <path> <issue>...
#   autochain-gate.sh check   <repo_root> <issue>
#   autochain-gate.sh consume <repo_root> <issue>
#   autochain-gate.sh disarm  <repo_root>
#
# Exit codes:
#   check:   0 approved (line 1 "approved <epic> armed_at=<ts>", line 2 "approval: <quote>")
#            1 not approved (prints "not-approved <reason>")
#   arm:     0 armed; 2 refused (bad arguments — nothing is written)
#   consume: 0 consumed or not listed; 2 state could not be rewritten
#   any:     2 usage

set -uo pipefail

STATE_REL=".claude/autochain-active.json"

usage() {
	sed -n '/^# Usage:/,/^# Exit codes:/p' "$0" | sed '$d; s/^# \{0,1\}//' >&2
	exit 2
}

is_posint() { [[ "$1" =~ ^[1-9][0-9]*$ ]]; }

# Keep the state file out of version control without touching any tracked file:
# info/exclude is per-clone and untracked, so a repo that does not already ignore
# .claude/ gets no diff noise. An approval quote is session material, and in a
# GitLab repo it would be the partner's.
ensure_ignored() {
	local repo="$1" exclude
	git -C "$repo" check-ignore -q "$STATE_REL" 2>/dev/null && return 0
	exclude="$(git -C "$repo" rev-parse --path-format=absolute --git-path info/exclude 2>/dev/null)" || return 0
	mkdir -p "$(dirname "$exclude")"
	printf '%s\n' "$STATE_REL" >>"$exclude"
}

cmd="${1:-}"
repo="${2:-}"
[[ -n "$cmd" && -n "$repo" ]] || usage
[[ -d "$repo" ]] || {
	echo "autochain-gate: repo_root '$repo' is not a directory" >&2
	exit 2
}
state="$repo/$STATE_REL"

case "$cmd" in
arm)
	epic="${3:-}"
	flag="${4:-}"
	approval_file="${5:-}"
	shift 5 2>/dev/null || usage
	is_posint "$epic" || {
		echo "autochain-gate: refusing to arm — epic '$epic' is not a positive integer" >&2
		exit 2
	}
	[[ "$flag" == "--approval-file" ]] || {
		echo "autochain-gate: refusing to arm — expected --approval-file <path>, got '$flag'" >&2
		exit 2
	}
	[[ -f "$approval_file" && -r "$approval_file" ]] || {
		echo "autochain-gate: refusing to arm — approval file '$approval_file' is not a readable file" >&2
		exit 2
	}
	[[ $# -gt 0 ]] || {
		echo "autochain-gate: refusing to arm — no issues listed" >&2
		exit 2
	}
	for n in "$@"; do
		is_posint "$n" || {
			echo "autochain-gate: refusing to arm — issue '$n' is not a positive integer" >&2
			exit 2
		}
	done
	mkdir -p "$(dirname "$state")"
	# JSON is built by the interpreter, never by string interpolation: the approval
	# quote is free text and may carry quotes, backslashes or backticks. The
	# interpreter also owns the empty-quote refusal, so the quote never transits bash.
	tmp="$(mktemp "$state.XXXXXX")" || exit 2
	python3 -I - "$tmp" "$epic" "$approval_file" "$@" <<'PY'
import json, sys, datetime
out, epic, approval_file, *issues = sys.argv[1:]
try:
    approval = open(approval_file, encoding="utf-8").read().strip()
except Exception as e:
    print(f"autochain-gate: refusing to arm — cannot read approval file: {e}", file=sys.stderr)
    sys.exit(3)
if not approval:
    print("autochain-gate: refusing to arm — the approval file is empty. Arm only on BJ's approval of the order, and record his words.", file=sys.stderr)
    sys.exit(3)
json.dump({
    "epic": int(epic),
    "issues": [int(i) for i in issues],
    "armed_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "approval": approval,
}, open(out, "w"), indent=2)
PY
	rc=$?
	if [[ $rc -ne 0 ]]; then
		rm -f "$tmp"
		[[ $rc -eq 3 ]] || echo "autochain-gate: failed to write state" >&2
		exit 2
	fi
	ensure_ignored "$repo"
	mv -f "$tmp" "$state"
	echo "armed epic #$epic for issue(s): $*"
	;;

check)
	issue="${3:-}"
	[[ -n "$issue" ]] || usage
	if ! is_posint "$issue"; then
		echo "not-approved issue '$issue' is not a positive integer"
		exit 1
	fi
	if [[ ! -f "$state" ]]; then
		echo "not-approved no armed chain ($STATE_REL absent)"
		exit 1
	fi
	# Any interpreter failure — including a non-zero exit after printing — falls
	# through to the not-approved branch below: `verdict` is emptied, and empty is
	# not "approved".
	verdict="$(
		python3 -I - "$state" "$issue" "${AUTOCHAIN_TTL_HOURS:-12}" 2>/dev/null <<'PY'
import json, sys, datetime
path, issue, ttl = sys.argv[1], int(sys.argv[2]), sys.argv[3]
def no(reason):
    print(f"not-approved {reason}"); sys.exit(0)
if not ttl.isdigit() or int(ttl) < 1:
    no(f"AUTOCHAIN_TTL_HOURS '{ttl}' is not a positive integer")
try:
    d = json.load(open(path, encoding="utf-8"))
except Exception:
    no("state file is unreadable or malformed")
if not isinstance(d, dict):
    no("state file is not a JSON object")
epic, issues, approval, armed_at = d.get("epic"), d.get("issues"), d.get("approval"), d.get("armed_at")
if not isinstance(epic, int) or isinstance(epic, bool) or epic < 1:
    no("state file has no valid epic")
if not isinstance(issues, list) or not all(isinstance(i, int) and not isinstance(i, bool) for i in issues):
    no("state file has no valid issue list")
if not isinstance(approval, str) or not approval.strip():
    no("state file carries no approval quote")
try:
    armed = datetime.datetime.strptime(armed_at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.timezone.utc)
except Exception:
    no("state file has no valid armed_at")
age = datetime.datetime.now(datetime.timezone.utc) - armed
if age < datetime.timedelta(minutes=-5):
    no(f"armed_at {armed_at} is in the future")
if age > datetime.timedelta(hours=int(ttl)):
    no(f"approval armed at {armed_at} has expired (TTL {ttl}h) — re-arm on a fresh approval")
if issue not in issues:
    no(f"issue #{issue} is not in the approved chain for epic #{epic}")
print(f"approved {epic} armed_at={armed_at}")
print("approval: " + " ".join(approval.split()))
PY
	)" || verdict=""
	case "$verdict" in
	"approved "*)
		echo "$verdict"
		exit 0
		;;
	"not-approved "*)
		echo "$verdict"
		exit 1
		;;
	*)
		echo "not-approved could not evaluate the state file"
		exit 1
		;;
	esac
	;;

consume)
	issue="${3:-}"
	is_posint "$issue" || usage
	if [[ ! -f "$state" ]]; then
		echo "not-listed no armed chain"
		exit 0
	fi
	tmp="$(mktemp "$state.XXXXXX")" || exit 2
	result="$(
		python3 -I - "$state" "$tmp" "$issue" <<'PY'
import json, sys
path, out, issue = sys.argv[1], sys.argv[2], int(sys.argv[3])
d = json.load(open(path, encoding="utf-8"))
issues = d["issues"]
if issue not in issues:
    print("not-listed"); sys.exit(0)
d["issues"] = [i for i in issues if i != issue]
json.dump(d, open(out, "w"), indent=2)
print("empty" if not d["issues"] else "consumed")
PY
	)" || result=""
	case "$result" in
	consumed)
		mv -f "$tmp" "$state"
		echo "consumed #$issue"
		;;
	empty)
		rm -f "$tmp" "$state"
		echo "consumed #$issue — chain complete, disarmed"
		;;
	not-listed)
		rm -f "$tmp"
		echo "not-listed #$issue"
		;;
	*)
		# Could not rewrite a state file we could not read: disarm rather than leave
		# an approval in place that we cannot narrow. Fail closed.
		rm -f "$tmp" "$state"
		echo "autochain-gate: could not consume #$issue — state unreadable, disarmed" >&2
		exit 2
		;;
	esac
	;;

disarm)
	rm -f "$state"
	echo "disarmed"
	;;

*)
	usage
	;;
esac
