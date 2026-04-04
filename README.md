# claudecode-workflow

Portable Claude Code workflow environment — skills, scripts, settings, and a drop-in `CLAUDE.md` template.

This repo packages the custom skills, utility scripts, and project instructions that make up a consistent Claude Code development environment. Clone it, run the installer, and you're set up on any machine.

## Documentation

| Guide | Description |
|-------|-------------|
| [Getting Started](docs/getting-started.md) | 15-minute walkthrough of your first session |
| [Concepts](docs/concepts.md) | How the pieces fit together |
| [Skill Reference](docs/skill-reference.md) | Detailed docs for every skill |
| [Discord Setup](docs/discord-config.md) | Bot token, watcher, inter-agent messaging |
| [Statusline Indicators](docs/statusline-indicators.md) | Per-session indicator interface for skills and scripts |
| [Troubleshooting](docs/troubleshooting.md) | Common issues and fixes |

## Quick Start

**One-liner install (no clone needed):**

```bash
curl -fsSL https://raw.githubusercontent.com/Wave-Engineering/claudecode-workflow/main/scripts/install-remote.sh | bash
```

**Or clone and install locally:**

```bash
git clone https://github.com/Wave-Engineering/claudecode-workflow.git
cd claudecode-workflow
./install.sh
```

**New here?** Start with [Getting Started](docs/getting-started.md), then [Concepts](docs/concepts.md).

## What's Included

### CLAUDE.md Template

A drop-in project instructions file that works with both GitHub and GitLab projects. Auto-detects the platform from `git remote -v` and adapts terminology and CLI commands accordingly.

Key features:
- **Platform detection** — GitHub (`gh`) vs GitLab (`glab`), auto-detected
- **Discovery-based code standards** — finds the project's linters, formatters, and test runners instead of assuming a stack
- **Pre-commit checklist** — enforced review protocol with mandatory verification steps
- **Agent identity system** — Dev-Team (persisted per-project) + Dev-Name/Dev-Avatar (ephemeral per-session)
- **Secrets guardrail** — warns before staging sensitive files, confirms with user before proceeding
- **PR/MR description format** — consistent structure for pull/merge requests

### Skills

| Skill | Command | What it does |
|-------|---------|-------------|
| assesswaves | `/assesswaves` | Quick assessment of wave-pattern suitability |
| ccfold | `/ccfold` | Merge upstream CLAUDE.md template updates into local project |
| ccwork | `/ccwork` | Onboarding hub — tour the kit, run labs, configure integrations |
| cryo | `/cryo` | Preserve session state before context compaction |
| ddd | `/ddd` | Domain-Driven Design facilitation — event storming, domain modeling, PRD generation |
| disc | `/disc` | Discord integration — check-in, send, read, list, resolve channels |
| edit | `/edit` | Open file/URL in GUI editor |
| engage | `/engage` | Load CLAUDE.md, confirm rules of engagement |
| ibm | `/ibm` | Issue-Branch-PR/MR workflow reminder |
| issue | `/issue` | Create structured issues (feature, bug, chore, docs, epic) with templates and labels |
| jfail | `/jfail` | CI job/workflow failure analysis |
| man | `/man` | Display usage information for any installed skill |
| mmr | `/mmr` | Merge a PR/MR with squash |
| name | `/name` | Report or pick agent session identity |
| nerf | `/nerf` | Context budget system — soft limits, doom modes, scope monitor |
| nextwave | `/nextwave` | Execute parallel spec-driven sub-agents |
| ping | `/ping` | Post to #ai-dev Slack channel |
| pong | `/pong` | Read #ai-dev Slack channel |
| precheck | `/precheck` | Pre-commit gate — verify compliance, run code review, present checklist |
| prepwaves | `/prepwaves` | Analyze issues and compute dependency waves |
| review | `/review` | Code review on staged/branch changes |
| scp | `/scp` | Stage, commit, and push workflow |
| scpmr | `/scpmr` | Stage, commit, push, and create PR/MR |
| scpmmr | `/scpmmr` | Stage, commit, push, create PR/MR, and merge |
| view | `/view` | Open file/URL in GUI viewer (read-only) |
| vox | `/vox` | Text-to-speech voice announcements for status updates and alerts |

### Scripts

| Script | Dependencies | What it does |
|--------|-------------|-------------|
| `discord-bot` | `curl`, `jq`, Discord bot token | Discord REST API client — send, read, create channels, resolve names |
| `discord-status-post` | `python3`, Discord bot token | Post/update wave-status embed in `#wave-status` Discord channel |
| `slackbot-send` | `curl`, `jq`, Slack bot token | Send Slack messages as a named Claude Code agent |
| `job-fetch` | `glab`, `python3` | Fetch GitLab CI job traces for analysis |
| `file-opener` | `xdg-open` / `open` | Cross-platform file/URL opener for `/view` and `/edit` |
| `vox` | `curl`, audio player (`aplay`/`afplay`) | Text-to-speech via Chatterbox API, with local fallback (espeak/piper/say) |
| `statusline-command.sh` | `jq`, `git` | Custom status line: git branch, dirty state, context window remaining, model |
| `cc-inspector` | `python3`, `mitmproxy` | Context window inspector — proxy + Flask UI for API payload capture |
| `discord-lock` | `flock`, `jq` | Advisory lock for serializing Discord channel writes across agents |
| `generate-status-panel` | `python3` | Generate HTML status panel for wave progress |
| `worktree-manager` | `git` | Manage isolated worktrees for parallel agent execution |

### MCP Servers

MCP servers are managed via `mcps.json` and installed from their own repos:

| Server | Repo | What it does |
|--------|------|-------------|
| `wtf-server` | [mcp-server-wtf](https://github.com/Wave-Engineering/mcp-server-wtf) | Flight recorder for incident troubleshooting |
| `discord-watcher` | [mcp-server-discord-watcher](https://github.com/Wave-Engineering/mcp-server-discord-watcher) | Discord channel notification server for inter-agent communication |
| `nerf-server` | [mcp-server-nerf](https://github.com/Wave-Engineering/mcp-server-nerf) | Deterministic context budget management (nerf darts, modes, statusline) |

Each MCP has its own `install-remote.sh` for standalone installation. Running `./install.sh` installs all MCPs from the manifest automatically.

### Context Crystallizer

The `context-crystallizer/` directory contains the hooks and libraries that power session state preservation. It installs to `~/.claude/context-crystallizer/` and provides:

- **Hooks** — SessionStart (restore crystallized state), PostToolUse (auto-crystallize at high context usage), SubagentStop (capture subagent results)
- **Libraries** — `context-analyzer.sh` (parse API payloads for token counts), `crystallizer.sh` (write crystal files)
- **CLI** — `cc-context` (watch token usage in a terminal), `cc-cleanup` (prune old crystal files)

Install standalone with `./install.sh --crystallizer`.

### Settings Template

`settings.template.json` provides a starting point for `~/.claude/settings.json` with:
- **Permissions** — Granular tool allowlists for common CLIs (git, gh, glab, docker, terraform, aws, etc.)
- **Hooks** — PostToolUse, SessionStart, and SubagentStop hook structure (requires [context-crystallizer](context-crystallizer/) for crystallization hooks)
- **Status line** — Points to the custom statusline script
- **Plugins** — Full plugin list (see Plugins section below)
- **Effort level** — Set to `high` for thorough responses

## Installation

### Remote Install

Install everything from a GitHub Release without cloning the repo:

```bash
curl -fsSL https://raw.githubusercontent.com/Wave-Engineering/claudecode-workflow/main/scripts/install-remote.sh | bash
```

Options:

```bash
curl ... | bash -s -- --version v1.0.0   # Install a specific release
curl ... | bash -s -- --no-mcps           # Skip MCP server installation
curl ... | bash -s -- --check             # Verify installation status
curl ... | bash -s -- --uninstall         # Remove everything
```

This downloads the release tarball, installs skills, scripts, config, pre-built packages, and MCP servers -- the same result as cloning and running `./install.sh`.

### Full Install (from clone)

```bash
./install.sh
```

This will:
- Copy skills to `~/.claude/skills/`
- Copy scripts to `~/.local/bin/`
- Install statusline to `~/.claude/statusline-command.sh`
- Smart-merge `settings.template.json` into `~/.claude/settings.json` — missing hooks, plugins, and permissions are added while your existing customizations are preserved. If no settings file exists yet, the template is installed directly (with internal comment keys stripped).
- Back up existing files before overwriting (`.bak`)
- Skip unchanged files
- Report missing dependencies

### Options

```bash
./install.sh --dry-run     # Show what would be done
./install.sh --check       # Show drift between repo and installed versions
./install.sh --skills      # Install skills only
./install.sh --scripts     # Install scripts only
./install.sh --config      # Install config files only
./install.sh --mcps         # Install MCP servers only (via mcps.json manifest)
./install.sh --crystallizer # Install context-crystallizer only
./install.sh --no-mcps      # Install everything except MCP servers
```

### Check for Drift

After making local changes to skills or scripts, see what's out of sync:

```bash
./install.sh --check
```

This compares every installed file against the repo version and reports `in sync`, `DIFFERS`, or `NOT INSTALLED`. It also checks:
- **Settings** — reports any hooks or plugins present in the template but missing from your local `settings.json`
- **MCPs** — verifies that each MCP server from `mcps.json` is registered via `claude mcp list`

### Sync Local Changes Back to Repo

When you've edited installed skills or scripts locally and want to capture those changes:

```bash
./sync.sh              # Interactive — prompt per changed file
./sync.sh --all        # Pull all changed files without prompting
./sync.sh --check      # Show drift summary only (no changes)
```

This is the reverse of `install.sh` — it copies local files *into* the repo working tree. After syncing, review the changes with `git diff` and commit through normal git workflow.

### Uninstall

```bash
./uninstall.sh              # Remove everything
./uninstall.sh --dry-run    # Preview what would be removed
./uninstall.sh --skills     # Remove skills only
./uninstall.sh --scripts    # Remove scripts only
```

Settings and credentials are never removed by the uninstall script.

### Using the CLAUDE.md Template

Copy `CLAUDE.md` into the root of any project:

```bash
cp /path/to/claudecode-workflow/CLAUDE.md /path/to/your-project/CLAUDE.md
```

On first session, Claude will:
1. Detect the platform (GitHub/GitLab)
2. Ask for the Dev-Team name (written into the file, only asked once)
3. Pick a session identity (Dev-Name + Dev-Avatar)

No other configuration needed.

## Plugins

The settings template enables these plugins from `claude-plugins-official`:

| Plugin | Purpose |
|--------|---------|
| `context7` | Up-to-date library documentation lookup |
| `code-review` | Structured code review |
| `github` | GitHub integration |
| `gitlab` | GitLab integration |
| `feature-dev` | Guided feature development |
| `code-simplifier` | Code simplification and cleanup |
| `commit-commands` | Git commit workflow commands |
| `pyright-lsp` | Python language server |
| `explanatory-output-style` | Educational code explanations |
| `claude-md-management` | CLAUDE.md audit and improvement |
| `claude-code-setup` | Automation recommendations |
| `slack` | Slack channel integration (MCP-based) |
| `frontend-design` | Frontend interface design |

### MCP-Based Integrations

Some plugins provide MCP (Model Context Protocol) server integrations that require OAuth setup on first use:

| Plugin | MCP Capability | Setup |
|--------|---------------|-------|
| `slack` | Read/write Slack channels | OAuth — prompted on first `/pong` or `/ping` use |
| `gitlab` | GitLab API access | OAuth — prompted on first `glab`-based operation |
| `github` | GitHub API access | Uses existing `gh auth` session |

These authenticate automatically through Claude Code's OAuth flow. No manual token configuration is needed — just approve the OAuth prompt when it appears.

**Exception:** The `slackbot-send` script uses a separate bot token (not the MCP OAuth). See Slack Setup below.

## Slack Setup (for /ping)

The `/ping` skill uses `slackbot-send`, which requires a Slack bot token:

```bash
mkdir -p ~/secrets
echo "xoxb-your-token" > ~/secrets/slack-bot-token
chmod 600 ~/secrets/slack-bot-token
```

This is separate from the Slack MCP plugin OAuth — `slackbot-send` posts as a custom bot identity (with Dev-Name and Dev-Avatar), while the MCP plugin uses your Slack user identity.

## Discord Setup

The `/disc` skill and discord-watcher channel server require a Discord bot token and server (guild).

### 1. Bot Token

```bash
mkdir -p ~/secrets
echo "your-bot-token" > ~/secrets/discord-bot-token
chmod 600 ~/secrets/discord-bot-token
```

The bot needs these permissions in your Discord server:
- **Send Messages** and **Read Message History** in target channels
- **Message Content Intent** enabled in the [Discord Developer Portal](https://discord.com/developers/applications) (Settings → Bot → Privileged Gateway Intents)

### 2. Discord-Watcher Channel Server

The discord-watcher is an MCP channel server that polls Discord and pushes real-time notifications into Claude Code sessions. It requires [Bun](https://bun.sh).

```bash
# Install bun (if not already installed)
curl -fsSL https://bun.sh/install | bash
```

`./install.sh` installs MCP servers from the `mcps.json` manifest via each server's `install-remote.sh`. You can also install them individually:

```bash
curl -fsSL https://raw.githubusercontent.com/Wave-Engineering/mcp-server-discord-watcher/main/scripts/install-remote.sh | bash
```

### 3. Start with Channels

```bash
claude --dangerously-load-development-channels server:discord-watcher
```

Or set up an alias:

```bash
alias ccode='claude --dangerously-load-development-channels server:discord-watcher'
```

The watcher monitors all text channels on the configured Discord server. Messages are **filtered by addressing** — agents only receive notifications for messages containing `@all`, `@<dev-team>`, or `@<dev-name>`. Self-echoes are suppressed via signature matching.

### Inter-Agent Communication

With the discord-watcher running in multiple Claude Code sessions, agents can talk to each other:

- **Address a specific team:** `@cc-workflow check the build status`
- **Address a specific agent:** `@beacon what's your current task?`
- **Address all agents:** `@all report your current status`
- **Unaddressed messages** are silently dropped (agents don't receive them)

Dev-Names must be **kebab-case** (e.g., `beacon`, `null-pointer`) so they work as routing keys for `@` addressing.

Each agent signs messages with its Dev-Name signature (e.g., `— **beacon** 📡 (cc-workflow)`), which the watcher uses to filter self-echoes while allowing messages from other agents through.

### Wave Status Channel

The `discord-status-post` script posts a rich embed to `#wave-status` whenever the wave state machine transitions. One message per project, edited in place — no spam.

The embed includes phase, wave, action, flight, a Unicode progress bar, and deferrals, with a color-coded sidebar that maps to the current action state. It's invoked automatically by `wave-status` after every state change (best-effort — skipped silently if not installed or Discord is unreachable).

**STT Configuration:**
- `STT_ENDPOINT` — Whisper-compatible endpoint (default: `http://archer:8300/v1/audio/transcriptions`)
- `STT_MODEL` — Model name (default: `deepdml/faster-whisper-large-v3-turbo-ct2`)

### Verbose Mode

To bypass filtering and receive all messages (useful for monitoring/debugging):

```bash
DISCORD_WATCHER_VERBOSE=1 claude --dangerously-load-development-channels server:discord-watcher
```

## Dependencies

| Tool | Required by | Install |
|------|------------|---------|
| `bun` | discord-watcher | [bun.sh](https://bun.sh) |
| `gh` | GitHub skills | [cli.github.com](https://cli.github.com) |
| `glab` | GitLab skills | [gitlab.com/gitlab-org/cli](https://gitlab.com/gitlab-org/cli) |
| `curl` | slackbot-send, discord-bot | Usually pre-installed |
| `jq` | slackbot-send, discord-bot, statusline | `apt install jq` / `brew install jq` |
| `python3` | job-fetch | Usually pre-installed |
| `shellcheck` | Validation | `apt install shellcheck` / `brew install shellcheck` |
| `shfmt` | Validation | `go install mvdan.cc/sh/v3/cmd/shfmt@latest` |

## Validation

```bash
./scripts/ci/validate.sh
```

Runs shellcheck, shfmt, and SKILL.md frontmatter validation. Also runs automatically on PRs via GitHub Actions.

## License

[MIT](LICENSE)
