#!/usr/bin/env bash
# reseed-revive.sh — CC SessionStart hook (matcher: "clear")
#
# Dormant unless an armed reseed file exists for this project. When armed
# and fresh, injects the seed content into the fresh agent context (stdout)
# and fires a tmux keystroke to kick the agent off — fully autonomous revival
# with no user action after /reseed.
#
# Contract (CC SessionStart hook, matcher: "clear"):
#   stdin:  JSON with .session_id, .cwd, .source
#   stdout: injected as system-reminder into the fresh agent context
#   exit:   always 0 (best-effort; never block session start)
#
# Armed file: <cwd>/.claude/reseed-armed.json
#   { "session_id": "...", "seed_path": "...", "armed_at": "...", "tmux_pane": "..." }
#
# Safety gate: auto-revive ONLY when fresh (< 5 min mtime). CWD-scoping of
# the armed file provides cross-project isolation; freshness provides temporal
# isolation. Session ID is NOT checked — /clear starts a new session ID by
# design, so old-vs-new ID is always a mismatch and would break every use.
# Consume-don't-lose: armed file deleted after inject; seed file kept until agent confirms.
#
# Issue: cc-workflow#757

LOG() { printf '[hooks/workflow/reseed-revive] %s\n' "$*" >&2; }

FRESH_WINDOW_SECS=300 # 5 minutes

INPUT=$(cat 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
HOOK_CWD="${HOOK_CWD:-$(pwd)}"

ARMED_FILE="${HOOK_CWD}/.claude/reseed-armed.json"

# --- No armed file → no-op ---
if [[ ! -f "$ARMED_FILE" ]]; then
	exit 0
fi

# --- Read armed metadata ---
ARMED_JSON=$(cat "$ARMED_FILE" 2>/dev/null || true)
SEED_PATH=$(printf '%s' "$ARMED_JSON" | jq -r '.seed_path // empty' 2>/dev/null || true)
TMUX_PANE=$(printf '%s' "$ARMED_JSON" | jq -r '.tmux_pane // empty' 2>/dev/null || true)

# --- Freshness check via mtime (portable: python3 preferred, date fallback) ---
now=$(date +%s)
file_mtime=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$ARMED_FILE" 2>/dev/null ||
	stat -c %Y "$ARMED_FILE" 2>/dev/null ||
	stat -f %m "$ARMED_FILE" 2>/dev/null ||
	echo 0)
age_secs=$((now - file_mtime))
is_fresh=false
[[ $age_secs -lt $FRESH_WINDOW_SECS ]] && is_fresh=true

# --- Seed file readable? ---
if [[ -z "$SEED_PATH" || ! -f "$SEED_PATH" ]]; then
	LOG "seed_path missing or unreadable ($SEED_PATH) — clearing armed file"
	rm -f "$ARMED_FILE"
	exit 0
fi

SEED_CONTENT=$(cat "$SEED_PATH" 2>/dev/null || true)

if [[ "$is_fresh" == "true" ]]; then
	# --- AUTO-REVIVE ---
	# Inject seed content into fresh context; trigger agent via tmux
	printf '[RESEED AUTO-REVIVE] Your context was seeded before /clear. Read the seed below, run /engage to confirm rules, then continue your work unblocked.\n\n%s\n' "$SEED_CONTENT"

	# Kick the agent via tmux after a short delay for TUI init
	if [[ -n "$TMUX_PANE" ]]; then
		(sleep 2 && tmux send-keys -t "$TMUX_PANE" "continue" Enter) &
		disown
	else
		LOG "no tmux pane available — agent will need manual trigger"
	fi

	# Consume armed file (seed file preserved until agent confirms)
	rm -f "$ARMED_FILE"
	LOG "auto-revived: seed injected, tmux trigger sent, armed file consumed"

else
	# --- CONFIRM REQUEST (stale armed file) ---
	age_min=$((age_secs / 60))

	printf '[RESEED PENDING — confirm required] An armed seed exists but auto-revive was skipped (stale: %dm old).\nSeed path: %s\nRun: Read "%s" and revive — or delete %s to discard.\n' \
		"$age_min" "$SEED_PATH" "$SEED_PATH" "$ARMED_FILE"

	# Nudge the agent to surface the confirm request
	if [[ -n "$TMUX_PANE" ]]; then
		(sleep 2 && tmux send-keys -t "$TMUX_PANE" "pending reseed — confirm or discard?" Enter) &
		disown
	fi

	LOG "confirm-request injected: stale (${age_min}m)"
fi

exit 0
