---
name: name
description: Report or pick the agent's session identity (Dev-Name, Dev-Avatar, Dev-Team)
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
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
   - `Dev-Name`: A single memorable name or short phrase (max 3 words). Draw from nerdcore canon — sci-fi, fantasy, comics, gaming, mythology, tech puns, wordplay. The wittier and more specific the reference, the better.
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
