#!/usr/bin/env bash
# install.sh — Deploy Claude Code workflow environment
#
# Installs skills, scripts, and the CLAUDE.md template from this repo
# into the correct locations on the local machine.
#
# Usage:
#   ./install.sh              Install everything
#   ./install.sh --dry-run    Show what would be done without doing it
#   ./install.sh --skills     Install skills only
#   ./install.sh --scripts    Install scripts only
#
# Targets:
#   Skills  → ~/.claude/skills/<name>/SKILL.md
#   Scripts → ~/.local/bin/<name>
#
# Existing files are backed up to <file>.bak before overwriting.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="$HOME/.claude/skills"
SCRIPTS_DIR="$HOME/.local/bin"
DRY_RUN=false
INSTALL_SKILLS=true
INSTALL_SCRIPTS=true

# --- Parse args ---------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)  DRY_RUN=true; shift ;;
    --skills)   INSTALL_SCRIPTS=false; shift ;;
    --scripts)  INSTALL_SKILLS=false; shift ;;
    --help|-h)
      grep '^#' "$0" | sed 's/^# \?//' | tail -n +2
      exit 0
      ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# --- Helpers ------------------------------------------------------------------
info()  { echo "  [+] $*"; }
warn()  { echo "  [!] $*"; }
skip()  { echo "  [-] $*"; }

do_copy() {
  local src="$1" dest="$2"
  if [[ "$DRY_RUN" == true ]]; then
    info "(dry-run) $src → $dest"
    return
  fi
  if [[ -f "$dest" ]]; then
    if diff -q "$src" "$dest" &>/dev/null; then
      skip "$dest (unchanged)"
      return
    fi
    cp "$dest" "${dest}.bak"
    warn "Backed up existing: ${dest}.bak"
  fi
  mkdir -p "$(dirname "$dest")"
  cp "$src" "$dest"
  info "$src → $dest"
}

# --- Install skills -----------------------------------------------------------
if [[ "$INSTALL_SKILLS" == true ]]; then
  echo ""
  echo "Skills → $SKILLS_DIR"
  echo "──────────────────────────────────────────"
  for skill_dir in "$REPO_DIR"/skills/*/; do
    skill_name="$(basename "$skill_dir")"
    src="$skill_dir/SKILL.md"
    dest="$SKILLS_DIR/$skill_name/SKILL.md"
    [[ -f "$src" ]] && do_copy "$src" "$dest"
  done
fi

# --- Install scripts ----------------------------------------------------------
if [[ "$INSTALL_SCRIPTS" == true ]]; then
  echo ""
  echo "Scripts → $SCRIPTS_DIR"
  echo "──────────────────────────────────────────"
  for script in "$REPO_DIR"/scripts/*; do
    [[ -f "$script" ]] || continue
    script_name="$(basename "$script")"
    dest="$SCRIPTS_DIR/$script_name"
    do_copy "$script" "$dest"
    if [[ "$DRY_RUN" != true ]]; then
      chmod +x "$dest"
    fi
  done
fi

# --- Summary ------------------------------------------------------------------
echo ""
echo "──────────────────────────────────────────"
if [[ "$DRY_RUN" == true ]]; then
  echo "Dry run complete. No files were modified."
else
  echo "Installation complete."
fi

# --- Dependency check ---------------------------------------------------------
echo ""
echo "Dependency check:"
missing=()
for cmd in curl jq glab gh python3; do
  if command -v "$cmd" &>/dev/null; then
    info "$cmd $(command -v "$cmd")"
  else
    warn "$cmd — NOT FOUND"
    missing+=("$cmd")
  fi
done

if [[ -f "$HOME/secrets/slack-bot-token" ]]; then
  info "slack-bot-token found"
else
  warn "~/secrets/slack-bot-token — NOT FOUND (needed for /ping)"
fi

if [[ ${#missing[@]} -gt 0 ]]; then
  echo ""
  warn "Missing dependencies: ${missing[*]}"
  echo "  Install them before using the skills that require them."
fi
