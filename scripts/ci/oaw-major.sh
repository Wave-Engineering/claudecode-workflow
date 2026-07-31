#!/usr/bin/env bash
# oaw-major.sh — resolve the kit MAJOR that partitions sandbox state (#1067, R-20).
#
# WHY THIS EXISTS. `dogfood-cutover.sh` and `soak-accrual-bridge.sh` each carried
# `OAW_MAJOR="${OAW_MAJOR:-1}"` — a hardcoded literal, sitting under a comment
# calling it "the kit major", while the kit was at 7.3.0. So every kit generation
# shared namespace `1` and R-20's guarantee ("the major partitions the namespace
# so mixing majors is isolated") did not hold in practice.
#
# WHY A WRONG MAJOR IS DANGEROUS RATHER THAN UNTIDY. It does not error. Docker's
# create-if-missing turns an absent bind source into an empty DIRECTORY, so
# ~/.oaw/state/<major>/memory and every cache come up BLANK — no warning, no
# failed mount, just an agent with no memory and cold caches. Identical shape to
# the missing ~/.secrets/.env in #1061.
#
# DERIVATION mirrors scripts/ci/oakandwave-oci-labels.sh rather than inventing a
# second mechanism: $OAW_MAJOR wins, else the major of `git describe --tags`.
# There is deliberately NO literal fallback — a constant is the defect this
# replaces, and guessing silently is worse than refusing.
#
# Usage:
#   OAW_MAJOR="$(scripts/ci/oaw-major.sh)"            # resolve, or fail loud
#   scripts/ci/oaw-major.sh --check                   # also verify the dirs exist
#
# Exit: 0 resolved; 2 cannot resolve; 3 resolved but --check found missing dirs.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
CHECK=false
[[ "${1:-}" == "--check" ]] && CHECK=true

resolve_major() {
	if [[ -n "${OAW_MAJOR:-}" ]]; then
		printf '%s' "$OAW_MAJOR"
		return 0
	fi
	local tag
	tag="$(git -C "$REPO_DIR" describe --tags --abbrev=0 2>/dev/null)" || tag=""
	[[ -n "$tag" ]] || return 1
	tag="${tag#v}" # tags are vX.Y.Z
	local major="${tag%%.*}"
	[[ "$major" =~ ^[0-9]+$ ]] || return 1
	printf '%s' "$major"
}

# Validate the OVERRIDE here, not inside resolve_major: that runs in a command
# substitution, where `exit` leaves only the subshell and the caller then reports
# "cannot resolve" — two messages, one of them wrong.
#
# mount_resolver coerces a full semver to its major int while profiles.py
# substitutes <major> as a raw string, so OAW_MAJOR=7.3.0 silently SPLITS the
# namespace: mounts land at ~/.oaw/state/7 and the skills overlay at
# ~/.oaw/overlay/7.3.0.
if [[ -n "${OAW_MAJOR:-}" && ! "$OAW_MAJOR" =~ ^[0-9]+$ ]]; then
	echo "oaw-major: \$OAW_MAJOR must be a bare major integer, got '$OAW_MAJOR'." >&2
	echo "  A semver like 7.3.0 splits the namespace: mount_resolver coerces it to 7" >&2
	echo "  while profiles.py substitutes it verbatim. Pass just the major." >&2
	exit 2
fi

if ! MAJOR="$(resolve_major)"; then
	echo "oaw-major: cannot resolve the kit major." >&2
	echo "  Set \$OAW_MAJOR explicitly, or run inside a checkout with a vX.Y.Z tag." >&2
	echo "  There is no literal fallback on purpose: a hardcoded major is the defect" >&2
	echo "  this replaces (#1067), and it fails SILENTLY as empty state rather than loudly." >&2
	exit 2
fi

printf '%s\n' "$MAJOR"

if [[ "$CHECK" == true ]]; then
	# The state namespace must already exist. Docker would otherwise materialise
	# each missing source as an empty dir and the agent boots with blank memory
	# and cold caches — the silent failure this whole guard is for.
	missing=()
	# All FOUR major-partitioned host roots. toolbox is declared at
	# mounts.d/30-user-overlay.toml (source = ~/.oaw/toolbox/<major>, rw) and is the
	# same failure class: absent -> docker makes an empty dir -> the discretionary
	# toolbox comes up bare, silently.
	for d in "$HOME/.oaw/state/$MAJOR" "$HOME/.oaw/cache/$MAJOR" \
		"$HOME/.oaw/overlay/$MAJOR" "$HOME/.oaw/toolbox/$MAJOR"; do
		[[ -d "$d" ]] || missing+=("$d")
	done
	if ((${#missing[@]} > 0)); then
		echo "oaw-major: major $MAJOR is NOT provisioned — missing:" >&2
		printf '  %s\n' "${missing[@]}" >&2
		echo "" >&2
		echo "  Docker would create these as EMPTY directories at launch, so the agent" >&2
		echo "  would come up with no memory and cold caches, silently." >&2
		echo "" >&2
		echo "  A major bump RE-NAMESPACES state (R-20) — it is a migration, not a" >&2
		echo "  reset. To carry state forward from the previous major <PREV>:" >&2
		echo "    cp -a ~/.oaw/state/<PREV>   ~/.oaw/state/$MAJOR" >&2
		echo "    cp -a ~/.oaw/cache/<PREV>   ~/.oaw/cache/$MAJOR" >&2
		echo "    cp -a ~/.oaw/overlay/<PREV> ~/.oaw/overlay/$MAJOR" >&2
		echo "    cp -a ~/.oaw/toolbox/<PREV> ~/.oaw/toolbox/$MAJOR" >&2
		echo "  Or provision empty deliberately if a clean namespace is intended." >&2
		exit 3
	fi
fi
