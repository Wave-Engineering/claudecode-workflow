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
#   Note: the shellcheck pass scans executable files in scripts/ (excluding
#   ci/) plus *.sh files in ci/, while shfmt scans all executable-or-*.sh
#   files in scripts/ (including ci/). Both scan skill helpers and config/.
#   The slight asymmetry means a non-.sh executable in ci/ is checked by
#   shfmt but not by the shellcheck pass.

set -euo pipefail

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
	# Scripts directory (excluding ci/)
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts" -type f -executable ! -path "*/ci/*" 2>/dev/null)
	# CI scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts/ci" -name "*.sh" -type f 2>/dev/null)
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

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
	exit 1
fi
