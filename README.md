# claudecode-workflow

Portable Claude Code workflow environment — skills, scripts, settings, and a drop-in `CLAUDE.md` template.

This repo packages the custom skills, utility scripts, and project instructions that make up a consistent Claude Code development environment. Clone it, run the installer, and you're set up on any machine.

## Quick Start

```bash
git clone https://github.com/Wave-Engineering/claudecode-workflow.git
cd claudecode-workflow
./install.sh
```

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
| cryo | `/cryo` | Preserve session state before context compaction |
| engage | `/engage` | Load CLAUDE.md, confirm rules of engagement |
| ibm | `/ibm` | Issue-Branch-PR/MR workflow reminder |
| jfail | `/jfail` | CI job/workflow failure analysis |
| mmr | `/mmr` | Merge a PR/MR with squash |
| nextwave | `/nextwave` | Execute parallel spec-driven sub-agents |
| ping | `/ping` | Post to #ai-dev Slack channel |
| pong | `/pong` | Read #ai-dev Slack channel |
| prepwaves | `/prepwaves` | Analyze issues and compute dependency waves |
| review | `/review` | Code review on staged/branch changes |
| scp | `/scp` | Stage, commit, and push workflow |

### Scripts

| Script | Dependencies | What it does |
|--------|-------------|-------------|
| `slackbot-send` | `curl`, `jq`, Slack bot token | Send Slack messages as a named Claude Code agent |
| `job-fetch` | `glab`, `python3` | Fetch GitLab CI job traces for analysis |
| `statusline-command.sh` | `jq`, `git` | Custom status line: git branch, dirty state, context window remaining, model |

### Settings Template

`settings.template.json` provides a starting point for `~/.claude/settings.json` with:
- **Permissions** — Granular tool allowlists for common CLIs (git, gh, glab, docker, terraform, aws, etc.)
- **Hooks** — PostToolUse, SessionStart, SubagentStop hook structure (requires [context-crystallizer](https://github.com/Wave-Engineering/context-crystallizer) or equivalent)
- **Status line** — Points to the custom statusline script
- **Plugins** — Full plugin list (see Plugins section below)
- **Effort level** — Set to `high` for thorough responses

## Installation

### Full Install

```bash
./install.sh
```

This will:
- Copy skills to `~/.claude/skills/`
- Copy scripts to `~/.local/bin/`
- Install statusline to `~/.claude/statusline-command.sh`
- Copy `settings.template.json` → `~/.claude/settings.json` (only if no settings exist yet)
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
```

### Check for Drift

After making local changes to skills or scripts, see what's out of sync:

```bash
./install.sh --check
```

This compares every installed file against the repo version and reports `in sync`, `DIFFERS`, or `NOT INSTALLED`.

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

## Dependencies

| Tool | Required by | Install |
|------|------------|---------|
| `gh` | GitHub skills | [cli.github.com](https://cli.github.com) |
| `glab` | GitLab skills | [gitlab.com/gitlab-org/cli](https://gitlab.com/gitlab-org/cli) |
| `curl` | slackbot-send | Usually pre-installed |
| `jq` | slackbot-send, statusline | `apt install jq` / `brew install jq` |
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
