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
# trivy covering none of them (bun.lock unsupported, flightdeck#8), and the
# pre-scan check with nothing to complain about. Two green checks either side of
# a stage prove nothing about the stage between them.
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
scannable_out="$(bash "$HERE/check-scannable.sh" "$ROOT" 2>&1)"
scannable_rc=$?
printf '%s\n' "$scannable_out"
if ((scannable_rc != 0)); then
	echo "dependency-scan: FAIL — nothing scannable and absence not declared" >&2
	exit 4
fi

# A DECLARED absence is a legitimate pass with nothing to ingest, so the
# present-but-uningested check below must not fire on it.
declared=0
if printf '%s' "$scannable_out" | grep -q "absence is DECLARED"; then
	declared=1
fi

# How many the PRE-scan found. Compared against the ingested count below, because
# "zero ingested" is only the extreme case: PARTIAL coverage is the same defect
# wearing a pass. cc-workflow itself is an instance — 2 scannable, 1 ingested,
# because this trivy cannot parse bun.lock either. Nothing said so before now.
scannable_n="$(printf '%s' "$scannable_out" |
	sed -n 's/^check-scannable: \([0-9][0-9]*\) scannable manifest.*/\1/p' | head -1)"
scannable_n="${scannable_n:-0}"

# --- the scan ------------------------------------------------------------------
# --skip-dirs MIRRORS check-scannable.sh's PRUNE list. Without it the two counts
# are over DIFFERENT file sets — it prunes node_modules/vendor/dist/... and trivy
# does not — so `coverage: N of M` would compare populations that do not
# correspond. In an npm repo with a populated node_modules, ingested VENDORED
# lockfiles could push N >= M while zero of the repo's own manifests were parsed,
# masking exactly the defect this script exists to find. It can also print the
# nonsense `coverage: 3 of 2`. Keep this list in step with check-scannable.sh.
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
# still exiting clean and still emitting a Results entry for the manifest —
# so `manifests` below reads nonzero and the "zero ingested" guard never
# fires. That is a silent false PASS, indistinguishable from a real one
# unless you check the package count, which is exactly the defect class
# this whole script exists to close. check-scannable.sh documents this same
# gap and explicitly leaves closing it to whatever runs the actual scan.
#
# --list-all-pkgs is ALSO required, not just --include-dev-deps: it only
# became trivy's default in v0.67.0, and this fleet pins no minimum trivy
# version — an older install never emits the Results[].Packages array this
# script reads without the flag, which would make every scan on any repo
# look like zero-packages-ingested and fail every precheck (cc-workflow#1169
# code review, ported here from /precheck's own Job C prompt).
trivy_err="$(mktemp)"
raw="$(timeout "${DEP_SCAN_TIMEOUT:-300}" trivy fs --scanners vuln --severity "$SEVERITY" \
	--include-dev-deps --list-all-pkgs \
	"${SKIP_DIRS[@]}" --format json --quiet "$ROOT" 2>"$trivy_err")"
trivy_rc=$?
if ((trivy_rc == 124)); then
	echo "dependency-scan: FAIL — trivy timed out after ${DEP_SCAN_TIMEOUT:-300}s (DB pull? network?)" >&2
	sed 's/^/    /' "$trivy_err" >&2
	rm -f "$trivy_err"
	exit 5
fi
if [[ -z "$raw" ]]; then
	# NOT exit 2. A scanner that failed is not a lockfile that could not be parsed,
	# and conflating them sends the operator hunting an ecosystem problem that does
	# not exist. Most likely cause is the vulnerability-DB pull: first run, offline
	# box, registry rate-limit, air-gap.
	echo "dependency-scan: FAIL — trivy produced no output (rc=$trivy_rc)" >&2
	sed 's/^/    /' "$trivy_err" >&2
	rm -f "$trivy_err"
	exit 5
fi
rm -f "$trivy_err"

# --- POST: what did it actually ingest? ----------------------------------------
# DENOMINATOR FIRST, on every path including the passing one — the same rule
# check-scannable.sh states for its own count. A verdict without the number that
# qualifies it is the failure this whole family of checks exists to prevent.
summary="$(printf '%s' "$raw" | python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except Exception as exc:
    print(f"PARSE_ERROR\t{exc}")
    raise SystemExit
results = doc.get("Results") or []
manifests, packages, findings = 0, 0, 0
lines = []
for r in results:
    target, rtype = r.get("Target", "?"), r.get("Type", "?")
    # --list-all-pkgs is passed explicitly above (cc-workflow#1169) rather than
    # relied on as a default: it only became trivy's default in v0.67.0, and
    # this fleet pins no minimum trivy version, so an older install would
    # otherwise leave Packages empty here on every repo, not just this one.
    pkgs = len(r.get("Packages") or [])
    vulns = len(r.get("Vulnerabilities") or [])
    manifests += 1
    packages += pkgs
    findings += vulns
    lines.append(f"  - {target}  ({rtype}, {pkgs} packages, {vulns} finding(s))")
print(f"COUNTS\t{manifests}\t{packages}\t{findings}")
for l in lines:
    print(f"LINE\t{l}")
for r in results:
    for v in (r.get("Vulnerabilities") or []):
        print("VULN\t{}\t{}\t{}\t{}".format(
            v.get("PkgName","?"), v.get("VulnerabilityID","?"),
            v.get("Severity","?"), v.get("FixedVersion") or "no fix available"))
')"

if printf '%s' "$summary" | grep -q '^PARSE_ERROR'; then
	echo "dependency-scan: FAIL — could not parse trivy output" >&2
	printf '%s\n' "$summary" >&2
	exit 2
fi

if ! printf '%s' "$summary" | grep -q '^COUNTS'; then
	# Without this guard the `${var:-0}` defaults below turn a python failure into
	# a confident "manifests present but ZERO ingested", complete with remediation
	# advice about lockfile formats. An unmeasured zero must never reach a verdict.
	echo "dependency-scan: FAIL — could not extract counts from trivy output" >&2
	printf '%s\n' "$summary" | head -5 >&2
	exit 5
fi
read -r _ manifests packages findings <<<"$(printf '%s' "$summary" | grep '^COUNTS' | head -1)"
manifests="${manifests:-0}"
packages="${packages:-0}"
findings="${findings:-0}"

# Scanner version alongside the counts. A coverage shortfall could be an
# ecosystem limit OR a stale binary, and the output cannot distinguish them
# without this — "a silently outdated scanner narrows coverage while reporting
# green" is this same defect class, one layer down.
echo "dependency-scan: scanner: $(trivy --version 2>/dev/null | head -1 | tr -d '\n')"
echo "dependency-scan: manifests ingested: ${manifests}"
printf '%s\n' "$summary" | sed -n "s/^LINE$(printf '\t')//p"
echo "dependency-scan: packages scanned: ${packages}"

# COVERAGE, stated explicitly. The two counts come from opposite sides of the
# scan and were never compared before; printing both without the comparison is
# how a shortfall stays invisible.
if ((scannable_n > 0)); then
	echo "dependency-scan: coverage: ${manifests} of ${scannable_n} scannable manifest(s) ingested"
	if ((manifests > 0)) && ((manifests < scannable_n)); then
		echo "dependency-scan: WARNING — $((scannable_n - manifests)) scannable manifest(s) NOT ingested." >&2
		echo "  A PASS below covers only what was ingested. The remainder is unscanned, not clean." >&2
	fi
fi

# --- the gap ------------------------------------------------------------------
# Manifests exist (check-scannable passed above) but the scanner covered none.
# Worded distinctly from "nothing scannable" because they are opposite conditions
# and previously both surfaced as an unremarkable green.
if ((manifests == 0)) && ((declared == 0)); then
	cat >&2 <<-MSG
		dependency-scan: FAIL — manifests are present but the scanner ingested ZERO of them.

		  This is NOT "nothing to scan" (check-scannable.sh passed, so input exists).
		  It is the scanner covering none of it — e.g. a lockfile format this trivy
		  build cannot parse. A pass here would be a scan over an empty denominator,
		  which is indistinguishable from a clean one.

		  Either use a scanner that understands this ecosystem, or declare the gap in
		  .no-scannable-dependencies with a reason.
	MSG
	exit 2
fi

if ((findings > 0)); then
	echo "dependency-scan: FINDINGS — ${findings} ${SEVERITY} across ${manifests} manifest(s)" >&2
	printf '%s\n' "$summary" | sed -n 's/^VULN\t/  /p' |
		awk -F'\t' '{printf "  %s | %s | %s | %s\n", $1, $2, $3, $4}' >&2
	exit 1
fi

verdict="dependency-scan: PASS — ${packages} package(s) across ${manifests} manifest(s), 0 ${SEVERITY}"
if ((scannable_n > manifests)); then
	verdict="${verdict} (COVERS ${manifests}/${scannable_n} — see WARNING above)"
fi
echo "$verdict"
exit 0
