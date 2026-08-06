#!/usr/bin/env bash
# Can this container actually build and RUN a container image? (#1108)
#
# Behavioural, not structural. `command -v podman` proves a binary is installed;
# it does not prove the kernel will let it start a process. The two diverge
# sharply here: a Dockerfile with only COPY steps builds fine under a runtime
# that cannot nest at all, because nothing ever executes. So this probe insists
# on a RUN step and on running the result.
#
# Exit codes are distinct on purpose — "the capability is missing" and "the probe
# could not run" must not collapse into one red result:
#   0  capability present     (built and ran)
#   3  broken in OUR image    — podman absent, networking incomplete, wrong output
#   4  runtime cannot nest    — host lacks default-runtime sysbox-runc
#   5  probe unavailable      — no registry/network; verdict unknown, not failed
set -uo pipefail

# Docker Hub rate-limits anonymous pulls hard enough to make this probe flaky —
# it returned "toomanyrequests" on the very first real run. ECR Public mirrors the
# same official images without an anonymous limit. Overridable so an air-gapped
# adopter can point at whatever they can actually reach.
BASE_IMAGE="${OAW_BUILDER_PROBE_BASE:-public.ecr.aws/docker/library/alpine:3.20}"
TAG=oaw-builder-probe:preflight
LOG=$(mktemp)
trap 'rm -f "$LOG"' EXIT

if ! command -v podman >/dev/null 2>&1; then
	echo "podman is not installed in this image"
	exit 3
fi

WORK=$(mktemp -d) || {
	echo "cannot create a work dir"
	exit 5
}
trap 'rm -f "$LOG"; rm -rf "$WORK"' EXIT

cat >"$WORK/Dockerfile" <<DF
FROM ${BASE_IMAGE}
RUN echo built-in-sandbox > /provenance.txt
CMD ["cat", "/provenance.txt"]
DF

if ! podman build -q -t "$TAG" "$WORK" >"$LOG" 2>&1; then
	# The nesting failure has a specific signature. Anything else is more likely
	# an unreachable registry than a missing capability, so do not claim a verdict.
	if grep -qE 'mount .?proc.? to .?proc.?|cannot clone|Operation not permitted|newuidmap' "$LOG"; then
		echo "the OCI runtime will not let podman nest: $(grep -oE 'mount .?proc.? to .?proc.?[^"]*|cannot clone[^"]*' "$LOG" | head -1)"
		exit 4
	fi
	echo "could not build the probe image (registry unreachable?): $(tail -1 "$LOG")"
	exit 5
fi

if ! OUT=$(podman run --rm "$TAG" 2>"$LOG"); then
	if grep -qE 'nftables|netavark|unable to execute' "$LOG"; then
		echo "built, but could not run it — container networking is incomplete: $(tail -1 "$LOG")"
		exit 3
	fi
	echo "built, but could not run it: $(tail -1 "$LOG")"
	exit 4
fi

# By this point podman has ALREADY built and run a container carrying a RUN step,
# so nesting demonstrably works. A wrong payload therefore cannot be a host
# problem — reporting it as one (exit 4) would downgrade the single case where the
# capability provably works but misbehaves into a non-failing host excuse.
if [[ "$OUT" != "built-in-sandbox" ]]; then
	echo "ran, but produced unexpected output: $OUT"
	exit 3
fi

podman rmi -f "$TAG" >/dev/null 2>&1
echo "built and ran a container image"
exit 0
