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
#       Fetch the PR/MR body and every issue it closes; run `boxes` on each (the issues
#       by section, the PR/MR body --all) and `lint` on all of them. ISSUE_N (`<n>`, or
#       `<path>#<n>` for another repository's issue) is graded when the PR/MR closes
#       nothing, or when the body names it in a Closes/Fixes/Resolves reference. Otherwise
#       it is graded as one of the closing issues, or listed as
#       `ac-gate: [info] <ref> is not among the closing issues; not graded` (#1397, #1407).
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
    # "tagged" only as a release tag (#1389): a version, release, rc or image before it (a closed
    # verb list between), "tagged release|version|rc", or a v-prefixed or dotted ref after it,
    # optionally quoted. A bare "tagged" is a tagged channel or the like, not a post-merge state.
    ("P5", re.compile(
        r"\b(released|deployed)\b"
        r"|\b((v\d+|\d+(\.\d+)+)\S*|releases?|versions?|rc|images?)\s+"
        r"(is |are |was |gets? |got |has been |is being |is then |will be )?tagged\b"
        r"|\btagged (release|version|rc)s?\b"
        r"|\btagged\s+(as\s+|with\s+)?[\"'`]?(v\d|\d+\.\d|:\w)", re.I)),
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
        graded = mode == "all" or (mode == "section" and in_ac)
        if mode == "none":  # lint: count every box, grade none of them
            total += 1
            waived += bool(w)
            checked += bool(is_checked and not w)
            unchecked += bool(not is_checked and not w)
        elif graded:
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
        elif lint and w and not graded:
            # Every waiver reaches the output, graded box or not (a graded one is listed
            # above): the script checks its form only, so BJ must see each one.
            out.append(f"  [waived] {ref}:{n} BJ {w[0]} {w[1]}")
    if mode == "section" and total == 0:
        out.append(f"  [no-ac] {ref} no AC checkbox under ## Acceptance Criteria")
        code = max(code, 1)
    pm = str(post) if lint else "-"
    head = f"ac-gate: {ref} | boxes={total} checked={checked} waived={waived} unchecked={unchecked} post-merge={pm}"
    return code, [head] + out


def split_ref(slug, issue_ref):
    """ISSUE_N as `<n>` (this repository) or `<path>#<n>`. Returns (path, n)."""
    path, _, n = issue_ref.rpartition("#")
    return (path or slug), int(n)


# The gate grades what the merge will close: the PR/MR body and every closing issue (#1397,
# #1407; design fork resolved by babelfish 2026-10-31, option A). What the merge closes is
# the platform's closing list plus every Closes line in the body, because the post-merge
# rule closes each `Closes #N` in the description (ruling A refined by babelfish
# 2026-10-31). So ISSUE_N, the issue the branch names, is graded when the PR/MR closes
# nothing or when the body names it in a closing reference. Otherwise it is graded as one
# of the closing issues, or reported `[info]` and left alone: an issue the merge doesn't
# close isn't claimed done, and grading it (an epic, a same-numbered local issue) only
# produced false blocks.
def not_closed(ref):
    return f"ac-gate: [info] {ref} is not among the closing issues; not graded"


# GitHub links only a reference with its own keyword (`Closes #5, #6` links #5 alone), and
# GitLab's list can lag the description, so the body is read for every keyword form.
REF = r"(?:[A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)?#[0-9]+"
# Lists: `#5, #6`, `#5,#6`, `#5 and #6`, `#5, #6, and #7`.
SEP = r"(?:\s*,\s*(?:and\s+)?|\s+and\s+)"
CLOSES_RE = re.compile(
    rf"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b:?\s+({REF}(?:{SEP}{REF})*)", re.I)
REF_RE = re.compile(r"([A-Za-z0-9._-]+(?:/[A-Za-z0-9._-]+)+)?#([0-9]+)")


def body_closes(body, slug, path, n, aliases=()):
    """Whether the body names `<path>#<n>` in a closing-keyword reference. `aliases` are other
    names of `path` (a renamed repository). Only ISSUE_N is looked for, per the ruling: a
    body-only reference to some other issue is not fetched or graded here."""
    names = {path.lower(), *(a.lower() for a in aliases)}
    for m in CLOSES_RE.finditer(body):
        for p, num in REF_RE.findall(m.group(1)):
            if int(num) == n and (p or slug).lower() in names:
                return True
    return False


# A closing list as long as the page it came on may have more on the next page, and an
# ISSUE_N there would read as [info]. Fail closed rather than guess.
PAGE = 100


def gh_plan(slug, pr_path, issue_ref):
    """(items, refs, need, ref): the PR body and closing issues, and whether ISSUE_N is read."""
    pr = json.load(open(pr_path))
    repo_node = (pr.get("data") or {}).get("repository") or {}
    node = repo_node.get("pullRequest")
    if not isinstance(node, dict):
        raise ValueError("the PR is not in the GraphQL answer")
    # After a rename, origin's slug and the repository's own name differ; both name it.
    own = (repo_node.get("nameWithOwner") or slug).lower()
    path, n = split_ref(slug, issue_ref)
    body = node.get("body") or ""
    items, refs = [(f"PR {slug}#{pr_number}", body, "all")], set()
    conn = node["closingIssuesReferences"]
    closing = conn["nodes"]
    if conn.get("totalCount", len(closing)) > len(closing):
        raise ValueError(f"the PR closes {conn['totalCount']} issues, more than one page holds")
    for c in closing:
        repo = c["repository"]["nameWithOwner"]
        key = f"{repo}#{c['number']}".lower()
        if key in refs:
            continue
        refs.add(key)
        if repo.lower() == own:
            refs.add(f"{slug}#{c['number']}".lower())
        items.append((f"{repo}#{c['number']}", c.get("body") or "", "section"))
    ref = f"{path}#{n}"
    aliases = [own, slug] if path.lower() in (slug.lower(), own) else []
    need = ref.lower() not in refs and (not closing or body_closes(body, slug, path, n, aliases))
    return items, refs, need, ref


def gl_plan(slug, mr_path, closes_path, issue_ref):
    """(items, refs, need, ref): the MR description and closing issues, and whether ISSUE_N is read."""
    mr = json.load(open(mr_path))
    closes = json.load(open(closes_path))
    if not isinstance(mr, dict) or "iid" not in mr:
        raise ValueError("the MR is not in the answer")
    if not isinstance(closes, list):
        raise ValueError("closes_issues is not a list")
    if len(closes) >= PAGE:
        raise ValueError(f"the MR closes {len(closes)} issues, a full page; there may be more")
    pid = mr.get("project_id")
    path, n = split_ref(slug, issue_ref)
    body = mr.get("description") or ""
    items, seen, refs = [(f"MR {slug}!{pr_number}", body, "all")], set(), set()
    for c in closes:
        key = (c.get("project_id"), int(c["iid"]))
        if key in seen:
            continue
        seen.add(key)
        # Each closing issue is its own project's, keyed by project_id, never resolved in
        # the MR's project (#1407). Its full reference names it when GitLab gives one.
        full = (c.get("references") or {}).get("full")
        if full:
            ref = full
        elif c.get("project_id") == pid:
            ref = f"{slug}#{c['iid']}"
        else:
            # No path to name it by, so a `<path>#<n>` ISSUE_N can't match it and reads as an
            # [info] line. GitLab's closes_issues carries references.full, so this is a fallback.
            ref = f"project {c.get('project_id')}#{c['iid']}"
        refs.add(ref.lower())
        if c.get("project_id") == pid:
            refs.add(f"{slug}#{c['iid']}".lower())
        items.append((ref, c.get("description") or "", "section"))
    ref = f"{path}#{n}"
    need = ref.lower() not in refs and (not closes or body_closes(body, slug, path, n))
    return items, refs, need, ref


def plan(platform, slug, files, issue_ref):
    if platform == "github":
        return gh_plan(slug, files[0], issue_ref)
    return gl_plan(slug, files[0], files[1], issue_ref)


def bodies(platform, slug, files, issue_path, issue_ref):
    items, refs, need, ref = plan(platform, slug, files, issue_ref)
    if need:
        issue = json.load(open(issue_path))
        field = ("number", "body") if platform == "github" else ("iid", "description")
        if not isinstance(issue, dict) or field[0] not in issue:
            raise ValueError(f"issue {ref} is not in the answer")
        return items + [(ref, issue.get(field[1]) or "", "section")], []
    return items, ([] if ref.lower() in refs else [not_closed(ref)])


cmd = sys.argv[1]
items, info, lint = [], [], True
if cmd == "lint":
    items = [(p, open(p).read(), "none") for p in sys.argv[2:]]
elif cmd == "boxes":
    label, path, mode = sys.argv[2], sys.argv[3], sys.argv[4]
    items, lint = [(label, open(path).read(), mode)], False
elif cmd in ("need", "pr"):
    # need: print whether ISSUE_N must be read, so the shell fetches it (or fails, exit 4)
    # before grading. pr: grade, reading ISSUE_N's answer only when need said so.
    platform, slug, pr_number, issue_n = sys.argv[2:6]
    files = sys.argv[6:7] if platform == "github" else sys.argv[6:8]
    try:
        if cmd == "need":
            print("yes" if plan(platform, slug, files, issue_n)[2] else "no")
            sys.exit(0)
        items, info = bodies(platform, slug, files, sys.argv[-1], issue_n)
    except (ValueError, KeyError, TypeError, AttributeError, OSError, json.JSONDecodeError) as e:
        print(f"ac-gate: cannot read the PR/MR and its issues: {e}", file=sys.stderr)
        print("VERDICT: FAIL")
        sys.exit(4)

worst = 0
for ref, body, mode in items:
    code, lines = grade(ref, body, mode, lint)
    worst = max(worst, code)
    print("\n".join(lines))
for line in info:
    print(line)  # stdout, beside the ac-gate: lines, so /precheck's checklist carries it
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
[[ "$pr_n" =~ ^[0-9]+$ && "$issue_n" =~ ^([A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)+#)?[0-9]+$ ]] || usage
# ISSUE_N as `<path>#<n>` names another repository's issue; a bare `<n>` is origin's.
issue_num="${issue_n##*#}"
issue_path=""
[[ "$issue_n" == *#* ]] && issue_path="${issue_n%#*}"
# A `.` or `..` segment would walk the API path out of the repository it names.
[[ "/$issue_path/" =~ /\.\.?/ ]] && usage

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

# Whether ISSUE_N must be read: the PR/MR closes nothing, or its body names ISSUE_N in a
# closing reference (#1397). An unreadable answer is exit 4, never a skipped fetch.
need_issue() {
	local out
	out="$(python3 -c "$PY" need "$platform" "$slug" "$pr_n" "$issue_n" "$@")" || {
		[[ "$out" == *"VERDICT: FAIL"* ]] || out="${out:+$out$'\n'}VERDICT: FAIL"
		printf '%s\n' "$out"
		exit 4
	}
	[[ "$out" == yes ]]
}

case "$platform" in
github)
	# shellcheck disable=SC2016 # GraphQL variables, not shell ones
	q='query($o: String!, $n: String!, $num: Int!) { repository(owner: $o, name: $n) { nameWithOwner pullRequest(number: $num) { body closingIssuesReferences(first: 100) { totalCount nodes { number body repository { nameWithOwner } } } } } }'
	gh api graphql -f query="$q" -f o="${slug%%/*}" -f n="${slug#*/}" -F num="$pr_n" </dev/null >"$tmp/pr.json" 2>/dev/null ||
		fetch_fail "read PR #$pr_n"
	if need_issue "$tmp/pr.json"; then
		gh api "repos/${issue_path:-$slug}/issues/$issue_num" </dev/null >"$tmp/issue.json" 2>/dev/null ||
			fetch_fail "read issue $issue_n"
	fi
	python3 -c "$PY" pr github "$slug" "$pr_n" "$issue_n" "$tmp/pr.json" "$tmp/issue.json"
	;;
gitlab)
	gl_api "projects/$enc/merge_requests/$pr_n" >"$tmp/mr.json" || fetch_fail "read MR !$pr_n"
	gl_api "projects/$enc/merge_requests/$pr_n/closes_issues?per_page=100" >"$tmp/closes.json" ||
		fetch_fail "read the issues MR !$pr_n closes"
	# A same-numbered local issue is not the closing one (#1407): read ISSUE_N only when need says.
	if need_issue "$tmp/mr.json" "$tmp/closes.json"; then
		ienc="$enc"
		[[ -n "$issue_path" ]] && ienc="$(printf '%s' "$issue_path" | jq -sRr @uri)"
		gl_api "projects/$ienc/issues/$issue_num" >"$tmp/issue.json" || fetch_fail "read issue $issue_n"
	fi
	python3 -c "$PY" pr gitlab "$slug" "$pr_n" "$issue_n" "$tmp/mr.json" "$tmp/closes.json" "$tmp/issue.json"
	;;
*)
	echo "unknown PRECHECK_PLATFORM '$platform'" >&2
	exit 3
	;;
esac
