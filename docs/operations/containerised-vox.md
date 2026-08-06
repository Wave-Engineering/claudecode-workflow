# Giving containerised agents a voice

`vox` cannot work inside a container. There is no provider config, and no player
at all — none of `afplay`/`paplay`/`aplay`/`ffplay`, and no `libpulse`. Discord
still reaches you, but the audible interrupt — the thing that gets your attention
when nobody is watching a channel — was gone for every agent moved into a
container (#1084).

## What was built

**Text is forwarded, not audio.** The container's `vox` provider writes the
message to a spool directory on a host-visible mount; a `systemd --user` path
unit on the host notices and runs your own already-configured `vox` on it.

```
container                          host
  vox "…"
   └─ ~/.config/vox/provider  ──────► ~/.oaw/state/8/vox-spool/<ts>.msg
        (host-forward.sh)                      │
      ~/.config/vox/player                     │  oaw-vox-spool.path
        (no-op — playback is over there)       ▼
                                        oaw-vox-drain ──► vox ──► 🔊
```

The provider/player **pair** is the whole trick: the provider forwards the text
and writes an empty `$VOX_OUTPUT_FILE`, and the player does nothing, because
playback happens on the other side of the mount. This needs no change to `vox`
itself — it already resolves `~/.config/vox/{provider,player}` ahead of its
bundled defaults.

### Why not pass the audio through

The host runs PipeWire and its socket *could* be mounted. Rejected: the container
has no client libraries and no player, so it would mean adding an entire audio
stack to every image in order to play one sentence, and coupling containers to
the host's audio devices. Forwarding text costs one directory.

### Why not just make it silent

Pointing `~/.config/vox/provider` at the bundled `silent.sh` also stops the
error. It does it by making the agent mute while it *believes* it has spoken —
converting a visible gap into an invisible one. That is the failure mode this
repo keeps producing (#1061, #1056, #1069, #1076) and #1084 refused it
explicitly.

## Enabling it on the host

One command, and it is an explicit operator step on purpose:

```bash
oaw-vox-drain --install-units
```

`./install` deliberately does **not** touch systemd. Installing units from the
kit installer would mutate your running session state under live sibling agents —
exactly the class of side effect the contained-workflow campaign exists to
eliminate.

Check it, and undo it:

```bash
oaw-vox-drain --status
oaw-vox-drain --uninstall-units
```

Run the drain by hand to test without waiting for a container:

```bash
printf 'dev_name: manual\n\nhello from the host\n' > ~/.oaw/state/8/vox-spool/test.msg
oaw-vox-drain
```

## If agents go quiet

**The provider warns when nothing is draining the spool.** That warning is the
most important part of this feature, not a nicety: without it an agent believes
it is speaking while you hear silence, and it has no way to notice from inside
the container.

```
host-forward: WARNING — 3 message(s) have been sitting in … unconsumed.
host-forward: nothing on the host is draining the spool, so this was NOT heard.
```

Diagnose in this order:

| symptom | check |
|---|---|
| the warning above | `systemctl --user status oaw-vox-spool.path oaw-vox-spool.service` |
| spool fills, unit active | `journalctl --user -u oaw-vox-spool.service -n 50` |
| `spooling into a void` in the journal | the host has no `~/.local/bin/vox` — run `./install` |
| nothing spooled at all | the mount is missing: `scripts/ci/check-mount-drift.sh <profile>` |

Messages older than 15 minutes are **dropped, not spoken** — hearing twenty
stale status updates in a row is worse than losing them. The drain also deletes
each message *before* speaking it: `vox` detaches playback, so a message that
made `vox` exit non-zero would otherwise be re-spoken on every trigger and a
`DirectoryNotEmpty` path unit would spin on it forever.

## Notes

- The spool is **major-partitioned** (`~/.oaw/state/<major>/vox-spool`) like the
  rest of sandbox state, so a v9 agent cannot spool into a v8 host unit's queue.
  `oaw-vox-drain` takes `OAW_MAJOR` if you run several.
- Messages carry the speaking agent's `dev_name`, resolved by walking up from the
  working directory the way `vox`'s own `resolve_speaker` does — several agents
  share one host spool, so what you hear has to be attributable.
- Adding the mount required regenerating the aoe profiles. It only takes effect
  on container recreation, so running agents are unaffected until they cycle.
