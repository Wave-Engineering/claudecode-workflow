#!/usr/bin/env bash
# context-freshness-warn.sh — CC SessionStart hook (matchers: "resume", "startup").
#
# Warns when a session's context PREDATES the last kit install. On `claude
# --continue`/`--resume`, the MCP binaries and on-disk skills refresh, but the
# skill BODIES already baked into the transcript do NOT — so a resumed agent can
# act on stale, pre-install skill instructions (e.g. a superseded gate check).
# This surfaces that so the agent re-invokes the skill (reloading the current
# body) or reorients before doing wave/gate work.
#
# Contract (CC SessionStart hook):
#   stdin:  JSON with .session_id, .transcript_path, .cwd, .source
#   stdout: injected as a system-reminder into the fresh agent context
#   exit:   ALWAYS 0 (fire-and-forget; never block session start)
#
# Staleness = the session's first genuinely-timestamped event is earlier than the
# `installed_at_epoch` in the last-install stamp (written by
# scripts/write-install-stamp at the end of ./install). Fresh startups
# self-filter: their first timestamped event is "now" > install, so nothing fires.
#
# Epic #906, story D1 #908.
set -u

INPUT=$(cat 2>/dev/null || true)
jqget() { printf '%s' "$INPUT" | jq -r "$1 // empty" 2>/dev/null || true; }

SOURCE=$(jqget '.source')
CWD=$(jqget '.cwd'); CWD="${CWD:-$(pwd)}"
TRANS=$(jqget '.transcript_path')

# clear/compact are explicitly-fresh contexts (handled by other hooks); skip them.
case "$SOURCE" in
	clear | compact) exit 0 ;;
esac

# Prefer a project-local stamp (from a --local install), else the global one.
STAMP=""
for cand in "$CWD/.claude/.last-kit-install" "$HOME/.claude/.last-kit-install"; do
	if [[ -f "$cand" ]]; then STAMP="$cand"; break; fi
done
[[ -n "$STAMP" ]] || exit 0
INSTALLED_EPOCH=$(jq -r '.installed_at_epoch // empty' "$STAMP" 2>/dev/null || true)
[[ -n "$INSTALLED_EPOCH" ]] || exit 0

# The transcript path comes from stdin (never reconstructed — CC's project-dir
# encoding replaces '/', '.', ':' and more with '-', which a naive rebuild misses).
[[ -n "$TRANS" && -f "$TRANS" ]] || exit 0

# Session start = the FIRST record carrying a top-level timestamp. Early CC records
# (custom-title, mode, queue-operation preamble) may have none, so line 1 is NOT a
# reliable source — scan for the first that does.
FIRST_TS=$(jq -r 'select(.timestamp) | .timestamp' "$TRANS" 2>/dev/null | head -n 1)
[[ -n "$FIRST_TS" ]] || exit 0
SESSION_EPOCH=$(python3 -c "import sys,datetime; print(int(datetime.datetime.fromisoformat(sys.argv[1].replace('Z','+00:00')).timestamp()))" "$FIRST_TS" 2>/dev/null || echo 0)

if [[ "$SESSION_EPOCH" -gt 0 && "$SESSION_EPOCH" -lt "$INSTALLED_EPOCH" ]]; then
	INSTALLED_AT=$(jq -r '.installed_at // "?"' "$STAMP" 2>/dev/null || echo "?")
	SHA=$(jq -r '.repo_sha // "?"' "$STAMP" 2>/dev/null | cut -c1-9)
	CHANGED=$(jq -r '(.changed_skills // []) | join(", ")' "$STAMP" 2>/dev/null || true)
	printf '[CONTEXT FRESHNESS WARNING] This session began before the last kit install (%s, cc-workflow %s). Skill bodies frozen in your transcript may be STALE — on-disk skills and MCP binaries have refreshed, but the instructions captured in your context have not. Before any wave/gate/precheck work, re-invoke the relevant skill (it reloads the current version) or run /reseed / reorient to flush stale skill text.' \
		"$INSTALLED_AT" "$SHA"
	[[ -n "$CHANGED" ]] && printf ' Skills changed in that install: %s.' "$CHANGED"
	printf '\n'
fi
exit 0
