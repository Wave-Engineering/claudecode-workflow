#!/usr/bin/env bash
# lowercase-image-guard.sh — fail CI if any container image path is not lowercase (#1031).
#
# GHCR and the Docker client reject uppercase repo names. Our org login
# "Wave-Engineering" carries capitals, so a raw ${{ github.repository_owner }} or a
# hand-typed capitalized path is a latent pull/auth trap. This guard turns "every
# published image path is lowercase" into a tested invariant, not a convention.
#
# Two failure classes, over the CI/deploy files that DECLARE image refs:
#   1. an uppercase char inside a registry path   (ghcr.io/Wave-Engineering/...)
#   2. a raw owner interpolation in an image ref  (ghcr.io/${{ github.repository_owner }}/...)
#      — the capital-generator, even when a downstream ${VAR,,} currently masks the push.
#
# Whole-line comments are ignored, so prose that names the rule can't self-trip; this
# guard and test trees are excluded (they carry example bad-patterns on purpose).
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

registries='ghcr\.io|docker\.io|quay\.io|public\.ecr\.aws'

# GUARD_FILES is a DI-seam for the regression test: a newline-separated explicit file
# list to scan instead of the tracked CI/deploy set (lets the test inject fixtures
# hermetically, no git). Unset in CI → scan the real tree via git ls-files.
if [[ -n "${GUARD_FILES:-}" ]]; then
	mapfile -t files <<<"$GUARD_FILES"
else
	mapfile -t files < <(
		git ls-files |
			grep -E '\.(ya?ml|sh|toml|py)$|/Dockerfile$|/Makefile$' |
			grep -E '^(\.github/|scripts/ci/|containers/|deploy/)' |
			grep -vE 'lowercase-image-guard\.sh$|(^|/)tests?/' || true
	)
fi

offenders=0
for f in "${files[@]}"; do
	[[ -f "$f" ]] || continue

	# Strip comments before matching so prose that names the rule can't self-trip —
	# BOTH whole-line and inline trailing comments. Only a '#' at line-start or after
	# whitespace counts, which leaves shell parameter expansions (${VAR#prefix}) intact.
	# sed preserves the line count, so grep -n still reports the true line number.
	code="$(sed -E 's/(^|[[:space:]])#.*$//' "$f")"

	# 1) uppercase inside a registry path
	while IFS=: read -r ln rest; do
		[[ -z "$ln" ]] && continue
		echo "  [FAIL] $f:$ln — uppercase in image path:$rest"
		offenders=$((offenders + 1))
	done < <(printf '%s\n' "$code" | grep -nE "(${registries})/[A-Za-z0-9._/-]*[A-Z]" || true)

	# 2) raw repository_owner interpolation in an image ref (interpolates capitals)
	while IFS=: read -r ln rest; do
		[[ -z "$ln" ]] && continue
		echo "  [FAIL] $f:$ln — raw repository_owner in image ref:$rest"
		offenders=$((offenders + 1))
	done < <(printf '%s\n' "$code" | grep -niE "(${registries}).*repository_owner" || true)
done

if [[ "$offenders" -gt 0 ]]; then
	echo "  [lowercase-image-guard] FAILED: $offenders offender(s) — image paths must be all-lowercase (#1031)"
	exit 1
fi
echo "  [lowercase-image-guard] OK: all image paths lowercase (${#files[@]} files scanned)"
