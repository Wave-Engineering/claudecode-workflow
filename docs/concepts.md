# Concepts

This document explains how the pieces of the ccwork kit fit together and why they are designed the way they are. Read this after completing the [Getting Started](getting-started.md) guide.

**Prefer interactive walkthroughs?** Run `/ccwork tour` for a guided orientation, `/ccwork tour workflow` for the commit/PR loop, or `/ccwork tour foundations` for the session lifecycle skills. The tours cover the same material as this document but run live commands against your actual setup.

---

## The Three Layers

The kit is built in three layers, each serving a different purpose. Understanding these layers is the key to understanding everything else.

### Layer 1: Settings

**What:** `~/.claude/settings.json` -- the global configuration file for Claude Code.

**What it controls:** Tool permissions (which CLI tools Claude can run without asking), hooks (automated behaviors triggered by Claude Code events), the status line format, enabled plugins, and effort level.

**Why it exists:** Claude Code out of the box has conservative defaults. The settings layer opens up the permissions Claude needs to be productive (running `git`, `gh`, `glab`, `docker`, etc.) and wires up hooks that automate routine behaviors. Without this layer, Claude would ask permission for every shell command.

The kit ships a `settings.template.json` that gets copied to `~/.claude/settings.json` on first install. After that, you own the file -- the installer will not overwrite it.

### Layer 2: Scripts

**What:** Shell scripts installed to `~/.local/bin/` -- things like `discord-bot`, `slackbot-send`, `vox`, `file-opener`, `afk-notify`, and `statusline-command.sh`.

**What they do:** Provide capabilities that Claude Code does not have natively. `discord-bot` is a REST client for the Discord API. `vox` converts text to speech via a Chatterbox endpoint. `slackbot-send` posts Slack messages as a bot. These are standalone tools that work from the command line independent of Claude Code.

**Why they are scripts, not skills:** Skills are prompts -- they tell Claude *what to do*. Scripts are executables -- they *do things*. A skill like `/disc` (Discord integration) calls the `discord-bot` script under the hood. The skill provides the intelligence (resolving intent, formatting messages, signing with identity), while the script provides the capability (HTTP calls to the Discord API). This separation means scripts can be tested independently, used outside of Claude Code, and updated without changing the skill logic.

### Layer 3: Skills

**What:** Markdown files installed to `~/.claude/skills/<name>/SKILL.md` and invoked with `/command` syntax in Claude Code sessions.

**What they do:** Encode complex multi-step workflows as reusable procedures. When you type `/precheck`, Claude reads the `precheck/SKILL.md` file and follows its instructions step by step -- verifying the branch, running validation, launching a code review sub-agent, and presenting the checklist.

**Why they are markdown, not code:** Skills are instructions for an LLM, not programs for a computer. They describe intent, decision trees, and workflows in natural language. This makes them easy to read, modify, and extend without programming knowledge. A skill file reads like a runbook because that is exactly what it is -- a runbook that Claude Code can execute.

### The Fourth Layer: Channels

**What:** MCP (Model Context Protocol) channel servers that push real-time notifications into Claude Code sessions. Currently the kit ships one: `discord-watcher`.

**What it does:** The discord-watcher polls Discord channels and delivers messages to the Claude Code session as `<channel>` notifications. This enables real-time inter-agent communication -- multiple Claude Code agents running on different machines (or different projects on the same machine) can talk to each other through Discord.

**Why it is a separate layer:** The first three layers are pull-based -- Claude decides when to use a script or skill. Channels are push-based -- external events (a Discord message, a Slack notification) arrive without Claude asking for them. This is a fundamentally different interaction pattern that requires the MCP channel server infrastructure. Not every deployment needs channels -- they add complexity and require a running Discord server with a bot token -- but for teams running multiple agents, they enable coordination that would otherwise require human relay.

---

## Identity System

The identity system has two layers that mirror the distinction between project-level and session-level state.

### Dev-Team (Persisted)

**What:** A short name identifying which project or team this agent belongs to (e.g., `cc-workflow`, `backend-team`, `infra`).

**Where it lives:** Written into the `Dev-Team:` field at the bottom of the project's `CLAUDE.md` file.

**Lifecycle:** Set once on first session in a project, then persisted forever. It survives across sessions, across machines (since `CLAUDE.md` is committed to the repo), and across context compactions. Every agent working on the same project shares the same Dev-Team.

**Why it exists:** When multiple agents are communicating through Discord or Slack, Dev-Team is the routing key for project-level addressing. A message to `@cc-workflow` reaches any agent working on the cc-workflow project, regardless of which specific session identity that agent has.

### Dev-Name and Dev-Avatar (Ephemeral)

**What:** A memorable name (e.g., `beacon`, `null-pointer`, `mother`) and a Slack-style emoji (e.g., `:satellite:`, `:skull:`, `:crystal_ball:`).

**Where it lives:** Written to a temp file at `/tmp/claude-agent-<hash>.json`, where `<hash>` is the md5 of the project root path.

**Lifecycle:** Picked fresh every session. A new Claude Code window means a new identity. The temp file is keyed by project root (not process ID), so the statusline and all skills can find it regardless of process ancestry.

**Why it exists:** Dev-Name provides session-level addressing. When two agents are both working on `cc-workflow`, you need a way to talk to a specific one -- `@beacon` reaches only the agent that picked that name this session. The ephemeral nature is intentional: it prevents stale identity references and makes the channel feel alive rather than static.

**Why kebab-case:** Dev-Names must be kebab-case (lowercase, hyphens between words) because they double as routing keys for `@` addressing in Discord. The watcher tokenizes messages and matches against `@<dev-name>` -- spaces or mixed case would break the matching.

### How Identity Flows

```
CLAUDE.md (Dev-Team: cc-workflow)
        |
        v
Session start: Claude picks Dev-Name + Dev-Avatar
        |
        v
/tmp/claude-agent-<hash>.json
  {
    "dev_team": "cc-workflow",
    "dev_name": "beacon",
    "dev_avatar": ":satellite:"
  }
        |
        v
Used by: /disc, /ping, /pong, /name, statusline,
         discord-watcher echo filtering, message signatures
```

Every skill and script that needs identity reads from the same file, resolved the same way. This is why the identity file is keyed by project root hash rather than PID -- it provides a stable rendezvous point for all components.

---

## Mandatory Workflows

The kit enforces several workflows that cannot be skipped. These exist because of real problems encountered in production use -- every mandatory rule was added in response to a specific failure mode.

### No Autonomous Commits

**The rule:** Claude never commits without explicit human approval. Even trivial changes require `/precheck` followed by one of `/scp`, `/scpmr`, or `/scpmmr`.

**Why it exists:** Context compaction (when Claude's context window fills up and gets summarized) causes loss of state. In early use, compaction led to Claude skipping the review checklist and committing directly -- pushing unreviewed code to the remote. The pre-commit gate exists to make this structurally impossible: `/precheck` presents the checklist and then *stops*. Claude cannot proceed until you respond.

### Always Have an Issue

**The rule:** Every piece of work must be tracked by an issue. No code is written until the issue exists and is linked to a branch.

**Why it exists:** Untracked work creates invisible state. If Claude starts implementing a feature without an issue, there is no record of what was requested, no acceptance criteria to verify against, and no way for other team members (human or agent) to know what is in progress. The issue is the contract -- it defines what "done" looks like.

### Test Before Push

**The rule:** Local tests must pass before any `git push`. This is non-negotiable regardless of time pressure or session state.

**Why it exists:** Pushing untested code wastes CI resources, blocks shared pipelines, and creates false signal for other developers. A failed CI run that could have been caught locally costs the team far more time than the seconds it takes to run `./scripts/ci/validate.sh`. Claude enforces this by running validation as part of both `/precheck` and `/scp`.

### Post-Compaction Re-Engagement

**The rule:** After any context compaction, Claude must immediately re-read `CLAUDE.md` and confirm the mandatory rules before doing any other work.

**Why it exists:** Compaction is lossy. Claude's summary of a long conversation may drop critical details like "we are on a feature branch" or "tests must pass before push." The `/engage` skill exists specifically to restore this context. Running it after compaction is the safety net that prevents compaction-induced rule violations.

---

## Skill Taxonomy

The skills are organized into four groups based on their purpose. This is not a rigid hierarchy -- some skills span groups -- but it provides a useful mental model.

### Foundation Skills

These manage the agent's own state and context. You use them at session boundaries and during maintenance.

| Skill | Purpose |
|-------|---------|
| `/engage` | Load rules, restore context, confirm ready state. The "thaw" operation. |
| `/cryo` | Freeze session state before context compaction. The "freeze" operation. |
| `/ccfold` | Merge upstream CLAUDE.md template changes into a project's local copy. |
| `/name` | Report or pick the agent's session identity (Dev-Name, Dev-Avatar). |

### Workflow Skills

These drive the development loop: creating issues, committing, reviewing, merging.

| Skill | Purpose |
|-------|---------|
| `/precheck` | Pre-commit gate -- the mandatory verification step before any commit. |
| `/scp` | Stage, commit, push. Creates a PR if one does not exist. |
| `/scpmr` | Stage, commit, push, create PR/MR -- stops before merging. |
| `/scpmmr` | Stage, commit, push, create PR/MR, merge -- the full pipeline. |
| `/mmr` | Merge an existing PR/MR with squash and source branch deletion. |
| `/ibm` | Issue-Branch-PR/MR workflow reminder. A cheat sheet, not an executor. |
| `/review` | Run a standalone code review on staged changes, a branch, or a file. |
| `/jfail` | Fetch and analyze a failed CI job or workflow run. |

### Communication Skills

These handle interaction with external systems: Discord, Slack, voice, and file viewers.

| Skill | Purpose |
|-------|---------|
| `/disc` | Discord integration -- send, read, create channels, check in. |
| `/ping` | Post a message to the `#ai-dev` Slack channel as this agent. |
| `/pong` | Read recent messages from `#ai-dev` with smart filtering. |
| `/vox` | Text-to-speech voice announcements. |
| `/view` | Open a file or URL in a GUI viewer (read-only). |
| `/edit` | Open a file or URL in a GUI editor (modification intent). |

### Advanced Skills

These enable parallel execution of work across multiple agents -- the "wave pattern."

| Skill | Purpose |
|-------|---------|
| `/assesswaves` | Quick assessment of whether work items are suitable for parallel execution. |
| `/prepwaves` | Full planning: validate sub-issue specs, compute dependency waves, prepare for execution. |
| `/nextwave` | Execute one wave at a time with isolated worktrees and flight-based conflict avoidance. |

The wave skills form a pipeline: `/assesswaves` decides if parallelism is worth it, `/prepwaves` plans the execution order, and `/nextwave` executes one wave at a time. Each wave can contain multiple "flights" -- groups of issues that can safely run in parallel without file-level conflicts. See the individual [skill files](../skills/) for full documentation.

---

## How CLAUDE.md Works

`CLAUDE.md` is the project instructions file that Claude Code reads at session start. Understanding how it works is important because it is the primary mechanism for controlling Claude's behavior in a project.

### Template vs Per-Project

The ccwork kit ships a `CLAUDE.md` template in the repo root. When you copy it into a project (`cp claudecode-workflow/CLAUDE.md /path/to/your-project/`), it becomes that project's local copy. The template and the local copy are independent files -- changes to one do not affect the other.

Over time, the template evolves (new sections, updated rules, improved workflows). To pull those changes into a project's local copy without losing project-specific customizations, use `/ccfold`. It performs a section-by-section merge: updating sections that have changed upstream, adding new sections, and preserving any sections that exist only in your local copy (like custom team rules or project-specific workflows).

### Platform Detection

The template supports both GitHub and GitLab out of the box. Rather than maintaining two separate templates, it uses runtime platform detection: Claude reads `git remote -v`, identifies the host, and adapts its terminology and CLI commands accordingly. A project on GitHub gets `gh` commands and "Pull Request" terminology. A project on GitLab gets `glab` commands and "Merge Request" terminology. The detection runs once on session start and the result is cached in `.claude-project.md` (generated by `/ccfold`) so it does not repeat every session.

### The `/ccfold` Sync Process

When you run `/ccfold`, it:

1. **Fetches** the latest template from the canonical GitHub repo
2. **Compares** each section (split on `## ` headers) between upstream and local
3. **Classifies** sections as identical, updated, new, or local-only
4. **Presents** a merge plan showing what will change
5. **Applies** the merge after your approval, preserving project-specific content (Dev-Team, local-only sections)
6. **Generates** `.claude-project.md` with cached platform detection results

The merge is semantic, not mechanical -- Claude uses judgment to combine content rather than blindly replacing text blocks. When in doubt about whether a local change is intentional customization or just an older template version, it asks.

### What CLAUDE.md Controls

The rules in `CLAUDE.md` are loaded into Claude's context at session start and take precedence over default behaviors. The key sections and what they govern:

| Section | Controls |
|---------|----------|
| Platform Detection | Which CLI and terminology to use |
| Mandatory: Local Testing | Test-before-push enforcement |
| Mandatory: Pre-Commit Gate | The `/precheck` workflow |
| Mandatory: Story Completion | Acceptance criteria verification |
| Mandatory: Issue Tracking | Issue-branch-PR/MR workflow |
| Work Item Standards | Issue template quality requirements |
| Branching Strategy | Branch naming and target resolution |
| Code Standards | Tooling discovery, linter/formatter defaults |
| Secrets and Sensitive Files | Pre-staging safety net for credentials |
| Agent Identity | Dev-Team persistence, Dev-Name assignment |
| Post-Compaction Rules | Re-engagement after context compaction |

All of these can be customized per project. The mandatory rules are written as hard constraints ("NEVER", "NON-NEGOTIABLE") because they protect against failure modes that have actually occurred. Project-specific customizations (like additional team rules or different branching conventions) can be added as new sections -- `/ccfold` will preserve them on future template merges.

---

## Skill Introductions

Each skill directory contains an optional `introduction.md` file that provides a brief first-run welcome when the skill is invoked.

### How It Works

Every SKILL.md contains a preamble instruction (an HTML comment near the top) that tells Claude to check for `introduction.md` in the skill's directory before executing. If the file exists, Claude reads it, presents the contents to the user as a brief welcome, and then deletes the file. On subsequent invocations, the file is gone and the skill executes immediately with no preamble.

### What Introductions Contain

Each introduction is 3-5 sentences covering:

- **What the skill does** -- one sentence summary
- **When you would use it** -- the trigger or use case
- **A practical tip** -- a "did you know" or best-practice note
- **Where to learn more** -- pointer to a tour, lab, or doc

### Reinstalling Introductions

Running `install.sh` copies the introduction files back from the repo, so a fresh install (or reinstall after a kit update) restores all introductions. This is intentional -- new versions may include updated or expanded introductions.

### Dismissing Introductions

If you do not want the first-run intros, ask the agent to remove them: "get rid of the intros" or "delete all introduction files." The agent will glob and delete `~/.claude/skills/*/introduction.md`. They will not come back until the next `install.sh` run.

---

## What's Next

- **[Getting Started](getting-started.md)** -- if you have not yet done the hands-on walkthrough
- **[README](../README.md)** -- full component reference (skills table, scripts table, installation options)
- **[Skill files](../skills/)** -- detailed documentation for each skill (`skills/<name>/SKILL.md`)
