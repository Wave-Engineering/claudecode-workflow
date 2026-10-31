#!/usr/bin/env bash
# fetch-code-review-benchmark.sh — fetch the Job D golden-comment benchmark at its pinned commit (#1195).
#
# The yardstick is withmartian/code-review-benchmark (MIT). Its `offline/` set is 50 PRs from
# five open-source codebases, each with human-verified golden comments. Results are only
# comparable run to run if every run reads the same goldens, so this script fetches exactly
# one commit and refuses any other. Nothing from it is vendored into this repo: the cache is
# gitignored, and the LICENSE travels with it.
#
# Usage:
#   scripts/bench/fetch-code-review-benchmark.sh [<cache_dir>]
#       Default cache: <repo_root>/.bench/code-review-benchmark. Prints the cache path.
#
# Exit: 0 the cache is at the pinned commit; 1 a fetch failed; 2 the cache holds another commit.
set -euo pipefail

BENCH_URL="https://github.com/withmartian/code-review-benchmark.git"
BENCH_SHA="949e4a1058c67b940f27b2c609958a7ea7a13b2c"

root="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
cache="${1:-$root/.bench/code-review-benchmark}"

if [[ ! -d "$cache/.git" ]]; then
	mkdir -p "$cache"
	git -C "$cache" init -q
	git -C "$cache" remote add origin "$BENCH_URL"
fi

have="$(git -C "$cache" rev-parse -q --verify HEAD 2>/dev/null || true)"
if [[ "$have" != "$BENCH_SHA" ]]; then
	if [[ -n "$have" ]]; then
		echo "fetch-code-review-benchmark: $cache is at $have, not the pinned $BENCH_SHA" >&2
		echo "fetch-code-review-benchmark: remove it to re-fetch; a moved cache is never reused" >&2
		exit 2
	fi
	git -C "$cache" fetch -q --depth 1 origin "$BENCH_SHA" || {
		echo "fetch-code-review-benchmark: fetch of $BENCH_SHA from $BENCH_URL failed" >&2
		exit 1
	}
	git -C "$cache" -c advice.detachedHead=false checkout -q FETCH_HEAD
fi

got="$(git -C "$cache" rev-parse HEAD)"
if [[ "$got" != "$BENCH_SHA" ]]; then
	echo "fetch-code-review-benchmark: checked out $got, expected $BENCH_SHA" >&2
	exit 2
fi
echo "$cache"
