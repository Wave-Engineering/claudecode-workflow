#!/usr/bin/env bash
# test_no_epic_label_reads.sh — regression test enforcing Dev Spec R-19.
#
# R-19 (docs/phase-epic-taxonomy-devspec.md §3): the SDLC pipeline MUST NOT
# read `epic::N` labels. Epic is a PM-layer concept; pipeline containers are
# Plan / Phase / Wave / Story, sourced from `phases-waves.json`, never from
# the `epic::N` or `type::epic` label families.
#
# This script greps the pipeline code surface for read-patterns of `epic::N`
# labels. Zero matches → exit 0. Any match → exit 1, printing offending
# files/lines.
#
# Scope (scanned):
#   skills/**/*.md     — SDLC pipeline skills
#   src/**             — MCP-server / wave-status / dashboard source
#   scripts/**         — build, CI, bootstrap, testing helpers
#   tools/**           — standalone CLI helpers
#
# Exceptions (EXCLUDED from the scan, with per-path rationale):
#   CHANGELOG.md                       — historical release notes
#   docs/**                            — Dev Spec / design docs (spec language)
#   tests/**                           — test files (including this one)
#   skills/issue/                      — PM-layer creation/application path;
#                                        `/issue … --epic N` APPLIES the
#                                        `epic::N` label but does not READ it.
#                                        This is the sole authorized write
#                                        site per Dev Spec §5.5.4 (R-19's
#                                        explicit PM/Pipeline boundary).
#   skills/devspec/SKILL.md            — spec language describing R-19
#                                        (mentions `epic::N` to state "the
#                                        pipeline does not read it").
#   scripts/bootstrap-repo-labels.sh   — label creation (one-time bootstrap);
#   scripts/bootstrap-repo-labels-gitlab.sh
#                                        creates the `type::epic` label in a
#                                        new repo; no pipeline read happens.
#   scripts/testing/wave-fixture-gen.py — test-fixture generator that writes
#                                        `type::epic` into synthetic fixture
#                                        payloads; not a pipeline read.
#
# Cross-repo expectation: `mcp-server-sdlc` will adopt an equivalent test in
# a follow-up story. This test is intentionally self-contained (bash + grep —
# no jq / python / node / bun deps) so it ports cleanly to sibling repos.
#
# Wired into CI via `scripts/ci/validate.sh`.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"

FAILS=0
OFFENDERS=()

fail() {
	echo "  [FAIL] $*"
	FAILS=$((FAILS + 1))
}

pass() {
	echo "  [PASS] $*"
}

echo "test_no_epic_label_reads (Dev Spec R-19)"
echo "──────────────────────────────────────────"

# --- Build the scan target list ----------------------------------------------
#
# Strategy: enumerate candidate files under the pipeline code surface, then
# filter out the explicit exceptions. Using `find` + a `case` filter (no
# `find -not -path` chains) keeps the exception list readable and auditable.

TARGETS=()
while IFS= read -r f; do
	# Per-path exceptions — keep this list aligned with the header comment.
	case "$f" in
	*/tests/*) continue ;;
	*/docs/*) continue ;;
	*/CHANGELOG.md) continue ;;
	*/skills/issue/*) continue ;;
	*/skills/devspec/SKILL.md) continue ;;
	*/scripts/bootstrap-repo-labels.sh) continue ;;
	*/scripts/bootstrap-repo-labels-gitlab.sh) continue ;;
	*/scripts/testing/wave-fixture-gen.py) continue ;;
	esac
	TARGETS+=("$f")
done < <(
	find \
		"$REPO_DIR/skills" \
		"$REPO_DIR/src" \
		"$REPO_DIR/scripts" \
		"$REPO_DIR/tools" \
		-type f \
		\( -name "*.md" -o -name "*.py" -o -name "*.sh" -o -name "*.ts" -o -name "*.js" -o -name "*.mjs" -o -name "*.cjs" -o -name "*.tsx" -o -name "*.jsx" \) \
		2>/dev/null
)

if [[ ${#TARGETS[@]} -eq 0 ]]; then
	fail "no scan targets found — test is broken"
	exit 1
fi

# --- Grep patterns -----------------------------------------------------------
#
# Three complementary patterns catch the common ways pipeline code might
# inadvertently read the `epic::N` label family:
#
#   1. `epic::[0-9]+`         — literal label values (`epic::42`)
#   2. `['"]epic::`           — quoted label prefix (matches filter args,
#                               dict keys, label-list entries)
#   3. `--label[ =]epic::`    — gh/glab CLI label filters
#
# Pattern 3 is a subset of pattern 2 in practice, but listing it explicitly
# makes a CLI-filter regression obvious in the failure output.

PATTERNS=(
	'epic::[0-9]+'
	"['\"]epic::"
	'\-\-label[ =]epic::'
)

for pattern in "${PATTERNS[@]}"; do
	while IFS= read -r hit; do
		[[ -n "$hit" ]] && OFFENDERS+=("$hit")
	done < <(grep -HnE "$pattern" "${TARGETS[@]}" 2>/dev/null || true)
done

# --- Report ------------------------------------------------------------------
if [[ ${#OFFENDERS[@]} -eq 0 ]]; then
	pass "no pipeline reads of epic::N labels found (R-19 upheld)"
	echo ""
	echo "  scanned ${#TARGETS[@]} file(s) across skills/ src/ scripts/ tools/"
	exit 0
fi

# De-duplicate (a single line might match more than one pattern).
UNIQUE_OFFENDERS=()
while IFS= read -r line; do
	UNIQUE_OFFENDERS+=("$line")
done < <(printf '%s\n' "${OFFENDERS[@]}" | sort -u)

echo ""
echo "  [FAIL] ${#UNIQUE_OFFENDERS[@]} pipeline read(s) of epic::N labels detected"
echo ""
echo "  Dev Spec R-19 forbids the SDLC pipeline from reading epic::N labels."
echo "  Epic is a PM-layer concept; pipeline containers come from"
echo "  phases-waves.json (Plan / Phase / Wave / Story)."
echo ""
echo "  Offending lines:"
for line in "${UNIQUE_OFFENDERS[@]}"; do
	# Strip the repo prefix for readability.
	echo "    ${line#"$REPO_DIR/"}"
done
echo ""
echo "  Fixes:"
echo "    - If the read is legitimate PM-layer creation (applying a label,"
echo "      not reading it), move it into skills/issue/ or add a documented"
echo "      exception at the top of this script."
echo "    - Otherwise, remove the read. Use phases-waves.json for container"
echo "      membership instead."

exit 1
