#!/usr/bin/env bash
# check-scannable.sh — fail when the dependency gate would examine NOTHING (#1073).
#
# WHY THIS EXISTS.
#
# A scan over zero manifests and a scan finding zero vulnerabilities produce the
# SAME verdict shape. On 2026-07-19 an agent reported "PASS — zero HIGH or
# CRITICAL" for a repo where trivy had parsed zero manifests; it had been masking
# an unscanned tree for months, and the gate's silence and the defect were the
# same event. cc-workflow itself then reported "0 manifests" on every /precheck
# for ELEVEN DAYS across FIVE filings (#922, #941, #944, #1053, #1056) — reported
# accurately every time, and read as noise every time, because an honest report
# that changes no outcome is indistinguishable from no report at all.
#
# So the denominator stops being advisory. If nothing is scannable, this exits 1.
#
# WHAT IT CHECKS — shapes, not filenames.
#
# The FILES are ecosystem-specific (bun.lock, go.sum, Cargo.lock, poetry.lock…)
# and pinning one repo's Python does nothing for a Go repo. But two SHAPES
# generalise, and they are the two that produced every filing above:
#
#   1. a package manifest with NO LOCKFILE beside it — the manifest carries
#      ranges (`^5.7.0`), and a range is not an installed version, so there is
#      nothing to match a CVE against;
#   2. a requirements.txt with UNPINNED entries — `flask` resolves to no version,
#      so the file parses to zero packages. Not a trivy limitation: there is
#      genuinely nothing to compare against a vulnerability database.
#
# ABSENCE MUST BE DECLARED, NOT INFERRED.
#
# Some repos legitimately have nothing to scan, and that must not read the same
# as "nobody pinned anything." A repo with genuinely no scannable dependencies
# writes .no-scannable-dependencies at its root, containing the reason. Exactly
# the shape of OAW_REQUIRED_SECRETS="" (#1061): declaring "none" is legitimate,
# OMITTING the declaration is not.
#
# WHAT IT DELIBERATELY DOES NOT DO.
#
# It does not run trivy and it does not judge vulnerabilities. It answers one
# question — "would a scan have anything to look at?" — so that a PASS from the
# real scanner means something. Keeping the two separate is the point: a gate
# that both measures and grades can hide an empty denominator inside a pass.
#
# Usage:  scripts/ci/check-scannable.sh [repo_root]
# Exit:   0 something is scannable, or absence is declared
#         1 nothing scannable and no declaration — the gate would examine nothing
set -uo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
# Resolved before the cd below: a relative BASH_SOURCE stops resolving after it.
PREDICATE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lock-predicate.sh"
cd "$ROOT" || {
	echo "check-scannable: cannot enter $ROOT" >&2
	exit 1
}

DECLARATION=".no-scannable-dependencies"

# THE PREDICATE lives in lock-predicate.sh (#1358): the prune list, the lock names,
# the requirements globs and the pin test. gate.js's trivySignalPrompt and
# SKILL.md's Job C fallback carry generated copies of the same find
# (scripts/ci/gen-lock-find.sh), so all three count the same locks.
if [[ ! -f "$PREDICATE" ]]; then
	echo "check-scannable: lock-predicate.sh missing (partial install?)" >&2
	exit 1
fi
# shellcheck source=scripts/ci/lock-predicate.sh
source "$PREDICATE"

scannable=0
declare -a REPORT=()

# --- every lock the predicate finds is counted (#1358) -----------------------
# Lock-centric, less two exclusions, the same on every path:
#
#   - a requirements file with no `==` pin is a range declaration, not a lock:
#     named UNSCANNABLE, not counted. `>=` and `~=` are ranges too.
#   - a bun.lockb with a bun.lock beside it is the same packages in bun's old
#     binary format: named as a duplicate, not counted. A bun.lockb ALONE is
#     counted, and dependency-scan.sh names it UNSCANNED (trivy cannot parse it).
#
# Presence is the test, not contents. A lockfile whose packages are all
# devDependencies scans as zero packages under trivy's DEFAULT invocation, so
# the scans pass --include-dev-deps (cc-workflow#1169); this script answers
# "would a scan have anything to look at", not "did the scan use the right flags".
#
# Every requirements file counts, though trivy's pip analyzer reads only a file
# named exactly `requirements.txt` (#1247). dependency-scan.sh scans each of the
# others alone under that name, and takes the list from the
# `[scannable] … pinned entr…` lines below.
while IFS= read -r lock; do
	[[ -n "$lock" ]] || continue
	if is_req_file "$lock"; then
		pinned="$(grep -cE "$PIN_RE" "$lock" 2>/dev/null || true)"
		entries="$(grep -cE '^[[:space:]]*[A-Za-z0-9._-]+' "$lock" 2>/dev/null || true)"
		if [[ "$pinned" =~ ^[0-9]+$ ]] && ((pinned > 0)); then
			scannable=$((scannable + 1))
			REPORT+=("  [scannable] $lock — $pinned pinned entr$([[ $pinned -eq 1 ]] && echo y || echo ies)")
		elif [[ "$entries" =~ ^[0-9]+$ ]] && ((entries > 0)); then
			REPORT+=("  [UNSCANNABLE] $lock — entries present but none pinned with '=='; trivy matches CVEs against versions")
		fi
	elif [[ "$(basename "$lock")" == bun.lockb && -f "$(dirname "$lock")/bun.lock" ]]; then
		REPORT+=("  [duplicate] $lock — bun.lock beside it carries the same packages")
	else
		scannable=$((scannable + 1))
		REPORT+=("  [scannable] $lock")
	fi
done < <(lock_find . | LC_ALL=C sort)

# --- diagnostics: a manifest with none of its locks beside it ----------------
# A manifest carries ranges (`^5.7.0`), and a range is not an installed version,
# so there is nothing to match a CVE against. Named, never counted.
prune_args=()
for d in "${LOCK_PRUNE[@]}"; do
	((${#prune_args[@]})) && prune_args+=(-o)
	prune_args+=(-name "$d")
done
for pair in "${MANIFEST_LOCKS[@]}"; do
	manifest_name="${pair%%:*}"
	IFS=, read -r -a locks <<<"${pair##*:}"
	while IFS= read -r manifest; do
		[[ -n "$manifest" ]] || continue
		dir="$(dirname "$manifest")"
		found_lock=""
		for l in "${locks[@]}"; do
			[[ -f "$dir/$l" ]] && {
				found_lock="$l"
				break
			}
		done
		[[ -n "$found_lock" ]] && continue
		if [[ "$manifest_name" == package.json ]]; then
			REPORT+=("  [UNSCANNABLE] $manifest — no lockfile beside it; a manifest carries ranges, not versions")
		else
			REPORT+=("  [UNSCANNABLE] $manifest — no ${locks[*]} beside it")
		fi
	done < <(find . \( "${prune_args[@]}" \) -prune -o -type f -name "$manifest_name" -print 2>/dev/null | LC_ALL=C sort)
done

# --- verdict ------------------------------------------------------------------
# DENOMINATOR FIRST, ALWAYS — before any verdict, and on every path including the
# passing one. The entire failure this guards against is a verdict printed
# without the count that qualifies it.
#
# dependency-scan.sh PARSES this output (#1247): every `  [scannable] ./<path>`
# line is its coverage denominator, by name, and their number must equal the
# count on the summary line. Keep both shapes. A reshaped line still fails
# safe there (exit 5, or the lock reported UNSCANNED), but it fails every scan
# that prints it.
echo "check-scannable: ${scannable} scannable manifest(s) in $ROOT"
((${#REPORT[@]})) && printf '%s\n' "${REPORT[@]}"

if ((scannable > 0)); then
	exit 0
fi

if [[ -s "$DECLARATION" ]]; then
	echo "check-scannable: nothing scannable, but absence is DECLARED in $DECLARATION:"
	sed 's/^/    /' "$DECLARATION"
	exit 0
fi

# An EMPTY declaration file is not a declaration. It is the same silence with a
# filename, and accepting it would rebuild the hole one layer out.
if [[ -f "$DECLARATION" ]]; then
	echo "check-scannable: $DECLARATION exists but is EMPTY — a declaration must carry a reason" >&2
fi

cat >&2 <<EOF
check-scannable: FAIL — nothing in this repo is scannable, and absence is not declared.

  A dependency scan over zero manifests and a scan finding zero vulnerabilities
  produce the same verdict shape. Until one of the following is true, a PASS from
  the scanner means nothing:

    * pin a requirements.txt with '==' (a range is not a version), or
    * commit the lockfile beside a package manifest, or
    * declare the absence deliberately:

        echo "why this repo has no scannable dependencies" > $DECLARATION

  Declaring "none" is legitimate. Omitting the declaration is not.
EOF
exit 1
