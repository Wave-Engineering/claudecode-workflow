# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- `ccfold` skill — Merge upstream CLAUDE.md template changes into a project's local CLAUDE.md, preserving project-specific content (Dev-Team, custom sections)
- `sync.sh` — Reverse-sync: pull local skill/script changes back into the repo

### Changed

- `install.sh --config` now smart-merges `settings.template.json` into existing `settings.json` — missing hooks, plugins, and permissions are added while user customizations are preserved
- `install.sh --check` now reports missing hooks, plugins, and MCP server registrations in addition to file drift

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
