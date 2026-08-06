#!/usr/bin/env bash
# backfill-release-tags.sh — give already-published release images their `:vX.Y.Z`
# tag, so the registry finally records which digest was which release (#1122).
#
# Until now the build pushed only `:edge`, so v8.1.1's image was indistinguishable
# from any intermediate build. Retention had no anchor (#1100's pruner had to
# approximate release history with "the last N manifests") and rollback meant
# reading OCI labels off candidate digests one at a time.
#
# THE VERSION IS READ FROM THE IMAGE, NOT TYPED IN. Every image carries
# `org.opencontainers.image.version` from oakandwave-oci-labels.sh, so the mapping
# is a fact the artifact already asserts about itself. A hand-maintained
# digest→version list is a second source of truth that can disagree with the
# first, and the disagreement would be silent.
#
# Only EXACT release versions are tagged. `oakandwave-oci-labels.sh` derives from
# `git describe`, so an off-tag build labels itself `8.2.0-4-g3a7f124`; that is a
# candidate, not a release, and tagging it `:v8.2.0-4-g3a7f124` would invent a
# release that never happened.
#
# Retag, never rebuild: `imagetools create -t <new> <image>@<digest>` points a new
# tag at the SAME digest. R-23 — the digest tested is the digest promoted.
#
# Usage:
#   backfill-release-tags.sh            # dry run: show what would be tagged
#   backfill-release-tags.sh --apply
#
# Exit: 0 ok; 1 a retag failed; 2 refused (nothing to work from).
set -uo pipefail

ORG="${OAW_REGISTRY_ORG:-Wave-Engineering}"
PACKAGE="${OAW_REGISTRY_PACKAGE:-oakandwave-workflow}"
IMAGE="ghcr.io/${ORG,,}/${PACKAGE}"
APPLY=false

while [[ $# -gt 0 ]]; do
	case "$1" in
	--apply)
		APPLY=true
		shift
		;;
	-h | --help)
		sed -n '2,26p' "$0"
		exit 0
		;;
	*)
		echo "backfill-release-tags: unknown flag $1" >&2
		exit 2
		;;
	esac
done

for tool in gh docker python3; do
	command -v "$tool" >/dev/null 2>&1 || {
		echo "backfill-release-tags: $tool not found" >&2
		exit 2
	}
done

echo "==> enumerating $IMAGE"
versions="$(mktemp)"
trap 'rm -f "$versions"' EXIT
if ! gh api --paginate "/orgs/$ORG/packages/container/$PACKAGE/versions" \
	--jq '.[] | [.name, ((.metadata.container.tags // []) | join(","))] | @tsv' \
	>"$versions" 2>/dev/null; then
	echo "backfill-release-tags: could not list versions (token needs read:packages)" >&2
	exit 2
fi
if [[ ! -s "$versions" ]]; then
	echo "backfill-release-tags: empty listing — refusing rather than concluding" >&2
	echo "backfill-release-tags: there are no releases to tag" >&2
	exit 2
fi

# Only top-level manifests can carry a release tag; cosign artifacts are tagged
# `sha256-<subject>.sig|.att` and are not releases.
mapfile -t ALL_MANIFESTS < <(
	awk -F'\t' '$2 !~ /\.sig$|\.att$/ {print $1}' "$versions"
)

# EXCLUDE INDEX CHILDREN. A release digest is an image INDEX; its children (the
# per-arch manifest and the provenance attestation) inherit the same
# `image.version` label, so a naive pass proposes the tag TWICE and the second
# write wins — leaving `:v8.1.0` pointing at an attestation manifest rather than
# the index a profile would pin. Caught by the dry run: every version appeared
# twice.
echo "==> resolving index children (a child must not receive the release tag)"
children="$(mktemp)"
trap 'rm -f "$versions" "$children"' EXIT
for d in "${ALL_MANIFESTS[@]}"; do
	docker buildx imagetools inspect --raw "$IMAGE@$d" 2>/dev/null |
		python3 -c '
import json, sys
try:
    doc = json.load(sys.stdin)
except Exception:
    raise SystemExit
for m in (doc.get("manifests") or []):
    if m.get("digest"):
        print(m["digest"])
' >>"$children" 2>/dev/null
done
sort -u -o "$children" "$children"

mapfile -t CANDIDATES < <(
	for d in "${ALL_MANIFESTS[@]}"; do
		grep -qxF "$d" "$children" || printf '%s\n' "$d"
	done
)
echo "==> ${#CANDIDATES[@]} top-level manifest(s) to inspect ($(wc -l <"$children") children excluded)"

tagged=0
skipped=0
failed=0

for digest in "${CANDIDATES[@]}"; do
	version="$(
		docker buildx imagetools inspect "$IMAGE@$digest" --format '{{json .Image}}' 2>/dev/null |
			python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    raise SystemExit
# A multi-platform index returns a map keyed by platform.
if isinstance(d, dict) and "config" not in d:
    vals = [v for v in d.values() if isinstance(v, dict)]
    d = vals[0] if vals else {}
labels = (d.get("config") or {}).get("Labels") or {}
print(labels.get("org.opencontainers.image.version", ""))
' 2>/dev/null
	)"

	# An exact release looks like 8.2.0. `git describe` adds -N-g<sha> off-tag,
	# and that is a candidate, not a release.
	if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
		skipped=$((skipped + 1))
		continue
	fi

	if grep -qF "	v${version}" "$versions" || grep -qE "^${digest}	.*\bv${version}\b" "$versions"; then
		echo "    v${version} already tagged — skipping"
		skipped=$((skipped + 1))
		continue
	fi

	echo "    ${digest:0:19}…  →  ${IMAGE}:v${version}"
	if [[ "$APPLY" == true ]]; then
		if docker buildx imagetools create -t "${IMAGE}:v${version}" "${IMAGE}@${digest}" >/dev/null 2>&1; then
			tagged=$((tagged + 1))
		else
			echo "    FAILED to tag v${version}" >&2
			failed=$((failed + 1))
		fi
	else
		tagged=$((tagged + 1))
	fi
done

echo
if [[ "$APPLY" != true ]]; then
	echo "==> DRY RUN — $tagged tag(s) would be created, $skipped skipped."
	echo "    Re-run with --apply. Retagging is additive and does not delete anything,"
	echo "    but it does publish, so it is still a deliberate act."
	exit 0
fi

echo "==> tagged $tagged, skipped $skipped, failed $failed"
((failed == 0)) || exit 1
