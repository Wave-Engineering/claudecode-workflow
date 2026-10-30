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

# --- #1247: pip locks in the other common layouts are counted ----------------
# The basename glob `requirements*.txt` missed the prefix form and the pip-tools
# directory layout: no count, no scan, no report. Each alone must satisfy the gate
# AND be listed by path, because dependency-scan.sh takes its scan list from these
# lines. A .in pip-tools input is ranges, not a lock, and must stay out.
for layout in dev-requirements.txt requirements/base.txt app/requirements/test.txt; do
	mkdir -p "$T/$(dirname "$layout")"
	printf 'flask==3.1.3\n' >"$T/$layout"
	out="$(bash "$GATE" "$T" 2>&1)"
	rc=$?
	if [[ "$rc" == "0" ]] && grep -qF "[scannable] ./$layout — 1 pinned entry" <<<"$out"; then
		ok "pinned $layout is counted and listed (#1247)"
	else
		no "pinned $layout must be counted and listed (rc=$rc): $out"
	fi
	rm -rf "${T:?}/${layout%%/*}"
done
mkdir -p "$T/requirements"
printf 'flask==3.1.3\n' >"$T/requirements/base.in"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "a pip-tools requirements/base.in is not a lock" ||
	no "requirements/base.in must not satisfy the gate (rc=$rc)"
rm -rf "$T/requirements"

# --- #1289: a Python lock alone is counted -----------------------------------
# A repo whose only lock was a uv.lock read "0 scannable" and was never scanned.
# Each lock trivy 0.74.0 ingests must satisfy the gate alone, at the root and
# nested, with or without a pyproject.toml beside it, and be listed by path,
# because dependency-scan.sh takes its denominator from these lines.
for lock in uv.lock poetry.lock Pipfile.lock py/uv.lock svc/api/poetry.lock app/Pipfile.lock; do
	mkdir -p "$T/$(dirname "$lock")"
	printf 'version = 1\n' >"$T/$lock"
	out="$(bash "$GATE" "$T" 2>&1)"
	rc=$?
	if [[ "$rc" == "0" ]] && grep -qxF "  [scannable] ./$lock" <<<"$out" &&
		grep -qF "check-scannable: 1 scannable manifest(s)" <<<"$out"; then
		ok "a lone $lock is counted and listed (#1289)"
	else
		no "a lone $lock must be counted and listed (rc=$rc): $out"
	fi
	rm -rf "${T:?}/${lock%%/*}"
done
mkdir -p "$T/py"
printf '[project]\nname = "p"\n' >"$T/py/pyproject.toml"
printf 'version = 1\n' >"$T/py/uv.lock"
out="$(bash "$GATE" "$T" 2>&1)"
rc=$?
[[ "$rc" == "0" ]] && grep -qxF "  [scannable] ./py/uv.lock" <<<"$out" &&
	ok "a uv.lock beside its pyproject.toml is counted once" ||
	no "a uv.lock beside its pyproject.toml must be counted (rc=$rc): $out"
# A pyproject.toml alone is often tool config (ruff, pytest), not a dependency
# manifest: it adds nothing to the count and no UNSCANNABLE line.
rm -f "$T/py/uv.lock"
out="$(bash "$GATE" "$T" 2>&1)"
rc=$?
[[ "$rc" == "1" ]] && ! grep -qF "pyproject.toml" <<<"$out" &&
	ok "a pyproject.toml with no lock is neither counted nor called UNSCANNABLE" ||
	no "a lone pyproject.toml must not count or be flagged (rc=$rc): $out"
rm -rf "$T/py"
# pdm.lock is left out on purpose: trivy 0.74.0 has no pdm analyzer and emits no
# Result for one, so counting it would fail every repo carrying it as UNSCANNED.
printf 'version = 1\n' >"$T/pdm.lock"
rc="$(run_gate "$T")"
[[ "$rc" == "1" ]] && ok "a pdm.lock is not counted (trivy 0.74.0 cannot read it, #1289)" ||
	no "pdm.lock must stay uncounted until a trivy that reads it is measured (rc=$rc)"
rm -f "$T/pdm.lock"

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

# --- #1358: lock-centric counting, one predicate -----------------------------
# The count line, read without a pipe into the check (see run_gate).
count_of() {
	local out
	out="$(bash "$GATE" "$1" 2>&1)"
	sed -n 's/^check-scannable: \([0-9]*\) scannable.*/\1/p' <<<"$out"
}
L="$(mktemp -d)"
mkdir -p "$L/web"
printf '{}\n' >"$L/web/package-lock.json"
printf '# yarn lockfile v1\n' >"$L/web/yarn.lock"
[[ "$(count_of "$L")" == "2" ]] && ok "yarn.lock beside package-lock.json counts 2, not 1" ||
	no "a second JS lock must be counted (got $(count_of "$L"))"
rm -rf "${L:?}"/*

for lock in bun.lock go.sum Cargo.lock; do
	mkdir -p "$L/x"
	printf 'x\n' >"$L/x/$lock"
	[[ "$(count_of "$L")" == "1" ]] && ok "a lone $lock counts 1, no manifest needed" ||
		no "a lone $lock must count 1 (got $(count_of "$L"))"
	rm -rf "${L:?}"/*
done

printf '{}\n' >"$L/bun.lock"
printf '\0bun\0' >"$L/bun.lockb"
out="$(bash "$GATE" "$L" 2>&1)"
[[ "$(count_of "$L")" == "1" ]] && grep -q '\[duplicate\] ./bun.lockb' <<<"$out" &&
	ok "bun.lockb beside bun.lock counts 1, with a [duplicate] line" ||
	no "bun.lockb beside bun.lock must count once and say [duplicate]: $out"
rm -rf "${L:?}"/*

for f in requirements.lock dev-constraints.txt; do
	printf 'flask==3.0.0\n' >"$L/$f"
	out="$(bash "$GATE" "$L" 2>&1)"
	grep -q "\[scannable\] ./$f" <<<"$out" && ok "a pinned $f is scannable" ||
		no "a pinned $f must be scannable: $out"
	rm -f "$L/$f"
done

printf 'flask>=3\n' >"$L/requirements.lock"
rc="$(run_gate "$L")"
out="$(bash "$GATE" "$L" 2>&1)"
[[ "$rc" == "1" ]] && grep -q '\[UNSCANNABLE\] ./requirements.lock' <<<"$out" &&
	ok "an unpinned requirements.lock is UNSCANNABLE" ||
	no "an unpinned requirements.lock must be UNSCANNABLE and fail (rc=$rc): $out"
rm -rf "$L"

P="$(mktemp -d)"
cp "$GATE" "$P/check-scannable.sh"
printf 'flask==3.0.0\n' >"$P/requirements.txt"
bash "$P/check-scannable.sh" "$P" >/dev/null 2>&1
rc=$?
[[ "$rc" == "1" ]] && ok "a missing lock-predicate.sh exits 1 (partial install)" ||
	no "a missing lock-predicate.sh must exit 1 (rc=$rc)"
rm -rf "$P"

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
