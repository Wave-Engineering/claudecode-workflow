#!/usr/bin/env bash
# gen-lock-find.sh — write the prose copies of the lock predicate (#1358).
#
# The trust gate's TRIVY prompt (skills/nextwave/gate.js) and the /precheck Job C
# fallback (skills/precheck/SKILL.md) cannot source lock-predicate.sh: a Workflow
# bundle is self-contained, and the fallback runs in repos without scripts/ci. So
# this script owns exactly these lines, and writes each from the predicate:
#
#   (a) gate.js            the find over <w>/tree
#   (b) gate.js            the main trivy scan of <w>/tree
#   (c) SKILL.md           the find over <repo_root>
#   (d) SKILL.md           the main trivy scan of <repo_root>
#   (e) kahuna-guide.md    the trust-signal list's trivy scan
#   (f) kahuna-devspec.md  the gate procedure's trivy scan
#
# Each line is found by an anchored regex that must match EXACTLY ONCE: zero or
# more than one exits 2, naming the file and the pattern, rather than guess.
#
# Usage:  scripts/ci/gen-lock-find.sh [--check] [repo_root]
#         Write mode rewrites the lines, then regenerates the per-wave bundle.
#         --check writes nothing, prints `DRIFT <file>: <expected>` per drifted
#         line, and exits 1 on any drift, 0 when every owned line matches.
# Exit:   0 in sync (or written), 1 drift (--check), 2 a line not found exactly once
set -uo pipefail

check=0
if [[ "${1:-}" == --check ]]; then
	check=1
	shift
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${1:-$(cd "$HERE/../.." && pwd)}"

if [[ ! -f "$HERE/lock-predicate.sh" ]]; then
	echo "gen-lock-find: lock-predicate.sh missing at $HERE" >&2
	exit 2
fi
# shellcheck source=scripts/ci/lock-predicate.sh
source "$HERE/lock-predicate.sh"

expr="$(lock_find_expr)"
skip="$(skip_dirs_args)"

# The rewrite runs in python with every string passed as argv: the find carries
# backslashes, and gate.js needs each one doubled inside its template literal,
# which sed would mangle.
# shellcheck disable=SC2016  # the $? and {} here are python's and the prose's, not the shell's
python3 -c '
import re, sys
root, check, expr, flags, skip = sys.argv[1], sys.argv[2] == "1", sys.argv[3], sys.argv[4], sys.argv[5]
js_expr = expr.replace("\\", "\\\\")
scan_w = f"trivy fs {flags} {skip} <w>/tree > <w>/trivy-0.json 2> <w>/trivy-0.err; echo \"exit=$?\""
scan_r = f"trivy fs {flags} {skip} <repo_root> > <marker_dir>/trivy-0.json 2> <marker_dir>/trivy-0.err; echo \"exit=$?\""
owned = [
    ("skills/nextwave/gate.js", r"^    `  find <w>/tree .+ -print`,$", lambda m: f"    `  find <w>/tree {js_expr}`,"),
    ("skills/nextwave/gate.js", r"^    `  trivy fs .* <w>/tree > <w>/trivy-0\.json .*`,$", lambda m: f"    `  {scan_w}`,"),
    ("skills/precheck/SKILL.md", r"^(\s+)find <repo_root> .+ -print$", lambda m: f"{m.group(1)}find <repo_root> {expr}"),
    ("skills/precheck/SKILL.md", r"^(\s+)trivy fs .* <repo_root> > <marker_dir>/trivy-0\.json .*$", lambda m: f"{m.group(1)}{scan_r}"),
    ("docs/kahuna-guide.md", r"^4\. `trivy fs .*` reports zero findings \(#1169\)$", lambda m: f"4. `trivy fs {flags} {skip}` reports zero findings (#1169)"),
    ("docs/kahuna-devspec.md", r"^(\s+)- `Bash\(\"trivy fs .* <repo_path>\"\)` \(cc-workflow#1169\)$", lambda m: f"{m.group(1)}- `Bash(\"trivy fs {flags} {skip} <repo_path>\")` (cc-workflow#1169)"),
]
texts, drift = {}, 0
for rel, pattern, render in owned:
    path = f"{root}/{rel}"
    if path not in texts:
        with open(path) as f:
            texts[path] = f.read()
    lines = texts[path].split("\n")
    hits = [i for i, line in enumerate(lines) if re.match(pattern, line)]
    if len(hits) != 1:
        print(f"gen-lock-find: {rel}: pattern {pattern} matched {len(hits)} lines, not exactly 1", file=sys.stderr)
        sys.exit(2)
    i = hits[0]
    want = render(re.match(pattern, lines[i]))
    if lines[i] != want:
        drift += 1
        if check:
            print(f"DRIFT {rel}: {want}")
        lines[i] = want
        texts[path] = "\n".join(lines)
if check:
    sys.exit(1 if drift else 0)
for path, text in texts.items():
    with open(path, "w") as f:
        f.write(text)
print(f"gen-lock-find: {drift} line(s) rewritten")
' "$ROOT" "$check" "$expr" "$TRIVY_PROSE_FLAGS" "$skip"
rc=$?
((rc == 0)) || exit "$rc"

# The bundle inlines gate.js, so it follows it.
if ((check == 0)); then
	node "$ROOT/skills/nextwave/bundle.mjs" >/dev/null || {
		echo "gen-lock-find: bundle.mjs failed" >&2
		exit 2
	}
fi
exit 0
