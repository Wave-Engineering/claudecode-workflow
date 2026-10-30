# shellcheck shell=bash
# shellcheck disable=SC2034  # sourced: its readers are check-scannable.sh, dependency-scan.sh and gen-lock-find.sh
# lock-predicate.sh — THE lock predicate of the dependency scan (#1358). Sourced, not run.
#
# Three paths count locks: check-scannable.sh (and so dependency-scan.sh), the
# per-wave trust gate's TRIVY prompt (skills/nextwave/gate.js) and the /precheck
# Job C raw-trivy fallback (skills/precheck/SKILL.md). They used to carry three
# copies of this predicate that counted different things: the script paired a JS
# lock with a package.json (first match wins) and a go.sum or Cargo.lock with its
# manifest, while both finds counted every lock they found. /precheck could PASS
# a tree the trust gate HOLDs.
#
# Now there is one. check-scannable.sh and dependency-scan.sh source this file.
# The two prose copies cannot: a Workflow bundle is self-contained, and the
# fallback runs in repos that carry no scripts/ci. So scripts/ci/gen-lock-find.sh
# writes their find and main-scan lines from these arrays, and
# tests/regression/test_lock_find_in_sync.sh fails CI when a copy drifts. Edit
# here, then run gen-lock-find.sh.
#
# COUNTING IS LOCK-CENTRIC: every file the find prints is in the denominator,
# less the same two exclusions on every path (a requirements file with no `==`
# pin, and a bun.lockb with a bun.lock beside it). It is the only rule a prose
# path can carry as a single find, and it fails closed: a lock trivy cannot read
# is a named UNSCANNED lock, never an uncounted one.

# Prune vendored and build trees. A package.json inside node_modules is a
# DEPENDENCY's manifest, not ours. Pruned by -name, at any depth, never by -path:
# `-path ./node_modules` matched only a root node_modules, and a nested one leaked
# five dependency manifests in as the repo's own.
LOCK_PRUNE=(node_modules .git dist build vendor .venv venv target)

# THE LOCK NAMES, on one line. Each is here because trivy 0.74.0 ingests it with
# this repo's flags (`--include-dev-deps --list-all-pkgs`).
#
# The Python locks are counted with no manifest beside them: a pyproject.toml is
# often tool config with no dependencies (ruff, pytest), and trivy reads each of
# these locks alone (#1289, measured on a minimal real lock, with and without its
# manifest): uv.lock (Type uv, 4 packages), poetry.lock (Type poetry, 3),
# Pipfile.lock (Type pipenv, 2).
#
# LEFT OUT ON PURPOSE: pdm.lock. trivy 0.74.0 has no pdm analyzer, so it emits no
# Result for one, with or without its pyproject.toml. Counted, every repo carrying
# one would fail as UNSCANNED (dependency-scan.sh exit 6, or 2) with no way to
# clear it. Add it only after re-measuring on a trivy that reads it.
LOCK_NAMES=(bun.lock bun.lockb package-lock.json yarn.lock pnpm-lock.yaml go.sum Cargo.lock uv.lock poetry.lock Pipfile.lock)

# Every pip requirements file, not only `requirements.txt` (#1247): the
# `requirements-dev.txt` sibling, the `dev-requirements.txt` prefix form, the
# pip-tools `requirements/<name>.txt` layout, hash-locked files named `*.lock`
# (`requirements.lock`, `build-requirements.lock`) and pip constraints files. The
# leading glob on `*constraints*.txt` also matches the `dev-` prefix form, as it
# does on `*requirements*.txt`. Measured, trivy 0.74.0: a hash-locked file, with
# `==` pins and `--hash=` continuation lines, read as `requirements.txt`, gives 2
# of 2 packages. dependency-scan.sh scans each of these alone under that name.
REQ_NAMES=('*requirements*.txt' '*requirements*.lock' '*constraints*.txt')
REQ_PATHS=('*/requirements/*.txt')

# manifest:locks. For DIAGNOSTICS only: check-scannable.sh names a manifest with
# none of its locks beside it as UNSCANNABLE (a manifest carries ranges, not
# versions). It never adds to the count.
MANIFEST_LOCKS=("package.json:bun.lock,bun.lockb,package-lock.json,yarn.lock,pnpm-lock.yaml" "go.mod:go.sum" "Cargo.toml:Cargo.lock")

# A requirements entry pinned by `==` (or `===`). `>=` and `~=` are ranges, and a
# range is not an installed version, so they parse to nothing, like a bare name.
PIN_RE='^[[:space:]]*[A-Za-z0-9._-]+[[:space:]]*===?[[:space:]]*[0-9]'

# The trivy flags the two prose main scans carry. --ignorefile /dev/null and
# --config /dev/null: trivy reads a .trivyignore and a trivy.yaml from the CURRENT
# DIRECTORY, and either can hide a finding or a whole lock (#1358).
TRIVY_PROSE_FLAGS='--scanners vuln --severity HIGH,CRITICAL --include-dev-deps --list-all-pkgs --ignorefile /dev/null --config /dev/null --format json --quiet'

# The find predicate as one line, for the prose copies: the prune, then
# LOCK_NAMES, then REQ_NAMES, then REQ_PATHS.
lock_find_expr() {
	local out='\(' d n first=1
	for d in "${LOCK_PRUNE[@]}"; do
		((first)) || out+=' -o'
		out+=" -name $d"
		first=0
	done
	out+=' \) -prune -o -type f \('
	first=1
	for n in "${LOCK_NAMES[@]}" "${REQ_NAMES[@]}"; do
		((first)) || out+=' -o'
		out+=" -name '$n'"
		first=0
	done
	for n in "${REQ_PATHS[@]}"; do
		out+=" -o -path '$n'"
	done
	printf '%s\n' "$out \\) -print"
}

# trivy's --skip-dirs for the prune list. .git is left out: trivy never walks it.
skip_dirs_args() {
	local out=() d
	for d in "${LOCK_PRUNE[@]}"; do
		[[ "$d" == .git ]] && continue
		out+=("--skip-dirs '**/$d'")
	done
	printf '%s\n' "${out[*]}"
}

# The same predicate, run: every lock under $1, one per line. Built as an argv,
# never by eval of lock_find_expr's string.
lock_find() {
	local root="$1" d n first=1
	local -a args=('(')
	for d in "${LOCK_PRUNE[@]}"; do
		((first)) || args+=(-o)
		args+=(-name "$d")
		first=0
	done
	args+=(')' -prune -o -type f '(')
	first=1
	for n in "${LOCK_NAMES[@]}" "${REQ_NAMES[@]}"; do
		((first)) || args+=(-o)
		args+=(-name "$n")
		first=0
	done
	for n in "${REQ_PATHS[@]}"; do
		args+=(-o -path "$n")
	done
	args+=(')' -print)
	find "$root" "${args[@]}" 2>/dev/null
}

# 0 when $1 is a pip requirements file: anything the find printed that is not one
# of LOCK_NAMES.
is_req_file() {
	local base n
	base="$(basename "$1")"
	for n in "${LOCK_NAMES[@]}"; do
		[[ "$base" == "$n" ]] && return 1
	done
	return 0
}
