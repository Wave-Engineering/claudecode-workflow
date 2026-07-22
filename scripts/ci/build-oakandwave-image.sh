#!/usr/bin/env bash
# build-oakandwave-image.sh — build the oakandwave-workflow image, stamp the OCI
# provenance labels, push it to the registry, and emit the resulting digest
# (Story 2.1 / #966, R-05/R-24).
#
# This is the procedural half of the image workflow (DM-03): the CI/CD YAML calls
# it in one line so no build logic lives in the workflow (project rule: "No
# Procedural Logic in CI/CD YAML"). The labels come from oakandwave-oci-labels.sh
# — the same producer the provenance oracle reads — so the pushed image carries
# exactly the labels the test asserts.
#
# The digest is written to $GITHUB_OUTPUT (as `digest=`) and to stdout so the
# throwaway-CI ring (Story 2.2) can pull *by digest*, never by a moving tag —
# the digest tested is the digest promoted (R-23).
#
# Inputs (env):
#   IMAGE        registry image name, e.g. ghcr.io/wave-engineering/oakandwave-workflow
#                (required).
#   TAG          moving tag to publish (default: edge).
#   BASE_IMAGE   override the FROM base (default: the Dockerfile ARG default).
#   PUSH         "true" (default) pushes to the registry; "false" builds+loads
#                locally (for a no-push PR validation lane).
#   Plus every input honored by oakandwave-oci-labels.sh (OAKANDWAVE_VERSION,
#   GITHUB_SHA, GITHUB_REPOSITORY, OAKANDWAVE_CREATED, …).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$HERE/../.." && pwd)"
DOCKERFILE="$REPO_DIR/containers/oakandwave-workflow/Dockerfile"

: "${IMAGE:?IMAGE must be set (e.g. ghcr.io/<org>/oakandwave-workflow)}"
# ghcr (and the OCI distribution spec) require the repository path to be
# lowercase; GITHUB_REPOSITORY_OWNER can carry capitals (Wave-Engineering).
IMAGE="${IMAGE,,}"
TAG="${TAG:-edge}"
PUSH="${PUSH:-true}"
REF="${IMAGE}:${TAG}"

# --- Assemble the OCI provenance labels (single source of truth) --------------
label_args=()
while IFS= read -r line; do
	[[ -n "$line" ]] || continue
	label_args+=(--label "$line")
done < <("$HERE/oakandwave-oci-labels.sh")

build_args=()
if [[ -n "${BASE_IMAGE:-}" ]]; then
	build_args+=(--build-arg "BASE_IMAGE=${BASE_IMAGE}")
fi

# --- Build → push, capturing the pushed digest --------------------------------
# buildx writes the image manifest digest to the metadata file under the
# "containerimage.digest" key; that is the immutable handle the ring pulls by.
metadata_file="$(mktemp -t oakandwave-buildmeta.XXXXXX.json)"
trap 'rm -f "$metadata_file"' EXIT

output_flag="--load"
[[ "$PUSH" == "true" ]] && output_flag="--push"

echo "==> docker buildx build $output_flag -t $REF (${#label_args[@]} labels)"
docker buildx build \
	"$output_flag" \
	--metadata-file "$metadata_file" \
	-f "$DOCKERFILE" \
	-t "$REF" \
	"${label_args[@]}" \
	"${build_args[@]}" \
	"$REPO_DIR"

# --- Extract + publish the digest ---------------------------------------------
digest="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("containerimage.digest",""))' "$metadata_file")"

if [[ -z "$digest" ]]; then
	if [[ "$PUSH" == "true" ]]; then
		echo "  [!] no containerimage.digest in buildx metadata — push likely failed" >&2
		exit 1
	fi
	# Local --load builds have no manifest push digest; fall back to the image ID.
	digest="$(docker image inspect --format '{{.Id}}' "$REF")"
fi

echo "==> image digest: $digest"
echo "digest_ref=${IMAGE}@${digest}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
	{
		echo "digest=${digest}"
		echo "digest_ref=${IMAGE}@${digest}"
		echo "ref=${REF}"
	} >>"$GITHUB_OUTPUT"
fi
