#!/usr/bin/env bash
# check-no-classic-mode.sh — regression check for cc-workflow#580.
#
# Issue cc-workflow#580 retired Wavemachine Classic mode. Kahuna is the only
# execution shape; there is no Classic / non-KAHUNA / legacy fallback. This
# script enforces that taint by grepping the wave-pattern skill surface for
# the prose patterns and code patterns that re-introduce mode-selection.
#
# Zero matches → exit 0. Any match → exit 1, printing offending files/lines.
#
# Scope (scanned):
#   skills/wavemachine/SKILL.md
#   skills/nextwave/SKILL.md
#   skills/assesswaves/SKILL.md
#   skills/prepwaves/SKILL.md
#   skills/devspec/SKILL.md
#   skills/_shared/recipes/cross-repo-wave-orchestration.md (if present)
#
# Exceptions (NOT scanned, with rationale):
#   docs/                              — Dev Spec / design docs (the canonical
#                                        kahuna-devspec.md still references
#                                        the historical migration narrative;
#                                        retiring those mentions is a separate
#                                        doc rewrite tracked in #580's
#                                        deferred-followup section).
#   tests/                             — test files (this script itself,
#                                        regression doc-shape tests, etc.).
#   CHANGELOG.md, CHANGELOG.fragment.md — historical release notes.
#   scripts/ci/check-no-classic-mode.sh — this script (it must contain the
#                                        forbidden patterns by definition).
#
# Wired into CI via scripts/ci/validate.sh's "Regression tests" pass.
#
# Cross-reference: skills/wavemachine/SKILL.md "Migration note" paragraph,
# docs/kahuna-devspec.md §1 "this is the only mode", WAVE_AXIOMS.md.

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

echo "check-no-classic-mode (cc-workflow#580)"
echo "──────────────────────────────────────────"

# --- Build the scan target list ----------------------------------------------
TARGETS=()
for f in \
	"$REPO_DIR/skills/wavemachine/SKILL.md" \
	"$REPO_DIR/skills/nextwave/SKILL.md" \
	"$REPO_DIR/skills/assesswaves/SKILL.md" \
	"$REPO_DIR/skills/prepwaves/SKILL.md" \
	"$REPO_DIR/skills/devspec/SKILL.md" \
	"$REPO_DIR/skills/nextwave/introduction.md" \
	"$REPO_DIR/skills/_shared/recipes/cross-repo-wave-orchestration.md"; do
	[[ -f "$f" ]] && TARGETS+=("$f")
done

if [[ ${#TARGETS[@]} -eq 0 ]]; then
	fail "no scan targets found — test is broken"
	exit 1
fi

# --- Forbidden patterns ------------------------------------------------------
#
# Each pattern is a string the wave-pattern skills MUST NOT contain. The
# patterns target the prose and code shapes that re-introduce Classic mode
# or any fallback that bypasses the kahuna sandbox.
#
# 1. Literal "Wavemachine Classic" / "Classic mode" / "Classic execution"
#    — the retired mode name in any spelling that suggests it is selectable.
# 2. "legacy non-KAHUNA" / "non-KAHUNA mode" / "non-KAHUNA execution"
#    — every prior reference to the now-retired alternative path.
# 3. "KAHUNA mode" / "KAHUNA-mode" — implies a non-KAHUNA mode exists.
# 4. "if kahuna_branch is empty" / "kahuna_branch is unset" / "absent or
#    empty" / "omit or leave empty for legacy" — the textual fingerprints of
#    the conditional fallback that #580 removed.
# 5. "fall back to main" / "fallback to main" — the literal fallback shape.
# 6. "--base main" / "base: \"main\"" / "origin/main" — hardcoded protected-
#    branch references in prompt templates and recipe code blocks (when
#    used in a wave-pattern skill's Flight stub or PR-create example, the
#    integration target should be `kahuna_branch`, not `main`). These hits
#    are also caught by the broader "no-main-assumption" rule from
#    feedback_no_main_assumption.md.
# 7. "preserves backward compat" / "backwards compat" — the prose shape that
#    introduces a fallback to placate non-KAHUNA consumers.

PATTERNS=(
	'Wavemachine Classic'
	'[Cc]lassic mode'
	'[Cc]lassic execution'
	'legacy non-KAHUNA'
	'non-KAHUNA mode'
	'non-KAHUNA execution'
	'KAHUNA mode'
	'KAHUNA-mode'
	'kahuna_branch is empty'
	'kahuna_branch is unset'
	'kahuna_branch.*absent or empty'
	'omit or leave empty for legacy'
	'fall back to main'
	'fallback to main'
	'\-\-base main'
	'base: *"main"'
	'origin/main'
	'[Pp]reserves backward compat'
	'[Bb]ackward[s]? compat'
)

for pattern in "${PATTERNS[@]}"; do
	while IFS= read -r hit; do
		[[ -n "$hit" ]] && OFFENDERS+=("$hit")
	done < <(grep -HnE "$pattern" "${TARGETS[@]}" 2>/dev/null || true)
done

# --- Report ------------------------------------------------------------------
if [[ ${#OFFENDERS[@]} -eq 0 ]]; then
	pass "no Classic-mode taint found in wave-pattern skill surface"
	echo ""
	echo "  scanned ${#TARGETS[@]} file(s)"
	exit 0
fi

# De-duplicate (a single line might match more than one pattern).
UNIQUE_OFFENDERS=()
while IFS= read -r line; do
	UNIQUE_OFFENDERS+=("$line")
done < <(printf '%s\n' "${OFFENDERS[@]}" | sort -u)

echo ""
echo "  [FAIL] ${#UNIQUE_OFFENDERS[@]} Classic-mode taint(s) detected"
echo ""
echo "  cc-workflow#580 retired Wavemachine Classic mode. Kahuna is the only"
echo "  execution shape — there is no fallback, no mode selection, no"
echo "  legacy non-KAHUNA path. The wave-pattern skills must describe"
echo "  Kahuna unconditionally."
echo ""
echo "  Offending lines:"
for line in "${UNIQUE_OFFENDERS[@]}"; do
	# Strip the repo prefix for readability.
	echo "    ${line#"$REPO_DIR/"}"
done
echo ""
echo "  Fixes:"
echo "    - Remove Classic/legacy/non-KAHUNA references entirely; the"
echo "      kahuna sandbox is the only execution shape."
echo "    - Replace hardcoded 'main' integration targets with the wave's"
echo "      kahuna_branch (Flight PR base) or the project's protected"
echo "      branch read from .claude-project.md (kahuna→<protected> MR)."
echo "    - Do NOT re-add 'KAHUNA mode' / 'non-KAHUNA mode' framing —"
echo "      mode framing implies an alternative. There is no alternative."

exit 1
