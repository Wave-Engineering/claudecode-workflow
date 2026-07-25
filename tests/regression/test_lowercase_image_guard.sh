#!/usr/bin/env bash
# test_lowercase_image_guard.sh — #1031.
#
# Two jobs in one file:
#   1. ENFORCE: the guard passes on the REAL tree — a capitalized image ref that lands
#      in the repo fails CI here (this is the actual guard).
#   2. PROVE: the guard actually catches capitalized + raw-owner refs, and ignores
#      whole-line comments — a probe only ever run on a clean tree is unverified.
# Fixtures are injected hermetically via the GUARD_FILES DI-seam (no git, no repo edits).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GUARD="$ROOT/scripts/ci/lowercase-image-guard.sh"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

pass=0
fail=0
check() { # want_exit  got_exit  label
	if [[ "$1" == "$2" ]]; then
		echo "  [PASS] $3"
		pass=$((pass + 1))
	else
		echo "  [FAIL] $3 (want exit $1, got $2)"
		fail=$((fail + 1))
	fi
}

# 1) ENFORCEMENT — the real tree must be all-lowercase.
"$GUARD" >/dev/null 2>&1
check 0 "$?" "real tree is all-lowercase"

# 2) a capitalized registry path is rejected.
printf 'IMAGE: ghcr.io/Wave-Engineering/oakandwave-workflow\n' >"$tmp/caps.yml"
GUARD_FILES="$tmp/caps.yml" "$GUARD" >/dev/null 2>&1
check 1 "$?" "capitalized path is rejected"

# 3) a raw repository_owner interpolation is rejected (the capital-generator).
# shellcheck disable=SC2016  # the literal ${{ … }} is the fixture — no expansion wanted
printf 'IMAGE: ghcr.io/${{ github.repository_owner }}/oakandwave-workflow\n' >"$tmp/owner.yml"
GUARD_FILES="$tmp/owner.yml" "$GUARD" >/dev/null 2>&1
check 1 "$?" "raw repository_owner is rejected"

# 4) a clean lowercase ref passes.
printf 'IMAGE: ghcr.io/wave-engineering/oakandwave-workflow\n' >"$tmp/ok.yml"
GUARD_FILES="$tmp/ok.yml" "$GUARD" >/dev/null 2>&1
check 0 "$?" "lowercase ref passes"

# 5) a whole-line comment naming the bad pattern is ignored (prose can't self-trip).
printf '# legacy: ghcr.io/Wave-Engineering used to break pulls\n' >"$tmp/comment.yml"
GUARD_FILES="$tmp/comment.yml" "$GUARD" >/dev/null 2>&1
check 0 "$?" "commented bad-ref is ignored"

# 6) an INLINE trailing comment naming the bad pattern is ignored — the code ref on the
#    same line is lowercase, only the comment carries the caps (#1031 review edge).
printf 'IMAGE: ghcr.io/wave-engineering/foo  # was ghcr.io/Wave-Engineering\n' >"$tmp/inline.yml"
GUARD_FILES="$tmp/inline.yml" "$GUARD" >/dev/null 2>&1
check 0 "$?" "inline-comment bad-ref is ignored"

echo "  $pass passed, $fail failed"
[[ "$fail" -eq 0 ]]
