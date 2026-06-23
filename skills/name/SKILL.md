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
   project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
   agent_file="${project_root}/.claude/agent-identity.json"
   ```

2. **Check for existing identity** — Read the resolved `$agent_file`
   - If it exists and has `dev_name`, `dev_avatar`, and `dev_team`: report them
   - If it does not exist, also check the legacy `/tmp` path as a transition fallback:
     ```bash
     dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
     legacy_file="/tmp/claude-agent-${dir_hash}.json"
     # if legacy_file exists and has dev_name, report and migrate: copy to agent_file
     ```
   - If neither exists: pick a new identity (see below)

3. **Read Dev-Team** — Check CLAUDE.md for the `Dev-Team:` field
   - If empty, ask the user what Dev-Team to use

4. **Pick identity (if needed)**
   - `Dev-Name`: A single memorable word or hyphenated phrase in **kebab-case** (e.g., `beacon`, `null-pointer`, `mother`). Draw from nerdcore canon — sci-fi, fantasy, comics, gaming, mythology, tech puns, wordplay. The wittier and more specific the reference, the better. Generic names are boring. Kebab-case is required so the name works as a routing key for `@<dev-name>` addressing.
   - `Dev-Avatar`: A Unicode emoji character (e.g., 🧠, 👾). Should feel like it belongs with the name.
   - Persist to the resolved identity file:
     ```bash
     mkdir -p "${project_root}/.claude"
     cat > "$agent_file" << 'EOF'
     {
       "dev_team": "<Dev-Team>",
       "dev_name": "<name>",
       "dev_avatar": "<emoji>"
     }
     EOF
     ```
     **Note:** When executing, dedent the heredoc body and closing `EOF` to column 0 so the shell correctly terminates the heredoc. `agent_file` is `${project_root}/.claude/agent-identity.json` — no md5 keying needed once the file lives under the project root.

5. **Announce** — Always respond with:
   > I'm **\<Dev-Name\>** \<Dev-Avatar\> from team `<Dev-Team>`.

6. **Check in via Discord** — Call `mcp__disc-server__disc_send` to announce yourself in `#roll-call`:

   ```
   mcp__disc-server__disc_send({
     channel_id: "roll-call",
     message: "<formatted message — see below>"
   })
   ```

   The MCP accepts the channel name directly (`"roll-call"`), so no jq lookup against `~/.claude/discord.json` is needed.

   Message format:
   ```
   **<dev-name>** <dev-avatar> online — team `<dev-team>` @ <project-root>

   — **<dev-name>** <dev-avatar> (<dev-team>)
   ```

   If the `disc-server` MCP is not registered or the call fails, skip silently — check-in is best-effort.

7. **Close with the session-name next-step (FINAL output line)** — Claude Code's native
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
