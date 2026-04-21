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

### `/man` -- Skill Usage Display

Displays the usage information for any installed skill by reading its SKILL.md frontmatter. A quick reference without loading the full skill into context.

**When to use it:**
- When you need a reminder of a skill's syntax or subcommands
- To list all installed skills and their descriptions
- To check what options a skill supports without invoking it

**Examples:**

```
/man nerf          # Show usage for /nerf
/man scp           # Show usage for /scp
/man               # List all installed skills
```

This is read-only -- it never invokes the target skill. It reads the `usage` frontmatter field for structured output, or interprets the full file when no usage field exists.

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

### `/issue` -- Structured Issue Creation

Creates properly templated and labeled issues from a natural language prompt. Detects the platform (GitHub/GitLab), applies the correct template for the issue type, infers labels, and creates the issue directly.

**When to use it:**
- When you need to create an issue following the project's template and labeling standards
- When starting new work and an issue does not exist yet
- When decomposing work into tracked items

**Examples:**

```
/issue feature add retry logic to the upload endpoint
/issue bug the login form crashes on empty password
/issue chore update dependencies to latest patch versions
/issue docs update the API reference for v2 endpoints
/issue epic redesign the authentication system
/issue                   # Infer from recent conversation context
```

The first word selects the template (feature, bug, chore, docs, epic). If omitted, the type is inferred from the prompt. Issues are created immediately -- the skill does not ask for confirmation since issues are cheap to edit.

**Key detail:** The skill is self-contained -- it carries its own templates rather than depending on CLAUDE.md. Labels follow the `group::value` taxonomy with priority and urgency as orthogonal axes.

---

### `/nerf` -- Context Budget Management

Routes to the `nerf-server` MCP for deterministic context budget control. Manages soft limits (darts), behavior modes, and a scope monitor for tracking token usage over time.

**When to use it:**
- To check your current context usage and dart thresholds
- To adjust the context budget (raise or lower limits)
- To switch behavior modes (more or less aggressive context management)
- To launch a terminal-based scope monitor for real-time token tracking

**Examples:**

```
/nerf                          # Show status (mode, darts, context usage)
/nerf status                   # Same as /nerf
/nerf mode                     # Show current behavior mode
/nerf mode hurt-me-plenty      # Set mode
/nerf darts                    # Show current dart thresholds
/nerf darts 120k 160k 180k    # Set all three thresholds
/nerf 200k                     # Set ouch dart, scale soft/hard proportionally
/nerf scope                    # Launch context monitor in new terminal
```

All operations are handled by the MCP server -- the skill is a thin routing stub that parses input and calls the appropriate MCP tool. Accepts `k` suffix (e.g., `200k` = 200000).

**Modes:** `not-too-rough` (gentle reminders), `hurt-me-plenty` (firm limits), `ultraviolence` (aggressive compaction pressure).

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
/disc thread "session-42" in #agent-ops  # Create a thread
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

## Advanced Skills -- Domain-Driven Design

---

### `/ddd` -- Domain-Driven Design Facilitation

A structured workflow for domain modeling using event storming. Guides you through 8 stages of domain discovery, formalizes the results into a Domain Model document, and hands off to `/devspec create` for Dev Spec generation.

**When to use it:**
- When starting a new project and need to discover the domain model
- When translating business requirements into technical architecture
- When you want a structured domain model to feed into Dev Spec creation

**Examples:**

```
/ddd begin       # Start interactive event storming session
/ddd draft       # Formalize sketchbook into Domain Model document
/ddd accept      # Verify domain model and hand off to Dev Spec creation
/ddd resume      # Resume interrupted event storming session
```

**The pipeline:** `/ddd begin` (8-stage event storming → `docs/SKETCHBOOK.md`) → `/ddd draft` (formalize → `docs/DOMAIN-MODEL.md`) → `/ddd accept` (verify and hand off) → `/devspec create` (generate Dev Spec).

**Event storming stages:** Domain Context → Events (brainstorm) → Events (organize) → Commands → Actors → Policies → Aggregates → Read Models. Progress is checkpointed to the sketchbook after each stage.

**Key detail:** This is a Socratic process — the agent asks probing questions rather than dictating the domain. The best domain models emerge from questioning and challenging assumptions.

---

### `/devspec` -- Interactive Dev Spec Creation

Creates Development Specifications through an interactive, section-by-section workflow. Instead of generating a Dev Spec in one shot, it walks each section collaboratively -- drafting, presenting, and waiting for feedback before moving on. Manages a unified Deliverables Manifest (Tier 1 required defaults, Tier 2 conditional triggers, Tier 3 opt-in) and runs a mechanical finalization checklist. Includes an approval gate and backlog population (upshift) for the full concept-to-execution pipeline.

**When to use it:**
- After `/ddd accept` produces a domain model and you need to create a Dev Spec from it
- When starting a new project and need a structured Dev Spec from a concept doc or verbal description
- When you have an existing Dev Spec and want to verify it meets completeness requirements
- When a finalized Dev Spec needs stakeholder approval before execution
- When an approved Dev Spec needs to be broken into trackable backlog issues

**Examples:**

```
/devspec create       # Start interactive Dev Spec generation
/devspec finalize     # Run the finalization checklist on an existing Dev Spec
/devspec approve      # Approval gate — finalize, summarize, and record approval
/devspec upshift      # Backlog population — create issues from approved Dev Spec
/devspec              # Show help
```

**The pipeline:** `/ddd accept` (domain model) or concept doc or verbal description → `/devspec create` (interactive Dev Spec generation → `docs/<project>-devspec.md`) → `/devspec finalize` (verify completeness) → `/devspec approve` (human approval gate) → `/devspec upshift` (backlog population) → `/prepwaves` (plan execution waves).

**`/devspec create` flow:**
1. Determine input source (DDD domain model, external doc, or verbal description)
2. Walk each Dev Spec section (1-9) interactively -- draft, present, get feedback, iterate
3. After Section 5: walk Tier 1 Deliverables Manifest defaults, confirm or N/A each row
4. Scan for Tier 2 triggers, add conditional rows
5. After Section 8: verify every manifest row has a wave assignment
6. Write the Dev Spec file

**`/devspec finalize` flow:**
Run the Section 7.2 Finalization Checklist mechanically against an existing Dev Spec. Reports pass/fail per item (Tier 1 file paths, Tier 2 triggers, wave assignments, MV-XX coverage, verb-only deliverables, audience-facing docs, DoD references). Summary: "X/7 checks passed. Dev Spec is ready / not ready for approval."

**`/devspec approve` flow:**
1. Run the finalization checklist automatically (rejects if any checks fail)
2. Present a Dev Spec summary: section count, story count, wave count, deliverable count
3. Hard stop: "Approve this Dev Spec? (yes/no)" -- waits for human response
4. On approval: records approval timestamp, approver, and finalization score in Dev Spec metadata
5. On rejection: lists failing items, suggests fixes, stops

**`/devspec upshift` flow:**
1. Verify Dev Spec has approval metadata (`approved: true`)
2. Parse Section 8 (Phased Implementation Plan) for phases, waves, and stories
3. Create one epic issue per phase with Phase DoD as acceptance criteria
4. Create one story issue per story with implementation steps, test procedures, and AC from Dev Spec
5. Create wave master issues linking constituent story issues
6. Report summary: "Created N epics, M stories, P wave master issues"
7. Backfill issue numbers into the Dev Spec (e.g., `### Phase 1: Foundation (#NNN)`)

**Key detail:** Tier 1 deliverables are opt-OUT (must provide "N/A -- because [reason]" to skip). The Deliverables Manifest (Section 5.A) is the single source of truth for all project outputs -- there is no separate Artifact Manifest or Documentation Kit.

---

### `/dod` -- Project Definition of Done Verification

Reads the Deliverables Manifest from the project's Dev Spec (Section 5.A) and mechanically verifies that every deliverable was produced, every test passed, and every artifact exists at its declared file path. Generates a pass/fail verification report and requires human sign-off to close the project. This is the final gate in the SDLC pipeline.

**When to use it:**
- After all implementation waves are complete and the project is ready for final verification
- When you want to confirm that every deliverable in the Dev Spec has been produced
- Before closing the parent epic or transitioning the campaign to the DoD stage
- When stakeholders ask for evidence that all requirements have been met

**Examples:**

```
/dod            # Run the full DoD verification (default)
/dod check      # Same as /dod
```

**Verification categories:**

| Category | What is checked |
|----------|----------------|
| Docs | File exists at declared path, is non-empty |
| Code (binary/package) | File exists, build command succeeds |
| Code (CI/CD) | Pipeline config exists, last CI run passed |
| Code (build system) | Makefile/task runner exists, `make test` succeeds |
| Test (results) | File exists, parse for pass/fail summary |
| Test (coverage) | File exists, parse coverage percentage |
| Test (manual procedures) | File exists, has recorded execution results |
| Trace (VRTM) | VRTM populated, no "Pending" status rows |

**Report format:** Each deliverable is marked V (verified), X (failing), or O (N/A opted out). The report includes a summary count, Global DoD (Section 7) verification, and a final READY/NOT READY verdict.

**Approval flow:**
1. All pass -> "Approve to close the project?"
2. Failures exist -> "Approve anyway, or fix first?"
3. On "fix" -> lists each failure with specific remediation (file paths, commands, Dev Spec sections)
4. On approval -> updates campaign state (if active), suggests closing the epic

**Key detail:** N/A rows with rationale are respected and do not count as failures. Bare "N/A" without explanation is flagged. VRTM completeness is mandatory -- every requirement must be traceable with no "Pending" rows.

---

## Advanced Skills -- Wave Pattern

The wave pattern decomposes work into dependency-ordered waves and executes each wave with lifecycle tracking, dashboard visibility, and an audit trail. It supports three topologies:

- **Parallel** — multiple agents execute independent issues concurrently on isolated worktrees with flight-based conflict avoidance
- **Serial** — single-issue flights execute sequentially with a streamlined fast-path (no worktree isolation, no conflict detection)
- **Mixed** — some waves are parallel, some are serial

The wave pattern is valuable for **tracking and visibility**, not just parallelism. Even fully sequential work benefits from the dashboard, lifecycle management, and git audit trail.

The pipeline is: `/assesswaves` (decide) -> `/prepwaves` (plan) -> `/nextwave` (execute).

---

### `/assesswaves` -- Quick Wave Assessment

Quickly assesses whether a set of work items can benefit from wave-pattern execution (parallel, serial, or mixed). This is a decision tool -- it recommends a topology and verdict but does not create issues, plans, or execute anything.

**When to use it:**
- Before `/prepwaves`, to decide whether wave-pattern execution is worth it
- When evaluating a new feature or epic — even fully sequential work can benefit from wave tracking
- After issues are created, to check for file-level conflicts and determine optimal topology

**Examples:**

```
/assesswaves #50 #51 #52     # Assess specific issues
/assesswaves 50 51 52        # Same, without # prefix
/assesswaves                  # Describe work items in conversation
```

It gathers work items, launches sub-agents to analyze file impact, builds a conflict matrix, and presents a verdict card: wave-able (yes/no/maybe), topology (parallel/serial/mixed), suggested waves, risk level, and a recommendation for next steps.

---

### `/prepwaves` -- Plan Execution Waves

Analyzes a master issue and its sub-issues, validates they are ready for spec-driven agent execution, computes dependency-ordered waves (parallel, serial, or mixed), and prepares everything for `/nextwave`.

**When to use it:**
- After `/assesswaves` confirms the work is wave-able (any topology)
- When you have a master issue (epic) with well-specified sub-issues
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

Executes the next pending wave from a plan created by `/prepwaves`. Automatically selects the right execution mode: for multi-issue flights, planning agents detect file conflicts and agents execute on isolated worktrees. For single-issue flights (serial topology), the fast-path skips conflict detection and worktree isolation.

**When to use it:**
- After `/prepwaves` has created a wave plan (any topology)
- To execute the next wave in the sequence (one wave per invocation)
- When the previous wave has been merged and you are ready to continue

**Examples:**

```
/nextwave
```

No arguments. It identifies the next pending wave from the task list and auto-detects topology. For parallel flights: launches planning agents, detects file conflicts, partitions into flights, executes on isolated worktrees. For serial flights: skips planning and worktree isolation, executes directly. Between flights, it runs re-validation. After all flights, it runs a drift check on the next wave's specs.

**Flow (parallel):** Pre-Flight Checks -> Planning Phase -> Flight 1 (execute + merge) -> Re-Validate -> Flight 2 -> ... -> Drift Check -> Wave Complete.

**Flow (serial):** Pre-Flight Checks -> Flight 1 (execute + merge) -> Flight 2 (execute + merge) -> ... -> Drift Check -> Wave Complete.

**Key detail:** One wave per invocation. The user controls the pace. Run `/cryo` between waves if compaction is imminent.

---

### `/wavemachine` -- Autopilot Wave Loop

Top-level loop that drives `/nextwave` across every pending wave of the current plan, without per-wave human interaction. This is the "fire and forget" mode for wave execution: once started, it continues until the plan is exhausted, a wave fails, or `wave_health_check` trips the circuit breaker.

**When to use it:**
- When a wave plan has multiple pending waves and you trust CI to gate merges (see `wave_ci_trust_level`)
- When you want the full plan executed end-to-end without approving each wave individually
- For dogfood runs on throwaway epics

**Examples:**

```
/wavemachine
```

No arguments. It reads the current wave plan, then iterates: call `/nextwave auto` -> wait for completion -> call `/nextwave auto` again, until no pending waves remain or a circuit breaker fires.

**Key detail:** `/wavemachine` is a thin wrapper; `/nextwave(auto)` is the single-wave primitive and carries all of the planning/merge/reconcile logic. The "auto" mode skips the interactive approval gate that `/nextwave` uses by default -- CI status stands in for human approval. Use the interactive form (`/nextwave` on its own) if you want to inspect each wave before remote state changes.

---

### Agent Architecture -- Orchestrator / Prime / Flight

Wave execution uses three distinct agent roles. Knowing which role is which clarifies the tool distribution, the merge sequencing, and the forensic trail left on disk.

**The three roles:**

- **Orchestrator Agent** -- the top-level Claude Code session that chats with you. It has the `Agent` tool, drives the wave loop directly (whether from `/nextwave` or `/wavemachine`), and is the only agent that can spawn sub-agents in parallel.
- **Prime Agent** -- one sub-agent per wave. Handles pre-wave planning (reads specs, runs `flight_overlap` / `flight_partition`, writes the flight prompts) and post-flight merge/CI/reconcile work. Cannot spawn further sub-agents; returns paths and status tokens only.
- **Flight Agent** -- one sub-agent per issue in a flight. Reads its prompt from a file, implements a single issue in its assigned worktree, runs the mechanical half of `/precheck`, writes results to a file, and returns only a result path plus `PASS|FAIL`.

**Where parallelism lives:** the Orchestrator spawns N Flight Agents in a single tool-use block. Flights are siblings of each other, not grandchildren. Prime is sequential per wave (one pre-wave, one post-flight per flight, one post-wave).

**Filesystem message bus.** Agents communicate by writing files under a namespaced bus root, not by passing content through Orchestrator context:

```
/tmp/wavemachine/{repo-slug}/wave-{N}/
├── plan.md                                 # Prime pre-wave plan
├── merge-report.md                         # Prime post-wave report
├── flight-{M}/
│   ├── merge-report.md                     # Prime post-flight report
│   └── issue-{X}/
│       ├── prompt.md                       # Flight input (written by Prime)
│       ├── results.md.partial              # Flight writes here first
│       ├── results.md                      # atomic rename target
│       └── DONE                            # contents: "PASS" or "FAIL"
```

The bus root is namespaced under `/tmp/wavemachine/` so `wave-cleanup` can safely refuse paths outside that prefix, and `ls /tmp/wavemachine/` enumerates active waves across all repos. The `flight-{M}` level is preserved even when a wave has a single flight -- it keeps forensic archaeology straightforward.

**How `/wavemachine` relates to `/nextwave`.** `/wavemachine` is a thin top-level loop that calls `/nextwave(auto)` once per pending wave. All of the Prime + Flight orchestration lives inside `/nextwave`; `/wavemachine` only decides when to stop (plan exhausted, wave failure, or circuit breaker). The parallelism lives in the Orchestrator's tool-use blocks inside `/nextwave`, not inside `/wavemachine`.

**Why this split exists.** Claude Code sub-agents do not have the `Agent` tool, so nested parallelism is impossible -- the top-level session is the only place N Flights can be spawned concurrently. See `~/.claude/projects/-home-bakerb-sandbox-github-claudecode-workflow/memory/lesson_cc_subagent_tools.md` for the bisect evidence and the design implication. Full architecture rationale is in `~/.claude/projects/-home-bakerb-sandbox-github-claudecode-workflow/memory/decision_wavemachine_v2.md`.

---

## Tools / CLI

### `campaign-status` -- SDLC Campaign Lifecycle CLI

A standalone CLI tool (Python zipapp) for tracking project progress through SDLC stages. Manages stage transitions with gates, deferrals, and generates an HTML dashboard. State is stored in `.sdlc/` and committed to git on every mutation.

**Subcommands:**

| Command | Purpose |
|---------|---------|
| `init <project-name>` | Create `.sdlc/` directory, initialize campaign with 5 stages |
| `stage-start <stage>` | Transition campaign to a new stage (concept/prd/backlog/implementation/dod) |
| `stage-review <stage>` | Mark stage as in-review (concept, prd, dod only) |
| `stage-complete <stage>` | Mark stage as complete (gate passed) |
| `defer <item> --reason <text>` | Defer a deliverable or work item with rationale |
| `show` | Print current campaign state to terminal (read-only) |
| `dashboard-url [--branch <branch>]` | Print the SDLC dashboard viewer URL for this repo |

**Stage progression:** concept -> prd -> backlog -> implementation -> dod. Each stage must be completed before the next can start. Concept, Dev Spec, and DoD have review gates; backlog and implementation go directly from active to complete.

**Examples:**

```
campaign-status init my-project
campaign-status stage-start concept
campaign-status stage-review concept
campaign-status stage-complete concept
campaign-status defer "Advanced analytics" --reason "Phase 2"
campaign-status show
```

---

### `wave-status` -- Wave Execution Lifecycle CLI

A standalone CLI tool (Python zipapp) for tracking wave-pattern execution. See the wave pattern skills above for context on how waves work.

---

### `sdlc-dashboard-viewer` -- Org-Wide SDLC Dashboard

A self-contained HTML+JS dashboard viewer deployed once per GitHub org via Pages. Opens in a browser and fetches campaign and wave state JSON from the repo's raw URL, renders the dashboard client-side, and polls for updates every 3-5 seconds. Zero per-project setup -- any project with a `.sdlc/` directory is immediately visible.

**Usage:**

Open in a browser with URL parameters:

```
https://<org>.github.io/sdlc-dashboard/?repo=<org>/<repo>&branch=<branch>
```

Or generate the URL from the CLI:

```bash
campaign-status dashboard-url
campaign-status dashboard-url --branch feature/42-work
```

**Features:**

- Campaign progress rail (5-stage pipeline visualization)
- Wave/flight detail view during implementation
- Auto-refresh: polls raw URLs every 3-5 seconds
- Offline indicator: shows "stale" badge if fetch fails for >30 seconds
- Private repo support: one-time PAT paste stored in localStorage
- Responsive: works on mobile for quick status checks
- Cyberpunk theme: consistent with wave-status panel aesthetic
- Self-contained: no external dependencies, no build step

---

## See Also

- [Getting Started](getting-started.md) -- hands-on walkthrough of your first session
- [Concepts](concepts.md) -- how the pieces fit together
- [Troubleshooting](troubleshooting.md) -- common failure modes and fixes
- [Discord Configuration](discord-config.md) -- setting up Discord integration
- [README](../README.md) -- full component reference
