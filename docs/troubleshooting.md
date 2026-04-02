# Troubleshooting

Common failure modes and their fixes. Each entry describes the symptom you see, the likely cause, and how to resolve it.

---

## 1. Vox is not speaking

**Symptom:** You run `/vox "message"` or `vox "message"` and nothing happens -- no audio plays, no error is shown.

**Cause:** One of several things can prevent audio output:

- **No audio player installed.** The `vox` script looks for `aplay` (Linux) or `afplay` (macOS). If neither is available, it cannot play the generated audio.
- **Chatterbox endpoint unreachable.** The `vox` script calls a remote TTS API. If the endpoint is down or the URL is wrong, generation fails silently (by design -- vox is best-effort).
- **Bluetooth audio clipping.** On Bluetooth speakers/headphones, the first fraction of a second can be clipped because the device needs a wake-up signal. This was fixed in [#106](https://github.com/Wave-Engineering/claudecode-workflow/pull/106) by prepending a short silence to the audio output.
- **No speakers or audio device.** On headless servers or SSH sessions, there is no audio output device.

**Fix:**

1. Test the audio player directly: `aplay /dev/null` (Linux) or `afplay /dev/null` (macOS). If it errors, install or configure your audio subsystem.
2. Test the TTS endpoint: `curl -s http://your-chatterbox-host:8234/health` (check your configured endpoint).
3. Check that `vox` is installed: `which vox`. If not found, run `./install.sh --scripts`.
4. If audio plays but the first word is clipped, update to the latest version (post-#106) which includes the Bluetooth wake noise.
5. On headless systems, use `vox --output /tmp/message.wav "text"` to generate the file without playing it, then transfer and play elsewhere.

---

## 2. Watcher dropping messages

**Symptom:** You send a message on Discord with `@cc-workflow` or `@beacon` addressing, but the agent does not receive the notification. Other messages get through fine.

**Cause:** The discord-watcher tokenizes message content and matches against `@<dev-team>`, `@<dev-name>`, and `@all`. Punctuation attached to the addressing token can prevent a match.

For example, `@beacon,` (with a trailing comma) or `@cc-workflow:` (with a trailing colon) would not match because the token includes the punctuation. This was fixed in [#108](https://github.com/Wave-Engineering/claudecode-workflow/pull/108) by stripping punctuation from addressing tokens before matching.

Other causes:

- **Identity not set.** If the agent has not picked a Dev-Name yet (no identity file exists), the watcher has nothing to match against for `@<dev-name>` addressing. `@<dev-team>` and `@all` would still work.
- **Echo filtering.** Messages that contain the agent's own signature (e.g., `-- **beacon** 📡 (cc-workflow)`) are suppressed to prevent loops. If you are testing by manually posting a message that includes the agent's signature, it will be filtered.
- **Watcher not running.** The session must be started with `--dangerously-load-development-channels server:discord-watcher` (or the `--channels` alias) for the watcher to be active.

**Fix:**

1. Update to the latest version (post-#108) which strips punctuation from addressing tokens.
2. Ensure the agent has picked an identity: run `/name` to check.
3. Avoid including the agent's signature in test messages.
4. Verify the watcher is running: check that the session was started with channels enabled.
5. For debugging, run with `DISCORD_WATCHER_VERBOSE=1` to bypass filtering and receive all messages.

---

## 3. install.sh says "in sync" but feature does not work

**Symptom:** You run `./install.sh --check` and everything shows "in sync", but a feature (e.g., a new hook, a new plugin, a new permission) is not working in your Claude Code sessions.

**Cause:** The `--check` comparison covers **skills, scripts, and config files** (file-level diff), but `settings.json` is handled by a **smart merge** that only adds missing keys -- it does not replace existing values or restructure your settings. If your `settings.json` has the right keys but wrong values, or is missing a nested entry that the template has added, `--check` may report "in sync" at the file level while the settings content is incomplete.

Specific scenarios:

- **New hook added to template.** The smart merge adds missing hook entries, but if you already have a hooks section with different structure, the new hook may not be inserted correctly.
- **New permission added to template.** Same issue -- the merge adds missing top-level keys but may not drill into nested arrays.
- **Plugin not enabled.** The plugin list in settings may be out of date. `--check` reports settings gaps but does not auto-fix them.

**Fix:**

1. Run `./install.sh --check` and read the **Settings** section of the output carefully. It reports missing hooks, plugins, and permissions separately from file-level diffs.
2. If specific hooks or plugins are reported as missing, run `./install.sh` (full install) to trigger the smart merge.
3. If the smart merge does not resolve the issue, compare your `~/.claude/settings.json` against `config/settings.template.json` manually. Look for structural differences in the hooks, plugins, or permissions sections.
4. As a last resort, back up your settings and install the template fresh:
   ```bash
   cp ~/.claude/settings.json ~/.claude/settings.json.bak
   cp config/settings.template.json ~/.claude/settings.json
   ```
   Then restore any custom settings from your backup.

---

## 4. /precheck not running -- branch not tracking issue

**Symptom:** You run `/precheck` and it stops at Step 1 with an error like "no issue number found in branch name" or "issue is closed or missing."

**Cause:** `/precheck` extracts the issue number from the branch name using the convention `feature/<number>-description` or `fix/<number>-description`. If the branch name does not follow this convention, it cannot find the linked issue.

Common causes:

- **Branch created without issue number.** If you created a branch like `feature/add-retry-logic` instead of `feature/42-add-retry-logic`, there is no issue number to extract.
- **Issue was closed.** If someone closed the issue while you were working, `/precheck` detects it as invalid.
- **Wrong branch prefix.** The branch must start with one of the recognized prefixes (`feature/`, `fix/`, `chore/`, `docs/`). Other prefixes may not parse correctly.
- **On a protected branch.** If you are on `main` or `release/*`, `/precheck` stops immediately and tells you to switch to a feature branch.

**Fix:**

1. Check your branch name: `git branch --show-current`. It should match `<type>/<issue-number>-description`.
2. If the issue number is missing from the branch name, either rename the branch or tell Claude the issue number when prompted.
3. If the issue is closed, reopen it or create a new one.
4. If you are on a protected branch, create a feature branch: `git checkout -b feature/<issue>-description`.
5. Use `/ibm` to review the correct workflow and ensure your branch is properly set up.

---

## 5. Identity not persisting across sessions

**Symptom:** Every time you start a new Claude Code session, the agent picks a brand new Dev-Name and Dev-Avatar, even though you expected it to remember the previous one.

**Cause:** This is by design, not a bug. Session identity (Dev-Name and Dev-Avatar) is intentionally **ephemeral** -- a new Claude Code window always means a new identity. Only Dev-Team is persisted (in CLAUDE.md).

The identity file at `/tmp/claude-agent-<hash>.json` is keyed by the md5 hash of the project root directory. It persists across context compactions within the same session but does not survive across separate Claude Code sessions. When a new session starts, the agent picks a fresh identity and overwrites the file.

**If identity is not persisting even within a single session:**

- **Wrong project root.** If `git rev-parse --show-toplevel` returns different paths (e.g., because of symlinks or worktrees), the md5 hash differs and the agent writes to a different file.
- **`/tmp` cleared.** Some systems clean `/tmp` aggressively. If the file is deleted mid-session, the agent loses its identity.
- **Permissions.** If the agent cannot write to `/tmp`, the identity file is not created.

**Fix:**

1. If you want the same Dev-Name across sessions, there is no built-in mechanism for this -- it is intentionally ephemeral. You can ask the agent to pick a specific name at session start.
2. For within-session persistence issues, check the identity file directly:
   ```bash
   project_root=$(git rev-parse --show-toplevel)
   dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
   cat "/tmp/claude-agent-${dir_hash}.json"
   ```
3. If the file is missing or has wrong content, run `/name` to re-establish identity.
4. For worktree issues, verify that `git rev-parse --show-toplevel` returns the expected path from within your working directory.

---

## 6. Discord bot commands failing with authentication errors

**Symptom:** Running `discord-bot send` or `discord-bot read` fails with a 401 Unauthorized or "Missing Access" error.

**Cause:** The bot token is invalid, expired, or the bot does not have the required permissions in the Discord server.

Common causes:

- **Token file missing or empty.** The default path is `~/secrets/discord-bot-token`. If the file does not exist or is empty, all API calls fail.
- **Token is invalid.** The token may have been regenerated in the Discord Developer Portal, invalidating the old one.
- **Bot not in the server.** The bot must be invited to your Discord server with the correct permissions.
- **Missing Message Content Intent.** Discord requires bots to enable the "Message Content Intent" in the Developer Portal (Settings -> Bot -> Privileged Gateway Intents) to read message content.
- **Channel permissions.** The bot needs Send Messages and Read Message History permissions in the specific channels you are targeting.

**Fix:**

1. Verify the token file exists and is not empty: `cat ~/secrets/discord-bot-token | head -c 20` (check the first 20 characters -- do not print the full token).
2. Test a simple read: `discord-bot read <channel-id> --limit 1`.
3. In the [Discord Developer Portal](https://discord.com/developers/applications), verify the bot's token, that Message Content Intent is enabled, and that the bot has been added to your server.
4. Check the bot's permissions in the server: it needs Send Messages and Read Message History at minimum.
5. Run `/ccwork setup discord` for a guided walk-through of the full configuration.

---

## See Also

- [Getting Started](getting-started.md) -- initial setup and first session walkthrough
- [Skill Reference](skill-reference.md) -- complete skill documentation with examples
- [Discord Configuration](discord-config.md) -- Discord setup details
- [README](../README.md) -- installation and component reference
