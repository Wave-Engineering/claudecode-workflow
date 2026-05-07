### chore(vox): instrument with mcp-log for fleet observability (#551)

`scripts/vox` now writes structured events to `~/.claude/logs/mcp.jsonl` for
every real (non-disabled) TTS invocation. Closes the observability gap where
agents complained "vox isn't working" but the fleet log had zero evidence.

**Events emitted (`server: vox`):**

- `call_start` — after arg parse, before provider resolution
  - `text_chars`, `bg`, `voice`, `output_only`
- `call_complete` — on success (foreground player exit 0, `--output` write,
  or background-player launch)
  - `ok=true`, `ms`, `bytes`, `provider`
- `call_failed` — on every covered failure path
  - `ok=false`, `reason`, `ms`, `provider`, `err` (≤200 chars)
  - Stable `reason` enum: `provider_missing`, `provider_failed`,
    `player_missing`, `player_failed`, `env_missing`, `network_failed`,
    `bad_args`, `unknown_exit`
- An `EXIT` trap emits `call_failed reason=unknown_exit` if vox exits
  non-zero without one of the above firing — guarantees no silent failure.

**Behavior preserved:**

- Exit codes, stderr passthrough, and audio playback are unchanged.
- `VOX_DISABLED=1` remains a clean exit 0 (no audio, no event — the issue
  spec explicitly permits skipping events on the no-op path; one `mcp-log`
  invocation would exceed the <50ms overhead bound on a 5ms baseline).
- `--help` / `--setup` exit pre-instrumentation as before.

**Performance:** real TTS invocations measured at ~28ms additional overhead
(silent provider + `true` player) — under the 50ms bound. Achieved by an
inline pure-bash JSON-line appender (no `mcp-log` shell-out, no `jq`
subprocesses) that conforms to the same wire format as
`docs/mcp-logging-standard.md`.

Pairs with #550 (precheck-skill vox-failure logging — the complementary
"vox didn't run at all" half).
