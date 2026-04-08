# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- **Renamed `/prd` skill to `/devspec`** (Development Specification). The old name collided with PM usage of "PRD" (customer need, ROI, value prop); the skill produces an implementation spec for a coding agent, which is semantically distinct. Template renamed to `docs/devspec-template.md`, translation protocol to `docs/DDD-to-devspec-protocol.md`, and output files use the `-devspec.md` suffix. The approval metadata marker changed from `<!-- PRD-APPROVAL -->` to `<!-- DEV-SPEC-APPROVAL -->`. Internal campaign-status stage ID `prd` is preserved for backward compatibility with existing `.sdlc/` state files; only the user-facing display label is updated to "Dev Spec". Closes #327.

### Added

- **Nerf MCP server** — Deterministic context budget management via `nerf-server` MCP. Includes dart thresholds (soft/hard/ouch), behavior modes (not-too-rough, hurt-me-plenty, ultraviolence), statusline indicators, and a terminal-based scope monitor
- **`/nerf` skill** — Thin routing stub for the nerf MCP server with `k`/`m` suffix parsing
- **`/issue` skill** — Create structured issues (feature, bug, chore, docs, epic) with proper templates and labels. Self-contained, dual-platform (GitHub/GitLab)
- **`/ddd` skill** — Domain-Driven Design facilitation with 8-stage event storming, domain model formalization, and PRD generation
- **`/man` skill** — Display usage information for any installed skill via SKILL.md frontmatter
- **`/cryopact` skill** — Background cryo via subagent — preserve state without blocking the main conversation
- **`/disc` skill** — Unified Discord integration: check-in, send, read, list channels, create threads
- **`/view` skill** — Open file/URL in a GUI viewer (read-only) with cross-platform file-opener
- **`/edit` skill** — Open file/URL in a GUI editor for modification
- **`/vox` skill** — Text-to-speech voice announcements via Chatterbox API with local fallback
- **`/precheck` skill** — Pre-commit gate: branch/issue compliance, validation, code review, checklist
- **`/assesswaves` skill** — Quick assessment of wave-pattern suitability for parallel execution
- **`/ccwork` skill** — Onboarding hub with interactive tours, labs, and setup wizards
- **`/scpmr` and `/scpmmr` combo skills** — Stage/commit/push/create PR/merge in one command
- **`/ccfold` skill** — Merge upstream CLAUDE.md template changes into local project CLAUDE.md
- **`sync.sh`** — Reverse-sync: pull local skill/script changes back into the repo
- **Context crystallizer** — Session state preservation pipeline: hooks (PostToolUse, SessionStart, SubagentStop), libraries (context-analyzer, crystallizer), CLI tools (cc-context, cc-cleanup). Tracked in `context-crystallizer/` and installed via `--crystallizer`
- **Discord watcher channel server** — Real-time inter-agent communication via Discord with targeted message filtering, thread polling, voice message STT, and Dev-Name echo suppression
- **Discord bot** — REST API client for Discord: send, read, create channels/threads, resolve names, with 429 retry handling and kill switch
- **Discord status post** — Wave-status embed with auto-updating pinned message, debounce, and dev-team fallback
- **`discord-lock`** — Advisory lock for serializing Discord channel writes across agents
- **`cc-inspector`** — Context window inspector: mitmproxy + Flask UI for API payload capture
- **`generate-status-panel`** — HTML status panel generator for wave progress
- **`worktree-manager`** — Manage isolated worktrees for parallel agent execution
- **Remote installer** — `scripts/install-remote.sh` for curl-pipe-bash installation from GitHub Releases
- **MCP manifest** — `mcps.json` with bundle-install architecture for wtf-server, discord-watcher, and nerf-server
- **GitHub Actions workflow** for GitHub Release packaging
- **Statusline v2** — Two-line layout with per-session indicators, visual refresh, and JSON-based indicator interface
- **Introduction system** — First-run introduction.md display for new skills with marker file gating
- **Work Item Standards** — Label taxonomy (`group::value`), issue templates (feature, bug, chore, docs, epic), and wave-pattern quality requirements in CLAUDE.md
- **`.claude-project.md`** — Cached platform detection results (GitHub/GitLab, CLI tool, labels, CI)
- **Agent identity keying** — Migrated from PPID to project-root md5 hash for stable cross-process resolution
- **PRD template v2.0** — EARS requirements, phased implementation, artifact manifest, CI/CD pipeline, documentation kit, test plan sections, foundation story checklist, one-story-one-repo rule
- **Getting Started guide** — 15-minute walkthrough of first session
- **Skill Reference** — Detailed documentation for all skills
- **Concepts guide** — Architecture overview of the three-layer kit
- **Troubleshooting guide** — Common issues and fixes
- **Discord configuration guide** — Bot token, watcher, inter-agent messaging setup
- **Statusline indicators guide** — Per-session indicator interface documentation

### Changed

- `install.sh --config` now smart-merges `settings.template.json` into existing `settings.json` — missing hooks, plugins, and permissions are added while user customizations are preserved
- `install.sh --check` now reports missing hooks, plugins, MCP server registrations, and crystallizer drift
- `install.sh` supports selective flags: `--skills`, `--scripts`, `--config`, `--mcps`, `--crystallizer`
- Repo restructured: skills carry their own scripts (discord-bot inside disc, file-opener inside view, etc.)
- `/cryopact` delegates to cryo subagent, removes auto-clear, fixes immediate mode
- `/disc` default action changed from read to check-in
- `/nextwave` uses pre-created worktrees instead of isolation worktrees, with granular lifecycle tasks and explicit wave-status calls
- `/pong` uses priority-ordered default discovery flow (active thread → addressed messages → general history)
- `/vox` adds `--output FILE` flag for render-to-disk mode
- Discord config abstracted into `~/.claude/discord.json`
- Agent check-in on session start via `#roll-call` channel
- RC display name set to match Dev-Name at session start
- Introduction-gate marker files use dot prefix for hiding
- Nerf default thresholds lowered for 200k context window safety

### Fixed

- `install.sh` unbound tmpdir variable on script exit
- `install.sh` handles `claude mcp add` failure gracefully
- Discord-bot 429 retry-after handling and JSONL API call logging
- Discord-bot kill switch to halt all API calls on global 429
- Discord watcher strips punctuation from @-addressing tokens
- Vox Bluetooth wake noise prepend to prevent audio clipping
- Vox help text for `-o` flag and `espeak-ng` fallback
- Wave-status meta-refresh fallback for `file://` dashboard viewing
- Wave-status infers phase/wave position when `current_wave` is null
- Identity keying migrated from PPID to project-root hash (fixes multi-session collisions)
- Ping/pong channel name corrected and channel ID added
- `/precheck` runs immediately without asking permission
- `/issue` removes per-issue approval gate (issues are cheap to edit)

### Removed

- `afk-notify` Stop hook — replaced by kill switch on discord-watcher

## [0.1.0] - 2026-03-22

### Added

- **CLAUDE.md template** — Drop-in project instructions with auto-detection for GitHub and GitLab
  - Platform detection from `git remote -v`
  - Discovery-based code standards (finds project's own tooling)
  - Agent identity system (Dev-Team persisted, Dev-Name/Dev-Avatar per-session)
  - Pre-commit checklist with mandatory verification
  - Secrets guardrail (warn-and-confirm before staging sensitive files)
  - PR/MR description format

- **11 custom skills** — All dual-platform (GitHub + GitLab)
  - `cryo` — Session state preservation before compaction
  - `engage` — Load rules of engagement
  - `ibm` — Issue-Branch-PR/MR workflow
  - `jfail` — CI job/workflow failure analysis
  - `mmr` — Merge PR/MR with squash
  - `nextwave` — Parallel sub-agent execution
  - `ping` — Post to #ai-dev Slack channel
  - `pong` — Read #ai-dev Slack channel
  - `prepwaves` — Dependency wave planning
  - `review` — Code review on staged/branch changes
  - `scp` — Stage/commit/push workflow

- **Utility scripts**
  - `slackbot-send` — Send Slack messages as a named Claude Code agent
  - `job-fetch` — Fetch GitLab CI job traces for analysis
  - `statusline-command.sh` — Custom status line with git info and context window

- **Deployment tooling**
  - `install.sh` — Install skills, scripts, and config with backup and diff-skip
  - `install.sh --check` — Show drift between repo and installed versions
  - `install.sh --dry-run` — Preview changes without modifying files
  - `uninstall.sh` — Clean removal of installed components
  - `settings.template.json` — Portable Claude Code settings template

- **CI and repo scaffolding**
  - GitHub Actions workflow for PR validation
  - `validate.sh` — shellcheck + shfmt + SKILL.md frontmatter checks
  - Issue templates (bug report, feature request)
  - PR template matching CLAUDE.md conventions
  - MIT license
