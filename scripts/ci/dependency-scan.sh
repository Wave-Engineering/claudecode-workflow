#!/usr/bin/env bash
# dependency-scan.sh — run the scan, and report what it ACTUALLY covered (#1137).
#
# WHY THIS EXISTS, GIVEN check-scannable.sh ALREADY REPORTS A DENOMINATOR.
#
# They measure different denominators, on opposite sides of the scan:
#
#   check-scannable.sh   scannable manifests   "is there anything to scan?"   PRE
#   this script          packages ingested     "what did the scanner cover?"  POST
#
# Passing the first proves INPUT EXISTED. It does not prove the scanner ingested
# it. flightdeck sits in exactly that gap today: manifests present and countable,
# trivy covering none of them (flightdeck#8), and the pre-scan check with
# nothing to complain about. Two green checks either side of a stage prove
# nothing about the stage between them.
#
# cc-workflow#1169 code review: flightdeck#8's own root cause is worth
# re-measuring before it anchors a remedy — this script's own --include-dev-deps
# fix (below) turned an apparently-unparseable bun.lock into a fully-ingested
# one on THIS repo (see the comment on that flag). If flightdeck's tree is also
# dev-only, "trivy cannot parse bun.lock" may be the same flag artifact wearing
# a different name, not a real ecosystem gap #1141 needs to work around.
#
# The other half of the gap is that the kit never ran the scan at all. It lived
# only as PROSE in /precheck's Job C, instructing a sub-agent to report the
# denominator. An instruction can be forgotten by the next agent; a tool that
# emits the number cannot. That distinction is the whole subject of #1138 in a
# different costume — telemetry emitted by instruction rather than construction.
#
# EXIT CODES (distinct on purpose — "nothing to scan" and "scanned nothing" are
# opposite conditions that previously produced similar-looking green):
#
#   0  scanned, zero HIGH/CRITICAL
#   1  findings (HIGH/CRITICAL present)
#   2  MANIFESTS PRESENT BUT ZERO INGESTED  <- the gap this script exists to close
#   3  trivy not installed (skip; the caller decides whether that is acceptable)
#   4  nothing scannable AND absence not declared (delegated to check-scannable.sh)
#   5  SCANNER/TOOLING ERROR — timeout, no output, unparseable output, OR a
#      partial install missing this script's own check-scannable.sh sibling.
#      Distinct from 2 on purpose: a broken scanner is not an unparseable
#      lockfile, and conflating them sends the operator hunting an ecosystem
#      problem that does not exist. Ordinary triggers: first run pulling
#      trivy's vulnerability DB, a rate-limited or air-gapped network —
#      expect to hit this, and never treat an unmapped/unrecognized rc as a
#      pass.
#   6  PARTIAL COVERAGE — some of check-scannable.sh's locks ingested, at least
#      one named UNSCANNED (#1247). A pass over part of the denominator is not a
#      pass, because an unscanned lock is not a clean one. The trust gate's
#      trivyCoverage() HOLDs the same shape, so /precheck must not PASS it.
#      Findings exit 1 first, on any trivy Result.
#
# COVERAGE IS BY NAME (#1247). A lock is INGESTED only when a trivy Result names
# it and carries at least one package, the rule the trust gate and the /precheck
# fallback apply. Comparing counts let a Result check-scannable.sh never counts
# (poetry.lock, uv.lock, Gemfile.lock, ...) stand in for a lock it does count.
#
# A .no-scannable-dependencies declaration applies only when no lock is found:
# it rescues 4, never 2 or 6. The trust gate's trivyCoverage() rules the same,
# so a found-but-unscanned lock fails on every path, declared or not (#1247).
set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SEVERITY="${DEP_SCAN_SEVERITY:-HIGH,CRITICAL}"

if ! command -v trivy >/dev/null 2>&1; then
	echo "dependency-scan: SKIP — trivy not installed"
	exit 3
fi

# --- PRE: is there anything to scan? -------------------------------------------
# Delegated rather than reimplemented. check-scannable.sh owns the shapes
# (manifest-without-lockfile, unpinned requirements) and the declared-absence
# contract; duplicating that here would let the two drift into disagreeing.
#
# Existence checked explicitly (cc-workflow#1169 code review): `install`
# excludes ci/* from distribution today (#1141 is the fleet-wide follow-up),
# so a repo carrying this script without its sibling would otherwise hit
# bash's "No such file or directory" as rc=127 from `bash "$HERE/..."`,
# which the guard below reads as "nothing scannable" — sending the operator
# after a dependency-pinning problem that does not exist.
if [[ ! -f "$HERE/check-scannable.sh" ]]; then
	echo "dependency-scan: FAIL — check-scannable.sh missing at $HERE (partial install?)" >&2
	exit 5
fi
scannable_out="$(bash "$HERE/check-scannable.sh" "$ROOT" 2>&1)"
scannable_rc=$?
printf '%s\n' "$scannable_out"
if ((scannable_rc != 0)); then
	echo "dependency-scan: FAIL — nothing scannable and absence not declared" >&2
	exit 4
fi

# How many the PRE-scan found. Not the coverage test: coverage is matched lock by
# lock, by name, against trivy's Results below (#1247), and this number only checks
# that the `[scannable]` names read there are the whole counted set. "Zero
# ingested" is the extreme case: PARTIAL coverage is the same defect wearing a
# pass. cc-workflow itself was an instance before the --include-dev-deps
# fix below: 2 scannable (3 in a checkout carrying the gitignored .claude/ copy),
# only 1 ingested — not because trivy cannot parse bun.lock, but because both
# bun.lock manifests here are entirely devDependencies, which trivy suppresses
# by default. Nothing said so before now.
scannable_n="$(printf '%s' "$scannable_out" |
	sed -n 's/^check-scannable: \([0-9][0-9]*\) scannable manifest.*/\1/p' | head -1)"
scannable_n="${scannable_n:-0}"

# --- the scan ------------------------------------------------------------------
# --skip-dirs MIRRORS check-scannable.sh's PRUNE list, so trivy reads the file set
# check-scannable.sh counts: it prunes node_modules/vendor/dist/... and trivy,
# unasked, does not. Since coverage is matched by name (#1247), a VENDORED lockfile
# can no longer stand in for one of the repo's own (its Result is outside the
# denominator and covers nothing), but without this list its Results, and their
# findings, would still decide a verdict about dependencies the repo does not
# declare. Keep this list in step with check-scannable.sh.
SKIP_DIRS=(--skip-dirs "**/node_modules" --skip-dirs "**/dist" --skip-dirs "**/build"
	--skip-dirs "**/vendor" --skip-dirs "**/.venv" --skip-dirs "**/venv" --skip-dirs "**/target")

# `timeout` because trivy pulls its vulnerability DB on first run; a flaky network
# would otherwise turn validate.sh — which /precheck runs on every gate — into a
# hang rather than a failure. stderr is CAPTURED, not discarded: it is the only
# place trivy explains a DB-pull failure, and throwing it away is what made a
# scanner error indistinguishable from an unparseable lockfile.
# --include-dev-deps is REQUIRED, not optional (cc-workflow#1169): trivy
# suppresses dev/test dependencies by default, and a project whose entire
# dependency tree is dev-only (a bun-based tools repo is the measured case —
# @types/*, typescript, nothing else) scans ZERO packages without it, while
# still exiting clean and still emitting a Results entry for the manifest.
# Counted as a Result, that read as ingested: a silent false PASS, which is
# exactly the defect class this whole script exists to close. Matched by
# name below, a Result with no packages leaves its lock UNSCANNED, so
# without the flag every such repo would FAIL instead, on a lock that is
# fine. check-scannable.sh documents this same gap and explicitly leaves
# closing it to whatever runs the actual scan.
#
# --list-all-pkgs is ALSO required, not just --include-dev-deps: it only
# became trivy's default in v0.67.0, and this fleet pins no minimum trivy
# version — an older install never emits the Results[].Packages array this
# script reads without the flag, which would make every scan on any repo
# look like zero-packages-ingested and fail every precheck (cc-workflow#1169
# code review, ported here from /precheck's own Job C prompt).
#
# --ignorefile /dev/null (cc-workflow#1169 code review): trivy auto-loads a
# `.trivyignore` from the CURRENT WORKING DIRECTORY by default, which would
# make this scan's strictness depend on where it happens to be invoked from
# rather than on this script's own severity contract — and would let a
# committed .trivyignore silently suppress findings with nothing here
# checking for one. Forcing an empty ignore file makes "every HIGH/CRITICAL
# blocks, no suppression channel" actually true rather than merely intended.
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
trivy_err="$work/trivy.err"
TRIVY_FLAGS=(--scanners vuln --severity "$SEVERITY" --include-dev-deps --list-all-pkgs
	--ignorefile /dev/null --format json --quiet)

# Run trivy on $1 (extra flags after it); its JSON goes to stdout. A timeout or an
# empty answer exits 5 here, naming what was being scanned.
scan() {
	local target="$1" what="$2" out rc
	shift 2
	out="$(timeout "${DEP_SCAN_TIMEOUT:-300}" trivy fs "${TRIVY_FLAGS[@]}" "$@" "$target" 2>"$trivy_err")"
	rc=$?
	if ((rc == 124)); then
		echo "dependency-scan: FAIL — trivy timed out after ${DEP_SCAN_TIMEOUT:-300}s scanning ${what} (DB pull? network?)" >&2
		sed 's/^/    /' "$trivy_err" >&2
		exit 5
	fi
	if [[ -z "$out" ]]; then
		# NOT exit 2. A scanner that failed is not a lockfile that could not be parsed,
		# and conflating them sends the operator hunting an ecosystem problem that does
		# not exist. Most likely cause is the vulnerability-DB pull: first run, offline
		# box, registry rate-limit, air-gap.
		echo "dependency-scan: FAIL — trivy produced no output scanning ${what} (rc=$rc)" >&2
		sed 's/^/    /' "$trivy_err" >&2
		exit 5
	fi
	printf '%s' "$out"
}

raw="$(scan "$ROOT" "the repo" "${SKIP_DIRS[@]}")" || exit $?
printf '%s' "$raw" >"$work/main.json"

# --- pip locks trivy will not read under their own name (#1247) -----------------
# trivy's pip analyzer reads ONLY a file named exactly `requirements.txt`. Any
# other pip lock (requirements-dev.txt, dev-requirements.txt, the pip-tools
# requirements/base.txt) is skipped with no warning, though check-scannable.sh
# rightly counts it (its REQ_FIND matches all of them), so the coverage line
# below could never close. Measured: a dev lock of 209 packages, never examined.
#
# So each sibling is scanned ALONE: copied into an empty directory under the one
# name trivy reads, its results folded into the totals under its real path. The
# list is check-scannable.sh's own pinned-requirements report, so the set scanned
# here is the set counted there. A `-r other.txt` include is not followed, which
# is also true of trivy reading the file in place.
sed -n 's/^  \[scannable\] \.\/\(.*\) — [0-9][0-9]* pinned entr.*$/\1/p' <<<"$scannable_out" >"$work/pip-locks"
# The DENOMINATOR, by name: every lock check-scannable.sh printed as [scannable],
# repo-relative as trivy names its Targets. Its count must be the one it printed,
# or the names below are not the set that was counted.
sed -n 's/^  \[scannable\] \.\///p' <<<"$scannable_out" | sed 's/ — [0-9][0-9]* pinned entr.*$//' >"$work/denominator"
if [[ "$(grep -c . "$work/denominator")" != "$scannable_n" ]]; then
	echo "dependency-scan: FAIL — could not read check-scannable.sh's ${scannable_n} scannable lock(s) by name" >&2
	exit 5
fi
: >"$work/siblings.tsv"
n=0
while IFS= read -r lock; do
	[[ -n "$lock" && "$(basename "$lock")" != requirements.txt ]] || continue
	n=$((n + 1))
	# A lock that cannot be staged was never scanned: a tooling error (5), never
	# a silent skip that the coverage line would only later call partial.
	if ! mkdir "$work/sib-$n" || ! cp -- "$ROOT/$lock" "$work/sib-$n/requirements.txt"; then
		echo "dependency-scan: FAIL — could not stage ${lock} for its own scan" >&2
		exit 5
	fi
	sib_raw="$(scan "$work/sib-$n" "$lock")" || exit $?
	printf '%s' "$sib_raw" >"$work/sib-$n.json"
	printf '%s\t%s\n' "$lock" "$work/sib-$n.json" >>"$work/siblings.tsv"
done <"$work/pip-locks"

# --- POST: what did it actually ingest? ----------------------------------------
# DENOMINATOR FIRST, on every path including the passing one — the same rule
# check-scannable.sh states for its own count. A verdict without the number that
# qualifies it is the failure this whole family of checks exists to prevent.
summary="$(python3 -c '
import json, sys
main_path, siblings_path, denominator_path = sys.argv[1:4]
def load(path):
    with open(path) as f:
        return json.load(f)
try:
    docs = [(None, load(main_path))]
    with open(siblings_path) as f:
        for row in f:
            label, path = row.rstrip("\n").split("\t", 1)
            docs.append((label, load(path)))
except Exception as exc:
    print(f"PARSE_ERROR\t{exc}")
    raise SystemExit
with open(denominator_path) as f:
    denominator = [l.rstrip("\n") for l in f if l.strip()]
in_place = {r.get("Target") for r in (docs[0][1].get("Results") or [])}
results = []
for label, doc in docs:
    for r in doc.get("Results") or []:
        if label is not None:
            # A trivy that reads this sibling in place already counted it once.
            if label in in_place:
                continue
            r = dict(r, Target=label, _alone=True)
        results.append(r)
def names(lock):
    # trivy names a Go module by its go.mod (measured, trivy 0.74.0), while
    # check-scannable.sh counts the go.sum beside it; either name covers it.
    if lock == "go.sum" or lock.endswith("/go.sum"):
        return {lock, lock[: -len("go.sum")] + "go.mod"}
    return {lock}
# INGESTED by name: a Result carrying the name of the lock AND at least one package.
# An empty Packages list is a lock read as nothing, not a scanned one, and a
# Result for a file outside the denominator stands in for no counted lock.
# --list-all-pkgs is passed explicitly above (cc-workflow#1169) rather than
# relied on as a default: it only became a trivy default in v0.67.0, and this
# fleet pins no minimum trivy version, so an older install would otherwise
# leave Packages empty here on every repo, not just this one.
with_packages = {r.get("Target") for r in results if r.get("Packages")}
claimed, unscanned = set(), []
for lock in denominator:
    claimed |= names(lock)
    if not names(lock) & with_packages:
        unscanned.append(lock)
packages, findings, outside = 0, 0, 0
lines = []
for r in results:
    target, rtype = r.get("Target", "?"), r.get("Type", "?")
    pkgs = len(r.get("Packages") or [])
    vulns = len(r.get("Vulnerabilities") or [])
    packages += pkgs
    findings += vulns
    alone = "; scanned alone as requirements.txt" if r.get("_alone") else ""
    if target not in claimed:
        outside += 1
        alone += "; NOT in the denominator, so it covers no counted lock"
    lines.append(f"  - {target}  ({rtype}, {pkgs} packages, {vulns} finding(s){alone})")
ingested = len(denominator) - len(unscanned)
print(f"COUNTS\t{ingested}\t{len(denominator)}\t{packages}\t{findings}\t{len(results)}\t{outside}")
for l in lines:
    print(f"LINE\t{l}")
for r in results:
    for v in (r.get("Vulnerabilities") or []):
        print("VULN\t{}\t{}\t{}\t{}".format(
            v.get("PkgName","?"), v.get("VulnerabilityID","?"),
            v.get("Severity","?"), v.get("FixedVersion") or "no fix available"))
# Every counted lock no scan ingested is UNSCANNED, by name: a count alone says
# something is missing, not what.
for lock in unscanned:
    print(f"UNSCANNED\t{lock}")
' "$work/main.json" "$work/siblings.tsv" "$work/denominator")"

if printf '%s' "$summary" | grep -q '^PARSE_ERROR'; then
	# exit 5 (scanner error), NOT 2 (present-but-uningested): malformed JSON is
	# a broken scanner, not an unparseable lockfile — the same distinction
	# test_stub_scanner_error_exits_5_NOT_2 pins for the timeout/no-output
	# cases. Conflating them sends the operator hunting an ecosystem problem
	# that does not exist.
	echo "dependency-scan: FAIL — could not parse trivy output" >&2
	printf '%s\n' "$summary" >&2
	exit 5
fi

if ! printf '%s' "$summary" | grep -q '^COUNTS'; then
	# Without this guard the `${var:-0}` defaults below turn a python failure into
	# a confident "manifests present but ZERO ingested", complete with remediation
	# advice about lockfile formats. An unmeasured zero must never reach a verdict.
	echo "dependency-scan: FAIL — could not extract counts from trivy output" >&2
	printf '%s\n' "$summary" | head -5 >&2
	exit 5
fi
read -r _ ingested denom packages findings results_n outside <<<"$(printf '%s' "$summary" | grep '^COUNTS' | head -1)"
ingested="${ingested:-0}"
denom="${denom:-0}"
packages="${packages:-0}"
findings="${findings:-0}"
results_n="${results_n:-0}"
outside="${outside:-0}"

# Scanner version alongside the counts. A coverage shortfall could be an
# ecosystem limit OR a stale binary, and the output cannot distinguish them
# without this — "a silently outdated scanner narrows coverage while reporting
# green" is this same defect class, one layer down.
echo "dependency-scan: scanner: $(trivy --version 2>/dev/null | head -1 | tr -d '\n')"
echo "dependency-scan: manifests ingested: ${ingested}"
printf '%s\n' "$summary" | sed -n "s/^LINE$(printf '\t')//p"
echo "dependency-scan: packages scanned: ${packages}"
if ((outside > 0)); then
	echo "dependency-scan: ${outside} trivy Result(s) outside the denominator: listed, never counted toward coverage"
fi

# COVERAGE, stated explicitly and matched by name. The two sides of the scan
# were never compared before; printing both without the comparison is how a
# shortfall stays invisible.
if ((denom > 0)); then
	echo "dependency-scan: coverage: ${ingested} of ${denom} scannable manifest(s) ingested"
fi
unscanned="$(sed -n "s/^UNSCANNED$(printf '\t')//p" <<<"$summary")"
unscanned_n=0
if [[ -n "$unscanned" ]]; then
	unscanned_n="$(wc -l <<<"$unscanned" | tr -d ' ')"
	echo "dependency-scan: UNSCANNED — ${unscanned_n} lock(s) no scan ingested a package from:" >&2
	while IFS= read -r lock; do echo "  - $lock"; done <<<"$unscanned" >&2
	if ((ingested > 0)); then
		echo "dependency-scan: WARNING — ${unscanned_n} scannable manifest(s) NOT ingested." >&2
		echo "  The remainder is unscanned, not clean, so this run cannot pass." >&2
	fi
fi

# Findings first, from every trivy Result, inside the denominator or not: a CVE in
# a lock check-scannable.sh does not count is still a CVE.
if ((findings > 0)); then
	echo "dependency-scan: FINDINGS — ${findings} ${SEVERITY} across ${results_n} manifest(s)" >&2
	printf '%s\n' "$summary" | sed -n "s/^VULN$(printf '\t')/  /p" |
		awk -F'\t' '{printf "  %s | %s | %s | %s\n", $1, $2, $3, $4}' >&2
	exit 1
fi

# --- the gap ------------------------------------------------------------------
# Manifests exist (check-scannable passed above) but no scan covered any of them.
# Worded distinctly from "nothing scannable" because they are opposite conditions
# and previously both surfaced as an unremarkable green. A declaration never
# reaches here: it exists only when check-scannable.sh counted no lock.
#
# The remedy depends on the lock, so name the one that fits each UNSCANNED lock
# (#1247). trivy cannot parse bun.lockb at all. A pinned requirements file that
# yields nothing is malformed. Any other lock that yields nothing is malformed or
# has nothing in it: trivy 0.74.0 emits no Result for a dependency-free
# package-lock.json (measured), and the escape there is deleting the lockfile,
# never a declaration beside it.
if ((unscanned_n > 0)) && ((ingested == 0)); then
	cat >&2 <<-MSG
		dependency-scan: FAIL — manifests are present but the scanner ingested ZERO of them.

		  This is NOT "nothing to scan" (check-scannable.sh passed, so input exists).
		  It is the scanner covering none of it — e.g. a lockfile format this trivy
		  build cannot parse, or a lock with nothing in it. A pass here would be a
		  scan over an empty denominator, which is indistinguishable from a clean one.

	MSG
	if grep -qE '(^|/)bun\.lockb$' <<<"$unscanned"; then
		cat >&2 <<-MSG
			  bun.lockb is bun's old binary format, which trivy cannot parse. Switch to
			  bun's text lockfile, bun.lock (bun 1.2+ writes it).
		MSG
	fi
	if grep -qvE '(^|/)bun\.lockb$|\.txt$' <<<"$unscanned"; then
		cat >&2 <<-MSG
			  A lock trivy reads gave it no packages. If the package has no dependencies,
			  delete the empty lockfile: there is nothing to lock. If that leaves nothing
			  scannable, declare it in .no-scannable-dependencies with a reason.
			  Otherwise the lock is malformed, or this trivy build cannot parse it.
		MSG
	fi
	if grep -q '\.txt$' <<<"$unscanned"; then
		cat >&2 <<-MSG
			  A pinned requirements file trivy read no package from is malformed, or this
			  trivy build cannot parse it.
		MSG
	fi
	cat >&2 <<-MSG
		  A .no-scannable-dependencies declaration does not rescue a lock that is still
		  here: it covers only a repo where no lock is found.
	MSG
	exit 2
fi

# --- partial coverage (#1247) -------------------------------------------------
# Some ingested, some not. This used to exit 0 with a COVERS note, on the theory
# that a human reads the checklist; but Job C and the autochain gate both read
# exit 0 as PASS, so the note passed what the trust gate HOLDs. One rule on all
# three paths: a partial run is not a pass.
if ((unscanned_n > 0)); then
	echo "dependency-scan: FAIL — PARTIAL COVERAGE: ${ingested} of ${denom} scannable manifest(s) ingested, ${unscanned_n} lock(s) UNSCANNED (named above). An unscanned lock is not a clean one." >&2
	exit 6
fi

# Never reached with a shortfall: every counted lock was ingested by name.
echo "dependency-scan: PASS — ${packages} package(s) across ${results_n} manifest(s), 0 ${SEVERITY}"
exit 0
