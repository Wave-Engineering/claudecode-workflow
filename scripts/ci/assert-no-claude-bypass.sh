#!/usr/bin/env bash
# assert-no-claude-bypass.sh — EVERY `claude` reachable on PATH must be the wrapper.
#
# WHY THIS EXISTS (#1076). The bootstrap wrapper only works if the agent actually
# runs it, and "which claude runs" is not a thing you get to assume:
#
#   docker exec <c> claude --version        -> wrapper BYPASSED
#   docker exec <c> /usr/local/bin/claude   -> wrapper runs
#   docker exec <c> sh -c 'claude'          -> wrapper runs
#
# `docker exec` resolves the binary against the IMAGE's configured PATH, not the
# interactive shell's. In this image that PATH reaches /root/.local/bin/claude
# (a symlink the base image ships) BEFORE /usr/local/bin, so a wrapper installed
# only at /usr/local/bin/claude is never executed by the real launch path. The
# first cut of this fix shipped exactly that way and was inert — the same
# declared-but-not-wired shape it was written to eliminate.
#
# Picking a "better" single path just moves the assumption. This asserts the
# property instead: walk PATH and require every `claude` found to be the wrapper.
# A future base-image bump that drops a new claude somewhere earlier fails the
# BUILD, loudly, instead of silently unbootstrapping every agent.
#
# Usage: assert-no-claude-bypass.sh [path-string]   (defaults to $PATH)
# Exit:  0 all reachable `claude` entries are the wrapper; 1 a bypass exists.
set -euo pipefail

MARKER="OAW-CLAUDE-BOOTSTRAP-WRAPPER"
search_path="${1:-$PATH}"

found=0
bypass=0

while IFS= read -r dir; do
	[[ -n "$dir" ]] || continue
	target="$dir/claude"
	# -e follows symlinks, which is what we want: /root/.local/bin/claude is a
	# symlink, and what matters is the file the kernel would ultimately execute.
	[[ -e "$target" ]] || continue
	found=$((found + 1))
	if grep -qF "$MARKER" "$target" 2>/dev/null; then
		echo "  [OK]     $target -> wrapper"
	else
		echo "  [BYPASS] $target is NOT the bootstrap wrapper" >&2
		echo "           An agent launched via this path boots UNBOOTSTRAPPED:" >&2
		echo "           no secret projection (so no auth), no skills-sync, no" >&2
		echo "           settings merge, no env validation — and says nothing." >&2
		bypass=$((bypass + 1))
	fi
	# An EMPTY PATH entry means the CURRENT DIRECTORY under POSIX, so dropping
	# empties would silently exclude a genuine bypass slot from a check whose whole
	# claim is "every reachable claude". Normalise it to `.` instead of discarding.
done < <(tr ':' '\n' <<<"$search_path" | sed 's|^$|.|' | awk '!seen[$0]++')

# An empty denominator is NOT a pass. Zero `claude` on PATH means this check
# examined nothing, which is indistinguishable from a clean result — the exact
# failure mode of the inert R-14 check (#1061) and trivy parsing zero manifests
# (#1056). If no claude is reachable, the image is broken in a different way.
if ((found == 0)); then
	echo "assert-no-claude-bypass: no 'claude' found on PATH — nothing was verified" >&2
	echo "  searched: $search_path" >&2
	exit 1
fi

if ((bypass > 0)); then
	echo "assert-no-claude-bypass: $bypass bypass path(s) of $found — failing the build" >&2
	exit 1
fi

echo "assert-no-claude-bypass: $found reachable 'claude' entr(y|ies), all wrapped"
