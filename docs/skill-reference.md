# Skill Reference

Complete reference for all skills in the ccwork kit. Each entry covers what the skill does, when to use it, example invocations, and common options.

For a conceptual overview of how skills fit into the kit architecture, see [Concepts](concepts.md#skill-taxonomy). For hands-on walkthroughs, run `/ccwork tour`.

---

## Foundation Skills

These manage the agent's own state and context. Use them at session boundaries and during maintenance.

---

### `/engage` -- Load Rules and Restore Context

Reads CLAUDE.md, confirms the mandatory development rules are loaded, restores any active plan from a prior session, and reports the agent's ready state. This is the "thaw" operation that pairs with `/cryo`.

**When to use it:**
- At the start of every new session
- After context compaction (when Claude's context window fills up and gets summarized)
- Whenever you are unsure whether Claude still has the project rules loaded

**Examples:**

```
/engage
```

No arguments -- it reads the environment and reports what it finds. If CLAUDE.md exists, it summarizes the mandatory rules. If a plan file exists, it summarizes pending work. It always ends with the current git branch and a prompt for direction.

---

### `/cryo` -- Freeze Session State

Cryogenically preserves session state into durable storage before context compaction hits. Rewrites the plan file as a factual snapshot of current state and prunes the task list to only what matters.

**When to use it:**
- When the context window is getting full and compaction is imminent
- Before ending a long session where you want to pick up exactly where you left off
- Any time you want to checkpoint your progress

**Examples:**

```
/cryo
```

No arguments. It audits the current git state, rewrites the plan file with commits, branches, decisions, and pending work, then prunes completed tasks from the task list. The audience is a future version of the agent with zero context.

**Key detail:** `/cryo` freezes, `/engage` thaws. Always run `/cryo` before compaction and `/engage` after.

---

### `/ccfold` -- Merge Upstream CLAUDE.md Template

Fetches the latest CLAUDE.md template from the ccwork repo and merges it into the current project's CLAUDE.md, preserving project-specific content like Dev-Team and any custom sections.

**When to use it:**
- After pulling new updates to the ccwork repo
- When you notice new features or rules in the template that your project's CLAUDE.md is missing
- Periodically, to keep your project instructions up to date

**Examples:**

```
/ccfold
```

No arguments. It fetches the upstream template, compares section by section, presents a merge plan showing what would change, and waits for your approval before applying. It also generates or updates `.claude-project.md` with cached platform detection results.

**What it preserves:** The `Dev-Team:` value, any local-only sections, and content appended below the Dev-Team line. These are never overwritten by upstream changes.

---

### `/name` -- Report or Pick Agent Identity

Reports the current session identity (Dev-Name, Dev-Avatar, Dev-Team) or picks a new one if none has been established.

**When to use it:**
- To check what identity the current session is using
- To force a re-pick if you want a different name
- To debug identity issues (e.g., Discord messages not signing correctly)

**Examples:**

```
/name
```

No arguments. If an identity file exists for this project, it reports the current identity. If not, it picks a new Dev-Name and Dev-Avatar, writes them to the identity file, and announces itself.

**Key detail:** Identity is keyed by project root (via md5 hash), not by process ID. All skills and scripts resolve the same file regardless of process ancestry.

---

### `/ccwork` -- Onboarding Hub

Single entry point for discovering and learning the ccwork kit. Routes to tours, labs, and setup wizards.

**When to use it:**
- When you are new to the kit and want a guided introduction
- To run interactive lab exercises in the ccwork-lab repo
- To configure integrations like Discord

**Examples:**

```
/ccwork                     # Show the overview menu
/ccwork tour                # Full orientation tour
/ccwork tour workflow       # Focused tour of the commit/PR loop
/ccwork tour foundations    # Focused tour of session lifecycle skills
/ccwork lab                 # List available lab exercises
/ccwork lab "First Workflow"  # Start a specific lab
/ccwork setup discord       # Guided Discord configuration wizard
```

**Tours** are interactive -- they run live commands against your actual setup rather than showing canned output. **Labs** are guided exercises where you do the work and the agent coaches. **Setup wizards** walk you through configuration one question at a time.

---

## Workflow Skills

These drive the development loop: issues, commits, reviews, merges.

---

### `/precheck` -- Pre-Commit Gate

The mandatory verification step before any commit. Checks branch/issue compliance, runs validation, launches a code-reviewer sub-agent, fixes high-risk findings, and presents a full checklist. Then stops and waits for approval.

**When to use it:**
- When implementation work is done and you are ready to commit
- Claude runs this proactively when it determines work is complete -- you do not always need to invoke it manually

**Examples:**

```
/precheck
```

No arguments. It runs through six steps: branch/issue check, validation, code review, present the checklist, announce completion via `/vox` (best-effort), and stop. High-risk review findings are fixed automatically before the checklist is shown.

**What happens after:** You respond with `/scp`, `/scpmr`, `/scpmmr`, or an affirmative to approve. Any other response means rework.

---

### `/scp` -- Stage, Commit, Push

Stages specific files, commits with a conventional commit message, pushes to the remote, and creates a PR if one does not exist for the branch.

**When to use it:**
- After `/precheck` has been run and you approve the commit
- As the standard "ship it" command for pushing code

**Examples:**

```
/scp
/scp -m "fix(auth): handle expired tokens gracefully"
```

Without a message, it auto-generates a conventional commit message. With `-m`, it uses your provided message. It always includes `Closes #N` if an issue is linked and adds the Co-Authored-By line.

**Safety checks:** Refuses to commit on protected branches (`main`, `release/*`). Verifies an issue exists. Runs validation if it has not been run recently. Never uses `git add -A`.

---

### `/scpmr` -- Stage, Commit, Push, Create PR/MR

Same as `/scp` but explicitly creates a PR/MR and stops before merging. Use this when you want human review on the PR before merging.

**When to use it:**
- When you want the PR up for review but do not want to merge yet
- When CI needs to pass before you decide to merge

**Examples:**

```
/scpmr
```

No arguments. Runs the full `/scp` workflow, then creates a PR/MR targeting the resolved base branch. Announces the PR via `/vox` (best-effort) and reports the URL. Run `/mmr` later to merge.

---

### `/scpmmr` -- Stage, Commit, Push, Create PR/MR, Merge

The full pipeline in one command: stage, commit, push, create PR/MR, verify CI, and merge with squash.

**When to use it:**
- When the change is straightforward and you want to go from code to merged in one step
- After `/precheck` when you are confident the change is ready

**Examples:**

```
/scpmmr
```

No arguments. Chains `/scp` and `/mmr` together. Announces the merge via `/vox` (best-effort) when done.

**Important:** CI must pass before merge. If CI fails, the skill stops and reports the failure.

---

### `/mmr` -- Merge a PR/MR

Merges an existing pull request or merge request with squash commits, a detailed squash commit message, and source branch deletion.

**When to use it:**
- When a PR/MR is approved and CI has passed, and you want to merge it
- After `/scpmr` when you are ready to complete the merge

**Examples:**

```
/mmr          # Merge the PR/MR for the current branch
/mmr 58       # Merge PR/MR #58 specifically
```

It gathers the PR/MR context, verifies CI status, generates a thorough squash commit message, presents it for approval, and merges on confirmation. Post-merge, it switches to the target branch, pulls, and deletes the local source branch.

**Hard rules:** Never merges with failing CI. Never merges without explicit user approval. Always uses squash.

---

### `/ibm` -- Issue-Branch-PR/MR Workflow Reminder

A quick-reference cheat sheet for the Issue-Branch-PR/MR workflow. Detects the platform, resolves the target branch, and presents the workflow steps with ready-to-run commands.

**When to use it:**
- When you need a reminder of the proper workflow sequence
- At the start of new work to ensure you are following the right steps
- When setting up a new project and need the branch/target resolution logic

**Examples:**

```
/ibm
```

No arguments. It detects the platform, resolves the target branch (caching the result), and presents the three-step workflow: Issue, Branch, PR/MR. It is a reminder, not an executor -- it tells you what to do, not does it for you.

---

### `/review` -- Code Review

Runs a code review using the `code-reviewer` sub-agent on staged changes, a branch diff, a specific file, or a PR/MR.

**When to use it:**
- When you want a standalone code review outside of the `/precheck` flow
- To review a specific file or PR/MR without going through the full pre-commit gate
- For a second opinion on changes before committing

**Examples:**

```
/review              # Review the full branch diff (default)
/review staged       # Review only staged changes
/review branch       # Review branch diff against base
/review src/auth.py  # Review a specific file
/review pr 58        # Review PR #58
```

It gathers the diff and issue context, dispatches a code-reviewer sub-agent, and presents findings organized by severity. This is read-only -- it never edits files or commits.

---

### `/jfail` -- CI Failure Analysis

Fetches and analyzes a failed CI job (GitLab) or workflow run (GitHub) without flooding the context window.

**When to use it:**
- When a CI pipeline or GitHub Actions workflow has failed and you need to understand why
- To quickly triage a failure without manually reading hundreds of lines of CI output

**Examples:**

```
/jfail              # Analyze the most recent failed run on the current branch
/jfail 12345        # Analyze a specific job/run by ID
/jfail latest fix/auth  # Most recent failure on a specific branch
```

It fetches the job output, launches a sub-agent (Haiku, for cost efficiency) to read and classify the failure, and presents a concise summary: classification, error sections, and actionable details (file paths, test names, commands). The full output is saved to `/tmp/<id>.out` for reference.

---

## Communication Skills

These handle interaction with external systems: Discord, Slack, voice, and file viewers.

---

### `/disc` -- Discord Integration

Unified Discord integration for the Oak and Wave server. Handles sending messages, reading channels, creating channels/threads, listing channels, and check-in -- all routed by natural language intent.

**When to use it:**
- To check in on `#roll-call` at session start
- To send status updates or announcements to Discord channels
- To read what other agents or team members have posted
- To create new channels or threads for coordination

**Examples:**

```
/disc                         # Check in to #roll-call (default)
/disc "build is green"        # Send a message to the default channel
/disc send #dev "deployed v2" # Send to a specific channel
/disc read #agent-ops         # Read recent messages from a channel
/disc create #wave-3-status   # Create a new channel
/disc list channels           # List all text channels
/disc thread "session-42" in #remote-sessions  # Create a thread
```

All messages are signed with the agent's Dev-Name, Dev-Avatar, and Dev-Team. Channel names are resolved via the `discord-bot resolve` command. Configuration is read from `~/.claude/discord.json` (see [Discord Configuration](discord-config.md)).

---

### `/ping` -- Post to Slack

Posts a message to the `#ai-dev` Slack channel as this Claude Code agent, using the full agent identity (Dev-Name, Dev-Avatar, Dev-Team).

**When to use it:**
- To communicate with other agents or humans on Slack
- To announce status updates, request feedback, or coordinate work

**Examples:**

```
/ping "build complete, PR is up for review"
/ping "need help with the auth module -- anyone available?"
```

Uses the `slackbot-send` script under the hood. Messages are formatted with Slack mrkdwn syntax. The thread timestamp is saved so subsequent `/pong` reads can follow the conversation.

---

### `/pong` -- Read Slack

Reads recent activity from the `#ai-dev` Slack channel with smart filtering and a priority-based discovery flow.

**When to use it:**
- To check what other agents or team members have posted on Slack
- To read thread replies in an ongoing conversation
- To scan for messages addressed to you

**Examples:**

```
/pong                    # Smart default: checks active thread, then addressed messages, then general history
/pong --limit 10         # Show the last 10 messages
/pong --thread           # Read your active thread
/pong --thread latest    # Read the most recent thread
/pong --grep "deploy"    # Filter messages containing "deploy"
/pong --since 2h         # Messages from the last 2 hours
```

**Default discovery flow (no arguments):** First checks your active thread for new replies, then scans for messages addressed to your Dev-Name or Dev-Team, and finally falls back to general channel history. Stops at the first level that yields results.

---

### `/vox` -- Voice Announcements

Speaks to the user via text-to-speech -- one-way audio for status updates, approvals, and alerts. Uses the Chatterbox API with local fallback.

**When to use it:**
- When approval is needed and the user might not be looking at the screen
- When a long-running task completes (build, test suite, wave execution)
- When errors require the user's attention
- When the user explicitly asked to be notified

**Examples:**

```
/vox "Hey BJ, tests are green and the PR is ready for review"
/vox --voice Emily "Deploy complete, all systems nominal"
/vox --bg "Build finished"              # Background playback
/vox --output /tmp/status.wav "Done"    # Save to file instead of playing
/vox --list-voices                       # Show available voices
```

**Tone:** Write for the ear, not the eye. Brief, conversational, informative. 1-2 sentences max. The default voice is Taylor.

**Best-effort:** If vox fails (no audio backend, network down, no speakers), it continues normally. Never blocks on audio. Use `vox "..." 2>/dev/null || true` in scripts.

**Paralinguistic tags:** Chatterbox supports expressive tags like `[laugh]`, `[sigh]`, `[clear throat]` -- use sparingly for personality.

---

### `/view` -- Open in GUI Viewer

Opens a file or URL in a GUI application for read-only viewing. Launches asynchronously so the chat can continue.

**When to use it:**
- To open a file in an appropriate viewer (PDF in a PDF reader, image in an image viewer)
- To open a URL in the browser
- When you want to see something outside the terminal

**Examples:**

```
/view docs/architecture.pdf
/view screenshots/error.png
/view https://github.com/your-org/your-repo/pull/58
/view "the install script"    # Natural language -- resolves to install.sh
```

It resolves the target (exact path, URL, or description), checks user preferences in memory, selects an appropriate viewer, and opens it. If the preferred app is not installed, it offers to install it and saves the preference for next time.

---

### `/edit` -- Open in GUI Editor

Opens a file or URL in a GUI editor for modification. Like `/view` but prefers full-featured editors over lightweight viewers.

**When to use it:**
- When you want to edit a file in an external application (VS Code, GIMP, LibreOffice)
- When the terminal is not the right tool for the edit (images, spreadsheets, rich documents)

**Examples:**

```
/edit src/main.py                # Opens in VS Code (or configured editor)
/edit assets/logo.png            # Opens in GIMP
/edit docs/report.docx           # Opens in LibreOffice Writer
/edit "the CI config"            # Natural language resolution
```

Checks `$VISUAL` and `$EDITOR` environment variables, then user preferences, then suggests by file type. Falls back to `file-opener` or the system default handler.

---

## Advanced Skills -- Wave Pattern

These enable parallel execution of work across multiple agents. The wave pattern decomposes a large feature into independent sub-issues, groups them into dependency-ordered waves, and executes each wave with isolated worktrees and flight-based conflict avoidance.

The pipeline is: `/assesswaves` (decide) -> `/prepwaves` (plan) -> `/nextwave` (execute).

---

### `/assesswaves` -- Quick Wave Assessment

Quickly assesses whether a set of work items can benefit from parallel agent execution via the wave pattern. This is a decision tool -- it recommends a verdict but does not create issues, plans, or execute anything.

**When to use it:**
- Before `/prepwaves`, to decide whether wave-pattern execution is worth the overhead
- When evaluating a new feature or epic for parallelism potential
- After issues are created, to check for file-level conflicts

**Examples:**

```
/assesswaves #50 #51 #52     # Assess specific issues
/assesswaves 50 51 52        # Same, without # prefix
/assesswaves                  # Describe work items in conversation
```

It gathers work items, launches sub-agents to analyze file impact, builds a conflict matrix, and presents a verdict card: wave-able (yes/no/maybe), suggested waves, risk level, and a recommendation for next steps.

---

### `/prepwaves` -- Plan Execution Waves

Analyzes a master issue and its sub-issues, validates they are ready for spec-driven agent execution, computes dependency-ordered waves, and prepares everything for `/nextwave`.

**When to use it:**
- After `/assesswaves` confirms the work is wave-able
- When you have a master issue (epic) with well-specified sub-issues and want to plan parallel execution
- Before running `/nextwave` for the first time on a set of issues

**Examples:**

```
/prepwaves 111       # Plan waves for master issue #111
/prepwaves #111      # Same, with # prefix
```

It validates the master issue structure, reads each sub-issue and checks for required sections (Changes, Tests, Acceptance Criteria), computes a topological sort for dependency ordering, presents a pre-flight report and wave plan, and waits for approval before persisting.

**Key detail:** `/prepwaves` plans, `/nextwave` executes. Branches are NOT created during prep -- they are created at execution time to avoid staleness.

---

### `/nextwave` -- Execute One Wave

Executes the next pending wave from a plan created by `/prepwaves`. Uses a two-phase approach: planning agents identify file targets, then issues are partitioned into conflict-free flights for safe parallel execution on isolated worktrees.

**When to use it:**
- After `/prepwaves` has created a wave plan
- To execute the next wave in the sequence (one wave per invocation)
- When the previous wave has been merged and you are ready to continue

**Examples:**

```
/nextwave
```

No arguments. It identifies the next pending wave from the task list, runs pre-flight checks, launches planning agents to detect file conflicts, partitions into flights, and executes each flight with isolated worktrees. Between flights, it runs re-validation to ensure merged changes have not invalidated the next flight's plans. After all flights, it runs a design review of the next wave's specs.

**Flow:** Pre-Flight Checks -> Planning Phase -> Flight 1 (execute + merge) -> Re-Validate -> Flight 2 (execute + merge) -> ... -> Design Review -> Wave Complete.

**Key detail:** One wave per invocation. The user controls the pace. Run `/cryo` between waves if compaction is imminent.

---

## See Also

- [Getting Started](getting-started.md) -- hands-on walkthrough of your first session
- [Concepts](concepts.md) -- how the pieces fit together
- [Troubleshooting](troubleshooting.md) -- common failure modes and fixes
- [Discord Configuration](discord-config.md) -- setting up Discord integration
- [README](../README.md) -- full component reference
