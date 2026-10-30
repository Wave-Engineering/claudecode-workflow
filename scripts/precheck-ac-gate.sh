#!/usr/bin/env bash
# precheck-ac-gate.sh — the mechanical acceptance-criteria gate (#1365).
#
# Two of BJ's rules, which no tool enforced before this:
#   1. Every AC box is checked, or carries a waiver BJ already gave for it. The issue's
#      `## Acceptance Criteria` boxes and every box in the PR/MR body are graded.
#   2. No AC or DoD line may need a merge to assess (BJ, 2026-10-24). `lint` refuses one,
#      wherever it is written: /issue, /prepwaves, devspec upshift, and /precheck.
#
# /precheck runs `pr` as Job E and reads its exit code itself (#1275: no sub-agent relays a
# gate value).
#
# Usage:
#   precheck-ac-gate.sh lint <file>...
#       The post-merge lint over every checkbox line in each file. Exit 0 or 2.
#   precheck-ac-gate.sh boxes <label> <file> [--section "Acceptance Criteria" | --all]
#       The checkbox rule over one body: the boxes under that H2 (default), or every box.
#       Exit 0 or 1.
#   precheck-ac-gate.sh pr <repo_root> <PR_NUMBER> <ISSUE_N>
#       Fetch the PR/MR body, every issue it closes, and ISSUE_N; run `boxes` on each
#       (the issues by section, the PR/MR body --all) and `lint` on all of them.
#       Exit with the worst code, 4 > 2 > 1 > 0.
#
# Exit: 0 pass; 1 an unchecked box with no valid waiver, or an issue with no AC box at all;
#       2 a post-merge criterion; 3 usage; 4 a fetch or API error (never a pass).
#
# A waiver is the box's text ending, exactly, in
#   WAIVED by BJ <YYYY-MM-DD>: <reason> (<url>)
# with a real date no later than today (UTC). Only BJ waives. The script checks the
# waiver's form, never where it came from: /precheck puts every waiver on the checklist.
# A line ending in `<!-- ac-gate: pre-merge -->` passes the lint (the false-positive
# override), and is listed too. Boxes inside fenced code blocks are never graded.
#
# Platform and repository come from origin's URL, as in precheck-status.sh (never the
# CLI's own repo resolution). PRECHECK_PLATFORM and PRECHECK_HOST override, for tests.
set -uo pipefail

usage() {
	sed -n '/^# Usage:/,/^# Exit:/p' "$0" | sed 's/^# \{0,1\}//' >&2
	exit 3
}

PY=$(
	cat <<'PYEOF'
import datetime, json, re, sys

CHECKBOX = re.compile(r"^\s*[-*+]\s+\[( |x|X)\]\s+(.*)$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")
AC_H2 = re.compile(r"^##\s+Acceptance Criteria\b", re.I)
H2 = re.compile(r"^## ")
WAIVER = re.compile(r"\bWAIVED by BJ (\d{4}-\d{2}-\d{2}): (\S.*?) \((https?://[^\s)]+)\)\s*$")
OVERRIDE = re.compile(r"<!-- ac-gate: pre-merge -->\s*$")
POST_MERGE = [
    ("P1", re.compile(r"\bpost[- ]?(merge|install|release|deploy(ment)?)\b", re.I)),
    ("P2", re.compile(r"\bafter (the |this |a |its )?(pr|mr|merge|install(ation)?|release|deploy(ment)?|tag)\b", re.I)),
    ("P3", re.compile(r"\bmerged\b", re.I)),
    ("P4", re.compile(r"\b(ci|pipeline|build)s? (is |are )?(green|passing|passes|pass) on (main|master|trunk|the default branch|the protected branch)\b", re.I)),
    ("P5", re.compile(r"\b(released|tagged|deployed)\b", re.I)),
    ("P6", re.compile(r"\b(in prod(uction)?|on the (live )?fleet|observed live|in the wild)\b", re.I)),
]


def waiver(text):
    m = WAIVER.search(text)
    if not m:
        return None
    try:
        day = datetime.date.fromisoformat(m.group(1))
    except ValueError:
        return None
    if day > datetime.datetime.now(datetime.timezone.utc).date():
        return None  # a waiver is one already obtained, never a future one
    return m.group(1), m.group(3)


def boxes(body):
    """Yield (line_no, checked, text, in_ac) for every checkbox outside a fence."""
    fence = None
    in_ac = False
    for n, line in enumerate(body.splitlines(), 1):
        f = FENCE.match(line)
        if fence:
            # CommonMark: the same character, at least as long, and nothing after it.
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and not f.group(2).strip():
                fence = None
            continue
        if f:
            fence = f.group(1)
            continue
        if H2.match(line):
            in_ac = bool(AC_H2.match(line))
            continue
        m = CHECKBOX.match(line)
        if m:
            yield n, m.group(1) != " ", m.group(2), in_ac


def grade(ref, body, mode, lint):
    """mode: section | all | none (lint only). Returns (worst exit code, output lines)."""
    total = checked = waived = unchecked = post = 0
    out, code = [], 0
    for n, is_checked, text, in_ac in boxes(body):
        w = waiver(text)
        if mode == "none":  # lint: count every box, grade none of them
            total += 1
            waived += bool(w)
            checked += bool(is_checked and not w)
            unchecked += bool(not is_checked and not w)
        elif mode == "all" or in_ac:
            total += 1
            if w:
                waived += 1
                out.append(f"  [waived] {ref}:{n} BJ {w[0]} {w[1]}")
            elif is_checked:
                checked += 1
            else:
                unchecked += 1
                out.append(f"  [unchecked] {ref}:{n} {text}")
                code = max(code, 1)
        if lint and not w:
            hit = next((pid for pid, rx in POST_MERGE if rx.search(text)), None)
            if hit and OVERRIDE.search(text):
                out.append(f"  [override] {ref}:{n} {text}")
            elif hit:
                post += 1
                out.append(f"  [post-merge] {ref}:{n} {hit}: {text}")
                code = 2
        elif lint and w and not (mode == "all" or in_ac):
            # Every waiver reaches the checklist, graded box or not: the script checks its
            # form only, so BJ must see each one at the merge call.
            out.append(f"  [waived] {ref}:{n} BJ {w[0]} {w[1]}")
    if mode == "section" and total == 0:
        out.append(f"  [no-ac] {ref} no AC checkbox under ## Acceptance Criteria")
        code = max(code, 1)
    pm = str(post) if lint else "-"
    head = f"ac-gate: {ref} | boxes={total} checked={checked} waived={waived} unchecked={unchecked} post-merge={pm}"
    return code, [head] + out


def gh_bodies(slug, pr_path, issue_path, issue_n):
    pr = json.load(open(pr_path))
    node = (((pr.get("data") or {}).get("repository") or {}).get("pullRequest"))
    if not isinstance(node, dict):
        raise ValueError("the PR is not in the GraphQL answer")
    issue = json.load(open(issue_path))
    if not isinstance(issue, dict) or "number" not in issue:
        raise ValueError(f"issue #{issue_n} is not in the answer")
    items = [(f"PR {slug}#{pr_number}", node.get("body") or "", "all")]
    seen = {(slug.lower(), int(issue_n))}
    items.append((f"{slug}#{issue_n}", issue.get("body") or "", "section"))
    for c in node["closingIssuesReferences"]["nodes"]:
        repo = c["repository"]["nameWithOwner"]
        key = (repo.lower(), int(c["number"]))
        if key not in seen:
            seen.add(key)
            items.append((f"{repo}#{c['number']}", c.get("body") or "", "section"))
    return items


def gl_bodies(slug, mr_path, closes_path, issue_path, issue_n):
    mr = json.load(open(mr_path))
    closes = json.load(open(closes_path))
    issue = json.load(open(issue_path))
    if not isinstance(mr, dict) or "iid" not in mr:
        raise ValueError("the MR is not in the answer")
    if not isinstance(closes, list):
        raise ValueError("closes_issues is not a list")
    if not isinstance(issue, dict) or "iid" not in issue:
        raise ValueError(f"issue #{issue_n} is not in the answer")
    pid = mr.get("project_id")
    items = [(f"MR {slug}!{pr_number}", mr.get("description") or "", "all")]
    seen = {(pid, int(issue_n))}
    items.append((f"{slug}#{issue_n}", issue.get("description") or "", "section"))
    for c in closes:
        key = (c.get("project_id"), int(c["iid"]))
        if key not in seen:
            seen.add(key)
            ref = f"{slug}#{c['iid']}" if c.get("project_id") == pid else f"project {c.get('project_id')}#{c['iid']}"
            items.append((ref, c.get("description") or "", "section"))
    return items


cmd = sys.argv[1]
items, lint = [], True
if cmd == "lint":
    items = [(p, open(p).read(), "none") for p in sys.argv[2:]]
elif cmd == "boxes":
    label, path, mode = sys.argv[2], sys.argv[3], sys.argv[4]
    items, lint = [(label, open(path).read(), mode)], False
elif cmd == "pr":
    platform, slug, pr_number, issue_n = sys.argv[2:6]
    try:
        if platform == "github":
            items = gh_bodies(slug, *sys.argv[6:8], issue_n)
        else:
            items = gl_bodies(slug, *sys.argv[6:9], issue_n)
    except (ValueError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as e:
        print(f"ac-gate: cannot read the PR/MR and its issues: {e}", file=sys.stderr)
        print("VERDICT: FAIL")
        sys.exit(4)

worst = 0
for ref, body, mode in items:
    code, lines = grade(ref, body, mode, lint)
    worst = max(worst, code)
    print("\n".join(lines))
print("VERDICT: PASS" if worst == 0 else "VERDICT: FAIL")
sys.exit(worst)
PYEOF
)

cmd="${1:-}"
case "$cmd" in
lint)
	(($# >= 2)) || usage
	for f in "${@:2}"; do
		[[ -f "$f" ]] || {
			echo "no such file: $f" >&2
			exit 3
		}
	done
	exec python3 -c "$PY" lint "${@:2}"
	;;
boxes)
	(($# == 3 || $# == 4 || $# == 5)) || usage
	label="$2" file="$3" mode=section
	[[ -f "$file" ]] || {
		echo "no such file: $file" >&2
		exit 3
	}
	case "${4:-}" in
	"") ;;
	--all) mode=all ;;
	--section)
		[[ "${5:-}" == "Acceptance Criteria" ]] || usage
		;;
	*) usage ;;
	esac
	exec python3 -c "$PY" boxes "$label" "$file" "$mode"
	;;
pr) ;;
*) usage ;;
esac

# --- pr <repo_root> <PR_NUMBER> <ISSUE_N> -----------------------------------------------
(($# == 4)) || usage
repo="$2" pr_n="$3" issue_n="$4"
[[ "$pr_n" =~ ^[0-9]+$ && "$issue_n" =~ ^[0-9]+$ ]] || usage

fetch_fail() {
	echo "precheck-ac-gate: ${platform:-?} API call failed: $*" >&2
	echo "VERDICT: FAIL"
	exit 4
}

# Same resolution as precheck-status.sh: origin, never the CLI's own repo resolution.
url="$(git -C "$repo" remote get-url origin 2>/dev/null)" || {
	echo "no origin remote in $repo" >&2
	exit 3
}
host="${PRECHECK_HOST:-$(printf '%s' "$url" | sed -E 's#^[a-z+]+://##; s#^[^@/]*@##; s#[:/].*$##')}"
slug="$(printf '%s' "$url" | sed -E 's#^[a-z+]+://[^/]+/##; s#^[^@/]*@[^:/]+[:/]##; s#\.git$##; s#/$##')"
platform="${PRECHECK_PLATFORM:-}"
if [[ -z "$platform" ]]; then
	case "$host" in
	*github*) platform=github ;;
	*gitlab*) platform=gitlab ;;
	*)
		echo "cannot tell the platform from origin host '$host'; set PRECHECK_PLATFORM" >&2
		exit 3
		;;
	esac
fi
[[ "$platform" == gitlab && -z "$host" ]] && host=gitlab.com
enc="$(printf '%s' "$slug" | jq -sRr @uri)"

# glab exits 0 on an HTTP error and prints the error body (precheck-status.sh gl_api).
gl_api() {
	local out
	out="$(glab api --hostname "$host" "$@" </dev/null 2>/dev/null)" || return 1
	if printf '%s' "$out" | jq -e 'type == "object" and (has("message") or has("error"))
		and ([has("id", "iid", "web_url", "sha", "name", "path")] | any | not)' >/dev/null 2>&1; then
		return 1
	fi
	printf '%s' "$out"
}

tmp="$(mktemp -d)" || exit 4
trap 'rm -rf "$tmp"' EXIT

case "$platform" in
github)
	# shellcheck disable=SC2016 # GraphQL variables, not shell ones
	q='query($o: String!, $n: String!, $num: Int!) { repository(owner: $o, name: $n) { pullRequest(number: $num) { body closingIssuesReferences(first: 50) { nodes { number body repository { nameWithOwner } } } } } }'
	gh api graphql -f query="$q" -f o="${slug%%/*}" -f n="${slug#*/}" -F num="$pr_n" </dev/null >"$tmp/pr.json" 2>/dev/null ||
		fetch_fail "read PR #$pr_n"
	gh api "repos/$slug/issues/$issue_n" </dev/null >"$tmp/issue.json" 2>/dev/null || fetch_fail "read issue #$issue_n"
	python3 -c "$PY" pr github "$slug" "$pr_n" "$issue_n" "$tmp/pr.json" "$tmp/issue.json"
	;;
gitlab)
	gl_api "projects/$enc/merge_requests/$pr_n" >"$tmp/mr.json" || fetch_fail "read MR !$pr_n"
	gl_api "projects/$enc/merge_requests/$pr_n/closes_issues" >"$tmp/closes.json" || fetch_fail "read the issues MR !$pr_n closes"
	gl_api "projects/$enc/issues/$issue_n" >"$tmp/issue.json" || fetch_fail "read issue #$issue_n"
	python3 -c "$PY" pr gitlab "$slug" "$pr_n" "$issue_n" "$tmp/mr.json" "$tmp/closes.json" "$tmp/issue.json"
	;;
*)
	echo "unknown PRECHECK_PLATFORM '$platform'" >&2
	exit 3
	;;
esac
