#!/usr/bin/env bash
# precheck-notify-target.sh — who gets /precheck's merge-call notice: BJ, or a named lead (#1365).
#
# Under a lead, BJ does not make the merge call: the lead merges on its own precheck
# (CLAUDE.md, Lead-Agent Grant item 3). So the notice goes to the lead, by SendMessage,
# with no #precheck post and no vox. BJ approved this routing (claudecode-workflow:triage #15).
#
# The lead is the optional `lead` field of <repo_root>/.claude/agent-identity.json,
#   {"lead": {"session": "<ListAgents session name>", "dev_name": "<the lead's Dev-Name>"}}
# written by /grunt step 5, and kept by /name's merge.
#
# Usage: precheck-notify-target.sh <repo_root> <self_dev_name>
#
# Prints one line:
#   bj                        exit 0: no file, no `lead`, or the lead is <self_dev_name>
#                             (a lead running its own precheck in a grunt's worktree)
#   lead <session> <dev_name> exit 0: a valid lead naming someone else
#   bj                        exit 3: `lead` is malformed; the reason is on stderr
# Exit 2: usage.
set -euo pipefail

repo="${1:-}" self="${2:-}"
[[ -n "$repo" && -n "$self" ]] || {
	echo "Usage: precheck-notify-target.sh <repo_root> <self_dev_name>" >&2
	exit 2
}

f="$repo/.claude/agent-identity.json"
if [[ ! -f "$f" ]]; then
	echo bj
	exit 0
fi

# One jq pass: `none`, `ok <session> <dev_name>`, or `bad <reason>`. A file that is not
# JSON at all can't name a lead, so it is malformed too, never a quiet `bj`.
out="$(jq -r '
	def name_ok: type == "string" and test("^[A-Za-z0-9._-]+$");
	if type != "object" then "bad the identity file is not a JSON object"
	elif has("lead") | not then "none"
	elif (.lead | type) != "object" then "bad lead is not an object"
	elif (.lead.session | name_ok) | not then "bad lead.session is missing or not ^[A-Za-z0-9._-]+$"
	elif (.lead.dev_name | name_ok) | not then "bad lead.dev_name is missing or not ^[A-Za-z0-9._-]+$"
	else "ok \(.lead.session) \(.lead.dev_name)" end' "$f" 2>/dev/null)" || out="bad the identity file is not valid JSON"

case "$out" in
none)
	echo bj
	;;
ok\ *)
	read -r _ session dev <<<"$out"
	if [[ "$dev" == "$self" ]]; then
		echo bj
	else
		echo "lead $session $dev"
	fi
	;;
*)
	echo "precheck-notify-target: $f: ${out#bad }" >&2
	echo bj
	exit 3
	;;
esac
