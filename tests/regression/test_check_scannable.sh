#!/usr/bin/env bash
# test_check_scannable.sh — oracle for the dependency-scannability gate (#1073).
#
# The gate's whole job is to make an empty denominator FAIL instead of passing
# quietly, so the cases that matter are the failing ones. Each is built red-first
# in a throwaway tree — a gate only ever exercised against a healthy repo has not
# been tested, it has been admired.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
GATE="$REPO_DIR/scripts/ci/check-scannable.sh"

PASS=0
FAIL=0
ok() {
	printf '  [PASS] %s\n' "$1"
	PASS=$((PASS + 1))
}
no() {
	printf '  [FAIL] %s\n' "$1" >&2
	FAIL=$((FAIL + 1))
}

# Run the gate and report ONLY its exit code. Never pipe it here: `cmd | tail`
# yields tail's status, and an early draft of this file "verified" the failure
# paths through a pipe and read 0 for a gate that had correctly exited 1.
run_gate() {
	bash "$GATE" "$1" >/dev/null 2>&1
	echo $?
}

echo "test_check_scannable"
echo "──────────────────────────────────────────"

[[ -x "$GATE" ]] && ok "gate exists and is executable" || no "gate missing or not executable: $GATE"

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

# --- the defect itself: nothing to scan, nothing declared --------------------
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "empty tree with no declaration FAILS (rc=$rc)" ||
	no "empty tree must fail — an empty denominator is not a pass (rc=$rc)"

# --- unpinned requirements.txt is NOT scannable ------------------------------
mkdir -p "$T/app"
printf 'flask\nrequests\n' >"$T/app/requirements.txt"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "unpinned requirements.txt FAILS (a name is not a version)" ||
	no "unpinned requirements.txt must fail (rc=$rc)"

# A RANGE is not a version either — this is the case most likely to look pinned.
printf 'flask>=3.0\nrequests~=2.0\n' >"$T/app/requirements.txt"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "ranged requirements.txt FAILS ('>=' and '~=' are not versions)" ||
	no "ranged requirements.txt must fail (rc=$rc)"

printf 'flask==3.1.3\n' >"$T/app/requirements.txt"
rc="$(run_gate "$T")"
[[ "$rc" == "0" ]] && ok "pinned requirements.txt PASSES" ||
	no "a pinned requirements.txt must satisfy the gate (rc=$rc)"
rm -rf "$T/app"

# --- package.json without a lockfile is NOT scannable ------------------------
mkdir -p "$T/svc"
printf '{"name":"svc","dependencies":{"left-pad":"^1.0.0"}}\n' >"$T/svc/package.json"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "package.json with no lockfile FAILS (a range is not a version)" ||
	no "package.json without a lockfile must fail (rc=$rc)"

printf '{}\n' >"$T/svc/bun.lock"
rc="$(run_gate "$T")"
[[ "$rc" == "0" ]] && ok "package.json WITH a lockfile beside it PASSES" ||
	no "a lockfile beside the manifest must satisfy the gate (rc=$rc)"
rm -rf "$T/svc"

# --- vendored trees must not satisfy the gate --------------------------------
# A dependency's own lockfile is not evidence that WE pinned anything. This also
# guards the prune bug the first draft shipped: `-path ./node_modules` matches
# only a root-level node_modules, so a nested one leaked five dependency
# manifests in and reported them as the repo's own.
mkdir -p "$T/pkg/node_modules/dep"
printf '{"name":"dep"}\n' >"$T/pkg/node_modules/dep/package.json"
printf '{}\n' >"$T/pkg/node_modules/dep/bun.lock"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "a lockfile inside a NESTED node_modules does not satisfy the gate" ||
	no "vendored trees must be pruned at any depth, not just the root (rc=$rc)"
rm -rf "$T/pkg"

# --- absence must be DECLARED, not inferred ----------------------------------
echo "pure-shell repo; no package manager in use" >"$T/.no-scannable-dependencies"
rc="$(run_gate "$T")"
[[ "$rc" == "0" ]] && ok "a declaration carrying a reason PASSES" ||
	no "declaring 'none' is legitimate and must pass (rc=$rc)"

: >"$T/.no-scannable-dependencies"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "an EMPTY declaration FAILS (silence with a filename is still silence)" ||
	no "an empty declaration must not satisfy the gate (rc=$rc)"

# --- the denominator is always printed, including on success -----------------
# The failure this whole gate guards against is a verdict without the count that
# qualifies it, so the count must appear on the passing path too.
out="$(bash "$GATE" "$REPO_DIR" 2>&1)"
grep -qE 'scannable manifest\(s\)' <<<"$out" && ok "prints the denominator on the passing path" ||
	no "the denominator must be printed before any verdict"

echo ""
if ((FAIL > 0)); then
	echo "  $FAIL check(s) failed" >&2
	exit 1
fi
echo "  all checks passed"
