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
cd "$ROOT" || {
	echo "check-scannable: cannot enter $ROOT" >&2
	exit 1
}

DECLARATION=".no-scannable-dependencies"

# Prune vendored/build trees. A package.json inside node_modules is a
# DEPENDENCY's manifest, not ours: counting it would let a vendored tree satisfy
# the gate for a repo that pins nothing of its own, and every one of them reports
# UNSCANNABLE (they ship no lockfile), burying the repo's real state in noise.
#
# -name, NOT -path. The first cut used `-path ./node_modules`, which matches only
# a node_modules at the REPO ROOT — so ./scripts/wave-watcher/node_modules sailed
# through and five dependency manifests were judged as if they were ours.
# Directory NAME matches at any depth; a path pattern has to guess the depth.
PRUNE=(-name node_modules -o -name .git -o -name dist -o -name build
	-o -name vendor -o -name .venv -o -name venv -o -name target)

find_files() {
	find . \( "${PRUNE[@]}" \) -prune -o -type f -name "$1" -print 2>/dev/null
}

scannable=0
declare -a REPORT=()

# --- shape 1: a manifest with a lockfile beside it ---------------------------
# Presence of the lockfile is the test, not its contents. A lockfile whose
# packages are all devDependencies yields no trivy Results today (measured:
# scripts/wave-watcher), but the repo is still doing the right thing and the
# moment a runtime dependency lands it becomes scannable with no further action.
while IFS= read -r manifest; do
	[[ -n "$manifest" ]] || continue
	dir="$(dirname "$manifest")"
	found_lock=""
	for lock in bun.lock bun.lockb package-lock.json yarn.lock pnpm-lock.yaml; do
		[[ -f "$dir/$lock" ]] && {
			found_lock="$lock"
			break
		}
	done
	if [[ -n "$found_lock" ]]; then
		scannable=$((scannable + 1))
		REPORT+=("  [scannable] $dir/$found_lock")
	else
		REPORT+=("  [UNSCANNABLE] $manifest — no lockfile beside it; a manifest carries ranges, not versions")
	fi
done < <(find_files 'package.json')

for pair in "go.mod:go.sum" "Cargo.toml:Cargo.lock"; do
	manifest_name="${pair%%:*}"
	lock_name="${pair##*:}"
	while IFS= read -r manifest; do
		[[ -n "$manifest" ]] || continue
		dir="$(dirname "$manifest")"
		if [[ -f "$dir/$lock_name" ]]; then
			scannable=$((scannable + 1))
			REPORT+=("  [scannable] $dir/$lock_name")
		else
			REPORT+=("  [UNSCANNABLE] $manifest — no $lock_name beside it")
		fi
	done < <(find_files "$manifest_name")
done

# --- shape 2: requirements.txt with pinned entries ---------------------------
# `==` only. `>=` and `~=` are ranges, and a range is not an installed version,
# so they parse to nothing for the same reason a bare name does.
while IFS= read -r req; do
	[[ -n "$req" ]] || continue
	pinned="$(grep -cE '^[[:space:]]*[A-Za-z0-9._-]+[[:space:]]*===?[[:space:]]*[0-9]' "$req" 2>/dev/null || true)"
	entries="$(grep -cE '^[[:space:]]*[A-Za-z0-9._-]+' "$req" 2>/dev/null || true)"
	if [[ "$pinned" =~ ^[0-9]+$ ]] && ((pinned > 0)); then
		scannable=$((scannable + 1))
		REPORT+=("  [scannable] $req — $pinned pinned entr$([[ $pinned -eq 1 ]] && echo y || echo ies)")
	elif [[ "$entries" =~ ^[0-9]+$ ]] && ((entries > 0)); then
		REPORT+=("  [UNSCANNABLE] $req — entries present but none pinned with '=='; trivy matches CVEs against versions")
	fi
done < <(find_files 'requirements*.txt')

# --- verdict ------------------------------------------------------------------
# DENOMINATOR FIRST, ALWAYS — before any verdict, and on every path including the
# passing one. The entire failure this guards against is a verdict printed
# without the count that qualifies it.
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
