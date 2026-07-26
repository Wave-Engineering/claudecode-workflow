#!/usr/bin/env bash
# oakandwave-oci-labels.sh — emit the OCI provenance labels for the
# oakandwave-workflow image (Story 2.1 / #966, R-24).
#
# Single source of truth for the four provenance facts R-24 requires — semver,
# source repo, git revision, build timestamp — plus the image title. The build
# script (build-oakandwave-image.sh) consumes each `key=value` line as a
# `docker build --label`; the unit oracle (tests/contained-workflow/
# test_provenance.py::test_oci_labels) consumes the same lines and asserts every
# required key is present with a sane value. One producer, two consumers: the
# label set CI stamps is exactly the label set the test verifies.
#
# Output: one `key=value` line per label on stdout, nothing else. Deterministic
# and hermetic — no docker, no network — so the oracle runs in the stock pytest
# lane.
#
# Inputs (all optional; each has a fail-safe fallback):
#   OAKANDWAVE_VERSION   semver for org.opencontainers.image.version.
#                        Falls back to `git describe --tags` then 0.0.0-dev.
#   GIT_REVISION / GITHUB_SHA
#                        git revision for ...image.revision (else `git rev-parse HEAD`).
#   OAKANDWAVE_SOURCE / GITHUB_REPOSITORY
#                        source repo for ...image.source (a repo slug becomes a
#                        https://github.com/<slug> URL; else the git origin URL).
#   OAKANDWAVE_CREATED   RFC3339 build timestamp for ...image.created (else now, UTC).

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

_git() { git -C "$REPO_DIR" "$@" 2>/dev/null; }

# --- semver -------------------------------------------------------------------
version="${OAKANDWAVE_VERSION:-}"
if [[ -z "$version" ]]; then
	version="$(_git describe --tags --always --dirty)" || version=""
fi
[[ -n "$version" ]] || version="0.0.0-dev"
# Strip a leading v (tags are vX.Y.Z; the OCI version label is bare semver).
version="${version#v}"

# --- git revision -------------------------------------------------------------
revision="${GIT_REVISION:-${GITHUB_SHA:-}}"
if [[ -z "$revision" ]]; then
	revision="$(_git rev-parse HEAD)" || revision=""
fi
[[ -n "$revision" ]] || revision="unknown"

# --- source repo --------------------------------------------------------------
source="${OAKANDWAVE_SOURCE:-}"
if [[ -z "$source" && -n "${GITHUB_REPOSITORY:-}" ]]; then
	source="https://github.com/${GITHUB_REPOSITORY}"
fi
if [[ -z "$source" ]]; then
	source="$(_git remote get-url origin)" || source=""
fi
[[ -n "$source" ]] || source="https://github.com/wave-engineering/claudecode-workflow"

# Lowercase the source URL. GHCR tolerates a capitalized org in an OCI label, but the
# Docker Hub mirror + the OaW lowercase-everywhere convention want it lowercase, and
# GITHUB_REPOSITORY carries the org's capitals ("Wave-Engineering"). github.com paths
# are case-insensitive, so this resolves to the identical repo.
source="${source,,}"

# --- build timestamp (RFC3339, UTC) -------------------------------------------
created="${OAKANDWAVE_CREATED:-}"
[[ -n "$created" ]] || created="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

printf 'org.opencontainers.image.title=%s\n' "oakandwave-workflow"
printf 'org.opencontainers.image.version=%s\n' "$version"
printf 'org.opencontainers.image.source=%s\n' "$source"
printf 'org.opencontainers.image.revision=%s\n' "$revision"
printf 'org.opencontainers.image.created=%s\n' "$created"
