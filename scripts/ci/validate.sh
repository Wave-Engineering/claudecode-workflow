#!/usr/bin/env bash
# validate.sh — Run validation checks on the claudecode-workflow repo
#
# Checks:
#   1. shellcheck on all shell scripts
#   2. shfmt formatting check on all shell scripts
#   3. SKILL.md frontmatter validation (name + description present)

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

info() { echo "  [+] $*"; }
err() { echo "  [!] $*"; }

# --- shellcheck ---------------------------------------------------------------
echo "shellcheck"
echo "──────────────────────────────────────────"
if ! command -v shellcheck &>/dev/null; then
	err "shellcheck not found — skipping"
	FAIL=$((FAIL + 1))
else
	SCRIPTS=()
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts" -type f -executable ! -path "*/ci/*" 2>/dev/null)
	# Also check CI scripts
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts/ci" -name "*.sh" -type f 2>/dev/null)

	if [[ ${#SCRIPTS[@]} -eq 0 ]]; then
		info "no scripts found"
	else
		for script in "${SCRIPTS[@]}"; do
			rel="${script#"$REPO_DIR/"}"
			if shellcheck "$script" 2>&1; then
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
	while IFS= read -r f; do
		SCRIPTS+=("$f")
	done < <(find "$REPO_DIR/scripts" -type f \( -executable -o -name "*.sh" \) 2>/dev/null)

	if [[ ${#SCRIPTS[@]} -eq 0 ]]; then
		info "no scripts found"
	else
		for script in "${SCRIPTS[@]}"; do
			rel="${script#"$REPO_DIR/"}"
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

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
echo "Results: $PASS passed, $FAIL failed"

if [[ $FAIL -gt 0 ]]; then
	exit 1
fi
