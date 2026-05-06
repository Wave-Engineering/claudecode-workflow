# Changelog

## Unreleased

<<<<<<< Updated upstream
### Fixes

- `wave_finalize`: durable-state fallback when wavebus has been cleaned up by `wave_complete`. Re-derives the MR body from `<project>/.claude/status/{phases-waves.json,state.json}` (issue #s + recorded `mr_urls`) so the kahuna→target finalize step succeeds at the end of the last wave instead of returning `no_artifacts`. Bus artifacts still take precedence when present. (#415, Plan #581 incident)
- `/wavemachine`: Wave-to-wave handoff is now a single tool-use boundary — skill body forbids narrative text between waves, and a new doc-shape regression test (`tests/regression/test_wavemachine_handoff_no_narrator.sh`) guards the contract. Closes "Bug B" from Plan #581 campaign A debrief (#600).
- `/nextwave`: Prime(post-flight) prompt now declares the canonical-line contract verbatim with concrete PASS/FAIL/BLOCKED examples, a forbidden-phrases list (including the exact `"Sleep is still running. Let me wait for the notification."` narration that broke Plan #581 wave-2), and an `Exit shape` section as the LAST section of the prompt so it is the most recent context when the agent emits its final message. Closes #606.
=======
### Features

- `/prepwaves` now ends with a `/clear` recommendation and a paste-ready `/wavemachine` seed prompt. The recommendation downgrades to a hint when `nerf_status` reports <30% of soft dart used. Reduces context drift between planning and execution sessions (Plan #581 debrief). Closes #602.

### Chore

- `/prepwaves` now refuses to run on a dirty working tree or a non-base branch, listing every offending path so the operator can choose between commit, stash, or discard. A `--force-dirty` override exists for legitimate edge cases and emits a noisy banner before proceeding. Rationale: Plan #581 sandbox cross-talk incident (#603).
- `/devspec approve` now self-commits the Dev Spec (and any auxiliary finalization-track writes) on the active branch with a `docs(devspec): finalize Dev Spec for Plan #N — <slug>` message instead of leaving the changes uncommitted. Refuses to commit on the project's protected base branch. Push remains the operator's affirmative act. (#604)
>>>>>>> Stashed changes

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Changed

- **wavemachine skill**: rename epic→Plan/Phase; add Exhaustive Legal Exits section per Dev Spec §5.3.3. [#512, Story 3.1]
- **nextwave skill**: rename epic→Plan/Phase; add Exhaustive Legal Exits section per Dev Spec §5.3.3. [#513, Story 3.2]
- **prepwaves skill**: rename epic→Plan/Phase; annotate surviving "epic" references as PM-layer. [#514, Story 3.3]
- **devspec skill**: teach Plan/Phase/Wave/Story vocabulary; append Decision-Ledger comments to Plan issue during walk; `/devspec upshift` emits `phases-waves.json` with `plan_id` + per-Story `depends_on`. [#515, Story 3.4]
- **issue skill**: add `type=plan` with Dev Spec §5.1.2 body template; add `--epic N` flag for Story creation; on-demand `label_create` for missing `type::plan` / `epic::N`. [#516, Story 3.5]
- **Refactored `vox` around the provider-hook pattern.** The previous `scripts/vox-tts` embedded five coupled backends (VOX_COMMAND, VOX_ENDPOINT, espeak, piper, say) in one cascade; it has been removed. `scripts/vox` is now a thin dispatcher that resolves a *provider* (synthesis) and a *player* (playback) at runtime. Providers live in `~/.config/vox/provider`; copy-and-adapt examples ship in `scripts/vox-providers/` (`silent.sh`, `openai-endpoint.sh`, `piper-local.sh`, `espeak.sh`, `macos-say.sh`). Contract documented in `scripts/vox-providers/README.md` (VOX_PROVIDER_CONTRACT=1). Closes #398.

  **Migration (existing vox users)**: your prior `VOX_COMMAND` / `VOX_ENDPOINT` settings no longer auto-dispatch. Run `vox --setup` once to pick a provider, or manually:

  ```bash
  cp scripts/vox-providers/openai-endpoint.sh ~/.config/vox/provider
  chmod +x ~/.config/vox/provider
  $EDITOR ~/.config/vox/provider   # set VOX_ENDPOINT, VOX_VOICE at the top
  ```

  `VOX_DISABLED=1` is a new escape hatch for clean no-op exit (CI / headless / temporary silence).

- **Renamed `/prd` skill to `/devspec`** (Development Specification). The old name collided with PM usage of "PRD" (customer need, ROI, value prop); the skill produces an implementation spec for a coding agent, which is semantically distinct. Template renamed to `docs/devspec-template.md`, translation protocol to `docs/DDD-to-devspec-protocol.md`, and output files use the `-devspec.md` suffix. The approval metadata marker changed from `<!-- PRD-APPROVAL -->` to `<!-- DEV-SPEC-APPROVAL -->`. Internal campaign-status stage ID `prd` is preserved for backward compatibility with existing `.sdlc/` state files; only the user-facing display label is updated to "Dev Spec". Closes #327.

### Chore

- **regression test**: grep-based test enforcing R-19 (no pipeline reads of `epic::N` labels); wired into CI. [#517, Story 3.6]

### Documentation

- **phase-epic-taxonomy VRTM closed**: MV-01..MV-06 executed; all 18 active requirements traced to Pass verifications; Plan #499 flipped to `plan-complete`. [#518, Story 3.7 — closing story for cc-workflow#499]

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

## [KAHUNA MVP] - 2026-04-25

### Added

- **KAHUNA — autonomous epic delivery via per-epic integration branches.** Lets `/wavemachine` ship a whole epic to `main` in one autonomous run instead of stopping for human review on every Flight MR/PR. All Flights for an epic merge into a short-lived `kahuna/<epic-id>-<slug>` branch (CI-gated, no human review); when the epic is fully assembled and the four-signal trust score is green (commutativity STRONG/MEDIUM, CI green, code-reviewer-clean, trivy zero HIGH/CRITICAL), the system opens a single kahuna→main MR/PR and auto-merges it. Main's existing branch protection, required reviews, and merge rules are unchanged — KAHUNA only relaxes rules on `kahuna/*` branches. cc-workflow surface area in this release:

  - **`/precheck` sandbox awareness** — Detects when a Flight Agent is operating inside a Kahuna sandbox (current branch's base ref matches `^kahuna/[0-9]+-`). When the full checklist passes (validation, code-reviewer no high+ findings, trivy clean, Discord `#precheck` post, vox announcement), `/precheck` emits the sentinel `[AUTO-APPROVED: kahuna sandbox]` and invokes `/scpmmr` directly instead of STOP-and-wait. Outside the sandbox, behavior is unchanged.
  - **`/wavemachine` trust-score gate** — Wavemachine integrates four-signal trust-score evaluation at the kahuna→main MR/PR. Any red signal pauses for human review; degraded-signal fallback to human is automatic, not configured.
  - **`/nextwave` kahuna base-ref plumbing** — Flight sub-agents branch off the kahuna integration branch (not main) and target it as their MR/PR base. The base ref is propagated end-to-end through wave planning, worktree creation, and PR creation.
  - **`wave-status` CLI additions** — New `set-kahuna-branch` subcommand for KAHUNA state writes; renderers for `kahuna_branch` / `kahuna_branches` fields; gate-action surfacing in the dashboard and Discord wave-status embed.
  - **New documentation** — [`docs/kahuna-guide.md`](docs/kahuna-guide.md) (engineer-facing how-to) and [`docs/kahuna-devspec.md`](docs/kahuna-devspec.md) (architecture, rationale, constraints, requirements).

Companion changes ship in `mcp-server-sdlc` (kahuna lifecycle tools, `wave_finalize`, schema relaxations) and `gitlab-settings-automation` (per-platform sandbox configuration). See those repos' CHANGELOGs for details.

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
