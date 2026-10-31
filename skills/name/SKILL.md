---
name: name
description: Report or pick the agent's session identity (Dev-Name, Dev-Avatar, Dev-Team)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-name does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-name
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Agent Identity

Report the current session identity, or pick one if not yet established.

## Steps

1. **Resolve identity file path** — Identity is keyed by project root, not PID:
   ```bash
   project_root=$(pwd)
   agent_file="${project_root}/.claude/agent-identity.json"
   ```

2. **Refuse a second live claimant** — Two sessions in one checkout share one identity
   file, so both would read and answer as the same Dev-Name (#1366):
   ```bash
   ~/.claude/scripts/identity-claimants.sh "$project_root"
   ```
   - **Exit 3** (`older <pids>`): an older live session in this checkout holds the identity.
     Do not read, migrate, pick or write any identity file, and skip steps 3-8. Report:
     > This checkout's identity is in use by another live session (pid \<pids\>). Two
     > sessions in one checkout share one identity file, so I won't use or overwrite it.
     > Move this session into its own worktree, then run /name there.
   - **Any other result** (`none`, `younger`, `unknown`): continue.

3. **Check for existing identity** — Read the resolved `$agent_file`
   - If it exists and has `dev_name`, `dev_avatar`, and `dev_team`: report them
   - If it does not exist, also check the legacy `/tmp` path as a transition fallback:
     ```bash
     dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
     legacy_file="/tmp/claude-agent-${dir_hash}.json"
     # if legacy_file exists and has dev_name, report and migrate: copy to agent_file
     ```
   - If neither exists: pick a new identity (see below)

4. **Read Dev-Team** — Check CLAUDE.md for the `Dev-Team:` field
   - If empty, ask the user what Dev-Team to use

5. **Pick identity (if needed)**
   - `Dev-Name`: A single memorable word or hyphenated phrase in **kebab-case** (e.g., `beacon`, `null-pointer`, `mother`). Draw from nerdcore canon — sci-fi, fantasy, comics, gaming, mythology, tech puns, wordplay. The wittier and more specific the reference, the better. Generic names are boring. Kebab-case is required so the name works as a routing key for `@<dev-name>` addressing.
   - `Dev-Avatar`: A Unicode emoji character (e.g., 🧠, 👾). Should feel like it belongs with the name.
   - Persist to the resolved identity file (dual-write during transition window). It is a **merge**: set only the three keys `/name` owns, and keep every other key, such as a `lead` that `/grunt` wrote before this session ran `/name` (#1365):
     ```bash
     agent_file="${project_root}/.claude/agent-identity.json"
     mkdir -p "${project_root}/.claude"
     [[ -s "$agent_file" ]] || echo '{}' >"$agent_file"
     tmp="$(mktemp "${agent_file}.XXXXXX")"
     jq --arg t "<Dev-Team>" --arg n "<name>" --arg a "<emoji>" \
       '.dev_team = $t | .dev_name = $n | .dev_avatar = $a' "$agent_file" >"$tmp" &&
       mv "$tmp" "$agent_file" || { rm -f "$tmp"; echo "not written: $agent_file is not valid JSON" >&2; }
     # Also keep /tmp copy fresh for sessions that haven't re-run /name yet
     dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
     cp "$agent_file" "/tmp/claude-agent-${dir_hash}.json" 2>/dev/null || true
     ```
     **Never rewrite the whole file.** A whole-file write drops the `lead` field, and `/precheck` then notifies BJ instead of the lead. If the file is not valid JSON, the merge writes nothing: show the user the file and ask before replacing it. `agent_file` is `${project_root}/.claude/agent-identity.json` — no md5 keying needed once the file lives under the project root.

6. **Announce** — Always respond with:
   > I'm **\<Dev-Name\>** \<Dev-Avatar\> from team `<Dev-Team>`.

7. **Check in on `#roll-call`**, by the dual-mode rule in `docs/chat-tools.md` ("Transport: `chat_*` or `disc_*`"). With crewchat it lands on your default backend, the OaW Mattermost server for every OaW org:

   ```
   # chat_send in your tool list (crewchat daemon on this host): no backend
   chat_send({ to: "roll-call", text: "<formatted message — see below>" })

   # otherwise (no crewchat: this goes to Discord, so say so once):
   mcp__disc-server__disc_send({
     channel_id: "roll-call",
     message: "<formatted message — see below>"
   })
   ```

   Both accept the channel name directly (`"roll-call"`), so no jq lookup against `~/.claude/discord.json` is needed.

   **Report the chat mode.** The crewchat shim reads `.claude/agent-identity.json` **once, when the session starts**, and registers from it. It does not see what you just wrote. With no identity file at start, it doesn't come up at all.
   - **`chat_send` is in your tool list:** call `chat_health()` and report the backends it lists, for example `chat: mattermost:dev, discord`.
     - If you changed the identity just now (a new name, team or avatar), add `chat: restart the session to register the new identity`.
     - A `chat_health` error is reported as such.
   - **No `chat_send`, but the daemon socket is usable** (`test -S /run/crewchat/crewchat.sock && test -w /run/crewchat/crewchat.sock`, the same test `install-crewchat.sh` gates on). The cause depends on where the identity came from:
     - **This run created the identity file** (step 5): report `chat: crewchat not started (no identity at session start); restart the session`. The shim had nothing to register.
     - **The identity file already existed:** a restart won't help. Report `chat: crewchat not registered or not running; run scripts/install-crewchat.sh check`. Usually `./install` hasn't run since the daemon was deployed.
   - **No `chat_send` and no socket:** report `chat: Discord only (no crewchat daemon on this host)`.

   Message format:
   ```
   **<dev-name>** <dev-avatar> online — team `<dev-team>` @ <project-root>

   — **<dev-name>** <dev-avatar> (<dev-team>)
   ```

   If the `disc-server` MCP is not registered or the call fails, skip silently — check-in is best-effort.

8. **Close with the session-name next-step (FINAL output line)** — Claude Code's native
   session name (shown in the session picker, prompt bar, and `--resume`) is **user-driven
   only**: an agent cannot run `/rename` itself, and there is no hook/setting/API to set the
   name programmatically. So do NOT emit a bare `/rename` and assume it ran. Instead, end the
   skill's output with a single, paste-ready next-step so the operator can mirror the identity
   into CC's UI in one action:

   > Run `/rename <Dev-Name>` to mirror this identity into Claude Code's session name.

   - Use the **bare Dev-Name** (e.g. `/rename babelfish`) — NOT the avatar emoji or the team.
     CC's session name is a plain label; the emoji/parens form does not belong in it.
   - Make this the **last line** of the skill's output. It is the deterministic paste path, and
     because CC's Prompt-Suggestions ghost-text is a model prediction over the recent
     conversation, a single unambiguous closing imperative also maximizes the chance CC
     pre-fills `/rename <Dev-Name>` for →+Enter acceptance. (Non-deterministic — the paste is
     the reliable path.)
   - **Interactive sessions only.** A spawned/background/orchestrated agent has no operator to
     accept the suggestion — skip this line when there is no human in the loop. The identity
     file remains the source of truth; CC's session name is a one-way mirror, never a replacement.
