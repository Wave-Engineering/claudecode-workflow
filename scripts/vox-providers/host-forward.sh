#!/usr/bin/env bash
# host-forward.sh — vox provider for containerised agents (#1084).
#
# A container has no audio: no synthesis provider, and no player at all (none of
# afplay/paplay/aplay/ffplay, no libpulse). So this provider does not synthesise
# anything. It writes the TEXT to a spool directory on a host-visible mount and
# lets the host's already-configured `vox` do both synthesis and playback.
#
# Audio is deliberately NOT forwarded. Passing the host's PipeWire socket through
# would mean adding an audio stack to every image to play one sentence, and
# coupling containers to the host's audio devices.
#
# Provider contract (scripts/vox-providers/README.md): text in $1 (or stdin),
# audio out at $VOX_OUTPUT_FILE, exit 0/non-zero. We honour it by writing an
# EMPTY $VOX_OUTPUT_FILE — there is no audio to produce here — which the paired
# no-op player then ignores. The pairing is the whole trick: provider forwards,
# player does nothing, because playback happens on the other side of the mount.
#
# THE BACKLOG WARNING IS THE POINT. If nothing is draining the spool — host unit
# masked, stopped, never installed, or watching a different major — an agent
# would otherwise believe it is speaking while the operator hears silence. That
# is the inert-guard shape this repo keeps producing (#1061 R-14, #1056 trivy,
# #1069 "[0 items]", #1076 bootstrap), and it is worse here than a hard failure
# would be, because the agent has no way to notice. So a stale spool is LOUD.
set -uo pipefail

SPOOL="${OAW_VOX_SPOOL:-$HOME/.oaw/vox-spool}"
# How long a file may sit unconsumed before we call the drain broken. The host
# path unit fires within a second; a minute is far outside normal and still short
# enough that the operator hears about it during the session that broke it.
STALE_SECONDS="${OAW_VOX_STALE_SECONDS:-60}"

TEXT="${1:-}"
if [[ -z "$TEXT" && ! -t 0 ]]; then
	TEXT="$(cat)"
fi
if [[ -z "$TEXT" ]]; then
	echo "host-forward: no text to speak" >&2
	exit 1
fi

# Honour the contract even though there is no audio: an empty file, so the paired
# no-op player has something to be handed and `vox` sees a provider that worked.
if [[ -n "${VOX_OUTPUT_FILE:-}" ]]; then
	: >"$VOX_OUTPUT_FILE" 2>/dev/null || true
fi

if ! mkdir -p "$SPOOL" 2>/dev/null; then
	echo "host-forward: cannot create the spool at $SPOOL — the agent has NO voice" >&2
	exit 1
fi
if [[ ! -w "$SPOOL" ]]; then
	echo "host-forward: spool $SPOOL is not writable — the agent has NO voice" >&2
	exit 1
fi

# WARN BEFORE WRITING, not after. Writing first and then checking would report a
# backlog that includes this very message, so the first stalled utterance would
# look fine and only the second would complain.
# `! -newermt "-N seconds"` is precise to the second. `-mmin +N` would have been
# minute-granular, so any threshold under 60s silently became "never stale".
# FAIL CLOSED. `find … 2>/dev/null | wc -l` yields 0 when find itself errors, so
# a find that cannot parse -newermt would silently disable the warning this whole
# feature is built around — the guard going quiet in exactly the way it exists to
# prevent. Check find's own status and say so.
if stale_out="$(find "$SPOOL" -maxdepth 1 -type f -name '*.msg' \
	! -newermt "-${STALE_SECONDS} seconds" 2>/dev/null)"; then
	stale="$(printf '%s' "$stale_out" | grep -c . || true)"
else
	echo "host-forward: WARNING — cannot check the spool for a backlog (find failed);" >&2
	echo "host-forward: treat delivery as UNVERIFIED rather than assume it worked." >&2
	stale=0
fi
if [[ "$stale" -gt 0 ]]; then
	echo "host-forward: WARNING — $stale message(s) have been sitting in $SPOOL unconsumed." >&2
	echo "host-forward: nothing on the host is draining the spool, so this was NOT heard." >&2
	echo "host-forward: check 'systemctl --user status oaw-vox-spool.path oaw-vox-spool.service' on the host." >&2
fi

# Identity so a multi-agent host can attribute what it hears. vox already
# front-loads "<Name> here." into the text (#952), so this is for the host-side
# log and for triage, not for re-deriving what to say.
#
# Resolved the way vox's own resolve_speaker does — walk UP from the working
# directory looking for `.claude/agent-identity.json`. The canonical file is
# project-rooted, not $HOME-rooted; reading `$HOME/.claude/agent-identity.json`
# looked right and produced `dev_name: unknown` on a real container, because
# that is simply not where it lives.
resolve_dev_name() {
	local d="${OAW_IDENTITY_DIR:-${CLAUDE_PROJECT_DIR:-$PWD}}"
	command -v python3 >/dev/null 2>&1 || return 0
	while [[ -n "$d" && "$d" != "/" ]]; do
		if [[ -r "$d/.claude/agent-identity.json" ]]; then
			python3 -c '
import json, sys
try:
    print(json.load(open(sys.argv[1])).get("dev_name") or "")
except Exception:
    pass
' "$d/.claude/agent-identity.json" 2>/dev/null
			return 0
		fi
		d="$(dirname "$d")"
	done
}

dev_name="$(resolve_dev_name)"
[[ -n "$dev_name" ]] || dev_name="unknown"

# Write to a temp name in the SAME directory, then rename. The host watcher fires
# on file creation, so a partially-written file would be read and spoken as a
# truncated sentence; rename within one filesystem is atomic.
# mktemp, not $$.$RANDOM: PIDs collide freely across containers sharing one host
# spool, and two agents colliding means one of them is never heard. The `.tmp`
# prefix keeps the in-flight file hidden from the host path unit, which ignores
# dot-entries (verified) — otherwise it would fire on a partial write.
stamp="$(date -u +%Y%m%dT%H%M%SZ 2>/dev/null || echo unknown)"
tmp="$(mktemp "$SPOOL/.tmp.XXXXXXXX" 2>/dev/null)" || {
	echo "host-forward: could not create a spool file in $SPOOL — the agent has NO voice" >&2
	exit 1
}
suffix="${tmp##*.}" # the random component mktemp chose
final="$SPOOL/${stamp}.${suffix}.msg"

{
	printf 'dev_name: %s\n' "$dev_name"
	printf 'voice: %s\n' "${VOX_VOICE:-}"
	printf '\n'
	printf '%s\n' "$TEXT"
} >"$tmp" 2>/dev/null || {
	echo "host-forward: could not write to $SPOOL — the agent has NO voice" >&2
	rm -f "$tmp" 2>/dev/null || true
	exit 1
}

if ! mv -f "$tmp" "$final" 2>/dev/null; then
	echo "host-forward: could not publish $final — the agent has NO voice" >&2
	rm -f "$tmp" 2>/dev/null || true
	exit 1
fi

exit 0
