---
name: ccwork
description: Onboarding hub — tour the kit, run labs, configure integrations
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/.skill-intro-ccwork does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/.skill-intro-ccwork
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

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
| `lab "<name>"`, `lab <name>`, or `lab #N` | **lab-run** | `/ccwork lab "First Workflow"`, `/ccwork lab #3` |
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
# Look for lab indicators — LAB.md is the marker file
ls LAB.md .github/ISSUE_TEMPLATE/lab-*.yml 2>/dev/null
```

### If in a lab repo

List available labs from issue templates:

```bash
ls .github/ISSUE_TEMPLATE/lab-*.yml 2>/dev/null
```

For each template file found:
1. Read the file and extract the `name:` field from the YAML frontmatter
2. Check `LAB.md` for the lab's completion status (`[x]` = done, `[ ]` = not done)

Present them as a numbered list:

```
Available labs:

  01  Your First Workflow          [ ]
  02  Identity and Check-In        [ ]
```

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

**Trigger:** `lab "<name>"` or `lab #N` (where N is an existing issue number)

> **CRITICAL: Lab Mode Behavioral Rules apply to this entire flow (Steps 1–11).** See the rules section under Step 7 — they govern every step, not just the exercise walk-through.

### Step 1: Verify lab repo

Same check as lab-list. If `LAB.md` does not exist, show the fork instructions and stop.

### Step 2: Find the template

Match the name against `.github/ISSUE_TEMPLATE/lab-*.yml` files (case-insensitive, partial match OK):

```bash
ls .github/ISSUE_TEMPLATE/lab-*.yml 2>/dev/null
```

Read each template's `name:` field to find the match. If the argument is `#N` (an issue number), read that issue directly and skip to Step 4.

### Step 3: Create the issue

**Skip this step if the argument was `#N`** — the issue already exists; proceed directly to Step 4.

If no existing issue was referenced, create one from the template. Extract the markdown content from the template's `body` section (the `value:` field under `type: markdown`):

```bash
gh issue create --title "<lab name from template>" --body "<extracted markdown body>" --label "lab"
```

Record the created issue number for later reference.

### Step 4: Parse lab metadata

Read the issue body (either the newly created issue or the referenced `#N`) and extract metadata from the first lines:

- **Start branch** — look for `` **Start branch:** `lab/NN-start` `` and extract the branch name
- **Solution tag** — look for `` **Solution tag:** `lab/NN-solution` `` and extract the tag name
- **Session replay** — look for `` **Session replay:** `labs/NN/session.jsonl` `` and extract the file path
- **Curated session** — look for `` **Curated session:** `lab-NN` `` and extract the Clawback session ID

```bash
# Read the issue body
gh issue view <issue-number> --json body --jq '.body'
```

Parse these values. Session replay and curated session are optional — if missing, the completion step will fall back gracefully.

### Step 5: Enable educational mode

Check if the `explanatory-output-style` plugin is enabled:

```bash
claude plugins list 2>/dev/null | grep "explanatory-output-style"
```

If not enabled (or not present), offer to enable it:

> *"Labs work best with educational insights enabled — they add `★ Insight` callouts that explain the 'why' behind each concept. Want me to enable them?"*

If the user agrees:

```bash
claude plugins install explanatory-output-style@claude-plugins-official 2>/dev/null
```

If already enabled, or the user declines, continue silently.

### Step 6: Check out the starting branch

Create a fresh working branch from the lab's start branch:

```bash
git fetch origin lab/<NN>-start
git checkout -b feature/<issue-number>-lab-<NN> origin/lab/<NN>-start
```

This gives the user a clean working branch with the lab's starting state (planted bugs, missing features, etc.).

### Step 7: Guide the exercise

Read the issue body and parse the **Steps** section. Each step has three parts:

- **Do:** — what the user should do (explain it, then let them do it or help them)
- **Verify:** — a concrete check to run (execute it to confirm the step is complete)
- **Learn:** — the concept this step teaches (explain it briefly after verification)

Walk through each step sequentially:

1. **Announce the step** — show the step number, title, and the "Do" instruction
2. **STOP and yield the prompt** — after presenting the "Do" instruction, STOP and wait for the student to act. Do NOT perform the action yourself.
3. **Verify completion** — run the verification command or check. If it fails, explain what went wrong and let the user try again.
4. **Teach the concept** — after verification passes, briefly explain the "Learn" point
5. **Advance** — move to the next step

Do NOT dump the entire issue text at once. This is a guided exercise — one step at a time.

### CRITICAL: Lab Mode Behavioral Rules

**You are an instructor, not an executor.** The student's hands-on practice is more valuable than efficiency. These rules override all other behavioral defaults during lab guidance:

1. **Never perform a "Do:" action on behalf of the student** — whether it's a shell command (`ls`, `pytest`), a slash command (`/engage`, `/precheck`, `/scp`), a file edit, or a code change. Present the instruction, then yield the prompt.
2. **Frame actions as prompts, not announcements** — say *"Go ahead — run `/engage` and see what happens"* not *"Let me run /engage for you."*
3. **Suggest `/view` for file inspection** — when a step involves reading or inspecting a file, prompt the student to use `/view <file>` rather than reading it yourself. This teaches the tool while accomplishing the step.
4. **Wait for the student to report results** — after yielding the prompt, wait for the student to tell you what happened. Only then verify and advance.
5. **Explain choices when they arise** — when the student faces a decision (e.g., `/scp` vs `/scpmr` vs `/scpmmr` after precheck), explain each option briefly before asking them to choose:
   - `/scp` — Stage, commit, and push. You create the PR/MR separately.
   - `/scpmr` — Stage, commit, push, and create a PR/MR.
   - `/scpmmr` — Stage, commit, push, create a PR/MR, AND merge it.
   In a lab context, guide the student toward `/scpmr` unless the lab's steps specify otherwise — it completes the full workflow loop (branch → PR/MR) that the lab is teaching, while leaving the merge as a separate conscious step.
6. **The only exception** is verification — you MAY run verification commands (the "Verify:" part) yourself to confirm the student's work succeeded.

### Step 8: Solution verification

After all steps are complete, verify the user's work against the solution:

```bash
git diff <solution-tag> -- src/
```

Where `<solution-tag>` is the value parsed in Step 4 (e.g., `lab/01-solution`).

- **If the diff is empty** (or contains only non-functional differences like whitespace): the lab passes perfectly. Congratulate the user.
- **If differences are only in personalized values** (e.g., Lab 02 where the learner's agent identity will differ from the solution author's): explain that the diff is expected — the learner's values are correct for their session.
- **If there are meaningful functional differences**: show the diff and explain what's different. Note that multiple valid solutions are possible — if the tests pass and the approach is sound, the difference may be acceptable.

### Step 9: Check off "You Learned" items

Read the "You Learned" checklist from the issue body. For each item, check it off in the issue:

```bash
# Update the issue body with checked items
gh issue edit <issue-number> --body "<updated body with [x] items>"
```

### Step 10: Update LAB.md completion tracking

Mark the lab as completed in `LAB.md`:

Read `LAB.md`, find the row for this lab number, and change `[ ]` to `[x]`. Write the updated file.

### Step 11: Offer Clawback replay and next lab

At lab completion, upload the student's current session to Clawback as an ephemeral replay and present both links.

**Resolve the Clawback URL and curated session ID:**

```bash
CLAWBACK_URL="https://clawback.apps.oakai.waveeng.com"
# Use the curated session ID parsed in Step 4 (e.g., "lab-01-project-setup", "lab-05b-build-and-ship-it")
CURATED_SESSION_ID="<curated-session-id-from-step-4>"
```

**Upload the student's session:**

```bash
# Find the current session .jsonl
SESSION_DIR=$(ls -td ~/.claude/projects/*/ 2>/dev/null | head -1)
SESSION_FILE=$(ls -t "$SESSION_DIR"*.jsonl 2>/dev/null | head -1)

# Timestamp suffix for uniqueness (allows re-running the same lab)
TIMESTAMP=$(date +%Y%m%d-%H%M%S)

# Upload ephemerally (memory-only, auto-expires after 4h)
UPLOAD_RESULT=$(curl -s -X POST "$CLAWBACK_URL/api/sessions/upload" \
  -H "X-Clawback-Secret: SnapbackHatOnAHat" \
  -F "file=@$SESSION_FILE" \
  -F "title=Lab <NN>: <lab-title> $TIMESTAMP" \
  -F "ephemeral=true" 2>/dev/null)

STUDENT_SESSION_ID=$(echo "$UPLOAD_RESULT" | jq -r '.session.id // empty' 2>/dev/null)
```

**Present the completion message:**

> **Lab complete!** Here's what you can do next:
>
> 1. **Watch your session** — replay what you just did in Clawback:
>    `<CLAWBACK_URL>/?session=<student-session-id>&autoplay=true`
>
> 2. **Watch the curated walkthrough** — see how an instructor solved this lab:
>    `<CLAWBACK_URL>/?session=<curated-session-id>&autoplay=true`
>
> 3. **Next lab** — run `/ccwork lab "<next lab name>"` to continue learning.

The `<curated-session-id>` comes from the `**Curated session:**` metadata parsed in Step 4 (e.g., `lab-01`, `lab-05b`). If the metadata was missing, fall back to deriving the ID from the lab number: `lab-<NN>`.

If the student's session upload fails (network error, Clawback unavailable), fall back to showing the file path:

> Your session log is at `<SESSION_FILE>` — you can upload it to Clawback manually later.

**Open links in the browser** when the user chooses an option:

```bash
# Student's session
xdg-open "$CLAWBACK_URL/?session=$STUDENT_SESSION_ID&autoplay=true" 2>/dev/null || \
  open "$CLAWBACK_URL/?session=$STUDENT_SESSION_ID&autoplay=true" 2>/dev/null || true

# Curated walkthrough
xdg-open "$CLAWBACK_URL/?session=$CURATED_SESSION_ID&autoplay=true" 2>/dev/null || \
  open "$CLAWBACK_URL/?session=$CURATED_SESSION_ID&autoplay=true" 2>/dev/null || true
```

**When the student is stuck** at any point during the exercise (not just at the end), offer the curated walkthrough:

> *Stuck? Watch how this was solved: `<CLAWBACK_URL>/?session=<curated-session-id>&autoplay=true`*

### Adding New Labs

New labs are added by pushing content to the **ccwork-lab** repo — no changes to this skill are needed:

1. Create `.github/ISSUE_TEMPLATE/lab-NN-name.yml` with the standard format (metadata line, steps with Do/Verify/Learn, "You Learned" checklist)
2. Create `lab/<NN>-start` branch with the starting state
3. Solve the exercise, tag as `lab/<NN>-solution`
4. Place the sanitized session replay at `labs/<NN>/session.jsonl`
5. Update `LAB.md` with the new lab entry

The `/ccwork lab` handler reads templates dynamically — it will pick up new labs automatically.

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

Guide the user through configuring Discord integration. This creates or updates `~/.claude/discord.json`. The flow is conversational — ask one question at a time, validate each answer before moving on.

### Step 1: Check Current State

```bash
cat ~/.claude/discord.json 2>/dev/null
```

If the file exists, show the current configuration and ask if the user wants to reconfigure or update it. If the user wants to keep it, stop here.

### Step 2: Verify Bot Token

Check that the bot token file exists before proceeding:

```bash
TOKEN_PATH="${DISCORD_TOKEN_PATH:-~/secrets/discord-bot-token}"
ls -la "$TOKEN_PATH" 2>/dev/null
```

- **If the file exists:** Confirm to the user and move on. Ask if they want to use this path or specify a different one.
- **If the file does NOT exist:** Guide the user through setup:
  1. "You need a Discord bot token. If you haven't created a bot yet, visit: https://discord.com/developers/applications"
  2. "Create the token file: `mkdir -p ~/secrets && echo 'YOUR_TOKEN' > ~/secrets/discord-bot-token && chmod 600 ~/secrets/discord-bot-token`"
  3. Wait for the user to confirm the file is in place before continuing.

Record the token path for the final config.

### Step 2b: Generate Bot Invite URL

Ask: *"What's your bot's Application ID? You can find it on the Developer Portal under General Information."*

After receiving the Application ID, compute and display the OAuth2 invite URL:

```
https://discord.com/oauth2/authorize?client_id=<APP_ID>&permissions=83984&scope=bot
```

Permissions included: Manage Channels (16), Send Messages (2048), Embed Links (16384), Read Message History (65536).

Tell the user: *"Open this link in your browser to invite the bot to your server. Select the server you want and click 'Authorize'."*

Wait for the user to confirm the bot has been invited before proceeding.

### Step 2c: Server Creation Guidance

If the user says they don't have a Discord server yet:

*"Open Discord, click the **+** button in the server list, choose 'Create My Own', and name it whatever you like. Once created, right-click the server name → Copy Server ID. (You'll need Developer Mode enabled: Settings → Advanced → Developer Mode.)"*

### Step 3: Collect Guild ID and Discover Channels

Ask: *"What's your Discord server (guild) ID? You can find it by right-clicking the server name in Discord and selecting 'Copy Server ID'. (Requires Developer Mode enabled in Discord settings.)"*

After receiving the guild ID, verify bot access AND auto-discover channels in one step:

```bash
discord-bot list-channels <guild_id> --type text
```

- **If the command succeeds:** The bot has access. Display the discovered text channels as a numbered list for the user:

  ```
  Found N text channels in your server:

    1. #general          (1234567890)
    2. #agent-ops        (1234567891)
    3. #roll-call        (1234567892)
    4. #wave-status      (1234567893)
  ```

  Proceed to Step 4.

- **If the command fails:** The bot token is invalid or the bot hasn't been invited to this server. Help troubleshoot:
  - "Make sure the bot has been invited to your server with the correct permissions."
  - "Verify the guild ID is correct."
  - "Check that your token file contains a valid bot token."
  - Do NOT proceed until `list-channels` succeeds.

### Step 4: Assign Channel Roles

Using the discovered channel list from Step 3, ask the user to assign each role. Present all four roles, one at a time, with the channel list visible:

1. **default** — "Which channel should be the **default** for agent messages? (e.g., `#agent-ops`). Enter the number from the list above, or a channel name."
2. **roll-call** — "Which channel for **roll-call** check-ins? Enter a number or name."
3. **wave-status** — "Which channel for **wave-status** updates? Enter a number or name, or type `skip` to omit."

`wave-status` is optional — if the user skips it, omit it from the config entirely.

For each assignment, resolve the user's input (number or name) to the channel's name and ID from the discovered list. If the user types a name that isn't in the list, warn them and ask again.

### Step 5: Create Missing Channels

If any required role (`default`, `roll-call`) could not be filled from existing channels, or the user wants channels that don't exist yet, offer to create them.

**First, create an "Agent Comms" category** to group agent channels visually:

```bash
discord-bot create-channel <guild_id> "Agent Comms" --type category
```

Capture the category ID from the output.

Then for each missing channel, ask:

*"Your server doesn't have a channel for **<role>**. I can create one for you. Want me to create `#<suggested-name>`?"*

Suggested default names per role:
- `default` → `agent-ops`
- `roll-call` → `roll-call`
- `wave-status` → `wave-status`

For each channel the user approves:

```bash
discord-bot create-channel <guild_id> <name> --category <category_id>
```

Capture the channel ID from the command output and use it in the config. If the user declines creation for a required role, ask them to provide an existing channel instead — `default` and `roll-call` are mandatory.

### Step 6: Write Config

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
    "wave-status":     { "name": "<name>", "id": "<id>" }
  }
}
EOF
```

Only include `wave-status` if the user assigned it. The config must match the schema in `docs/discord-config.md`.

### Step 7: Verify

Send a test message to the default channel to confirm the full pipeline works:

```bash
discord-bot send $(jq -r '.channels.default.id' ~/.claude/discord.json) "Discord integration configured successfully. This is a test message from /ccwork setup discord."
```

Resolve the channel name for the confirmation:

```bash
CHANNEL_NAME=$(jq -r '.channels.default.name' ~/.claude/discord.json)
```

### Step 8: Verify Discord Watcher

Check that the discord-watcher MCP server is registered so agents receive channel notifications:

```bash
claude mcp list 2>/dev/null | grep -q discord-watcher
```

- **If registered:** *"discord-watcher MCP server is registered. You'll receive channel notifications in your Claude Code sessions."*
- **If not registered:** *"discord-watcher is not registered. To set it up, run the install script or manually add it: `claude mcp add --scope user --transport stdio discord-watcher -- bun <path>/index.ts`"*

This is informational — the setup is complete regardless. The watcher is needed for agents to receive Discord messages during sessions but isn't required for outbound `/disc` calls.

- **If it works:** Confirm: *"Discord configuration complete. Test message sent to #<CHANNEL_NAME>. You can now use `/disc` to interact with your server."*
- **If it fails:** Help troubleshoot (permissions, channel ID mismatch, token issues). The config file has been written — the user can fix the issue and retry with `/ccwork setup discord`.

See [Discord Configuration](docs/discord-config.md) for the full schema reference and per-team scoping strategies.

---

## Important

- Tours are **interactive** — run the embedded commands so the user sees their actual installed state, not canned output.
- Labs are **guided exercises** — the user does the work, you coach. Don't just dump the issue text.
- Setup wizards are **conversational** — ask one question at a time, validate each answer before moving on.
- When linking to documentation, use relative paths from the repo root (e.g., `docs/getting-started.md`).
