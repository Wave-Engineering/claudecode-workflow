---
name: ccwork
description: Onboarding hub — tour the kit, run labs, configure integrations
---

<!-- introduction-gate: If introduction.md exists in this skill's directory, read it,
     present its contents to the user as a brief welcome, then delete the file.
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

```bash
# Read the issue body
gh issue view <issue-number> --json body --jq '.body'
```

Parse these three values. If any are missing, warn the user and attempt to continue with what's available.

### Step 5: Check out the starting branch

Create a fresh working branch from the lab's start branch:

```bash
git fetch origin lab/<NN>-start
git checkout -b feature/<issue-number>-lab-<NN> origin/lab/<NN>-start
```

This gives the user a clean working branch with the lab's starting state (planted bugs, missing features, etc.).

### Step 6: Guide the exercise

Read the issue body and parse the **Steps** section. Each step has three parts:

- **Do:** — what the user should do (explain it, then let them do it or help them)
- **Verify:** — a concrete check to run (execute it to confirm the step is complete)
- **Learn:** — the concept this step teaches (explain it briefly after verification)

Walk through each step sequentially:

1. **Announce the step** — show the step number, title, and the "Do" instruction
2. **Coach, don't lecture** — the user does the work. Offer guidance if they ask, but don't just do it for them. If they're stuck, offer progressively more specific hints.
3. **Verify completion** — run the verification command or check. If it fails, explain what went wrong and let the user try again.
4. **Teach the concept** — after verification passes, briefly explain the "Learn" point
5. **Advance** — move to the next step

Do NOT dump the entire issue text at once. This is a guided exercise — one step at a time.

### Step 7: Solution verification

After all steps are complete, verify the user's work against the solution:

```bash
git diff <solution-tag> -- src/
```

Where `<solution-tag>` is the value parsed in Step 4 (e.g., `lab/01-solution`).

- **If the diff is empty** (or contains only non-functional differences like whitespace): the lab passes perfectly. Congratulate the user.
- **If differences are only in personalized values** (e.g., Lab 02 where the learner's agent identity will differ from the solution author's): explain that the diff is expected — the learner's values are correct for their session.
- **If there are meaningful functional differences**: show the diff and explain what's different. Note that multiple valid solutions are possible — if the tests pass and the approach is sound, the difference may be acceptable.

### Step 8: Check off "You Learned" items

Read the "You Learned" checklist from the issue body. For each item, check it off in the issue:

```bash
# Update the issue body with checked items
gh issue edit <issue-number> --body "<updated body with [x] items>"
```

### Step 9: Update LAB.md completion tracking

Mark the lab as completed in `LAB.md`:

Read `LAB.md`, find the row for this lab number, and change `[ ]` to `[x]`. Write the updated file.

### Step 10: Offer Clawback replay and next lab

Present the completion message:

> Lab complete! Here's what you can do next:
>
> **Review the solution:**
> Load `<session-replay-path>` into [Clawback](https://github.com/bakeb7j0/clawback) to watch how this lab was solved step by step.
>
> **Next lab:**
> Run `/ccwork lab "<next lab name>"` to continue learning.

If the user is stuck at any point during the exercise (not just at the end), also offer the replay:

> *Stuck? Load `<session-replay-path>` into [Clawback](https://github.com/bakeb7j0/clawback) to see how this step was solved.*

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
