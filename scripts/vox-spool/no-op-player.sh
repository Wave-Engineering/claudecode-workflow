#!/usr/bin/env bash
# no-op-player.sh — the playback half of the containerised-vox pair (#1084).
#
# Paired with host-forward.sh. That provider does not synthesise audio; it
# forwards the TEXT to a host-visible spool, and the host's own vox synthesises
# and plays it. So there is nothing here to play, and this exists so `vox` does
# not fail resolving a player that could not work anyway — the container has no
# afplay/paplay/aplay/ffplay and no libpulse.
#
# It lives HERE rather than in scripts/vox-providers/ on purpose: everything in
# that directory is offered by `vox --setup --pick=<name>`, and a PLAYER picked
# as a PROVIDER produces exactly the mute-while-believing-it-spoke outcome #1084
# refused to ship.
#
# It is NOT a silencer. It is only ever wired alongside host-forward.sh, whose
# job is to be loud when the far side is not draining the spool. Pointing this at
# a real synthesis provider would convert a working voice into a silent one, and
# pointing `~/.config/vox/provider` at `silent.sh` instead of this pair would
# convert a visible gap into an invisible one — the failure #1084 explicitly
# refused to ship.
#
# Usage: no-op-player.sh <audio-file>   (argument accepted and ignored)
exit 0
