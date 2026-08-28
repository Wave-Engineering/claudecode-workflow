#!/usr/bin/env bash
# validate.sh — Run validation checks on the claudecode-workflow repo
#
# Checks:
#   1. shellcheck on all shell scripts
#   2. shfmt formatting check on all shell scripts
#   3. Python syntax check (py_compile) on Python files in src/ and scripts/
#   4. SKILL.md frontmatter validation (name + description present)
#
# File discovery:
#   Shell scripts are identified by .sh extension or #!/…sh shebang.
#   Python files are identified by .py extension or #!/…python shebang.
#
#   Note: the shellcheck pass scans executable-or-*.sh files in scripts/
#   (excluding ci/) plus *.sh files in ci/, while shfmt scans all
#   executable-or-*.sh files in scripts/ (including ci/). Both scan skill
#   helpers and config/. The two selectors match for scripts/ — coverage does
#   NOT depend on the exec bit (#948). The one remaining asymmetry: a non-.sh
#   executable in ci/ is checked by shfmt but not by the shellcheck pass, since
#   the shellcheck ci/ pass is *.sh-only.

set -euo pipefail

# Mute operator-facing hook side effects for the whole suite. Several regression
# tests drive the real Stop hooks against gated-keyword fixtures; without this
# every such case would fire a real vox announcement + Discord ping. The hooks'
# decision logic (block/pass) is unaffected. (cc-workflow#818)
export GODSPEED_NOTIFY_DISABLED=1

# Isolate the FlightDeck emit buffer for the whole suite. Several regression tests
# (e.g. test_wave_engine_e2e_smoke.sh) drive the REAL wave-status CLI, whose
# mutators now emit a FlightDeck event per mutation (cc-workflow#855). Without this
# those emits would append to the operator's real ~/.claude/status/events.jsonl.
# Redirect to a throwaway file and leave the ingest URL unset (buffer-only, no
# POST). Mirrors tests/conftest.py's autouse isolation for the pytest side.
FLIGHTDECK_EVENTS_PATH="$(mktemp -u -t flightdeck-validate-events.XXXXXX.jsonl)"
export FLIGHTDECK_EVENTS_PATH
unset FLIGHTDECK_INGEST_URL

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

info() { echo "  [+] $*"; }
err() { echo "  [!] $*"; }

# Detect shell scripts by extension or shebang
is_shell_script() {
	local f="$1"
	[[ "$f" == *.sh ]] && return 0
	local shebang
	shebang=$(head -1 "$f" 2>/dev/null)
	[[ "$shebang" =~ ^#!.*/((ba|da|k|z)?sh|env[[:space:]]+(ba|da|k|z)?sh) ]] && return 0
	return 1
}

# --- shellcheck ---------------------------------------------------------------
echo "shellcheck"
echo "──────────────────────────────────────────"
if ! command -v shellcheck &>/dev/null; then
	err "shellcheck not found — skipping"
	FAIL=$((FAIL + 1))
else
	SCRIPTS=()
	# Root-level shell scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR" -maxdepth 1 -name "*.sh" -type f 2>/dev/null)
	# Scripts directory (excluding ci/). Executable OR *.sh — coverage must
	# NOT depend on the exec bit: godspeed-lookback.sh is mode 644 (it is
	# sourced, not executed), so an executable-only selector silently skipped
	# the shared library both Stop hooks source while reporting all-green.
	# The shfmt selector below already used this predicate; shellcheck's was
	# never updated to match. (#948)
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts" -type f \( -executable -o -name "*.sh" \) ! -path "*/ci/*" 2>/dev/null)
	# CI scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts/ci" -name "*.sh" -type f 2>/dev/null)
	# Container scripts (e.g. the oakandwave-workflow bootstrap). Executable OR
	# *.sh; the is_shell_script filter below drops non-shell files. Without this,
	# containers/**/*.sh would escape shellcheck entirely (config exists != works).
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/containers" -type f \( -executable -o -name "*.sh" \) 2>/dev/null)
	# Skill helper scripts (non-SKILL.md files in skill dirs)
	for skill_dir in "$REPO_DIR"/skills/*/; do
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			[[ "$(basename "$helper")" == "SKILL.md" ]] && continue
			SCRIPTS+=("$helper")
		done
	done
	# Config scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/config" -type f 2>/dev/null)

	if [[ ${#SCRIPTS[@]} -eq 0 ]]; then
		info "no scripts found"
	else
		for script in "${SCRIPTS[@]}"; do
			rel="${script#"$REPO_DIR/"}"
			if ! is_shell_script "$script"; then
				info "$rel (not a shell script — skipped)"
				continue
			fi
			if shellcheck -x "$script" 2>&1; then
				info "$rel"
				PASS=$((PASS + 1))
			else
				err "$rel"
				FAIL=$((FAIL + 1))
			fi
		done
	fi
fi

# --- shfmt -------------------------------------------------------------------
echo ""
echo "shfmt"
echo "──────────────────────────────────────────"
if ! command -v shfmt &>/dev/null; then
	err "shfmt not found — skipping"
	FAIL=$((FAIL + 1))
else
	SCRIPTS=()
	# Root-level shell scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR" -maxdepth 1 -name "*.sh" -type f 2>/dev/null)
	# All scripts in scripts/
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts" -type f \( -executable -o -name "*.sh" \) 2>/dev/null)
	# Container scripts (e.g. the oakandwave-workflow bootstrap) — mirror the
	# selector used above so shfmt covers the same tree as the linter.
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/containers" -type f \( -executable -o -name "*.sh" \) 2>/dev/null)
	# Skill helper scripts (non-SKILL.md files in skill dirs)
	for skill_dir in "$REPO_DIR"/skills/*/; do
		for helper in "$skill_dir"/*; do
			[[ -f "$helper" ]] || continue
			[[ "$(basename "$helper")" == "SKILL.md" ]] && continue
			SCRIPTS+=("$helper")
		done
	done
	# Config scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/config" -type f 2>/dev/null)

	if [[ ${#SCRIPTS[@]} -eq 0 ]]; then
		info "no scripts found"
	else
		for script in "${SCRIPTS[@]}"; do
			rel="${script#"$REPO_DIR/"}"
			if ! is_shell_script "$script"; then
				info "$rel (not a shell script — skipped)"
				continue
			fi
			if shfmt -d "$script" &>/dev/null; then
				info "$rel"
				PASS=$((PASS + 1))
			else
				err "$rel (formatting differs)"
				FAIL=$((FAIL + 1))
			fi
		done
	fi
fi

# --- Python syntax check -----------------------------------------------------
echo ""
echo "Python syntax (py_compile)"
echo "──────────────────────────────────────────"
is_python_script() {
	local f="$1"
	[[ "$f" == *.py ]] && return 0
	local shebang
	shebang=$(head -1 "$f" 2>/dev/null)
	[[ "$shebang" =~ ^#!.*/python ]] && return 0
	[[ "$shebang" =~ ^#!.*env[[:space:]]+python ]] && return 0
	return 1
}

PY_FILES=()
# Python files in src/
if [[ -d "$REPO_DIR/src" ]]; then
	while IFS= read -r f; do
		PY_FILES+=("$f")
	done < <(find "$REPO_DIR/src" -name "*.py" -type f 2>/dev/null)
fi
# Python scripts in scripts/ (by extension or shebang)
if [[ -d "$REPO_DIR/scripts" ]]; then
	while IFS= read -r f; do
		[[ -f "$f" ]] || continue
		is_python_script "$f" && PY_FILES+=("$f")
	done < <(find "$REPO_DIR/scripts" -type f -not -path "*/ci/*" 2>/dev/null)
fi

if [[ ${#PY_FILES[@]} -eq 0 ]]; then
	info "no Python files found"
else
	for py_file in "${PY_FILES[@]}"; do
		rel="${py_file#"$REPO_DIR/"}"
		if python3 -m py_compile "$py_file" 2>&1; then
			info "$rel"
			PASS=$((PASS + 1))
		else
			err "$rel"
			FAIL=$((FAIL + 1))
		fi
	done
fi

# --- SKILL.md frontmatter validation -----------------------------------------
echo ""
echo "SKILL.md frontmatter"
echo "──────────────────────────────────────────"
for skill_file in "$REPO_DIR"/skills/*/SKILL.md; do
	[[ -f "$skill_file" ]] || continue
	rel="${skill_file#"$REPO_DIR/"}"
	has_name=false
	has_desc=false

	# Read frontmatter (between --- delimiters)
	in_frontmatter=false
	while IFS= read -r line; do
		if [[ "$line" == "---" ]]; then
			if [[ "$in_frontmatter" == true ]]; then
				break
			fi
			in_frontmatter=true
			continue
		fi
		if [[ "$in_frontmatter" == true ]]; then
			[[ "$line" =~ ^name: ]] && has_name=true
			[[ "$line" =~ ^description: ]] && has_desc=true
		fi
	done <"$skill_file"

	if [[ "$has_name" == true && "$has_desc" == true ]]; then
		info "$rel"
		PASS=$((PASS + 1))
	else
		[[ "$has_name" == false ]] && err "$rel — missing 'name:' in frontmatter"
		[[ "$has_desc" == false ]] && err "$rel — missing 'description:' in frontmatter"
		FAIL=$((FAIL + 1))
	fi
done

# --- Install script skill registration ---------------------------------------
# Ensures every skills/*/ directory is reachable by the install script's
# skill-discovery loop. This guards against regressions where a new skill
# (e.g. wavemachine) gets filed but the install path is accidentally narrowed
# to a hardcoded list. Both install and scripts/install-remote.sh must loop
# over skills/*/ unconditionally.
echo ""
echo "Install script skill registration"
echo "──────────────────────────────────────────"
for install_script in "$REPO_DIR/install" "$REPO_DIR/scripts/install-remote.sh"; do
	[[ -f "$install_script" ]] || continue
	rel="${install_script#"$REPO_DIR/"}"
	if grep -q 'for skill_dir in .*skills/\*/' "$install_script"; then
		info "$rel — discovers skills/*/ unconditionally"
		PASS=$((PASS + 1))
	else
		err "$rel — does not appear to discover skills/*/ (possible hardcoded list)"
		FAIL=$((FAIL + 1))
	fi
done

# --- Regression tests --------------------------------------------------------
echo ""
echo "Regression tests"
echo "──────────────────────────────────────────"
for test_script in "$REPO_DIR"/tests/regression/*.sh; do
	[[ -f "$test_script" ]] || continue
	rel="${test_script#"$REPO_DIR/"}"
	if bash "$test_script"; then
		info "$rel"
		PASS=$((PASS + 1))
	else
		err "$rel"
		FAIL=$((FAIL + 1))
	fi
done

# --- Dependency scannability (#1073) ------------------------------------------
#
# Asks one question — "would a dependency scan have anything to look at?" — and
# FAILS if the answer is no. It does not run trivy and does not judge
# vulnerabilities; keeping measurement separate from grading is the point, because
# a gate that does both can hide an empty denominator inside a pass.
#
# It lives HERE, in the lane CI runs, rather than in /precheck's prose. This repo
# reported "0 manifests" on every precheck for eleven days across five filings
# (#922, #941, #944, #1053, #1056) — reported accurately every time, and waved
# through every time. An honest report that changes no outcome is indistinguishable
# from no report at all, so the denominator now decides the exit code.
echo ""
echo "Dependency scannability"
echo "──────────────────────────────────────────"
if bash "$REPO_DIR/scripts/ci/check-scannable.sh" "$REPO_DIR"; then
	info "scripts/ci/check-scannable.sh"
	PASS=$((PASS + 1))
else
	err "scripts/ci/check-scannable.sh — nothing scannable and absence not declared"
	FAIL=$((FAIL + 1))
fi

# --- Dependency COVERAGE (#1137) ----------------------------------------------
#
# The check above is PRE-scan: it proves input exists. It cannot prove the scanner
# ingested that input. Those are different denominators on opposite sides of the
# scan, and two green checks either side of a stage prove nothing about the stage
# between them — flightdeck sits in exactly that gap (manifests present, trivy
# parsing none of them, both checks green, flightdeck#8).
#
# It also closes the other half: the kit never ran the scan at all. It existed only
# as PROSE in /precheck's Job C asking a sub-agent to report the denominator. An
# instruction can be forgotten by the next agent; a tool that emits the number
# cannot.
#
# trivy absent is a SKIP, not a failure — the scan is not universally installable
# and a hard dependency here would make validate.sh unrunnable on a fresh box.
# `dep_rc=0` then `|| dep_rc=$?` — NOT a bare assignment followed by `$?`.
# This script runs under `set -euo pipefail` (line 22). A simple command that is
# only an assignment takes the exit status of its command substitution, and
# errexit fires on it: the `case` below would be DEAD CODE, validate.sh would
# abort mid-section with no summary, and `$dep_out` — which captured stderr too —
# would be discarded unprinted.
#
# It would have failed in CI on the very first run: at the time this bug was
# found, .github/workflows/validate.yml installed shellcheck, shfmt and Python
# but NOT trivy, so the script returned 3, and the branch that exists to make
# that a [SKIPPED] was unreachable. It passed locally only because trivy
# happens to be installed here and this repo is clean — rc=0, errexit never
# trips. The one path that worked was the one path exercised. CI now installs
# trivy too (cc-workflow#1169 code review) — the [SKIPPED] branch below is a
# genuine fallback for a fresh box again, not a standing blind spot.
dep_rc=0
dep_out="$(bash "$REPO_DIR/scripts/ci/dependency-scan.sh" "$REPO_DIR" 2>&1)" || dep_rc=$?
printf '%s\n' "$dep_out" | sed -n 's/^dependency-scan: /  /p'
case "$dep_rc" in
0)
	info "scripts/ci/dependency-scan.sh"
	PASS=$((PASS + 1))
	;;
3)
	info "scripts/ci/dependency-scan.sh — [SKIPPED] trivy not installed"
	;;
*)
	err "scripts/ci/dependency-scan.sh — rc=$dep_rc (1=findings, 2=present-but-uningested, 4=nothing scannable, 5=scanner error)"
	printf '%s\n' "$dep_out" >&2
	FAIL=$((FAIL + 1))
	;;
esac

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
	exit 1
fi
