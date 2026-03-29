---
name: ccwork
description: Onboarding hub — tour the kit, run labs, configure integrations
---

# CCWork: Onboarding, Education, and Configuration Hub

Single entry point for discovering and learning the Claude Code workflow kit. Routes to tour, lab, and setup subcommands.

## Resolve Intent

{{#if args}}
Parse the argument: `{{args}}`
{{else}}
No argument — show the overview of available subcommands.
{{/if}}

Determine the subcommand from the phrasing:

| Pattern | Intent | Examples |
|---------|--------|---------|
| No args | **overview** | `/ccwork` |
| `tour` (alone) | **tour-orientation** | `/ccwork tour` |
| `tour orientation` | **tour-orientation** | `/ccwork tour orientation` |
| `tour workflow` | **tour-workflow** | `/ccwork tour workflow` |
| `tour foundations` | **tour-foundations** | `/ccwork tour foundations` |
| `lab` (alone) | **lab-list** | `/ccwork lab` |
| `lab "<name>"` or `lab <name>` | **lab-run** | `/ccwork lab "First Workflow"` |
| `setup discord` | **setup-discord** | `/ccwork setup discord` |
| `setup` (alone) | **setup-list** | `/ccwork setup` |

---

## Overview (no args)

Present the available subcommands as a concise menu:

```
/ccwork — Claude Code Workflow Kit

  tour                Full orientation tour (or: tour workflow, tour foundations)
  lab                 List available labs (or: lab "<name>" to start one)
  setup discord       Guided Discord configuration

Docs:
  - Getting Started .... docs/getting-started.md
  - Concepts ........... docs/concepts.md
  - Discord Config ..... docs/discord-config.md
  - README ............. README.md
```

Do NOT run any commands or start any workflow. Just show the menu and wait.

---

## Tour: Orientation

**Trigger:** `tour` or `tour orientation`

Read and execute the tour script at `skills/ccwork/tours/orientation.md` (relative to the repo root, or resolve via the installed skill path). The tour file contains the full narration and embedded commands to run.

### Resolving Tour Files

Tour files live alongside this SKILL.md in the `tours/` subdirectory. Resolve the path:

```bash
# Installed location
TOUR_DIR="$HOME/.claude/skills/ccwork/tours"

# Fallback: repo location (for development)
if [[ ! -d "$TOUR_DIR" ]]; then
  REPO_ROOT=$(git rev-parse --show-toplevel 2>/dev/null)
  TOUR_DIR="$REPO_ROOT/skills/ccwork/tours"
fi
```

Read the tour file and follow its instructions step by step.

---

## Tour: Workflow

**Trigger:** `tour workflow`

Read and execute `tours/workflow.md` using the same resolution logic as above.

---

## Tour: Foundations

**Trigger:** `tour foundations`

Read and execute `tours/foundations.md` using the same resolution logic as above.

---

## Lab: List

**Trigger:** `lab` (alone)

Check whether the current repo is a lab repo:

```bash
# Look for lab indicators
ls LAB.md .github/ISSUE_TEMPLATE/lab-*.md 2>/dev/null
```

### If in a lab repo

List available labs from issue templates:

```bash
ls .github/ISSUE_TEMPLATE/lab-*.md 2>/dev/null
```

Present them as a numbered list with their titles (read the first `name:` line from each template's frontmatter).

Tell the user: *"Run `/ccwork lab \"<name>\"` to start a lab exercise."*

### If NOT in a lab repo

Tell the user:

> You're not in a lab repo. To get started with hands-on exercises:
>
> 1. Fork and clone **ccwork-lab**: `gh repo fork Wave-Engineering/ccwork-lab --clone`
> 2. `cd ccwork-lab && claude`
> 3. Run `/ccwork lab` to see available exercises
>
> Labs are self-contained issue templates. Each one walks you through a real workflow scenario using the ccwork kit.

---

## Lab: Run

**Trigger:** `lab "<name>"`

1. **Verify lab repo** — same check as lab-list. If not a lab repo, show the fork instructions and stop.

2. **Find the template** — match the name against `.github/ISSUE_TEMPLATE/lab-*.md` files (case-insensitive, partial match OK):
   ```bash
   ls .github/ISSUE_TEMPLATE/lab-*.md 2>/dev/null
   ```

3. **Create the issue** — read the template and create a GitHub issue from it:
   ```bash
   gh issue create --title "<lab title>" --body "$(cat <template-file>)"
   ```

4. **Guide the exercise** — read the created issue and walk the user through it step by step. Each step should be explained, then executed (or the user is prompted to execute it). This is a guided exercise, not a lecture — the user should be doing things, not just reading.

---

## Setup: List

**Trigger:** `setup` (alone)

Show available setup subcommands:

```
/ccwork setup — Available configuration wizards

  discord       Configure Discord integration (~/.claude/discord.json)

Coming soon:
  slack         Configure Slack integration
  ci            Configure CI/CD pipeline integration
```

---

## Setup: Discord

**Trigger:** `setup discord`

Guide the user through configuring Discord integration. This creates or updates `~/.claude/discord.json`.

### Step 1: Check Current State

```bash
cat ~/.claude/discord.json 2>/dev/null
```

If the file exists, show the current configuration and ask if the user wants to reconfigure or update it.

### Step 2: Gather Information

Walk through each field, explaining what it is and where to find it:

1. **Guild ID** — "What's your Discord server (guild) ID? You can find it by right-clicking the server name in Discord and selecting 'Copy Server ID'. (Requires Developer Mode enabled in Discord settings.)"

2. **Bot Token Path** — "Where is your Discord bot token stored? Default is `~/secrets/discord-bot-token`. If you haven't created a bot yet, see: https://discord.com/developers/applications"

3. **Channels** — For each channel role, ask for the channel ID:
   - `default` (general agent communications)
   - `roll-call` (agent check-in)
   - `wave-status` (wave execution status posts)
   - `remote-sessions` (AFK session relay threads)

   For each: "What's the channel ID for **<role>**? Right-click the channel and 'Copy Channel ID'."

### Step 3: Write Config

Write the collected values to `~/.claude/discord.json`:

```bash
mkdir -p ~/.claude
cat > ~/.claude/discord.json << 'EOF'
{
  "guild_id": "<collected>",
  "token_path": "<collected>",
  "channels": {
    "default":         { "name": "<name>", "id": "<id>" },
    "roll-call":       { "name": "<name>", "id": "<id>" },
    "wave-status":     { "name": "<name>", "id": "<id>" },
    "remote-sessions": { "name": "<name>", "id": "<id>" }
  }
}
EOF
```

### Step 4: Verify

Test the configuration:

```bash
discord-bot read $(jq -r '.channels.default.id' ~/.claude/discord.json) --limit 1
```

If it works, confirm: *"Discord configuration complete. You can now use `/disc` to interact with your server."*

If it fails, help troubleshoot (missing token, wrong channel ID, bot not in server, etc.).

See [Discord Configuration](docs/discord-config.md) for the full schema reference and per-team scoping strategies.

---

## Important

- Tours are **interactive** — run the embedded commands so the user sees their actual installed state, not canned output.
- Labs are **guided exercises** — the user does the work, you coach. Don't just dump the issue text.
- Setup wizards are **conversational** — ask one question at a time, validate each answer before moving on.
- When linking to documentation, use relative paths from the repo root (e.g., `docs/getting-started.md`).
