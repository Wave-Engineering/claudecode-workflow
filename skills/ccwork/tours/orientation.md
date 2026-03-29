# Tour: Orientation

A guided walkthrough of the Claude Code workflow kit. This tour shows the user what is installed, how the pieces connect, and where to go next.

**Pace:** Pause after each section. Keep narration conversational — explain what you are about to show, run the command, then explain what the output means.

**Cross-references:** Point users to the detailed docs when appropriate:
- [Getting Started](../../../docs/getting-started.md) for the hands-on first-session walkthrough
- [Concepts](../../../docs/concepts.md) for architecture and design rationale

---

## Section 1: What You Have

Narration: "Let's start by seeing what the ccwork kit installed on your machine. There are three layers: settings, scripts, and skills."

### Check installed skills

```bash
ls ~/.claude/skills/
```

Narration: "These are your skills — slash commands you can use in any Claude Code session. Each one is a markdown file that tells Claude how to execute a specific workflow."

### Check installed scripts

```bash
ls ~/.local/bin/discord-bot ~/.local/bin/slackbot-send ~/.local/bin/vox ~/.local/bin/file-opener ~/.local/bin/afk-notify ~/.local/bin/statusline-command.sh 2>/dev/null || echo "(some scripts not installed)"
```

Narration: "These are your scripts — standalone tools that skills call under the hood. `discord-bot` talks to Discord, `vox` does text-to-speech, `file-opener` opens files in your GUI apps. Skills provide the intelligence; scripts provide the capabilities."

### Check settings

```bash
jq 'keys' ~/.claude/settings.json 2>/dev/null || echo "(no settings.json found)"
```

Narration: "Your `settings.json` controls tool permissions, hooks, plugins, and the status line. The kit sets this up on first install — you own the file after that."

### Check for drift

```bash
cd "$(git rev-parse --show-toplevel 2>/dev/null || echo .)" && ./install.sh --check 2>/dev/null | tail -5 || echo "(install.sh not found in this repo)"
```

Narration: "The `--check` flag compares what is installed against the repo version. If anything says DIFFERS or NOT INSTALLED, run `./install.sh` to update."

For a deeper explanation of how these three layers work together, see the [Three Layers](../../../docs/concepts.md#the-three-layers) section in Concepts.

---

## Section 2: The Core Loop

Narration: "Every change follows the same loop: issue, branch, code, precheck, ship. Let me show you what that looks like."

### Show current branch and status

```bash
git branch --show-current
git status --short
```

### Show the workflow skills

Narration: "These are the skills that drive the loop:"

Present this table:

| Step | What you do | Skill |
|------|------------|-------|
| 1. Track | Create or pick an issue | `gh issue create` / `gh issue view` |
| 2. Branch | Create a feature branch | `git checkout -b feature/42-description` |
| 3. Code | Write the implementation | (you or Claude) |
| 4. Gate | Run the pre-commit checklist | `/precheck` |
| 5. Ship | Stage, commit, push, PR | `/scp`, `/scpmr`, or `/scpmmr` |

Narration: "The system enforces this loop — if you try to commit without `/precheck`, or start coding without an issue, Claude will stop you. That's by design. See the [Mandatory Workflow](../../../docs/getting-started.md#step-4-the-mandatory-workflow) section in Getting Started for the full walkthrough."

---

## Section 3: Session Lifecycle

Narration: "Sessions have a rhythm: start, work, freeze, compact, thaw. Here's how the lifecycle skills fit in."

| Moment | What happens | Skill |
|--------|-------------|-------|
| Session start | Load rules, confirm ready state | `/engage` |
| Before compaction | Freeze state to plan file | `/cryo` |
| After compaction | Thaw — restore rules and context | `/engage` |
| Any time | Check or pick your identity | `/name` |
| Template update | Merge upstream CLAUDE.md changes | `/ccfold` |

### Show identity

```bash
project_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
dir_hash=$(echo -n "$project_root" | md5sum | cut -d' ' -f1)
agent_file="/tmp/claude-agent-${dir_hash}.json"
cat "$agent_file" 2>/dev/null || echo "(no identity file — run /name to create one)"
```

Narration: "Your identity file tracks who you are this session — Dev-Name, Dev-Avatar, and Dev-Team. It's ephemeral (new session, new name) but the Dev-Team is persisted in CLAUDE.md."

For the full explanation of the two-layer identity system, see [Identity System](../../../docs/concepts.md#identity-system) in Concepts.

---

## Section 4: Communication

Narration: "The kit can talk to Discord and Slack. Let me check what's configured."

### Check Discord config

```bash
cat ~/.claude/discord.json 2>/dev/null || echo "(no Discord config — run /ccwork setup discord to configure)"
```

### Check Slack token

```bash
test -f ~/secrets/slack-bot-token && echo "Slack bot token: found" || echo "Slack bot token: not found"
```

### Communication skills

| Skill | What it does |
|-------|-------------|
| `/disc` | Discord — send, read, check in, create channels |
| `/ping` | Post to Slack #ai-dev |
| `/pong` | Read Slack #ai-dev |
| `/vox` | Text-to-speech announcements |

Narration: "If you're running multiple agents, Discord is how they coordinate. The discord-watcher channel server pushes real-time notifications into your session. See [Discord Configuration](../../../docs/discord-config.md) for setup details and per-team scoping strategies."

---

## Section 5: Advanced — Wave System

Narration: "For large features that decompose into independent sub-issues, the wave system lets multiple agents work in parallel."

| Skill | Purpose |
|-------|---------|
| `/assesswaves` | Quick check: is this work suitable for parallel execution? |
| `/prepwaves` | Full planning: validate specs, compute dependency waves, partition into flights |
| `/nextwave` | Execute one wave at a time with isolated worktrees |

Narration: "You don't need this for everyday work. It's for when you have a big feature with 5+ sub-issues that can be done in parallel. The wave system manages the complexity — isolated git worktrees, conflict avoidance, progress tracking."

---

## Section 6: What's Next

Narration: "That's the orientation. Here's where to go from here:"

- **Try the workflow** — `/ccwork tour workflow` walks you through a real issue-to-merge cycle
- **Learn the foundations** — `/ccwork tour foundations` covers the session lifecycle skills in depth
- **Read the docs** — [Getting Started](../../../docs/getting-started.md) for the hands-on walkthrough, [Concepts](../../../docs/concepts.md) for architecture
- **Run a lab** — `/ccwork lab` to see available hands-on exercises (requires the ccwork-lab repo)
- **Explore skills** — run any `/command` to see what it does

Narration: "That's it. You know what's installed, how the loop works, and where the docs live. Ready when you are."
