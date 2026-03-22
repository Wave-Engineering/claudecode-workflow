# claudecode-workflow

Portable Claude Code workflow environment — skills, scripts, and a drop-in `CLAUDE.md` template.

This repo packages the custom skills, utility scripts, and project instructions that make up a consistent Claude Code development environment. Clone it, run the installer, and you're set up on any machine.

## What's Included

### CLAUDE.md Template

A drop-in project instructions file that works with both GitHub and GitLab projects. Auto-detects the platform from `git remote -v` and adapts terminology and CLI commands accordingly.

Key features:
- **Platform detection** — GitHub (`gh`) vs GitLab (`glab`), auto-detected
- **Discovery-based tooling** — finds the project's linters, formatters, and test runners instead of assuming a stack
- **Pre-commit checklist** — enforced review protocol with mandatory verification steps
- **Agent identity system** — Dev-Team (persisted per-project) + Dev-Name/Dev-Avatar (ephemeral per-session)
- **Secrets guardrail** — warns before staging sensitive files, confirms with user before proceeding

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

## Installation

```bash
git clone https://github.com/Wave-Engineering/claudecode-workflow.git
cd claudecode-workflow
./install.sh
```

The installer:
- Copies skills to `~/.claude/skills/`
- Copies scripts to `~/.local/bin/`
- Backs up existing files before overwriting (`.bak`)
- Skips unchanged files
- Reports missing dependencies

### Options

```bash
./install.sh --dry-run    # Show what would be done
./install.sh --skills     # Install skills only
./install.sh --scripts    # Install scripts only
```

### Dependencies

| Tool | Required by | Install |
|------|------------|---------|
| `gh` | GitHub skills | [cli.github.com](https://cli.github.com) |
| `glab` | GitLab skills | [gitlab.com/gitlab-org/cli](https://gitlab.com/gitlab-org/cli) |
| `curl` | slackbot-send | Usually pre-installed |
| `jq` | slackbot-send | `apt install jq` / `brew install jq` |
| `python3` | job-fetch | Usually pre-installed |
| `shellcheck` | Validation | `apt install shellcheck` / `brew install shellcheck` |
| `shfmt` | Validation | `go install mvdan.cc/sh/v3/cmd/shfmt@latest` |

### Slack Setup (for /ping and /pong)

Create a Slack bot token and save it:

```bash
mkdir -p ~/secrets
echo "xoxb-your-token" > ~/secrets/slack-bot-token
chmod 600 ~/secrets/slack-bot-token
```

## Using the CLAUDE.md Template

Copy `CLAUDE.md` into the root of any project:

```bash
cp /path/to/claudecode-workflow/CLAUDE.md /path/to/your-project/CLAUDE.md
```

On first session, Claude will:
1. Detect the platform (GitHub/GitLab)
2. Ask for the Dev-Team name (written into the file, only asked once)
3. Pick a session identity (Dev-Name + Dev-Avatar)

No other configuration needed.

## Validation

```bash
./scripts/ci/validate.sh
```

Runs shellcheck, shfmt, and SKILL.md frontmatter validation.

## License

[MIT](LICENSE)
