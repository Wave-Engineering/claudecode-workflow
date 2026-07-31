#!/usr/bin/env bash
# test_oaw_major.sh — #1067: the kit major is DERIVED, never a literal.
#
# The defect this guards: `OAW_MAJOR="${OAW_MAJOR:-1}"` sat in two scripts under a
# comment calling it "the kit major", while the kit was at 7.3.0. Every generation
# therefore shared namespace `1` and R-20's isolation did not hold. A wrong major
# does not error — Docker's create-if-missing turns an absent bind source into an
# empty DIRECTORY, so memory and caches come up blank with no warning.
set -uo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
SCRIPT="$REPO_DIR/scripts/ci/oaw-major.sh"
FAILS=0
pass() { echo "  [PASS] $1"; }
fail() {
	echo "  [FAIL] $1" >&2
	FAILS=$((FAILS + 1))
}

[[ -x "$SCRIPT" ]] || fail "oaw-major.sh is not executable (it is invoked directly)"
bash -n "$SCRIPT" || fail "bash -n failed on oaw-major.sh"
pass "syntax + executable"

# Derives from the git tag, and is NOT the old literal.
# Derivation needs a reachable tag. CI checks out shallow+--no-tags by default
# (validate.yml now sets fetch-depth: 0), but a contributor's shallow clone still
# will not have one — SKIP rather than hard-fail, and never inherit an ambient
# $OAW_MAJOR, which would silently turn this into an override test.
tag_major="$(git -C "$REPO_DIR" describe --tags --abbrev=0 2>/dev/null | sed 's/^v//' | cut -d. -f1)"
if [[ -n "$tag_major" ]]; then
	got="$(env -u OAW_MAJOR "$SCRIPT" 2>/dev/null)"
	[[ "$got" =~ ^[0-9]+$ ]] || fail "did not emit a numeric major, got: '$got'"
	[[ "$got" == "$tag_major" ]] ||
		fail "major '$got' does not match the repo tag major '$tag_major'"
	pass "derives the major from the repo tag (got $got)"
else
	echo "  [SKIP] no reachable tag (shallow clone) — derivation case not exercised"
fi

# The env override wins.
got="$(OAW_MAJOR=42 "$SCRIPT" 2>/dev/null)"
[[ "$got" == "42" ]] || fail "OAW_MAJOR override ignored, got '$got'"
pass "\$OAW_MAJOR overrides the derivation"

# NO literal fallback: outside a tagged checkout it must REFUSE, not guess.
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
git -C "$tmp" init -q 2>/dev/null
mkdir -p "$tmp/scripts/ci" && cp "$SCRIPT" "$tmp/scripts/ci/"
(cd "$tmp" && env -u OAW_MAJOR ./scripts/ci/oaw-major.sh >/dev/null 2>&1)
rc=$?
[[ "$rc" -eq 2 ]] ||
	fail "an untagged checkout must REFUSE (exit 2), got $rc — a silent guess is the defect"
pass "no literal fallback: untagged checkout refuses (exit 2)"

# --check refuses an unprovisioned major, and says how to migrate.
err="$(OAW_MAJOR=99999 "$SCRIPT" --check 2>&1 >/dev/null)"
rc=$?
[[ "$rc" -eq 3 ]] || fail "--check on an unprovisioned major must exit 3, got $rc"
grep -q 'NOT provisioned' <<<"$err" || fail "--check must say the major is unprovisioned"
grep -q 'EMPTY directories' <<<"$err" ||
	fail "--check must explain the SILENT failure (docker creates empty dirs)"
grep -q 'cp -a' <<<"$err" || fail "--check must give the migration recipe, not just refuse"
pass "--check refuses an unprovisioned major with the migration recipe"

# Consumers must not carry a hardcoded major.
for f in "$REPO_DIR/scripts/ci/dogfood-cutover.sh" "$REPO_DIR/scripts/ci/soak-accrual-bridge.sh"; do
	# Positive: it must DERIVE. A negative-only guard passes if someone re-hardcodes
	# to a different literal (${OAW_MAJOR:-7}, or a bare OAW_MAJOR=7), which is the
	# same defect wearing a new number.
	grep -q 'oaw-major.sh' "$f" ||
		fail "$(basename "$f") does not derive the major via oaw-major.sh"
	grep -qE 'OAW_MAJOR:-[0-9]' "$f" &&
		fail "$(basename "$f") hardcodes a major literal — derive via oaw-major.sh"
	grep -qE '^[[:space:]]*OAW_MAJOR=[0-9]' "$f" &&
		fail "$(basename "$f") assigns a bare major literal — derive via oaw-major.sh"
done
pass "every consumer derives the major; no literal fallback"

# The override must be validated, not passed through: a semver splits the namespace
# (mount_resolver coerces to the major int, profiles.py substitutes verbatim).
OAW_MAJOR=7.3.0 "$SCRIPT" >/dev/null 2>&1
[[ "$?" -eq 2 ]] || fail "a semver \$OAW_MAJOR must be refused (exit 2)"
pass "semver override refused (namespace-split guard)"

echo ""
if ((FAILS > 0)); then
	echo "  $FAILS oaw-major check(s) FAILED"
	exit 1
fi
echo "  all oaw-major checks passed"
