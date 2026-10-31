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

**What:** Shell scripts installed to `~/.local/bin/` -- things like `vox`, `file-opener`, and `statusline-command.sh`.

**What they do:** Provide capabilities that Claude Code does not have natively. `vox` converts text to speech via a Chatterbox endpoint. `file-opener` opens files in the user's GUI editor. These are standalone tools that work from the command line independent of Claude Code.

**Why they are scripts, not skills:** Skills are prompts -- they tell Claude *what to do*. Scripts are executables -- they *do things*. A skill like `/vox` calls the `vox` script under the hood. The skill provides the intelligence (resolving intent, formatting the announcement); the script provides the capability (calling the TTS provider). This separation means scripts can be tested independently, used outside of Claude Code, and updated without changing the skill logic.

For richer integrations that need bidirectional data (Discord, GitLab/GitHub origin operations), the kit uses **MCP servers** instead of scripts -- e.g. `disc-server` for Discord, `sdlc-server` for origin operations. MCP servers expose typed tool calls that skills invoke directly, with the server handling auth, rate-limiting, and protocol details. The Discord integration was originally a `discord-bot` shell script and migrated to the `disc-server` MCP because the typed-tool surface is easier for skills to call correctly.

### Layer 3: Skills

**What:** Markdown files installed to `~/.claude/skills/<name>/SKILL.md` and invoked with `/command` syntax in Claude Code sessions.

**What they do:** Encode complex multi-step workflows as reusable procedures. When you type `/precheck`, Claude reads the `precheck/SKILL.md` file and follows its instructions step by step -- verifying the branch, running validation, launching a code review sub-agent, and presenting the checklist.

**Why they are markdown, not code:** Skills are instructions for an LLM, not programs for a computer. They describe intent, decision trees, and workflows in natural language. This makes them easy to read, modify, and extend without programming knowledge. A skill file reads like a runbook because that is exactly what it is -- a runbook that Claude Code can execute.

### The Fourth Layer: The Doorbell

**What:** a background task that wakes the agent when something arrives for it. On a host that runs the crewchat daemon it is `crewchat-doorbell`, one stream for Mattermost, Discord and squawk answers. (The kit's earlier Discord channel server, `discord-watcher`, was retired in #1344.)

**What it does:** the doorbell blocks until an event addressed to this agent arrives, prints it, and exits. The exit is what wakes the agent. This enables real-time inter-agent communication -- multiple Claude Code agents running on different machines (or different projects on the same machine) can talk to each other.

**Why it is a separate layer:** The first three layers are pull-based -- Claude decides when to use a script or skill. The doorbell is push-based -- external events (a chat message) arrive without Claude asking for them. Not every deployment needs it -- it needs the crewchat daemon on the host -- but for teams running multiple agents, it enables coordination that would otherwise require human relay.

---

## Identity System

The identity system has two layers that mirror the distinction between project-level and session-level state.

### Dev-Team (Persisted)

**What:** A short name identifying which project or team this agent belongs to (e.g., `cc-workflow`, `backend-team`, `infra`).

**Where it lives:** Written into the `Dev-Team:` field at the bottom of the project's `CLAUDE.md` file.

**Lifecycle:** Set once on first session in a project, then persisted forever. It survives across sessions, across machines (since `CLAUDE.md` is committed to the repo), and across context compactions. Every agent working on the same project shares the same Dev-Team.

**Why it exists:** When multiple agents are communicating through Discord, Dev-Team is the routing key for project-level addressing. A message to `@cc-workflow` reaches any agent working on the cc-workflow project, regardless of which specific session identity that agent has.

### Dev-Name and Dev-Avatar (Ephemeral)

**What:** A memorable name (e.g., `beacon`, `null-pointer`, `mother`) and a Unicode emoji (e.g., 📡, 💀, 🔮).

**Where it lives:** Written to `<project_root>/.claude/agent-identity.json` — reboot-durable, gitignored, keyed by project root (not session or PID).

**Lifecycle:** Persists across sessions for the same checkout. Re-running `/name` overwrites with a fresh pick. The statusline and all skills resolve it the same way regardless of process ancestry.

**Why it exists:** Dev-Name provides session-level addressing. When two agents are both working on `cc-workflow`, you need a way to talk to a specific one -- `@beacon` reaches only the agent that picked that name this session. The ephemeral nature is intentional: it prevents stale identity references and makes the channel feel alive rather than static.

**Why kebab-case:** Dev-Names must be kebab-case (lowercase, hyphens between words) because they double as routing keys for `@` addressing in chat. Addressing tokenizes messages and matches against `@<dev-name>` -- spaces or mixed case would break the matching.

### How Identity Flows

```
CLAUDE.md (Dev-Team: cc-workflow)
        |
        v
Session start: Claude picks Dev-Name + Dev-Avatar
        |
        v
<project_root>/.claude/agent-identity.json
  {
    "dev_team": "cc-workflow",
    "dev_name": "beacon",
    "dev_avatar": "📡"
  }
        |
        v
Used by: /owtx, /owrx, /name, statusline,
         chat addressing, message signatures
```

Every skill and script that needs identity reads from the same file, resolved the same way. This is why the identity file is keyed by project root hash rather than PID -- it provides a stable rendezvous point for all components.

---

## Mandatory Workflows

The kit enforces several workflows that cannot be skipped. These exist because of real problems encountered in production use -- every mandatory rule was added in response to a specific failure mode.

### No Autonomous Merges

**The rule:** Commits and pushes to Claude's own working branch are free (`/scp`). The gate is the PR/MR: Claude never marks a PR/MR ready without a `/precheck` pass on its head, and never merges without your merge call. Even trivial changes go `/scpmr` (draft PR/MR + `/precheck`) and then wait for `/mmr`, `/scpmmr`, or an affirmative.

**Why it exists:** Context compaction (when Claude's context window fills up and gets summarized) causes loss of state. In early use, compaction led to Claude skipping the review checklist and shipping unreviewed code. The MR gate makes this structurally impossible: `/precheck` reviews the pushed commits, reads CI, posts a `precheck` commit status, marks the PR/MR ready, and then *stops*. A hook refuses to mark a PR/MR ready without that status, and Claude cannot merge until you respond.

### Always Have an Issue

**The rule:** Every piece of work must be tracked by an issue. No code is written until the issue exists and is linked to a branch.

**Why it exists:** Untracked work creates invisible state. If Claude starts implementing a feature without an issue, there is no record of what was requested, no acceptance criteria to verify against, and no way for other team members (human or agent) to know what is in progress. The issue is the contract -- it defines what "done" looks like.

### Test Before a Protected Push or a PR/MR

**The rule:** Testing gates the PR/MR, not the push. An agent pushes its own working branch (`feature/`, `fix/`, `chore/`, `doc/`) freely, as a plain `git push <remote> <branch>`. Local tests must pass before any push to a protected or release branch, before any compound or unusual push, and before a PR/MR is marked ready (CI's verdict for the pushed HEAD counts). This is non-negotiable regardless of time pressure or session state.

**Why it exists:** Pushing untested code wastes CI resources, blocks shared pipelines, and creates false signal for other developers. A failed CI run that could have been caught locally costs the team far more time than the seconds it takes to run `./scripts/ci/validate.sh`. Claude enforces this at the PR/MR: `/precheck` reads CI's verdict for the pushed HEAD and runs local validation where CI doesn't cover it, and the push hook refuses protected and release refs.

### Post-Compaction Re-Engagement

**The rule:** After any context compaction or `/reseed revive`, Claude must re-read `CLAUDE.md` in full before any other work; no confirmation message is sent. `/engage reload` does the re-read, then the work carries on.

**Why it exists:** Compaction is lossy. Claude's summary of a long conversation may drop critical details like "we are on a feature branch" or "tests must pass before a protected push or a PR/MR." The `/engage` skill exists specifically to restore this context. Running it after compaction is the safety net that prevents compaction-induced rule violations.

---

## Skill Taxonomy

The skills are organized into four groups based on their purpose. This is not a rigid hierarchy -- some skills span groups -- but it provides a useful mental model.

### Foundation Skills

These manage the agent's own state and context. You use them at session boundaries and during maintenance.

| Skill | Purpose |
|-------|---------|
| `/engage` | Load rules, restore context, confirm ready state. The resume entry point. |
| `/ccfold` | Merge upstream CLAUDE.md template changes into a project's local copy. |
| `/name` | Report or pick the agent's session identity (Dev-Name, Dev-Avatar). |

State preservation across compaction is automatic: durable facts live in memory files (project-scoped), and plan files (`.claude/plans/`) capture working state. `/engage` is the single entry point for resume — memory is loaded by the harness before the skill runs.

### Workflow Skills

These drive the development loop: creating issues, committing, reviewing, merging.

| Skill | Purpose |
|-------|---------|
| `/precheck` | MR gate -- reviews the pushed commits, reads CI, marks the PR/MR ready, stops for the merge call. |
| `/scp` | Stage, commit, push your working branch. Free; opens no PR. |
| `/scpmr` | `/scp`, open a draft PR/MR, run `/precheck` -- stops for the merge call. |
| `/scpmmr` | `/scpmr` then `/mmr`. Typed after a precheck STOP, it is the merge call. |
| `/mmr` | Merge a prechecked PR/MR with squash and source branch deletion. |
| `/ibm` | Issue-Branch-PR/MR workflow reminder. A cheat sheet, not an executor. |
| `/review` | Run a standalone code review on staged changes, a branch, or a file. |
| `/jfail` | Fetch and analyze a failed CI job or workflow run. |

### Communication Skills

These handle interaction with external systems: Discord, voice, and file viewers.

| Skill | Purpose |
|-------|---------|
| `/owtx` | Send chat -- a channel, a DM, or a roll-call check-in. OaW Mattermost by default; `> discord` for Discord. |
| `/owrx` | Read chat -- a channel or a thread. OaW Mattermost by default; `> discord` for Discord. |
| `/disc` | **Deprecated** (use `/owtx` and `/owrx`). Discord integration -- send, read, create channels, check in. |
| `/vox` | Text-to-speech voice announcements. |
| `/view` | Open a file or URL in a GUI viewer (read-only). |
| `/edit` | Open a file or URL in a GUI editor (modification intent). |

### Advanced Skills

The "wave pattern" provides lifecycle tracking, dashboard visibility, and audit trails for structured work -- parallel, serial, or mixed.

| Skill | Purpose |
|-------|---------|
| `/assesswaves` | Quick assessment of whether work items are suitable for wave-pattern execution (parallel, serial, or mixed). |
| `/prepwaves` | Full planning: validate sub-issue specs, compute dependency waves, prepare for execution. |
| `/nextwave` | Execute one wave at a time -- parallel flights use isolated worktrees, serial flights use a streamlined fast-path. |

The wave skills form a pipeline: `/assesswaves` determines the topology, `/prepwaves` plans the execution order, and `/nextwave` executes one wave at a time. Parallel flights use isolated worktrees with flight-based conflict avoidance. Serial flights (1 issue per flight) skip worktree isolation and conflict detection. See the individual [skill files](../skills/) for full documentation.

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
| Mandatory: Testing Gates the PR/MR | Tests before a protected push or a ready PR/MR |
| Mandatory: MR Gate | The `/precheck` workflow and the merge call |
| Mandatory: Story Completion | Acceptance criteria verification |
| Mandatory: Issue Tracking | Issue-branch-PR/MR workflow |
| Work Item Standards | Issue template quality requirements |
| Branching Strategy | Branch naming and target resolution |
| Code Standards | Tooling discovery, linter/formatter defaults |
| Secrets and Sensitive Files | Pre-staging safety net for credentials |
| Agent Identity | Dev-Team persistence, Dev-Name assignment |
| Post-Compaction Re-Read | Re-read after context compaction, no confirmation |

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
- **[Skill Reference](skill-reference.md)** -- detailed documentation for every skill with examples and common options
- **[Troubleshooting](troubleshooting.md)** -- common failure modes and fixes for vox, the doorbell, install, identity, and more
- **[README](../README.md)** -- full component reference (skills table, scripts table, installation options)
- **[Skill files](../skills/)** -- raw agent prompts for each skill (`skills/<name>/SKILL.md`)
