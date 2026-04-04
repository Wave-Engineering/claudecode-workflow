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
   dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
   agent_file="/tmp/claude-agent-${dir_hash}.json"
   ```

2. **Check for existing identity** — Read the resolved `$agent_file`
   - If it exists and has `dev_name`, `dev_avatar`, and `dev_team`: report them
   - If it does not exist: pick a new identity (see below)

3. **Read Dev-Team** — Check CLAUDE.md for the `Dev-Team:` field
   - If empty, ask the user what Dev-Team to use

4. **Pick identity (if needed)**
   - `Dev-Name`: A single memorable word or hyphenated phrase in **kebab-case** (e.g., `beacon`, `null-pointer`, `mother`). Draw from nerdcore canon — sci-fi, fantasy, comics, gaming, mythology, tech puns, wordplay. The wittier and more specific the reference, the better. Generic names are boring. Kebab-case is required so the name works as a routing key for `@<dev-name>` addressing.
   - `Dev-Avatar`: A Unicode emoji character (e.g., 🧠, 👾). Should feel like it belongs with the name.
   - Persist to the resolved identity file:
     ```bash
     cat > "$agent_file" << 'EOF'
     {
       "dev_team": "<Dev-Team>",
       "dev_name": "<name>",
       "dev_avatar": "<emoji>"
     }
     EOF
     ```
     **Note:** When executing, dedent the heredoc body and closing `EOF` to column 0 so the shell correctly terminates the heredoc.

5. **Announce** — Always respond with:
   > I'm **\<Dev-Name\>** \<Dev-Avatar\> from team `<Dev-Team>`.

6. **Set session display name** — So the Remote Control UI shows your identity:
   ```
   /rename <Dev-Name> <Dev-Avatar> (<Dev-Team>)
   ```
   Example: `/rename neuron ⚡ (cc-workflow)`. Skip silently if `/rename` is unavailable.

7. **Check in via Discord** — If `discord-bot` is available on PATH, announce yourself in `#roll-call`:
   ```bash
   ROLL_CALL=$(jq -r '.channels["roll-call"].id' ~/.claude/discord.json 2>/dev/null || echo "1487382005036617851")
   discord-bot send "$ROLL_CALL" "<message>"
   ```
   Message format:
   ```
   **<dev-name>** <dev-avatar> online — team `<dev-team>` @ <project-root>

   — **<dev-name>** <dev-avatar> (<dev-team>)
   ```
   If `discord-bot` is not available or the send fails, skip silently — check-in is best-effort.
