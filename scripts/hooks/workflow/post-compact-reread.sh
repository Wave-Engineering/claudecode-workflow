#!/usr/bin/env bash
# shellcheck source-path=SCRIPTDIR
# post-compact-reread.sh — PostCompact hook
#
# After context compaction, injects a reminder to re-read CLAUDE.md
# and confirm rules before proceeding. This replaces the prose rule
# "MANDATORY: Post-Compaction Rules Confirmation" in CLAUDE.md.
set -uo pipefail

INPUT=$(cat 2>/dev/null || true)
SESSION_ID=$(printf '%s' "$INPUT" | jq -r '.session_id // "unknown"' 2>/dev/null || true)
source "$(dirname "$0")/metrics.sh"
log_metric "$SESSION_ID" "compact"

cat <<'EOF'
⚠️ Context was compacted. Before continuing work:
1. Re-read CLAUDE.md (the full file — it is short)
2. Confirm rules of engagement apply to current work
3. Check git status for working state

Past failures after compaction: skipped pre-commit checks, commits without testing, push without validation.
EOF
exit 0
