#!/usr/bin/env bash
# crewchat-waiter.sh — CC SessionStart + Stop hook, run with asyncRewake. (#1420)
#
# Delivery that does not depend on the agent. `crewchat-doorbell` is a background task the
# agent must start, restart and not duplicate, so every way an agent can forget (/clear, a
# reseed, a lost notification, a re-arm through an outage, a second copy) is a way for chat
# to fail or to double. `crewchat-waiter` (mattermost-crew#204) is the same wait, started by
# the harness: Claude Code runs a hook with `asyncRewake: true` in the background and wakes
# the model when it exits 2. Registered on SessionStart (covers startup, resume, /clear and
# compact) and on Stop (re-arms it after every turn), an idle agent is woken by a message and
# a busy one gets it folded into the turn it is in. Nobody types anything.
#
# This script is only the guard that makes registering the hook safe everywhere:
#   - no `crewchat-waiter` on this host (no crewchat daemon, an older install): exit 0 and
#     say nothing. Only exit 2 wakes the model, so a host without crewchat is untouched.
#   - otherwise exec it, so its exit code (2 = an event to wake for) is the hook's own.
# The waiter is single-instance per Dev-Name by an flock, so the Stop hook starting another
# at the end of every turn is a silent no-op while one is still waiting, and it exits 0
# without an identity, so a repo that is not a crew checkout never wakes anyone.
#
# Not on PATH is the usual case for a `uv tool install`: ~/.local/bin is checked as well.
set -u

waiter="$(command -v crewchat-waiter 2>/dev/null || true)"
if [[ -z "$waiter" && -x "${HOME:-/nonexistent}/.local/bin/crewchat-waiter" ]]; then
	waiter="${HOME:-/nonexistent}/.local/bin/crewchat-waiter"
fi
[[ -n "$waiter" ]] || exit 0

exec "$waiter" "$@"
