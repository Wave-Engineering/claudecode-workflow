#!/usr/bin/env bash
# compat-guard.sh — the mechanical compat-break guard, wired to git
# (Story 3.4 / #973, Plan #959, Dev Spec §5.8, R-18/R-19).
#
# The live CI gate: it sources the shared-state schema's committed BASELINE and
# diffs the working-tree CANDIDATE against it, then hands both to the unit-tested
# decision module. If the candidate is a same-major-breaking change that did NOT
# bump the major — the silent minor ship R-19 forbids — the guard trips and this
# wrapper exits non-zero, blocking the change.
#
# The DECISION lives in containers/oakandwave-workflow/compat_guard.py (fail-loud
# on a malformed schema; blocks only a silent same-major break or a version
# regression). This wrapper only *sources* the baseline from git and *applies* the
# verdict as an exit code — the guard logic stays in the tested module, never in
# this shell (project rule: decisions in a tested module, not the wrapper).
#
# Inputs (env):
#   COMPAT_GUARD_BASE_REF   the git ref holding the baseline schema to diff against
#                           (default: origin/main). On a first-ever commit of the
#                           schema — or when the ref lacks the file — there is no
#                           baseline; the guard self-validates the candidate only.
#   COMPAT_GUARD_SCHEMA     repo-root-relative path to the schema
#                           (default: containers/oakandwave-workflow/state-schema.json).
#   COMPAT_GUARD_REPO       the git checkout whose schema is under guard
#                           (default: the CWD's git toplevel). The TOOL
#                           (compat_guard.py) is always this repo's module;
#                           overriding the repo lets the wrapper be exercised
#                           end-to-end against a throwaway checkout.
#
# Exit: 0 when the change is shippable (or self-validates); 2 when the guard trips.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_PY="$(cd "$HERE/../.." && pwd)/containers/oakandwave-workflow/compat_guard.py"

BASE_REF="${COMPAT_GUARD_BASE_REF:-origin/main}"
SCHEMA_REL="${COMPAT_GUARD_SCHEMA:-containers/oakandwave-workflow/state-schema.json}"
REPO="${COMPAT_GUARD_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
CANDIDATE="$REPO/$SCHEMA_REL"

if [[ ! -f "$CANDIDATE" ]]; then
	echo "compat-guard: candidate schema not found: $CANDIDATE" >&2
	exit 2
fi

# Source the baseline from git. `git show REF:path` fails (non-zero) when the ref
# is unknown or the file did not exist there — either way we have no baseline to
# diff against, so we self-validate the candidate only (a new schema is trivially
# compatible; it cannot break anything that never existed).
baseline_tmp="$(mktemp -t compat-guard-baseline.XXXXXX.json)"
cleanup() { rm -f "$baseline_tmp"; }
trap cleanup EXIT

if git -C "$REPO" show "$BASE_REF:$SCHEMA_REL" >"$baseline_tmp" 2>/dev/null; then
	echo "compat-guard: diffing $SCHEMA_REL against baseline $BASE_REF" >&2
	python3 "$GUARD_PY" --baseline "$baseline_tmp" --candidate "$CANDIDATE"
else
	echo "compat-guard: no baseline at $BASE_REF:$SCHEMA_REL — self-validating candidate only" >&2
	python3 "$GUARD_PY" --candidate "$CANDIDATE"
fi
