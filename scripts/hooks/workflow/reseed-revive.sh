#!/usr/bin/env bash
# reseed-revive.sh — CC SessionStart hook (matcher: "clear")
#
# Dormant unless an armed reseed file exists for this project. When armed and
# fresh, it points the fresh session at the seed and launches reseed-kick.sh,
# which types `/reseed revive` into the pane until the session acknowledges it.
#
# Contract (CC SessionStart hook, matcher: "clear"):
#   stdin:  JSON with .session_id, .cwd, .source, .transcript_path (handed to the
#           kicker, which reads it to see a revive that submitted no prompt, #1244)
#   stdout: injected as system-reminder into the fresh agent context
#   exit:   always 0 (best-effort; never block session start)
#
# Armed file: <cwd>/.claude/reseed-armed.json   { "armed_at": "...", "tmux_pane": "..." }
# Seed:       <cwd>/.claude/reseed-revive.md    — ONE fixed path (#1225)
#
# What changed in #1225, and why:
#   - The seed is NOT injected. One pointer line only; `/reseed revive` reads the
#     file. Injecting made the revive depend on this hook firing exactly once —
#     it fired twice on hosts whose --local install doubled every hook, and the
#     seed arrived twice (2026-08-31).
#   - The armed file is CLAIMED with an atomic mv; only the mv winner proceeds,
#     so a concurrent second invocation finds nothing to do.
#   - The kick is reseed-kick.sh under setsid: out of this hook's process group
#     (a `( … ) & disown` child may be reaped when the hook exits), retried with
#     backoff, ack-verified, and loud when it fails. This hook logs that it
#     LAUNCHED the kicker — the kicker logs what actually happened.
#
# Safety gate: auto-revive ONLY when fresh (< 5 min mtime). CWD-scoping of the
# armed file provides cross-project isolation; freshness provides temporal
# isolation. Session ID is NOT checked — /clear starts a new session ID by
# design, so old-vs-new ID is always a mismatch and would break every use.
#
# Issues: cc-workflow#757, #1225

LOG() { printf '[hooks/workflow/reseed-revive] %s\n' "$*" >&2; }

FRESH_WINDOW_SECS=300 # 5 minutes

INPUT=$(cat 2>/dev/null || true)
HOOK_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null || true)
HOOK_CWD="${HOOK_CWD:-$(pwd)}"
TRANSCRIPT=$(printf '%s' "$INPUT" | jq -r '.transcript_path // empty' 2>/dev/null || true)

ARMED_FILE="${HOOK_CWD}/.claude/reseed-armed.json"
SEED_PATH="${HOOK_CWD}/.claude/reseed-revive.md"
KICK="${RESEED_KICK_BIN:-$(dirname "$0")/../../reseed-kick.sh}"

# --- Claim the armed file atomically; no armed file (or lost the race) → no-op ---
CLAIMED="${ARMED_FILE}.claimed.$$"
mv "$ARMED_FILE" "$CLAIMED" 2>/dev/null || exit 0
trap 'rm -f "$CLAIMED"' EXIT

TMUX_PANE=$(jq -r '.tmux_pane // empty' "$CLAIMED" 2>/dev/null || true)

# --- Freshness check via mtime (mv preserves it) ---
now=$(date +%s)
file_mtime=$(python3 -c "import os,sys; print(int(os.path.getmtime(sys.argv[1])))" "$CLAIMED" 2>/dev/null ||
	stat -c %Y "$CLAIMED" 2>/dev/null ||
	stat -f %m "$CLAIMED" 2>/dev/null ||
	echo 0)
age_secs=$((now - file_mtime))

if [[ ! -f "$SEED_PATH" ]]; then
	printf '[RESEED] A reseed was armed, but its seed %s is missing — nothing to revive from.\n' "$SEED_PATH"
	LOG "armed but seed missing ($SEED_PATH) — armed file consumed"
	exit 0
fi

if [[ $age_secs -ge $FRESH_WINDOW_SECS ]]; then
	# Stale: no automatic kick. An explicit `/reseed revive` is the intent signal.
	printf '[RESEED PENDING] A seed from before /clear is waiting (armed %dm ago): %s\nRun /reseed revive to continue from it, or delete it to discard.\n' \
		"$((age_secs / 60))" "$SEED_PATH"
	LOG "stale armed file (${age_secs}s) — pointer only, no kick"
	exit 0
fi

printf '[RESEED AUTO-REVIVE] This session was seeded before /clear: %s\n%s is being typed into this pane automatically. If it has not arrived, type it.\n' "$SEED_PATH" "/reseed revive"

if [[ -z "$TMUX_PANE" ]]; then
	LOG "no tmux pane recorded — revive needs a manual /reseed revive"
	exit 0
fi
if [[ ! -f "$KICK" ]]; then
	LOG "kicker not found at $KICK — revive needs a manual /reseed revive"
	exit 0
fi

# Detach the kicker into its own session, and CHECK that it happened: the pager
# lives inside the kicker, so a launch that silently fails means no revive and
# no page — the exact failure #1225 exists to remove. `setsid -f` first; then a
# python3 double-fork + setsid (macOS has no setsid; old util-linux and busybox
# lack -f). Not `nohup … &`: that stays in this hook's process group.
launched=""
if command -v setsid &>/dev/null &&
	setsid -f bash "$KICK" "$TMUX_PANE" "$HOOK_CWD" "$TRANSCRIPT" </dev/null >/dev/null 2>&1; then
	launched="setsid"
elif python3 -I -c '
import os, sys
if os.fork():
    os._exit(0)
os.setsid()
if os.fork():
    os._exit(0)
os.execvp("bash", ["bash"] + sys.argv[1:])
' "$KICK" "$TMUX_PANE" "$HOOK_CWD" "$TRANSCRIPT" </dev/null >/dev/null 2>&1; then
	launched="python3 setsid"
fi

if [[ -n "$launched" ]]; then
	LOG "kicker launched ($launched) for pane $TMUX_PANE — outcome in ~/.claude/logs/reseed-kick.log"
else
	printf 'The automatic revive could not start (no setsid, no python3) — type /reseed revive.\n'
	LOG "kicker launch FAILED — no setsid and no python3; revive needs a manual /reseed revive"
fi
exit 0
