# Skill Reference

Complete reference for all skills in the ccwork kit. Each entry covers what the skill does, when to use it, example invocations, and common options.

For a conceptual overview of how skills fit into the kit architecture, see [Concepts](concepts.md#skill-taxonomy). For hands-on walkthroughs, run `/ccwork tour`.

---

## Foundation Skills

These manage the agent's own state and context. Use them at session boundaries and during maintenance.

---

### `/engage` -- Load Rules and Restore Context

Reads CLAUDE.md, confirms the mandatory development rules are loaded, restores any active plan, and reports the agent's ready state. This is the single entry point for resuming work.

**When to use it:**
- At the start of every new session
- After context compaction (when Claude's context window fills up and gets summarized)
- Whenever you are unsure whether Claude still has the project rules loaded

**Examples:**

```
/engage
```

No arguments -- it reads the environment and reports what it finds. Memory files are loaded automatically by the harness; `/engage` reads CLAUDE.md, summarizes the mandatory rules, surfaces any pending work, and ends with the current git branch and a prompt for direction.

**State preservation:** There is no explicit "freeze before compact" step. Durable facts are captured in memory files (plain file writes to the project's memory directory); working state lives in plan files (`.claude/plans/`). The `PostCompact` hook reminds the agent to re-read CLAUDE.md after compaction.

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

**Key detail:** Identity is stored at `<project_root>/.claude/agent-identity.json` (reboot-durable, gitignored), keyed by project root, not process ID. All skills and scripts resolve the same file regardless of process ancestry. A legacy `/tmp/claude-agent-<md5>.json` fallback is read during the transition window.

---

### `/reseed` -- Guided Context-Window Reduction

The careful, mid-flight context reduction: authors a detailed seed, then you `/clear` and revive from it. There is no decision step — seed-and-clear is the right call whenever work is mid-flight. For a cheap summarize where little is at stake, use `/compact` directly instead.

**When to use it:**
- When the context window is getting full and you are mid-task
- Before a deliberate `/clear`, to protect valuable volatile state and scoped operating decisions
- Whenever you would otherwise hand-type a long "here is where we are" revival prompt

**Examples:**

```
/reseed
```

No arguments. It authors the seed (pointers to durable state + volatile working-state + the conversation-only operating decisions that have no durable home, each carried with its scope **and** live status), then hands you the exact `/clear`-and-revive follow-up.

**Why not just `/compact`?** Measured on the same transcript and oracle, `/compact` scores ~0.72 recall / ~0.45–0.60 fidelity versus tuned `/reseed`'s ~0.95 / ~0.96 — it drops ~a quarter of the must-capture content and roughly half the scope-fidelity, flattening exactly the scoped grants that mislead a revived agent. See [`reseed-prompt-improvement.md`](reseed-prompt-improvement.md) for the methodology behind the reseed authoring rules and the full comparison.

**The kernel:** a good seed **points at durable artifacts and carries only volatile working-state** -- branch, uncommitted files, the immediate next action, open threads, and communication nuance. It never duplicates what is on disk or what auto-reloads at session start (CLAUDE.md, the memory index, hooks).

**Durability caveat:** `/tmp` is reboot-wiped, so a `/tmp` seed is fine for same-session readback but not across a reboot. If the reduction might span a reboot, the skill writes the seed to a durable path under `.claude/` instead.

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

### `/multithread` -- Parallel Discussion Over Independent Items

Converts a serial walk through N independent questions, design holes, or review comments into a concurrent discussion: lay out all threads at once (each with a proposed take), the human batch-answers any subset in one turn, sorted threads drop out, open ones iterate — until dry. Minimizes human round-trips the same way wave-pool minimizes wall-clock.

**When to use it:**
- Working through an open-questions block in a Dev Spec (e.g. a §5.N section with 5–10 design holes)
- Triaging a batch of PR review comments or design feedback
- Any situation with N independent decisions where N serial round-trips would be wasteful

**Examples:**

```
/multithread docs/agent-smith-devspec.md §5.N   # Walk an open-questions section
/multithread the open questions                  # Infer from conversation context
/multithread PR #813 review comments             # Work through PR feedback
/multithread these: [auth model, rate limiting, error format]  # Ad-hoc list
/multithread                                     # Infer from most recent list in conversation
```

**The pattern:**
1. Enumerate the source into labeled threads `T1…TN` — split items that are two questions, merge items that are one
2. Annotate dependencies (`T3 depends: T1`) before presenting — the whole edge over a serial walk is declaring couplings on turn one, not discovering them midway
3. Present all threads at once with a **mandatory take** per thread (reacting is faster than composing)
4. After the human's batch-answer, report explicitly: `sorted: T1, T3, T7 · still open: T2, T5, T6`
5. Re-present only open threads with takes updated by resolved ones — loop until dry
6. Emit a **Decision Record** (`label → decision → rationale`) formatted for the destination (Dev Spec ledger entries, PR reply table, plain list)

**Wave taxonomy:** multithread is wave-pool for dialogue. The unit is a discussion thread; the convergence checkpoint is the inter-wave barrier; loop-until-dry is the same tail-catching discipline wave-pool workflows use.

**When NOT to use it:** Genuinely sequential decisions (each answer reshapes the next question), a single decision (nothing to parallelize), or tightly-coupled items where one choice cascades and rewrites all the others. The independence test: *Would resolving A change what B even asks?* If yes → serial walk. If no → multithread.

---

## Communication Skills

These handle interaction with external systems: Discord, voice, and file viewers.

---

### `/disc` -- Discord Integration

Unified Discord integration for the Oak and Wave server. Handles sending messages, reading channels, creating channels/threads, listing channels, and check-in -- all routed by natural language intent.

**Two surfaces, not one.** Most intents are `disc-server` MCP tool calls. **`forward` and `directmsg` are `discord-watcher` CLI subcommands** — there is no `disc_forward` MCP tool and never has been. An intent having no `disc_*` tool is the expected shape for watcher-owned features.

**When to use it:**
- To check in on `#roll-call` at session start
- To send status updates or announcements to Discord channels
- To read what other agents or team members have posted
- To create new channels or threads for coordination
- To route your doorbells to another agent while you are away, or to reach one whose doorbells are forwarded
- To arm the **channels-free doorbell** when the session has no `--channels` sink — the only way to hear Discord at all when `Monitor` is gated off (third-party provider, gateway auth, or telemetry disabled)

**Examples:**

```
/disc                         # Check in to #roll-call (default)
/disc "build is green"        # Send a message to the default channel
/disc send #dev "deployed v2" # Send to a specific channel
/disc read #agent-ops         # Read recent messages from a channel
/disc create #wave-3-status   # Create a new channel
/disc list channels           # List all text channels
/disc thread "session-42" in #agent-ops  # Create a thread

/disc forward babelfish                  # Route MY doorbells to agent babelfish
/disc forward babelfish --exclude dev,ci # ...except doorbells from #dev or #ci
/disc forward off                        # Clear the rule
/disc dm treebeard "PR #12 is red"       # Direct message, bypasses forwarding

/disc doorbell                           # Arm the channels-free doorbell (no --channels)
```

**`<agent>` is an agent, never a channel** — a Dev-Name or Dev-Team token. Passing a channel silently "succeeds" and then fails at every delivery. `--exclude` names channels/authors whose doorbells **stay local**, not recipients to omit.

To reach a forwarded agent from Discord itself, a user sends `//dm @<dev-name|dev-team> <message>` — both the target and a non-empty body are required.

All messages are signed with the agent's Dev-Name, Dev-Avatar, and Dev-Team. Channel names are resolved via `mcp__disc-server__disc_resolve`. Configuration is read from `~/.claude/discord.json` (see [Discord Configuration](discord-config.md)).

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

**Best-effort:** If vox fails (no audio backend, network down, no speakers), it continues normally. Never blocks on audio. In scripts, **pipe the message — never pass it as a double-quoted argument** (#942), because backticks and `$(...)` in a double-quoted shell string are command substitution and run before vox sees the text:

```bash
vox 2>/dev/null <<'EOF' || true
Build finished
EOF
```

For anything filled in at invocation time, write the text with the `Write` tool and feed the file on **stdin** — `vox < /tmp/announcement.md`. **`vox` takes no path argument**: `vox /tmp/announcement.md` synthesises the literal path and exits 0. A quoted heredoc stops substitution but not *termination*, so a body containing a line equal to the delimiter truncates and leaks the remainder to the shell (#1136). Full rationale in `/vox`.

(The `/vox "..."` examples above are slash-command syntax typed into Claude Code, not shell — they are not affected.)

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

### `/muse` -- Conception and Shaping (the front door)

The conversation that happens *before* anyone knows what they're building. Takes an ill-defined itch and gets it to `/ddd`-ready in two movements: **conception** (find the real problem, the Designer confirms it) and **shaping** (propose candidate solutions, record what was decided and why). Writes `docs/SKETCHBOOK.md`, which `/ddd begin` then extends.

**When to use it:**
- When the problem itself is still fuzzy — "something's off but I can't name it"
- When you have a feature request and suspect the real pain is somewhere else
- Before `/ddd`, always: event storming an undecided identity models a thing nobody chose

**Examples:**

```
/muse            # start the conversation; there are no subcommands
```

**The two movements:** conception (four ADD drivers elicited invisibly → the Designer explicitly confirms the problem statement) → shaping (candidate shapes proposed and pressed → numbered, attributed, reasoned decisions + an open-questions register). One continuous conversation; the movements are never announced to the Designer.

**How it ends:** when every remaining open question is *behavioral* ("what happens when X fails?") rather than *definitional* ("what is this thing?"). Behavioral questions are exactly what `/ddd` answers; definitional ones still open means shaping isn't finished.

**Key detail:** the Designer holds the lock. `/muse` never self-confirms the problem statement, and a later re-see that amends it must go back for explicit re-confirmation. The decision ledger is append-only — a decision found wrong is superseded by a new numbered decision, never edited away, because the correction is meaningless without the thing it corrected.

---

### `/ddd` -- Domain-Driven Design Facilitation

A structured workflow for domain modeling using event storming. Guides you through 8 stages of domain discovery, formalizes the results into a Domain Model document, and hands off to `/devspec create` for Dev Spec generation.

**When to use it:**
- After `/muse` has settled the problem and shaped a solution (the normal path)
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

**The pipeline:** `/muse` (conception + shaping → `docs/SKETCHBOOK.md`) → `/ddd begin` (8-stage event storming, **appended to the same sketchbook**) → `/ddd draft` (formalize → `docs/DOMAIN-MODEL.md`) → `/ddd accept` (verify and hand off) → `/devspec create` (generate Dev Spec).

**Sketchbook ownership:** `/ddd begin` resolves the sketchbook path first and **appends** when it already exists — it never overwrites `/muse`'s problem statement, decision ledger, or open questions. One document, growing across stages, each adding resolution to the last.

**Event storming stages:** Domain Context → Events (brainstorm) → Events (organize) → Commands → Actors → Policies → Aggregates → Read Models. Progress is checkpointed to the sketchbook after each stage.

**Key detail:** This is a Socratic process — the agent asks probing questions rather than dictating the domain. The best domain models emerge from questioning and challenging assumptions.

---

### `/devspec` -- Interactive Dev Spec Creation

Creates Development Specifications through an interactive, section-by-section workflow. Instead of generating a Dev Spec in one shot, it walks each section collaboratively -- drafting, presenting, and waiting for feedback before moving on. Appends a Decision-Ledger comment to the Plan tracking issue after each section the Pair approves. Manages a unified Deliverables Manifest (Tier 1 required defaults, Tier 2 conditional triggers, Tier 3 opt-in) and runs a mechanical finalization checklist. Includes an approval gate and backlog population (upshift) for the full concept-to-execution pipeline.

**Pipeline taxonomy (locked 2026-04-26):** Plan (tracking issue, `type::plan`) → Phase (internal to `phases-waves.json`) → Wave (internal to `phases-waves.json`) → Story (issue with `type::feature`/`type::bug`/`type::chore`/`type::docs`). Epic is an optional PM-layer label only; the pipeline never reads it.

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

**The pipeline:** `/issue plan` (creates Plan tracking issue) → `/ddd accept` (domain model) or concept doc or verbal description → `/devspec create` (interactive Dev Spec generation → `docs/<project>-devspec.md`; appends ledger comments to Plan issue) → `/devspec finalize` (verify completeness) → `/devspec approve` (human approval gate) → `/devspec upshift` (backlog population + `phases-waves.json`) → `/prepwaves` (plan execution waves).

**`/devspec create` flow:**
1. Resolve the Plan tracking issue number (prerequisite — run `/issue plan` first if none exists)
2. Determine input source (DDD domain model, external doc, or verbal description)
3. Walk each Dev Spec section (1-9) interactively -- draft, present, get feedback, iterate
4. After each section the Pair approves, append a `[ledger D-NNN]` comment to the Plan issue via `pr_comment` (schema per Dev Spec §5.2.1: source, Decision, Rationale, signature)
5. After Section 5: walk Tier 1 Deliverables Manifest defaults, confirm or N/A each row
6. Scan for Tier 2 triggers, add conditional rows
7. After Section 8: verify every manifest row has a wave assignment
8. Write the Dev Spec file; post a reference comment on the Plan issue

**`/devspec finalize` flow:**
Run the Section 7.2 Finalization Checklist mechanically against an existing Dev Spec. Reports pass/fail per item (Tier 1 file paths, Tier 2 triggers, wave assignments, MV-XX coverage, verb-only deliverables, audience-facing docs, DoD references). Summary: "X/7 checks passed. Dev Spec is ready / not ready for approval."

**`/devspec approve` flow:**
1. Run the finalization checklist automatically (rejects if any checks fail)
2. Present a Dev Spec summary: section count, Story count, Wave count, deliverable count
3. Hard stop: "Approve this Dev Spec? (yes/no)" -- waits for human response
4. On approval: records approval timestamp, approver, and finalization score in Dev Spec metadata; appends a final `[ledger D-NNN]` entry to the Plan issue recording the approval
5. On rejection: lists failing items, suggests fixes, stops

**`/devspec upshift` flow:**
1. Verify Dev Spec has approval metadata (`approved: true`)
2. Resolve the Plan issue number (the `plan_id`)
3. Parse Section 8 (Phased Implementation Plan) for phases, waves, and stories
4. Create one Story issue per Story with implementation steps, test procedures, and AC from Dev Spec; each body has a Metadata block citing Plan / Phase / Wave / Depends on
5. Optionally create a PM-layer Epic parent tracker (`type::epic`) if the Pair requests one; apply `epic::<N>` labels to the Stories. This is ignored by the pipeline.
6. Write `phases-waves.json` at `.claude/status/phases-waves.json` with `plan_id`, per-Story `issue`, and per-Story `depends_on` (possibly empty `[]`)
7. Backfill Story numbers into the Dev Spec (`#### Story 3.4: ... (#515)`) and into the Plan issue's Phases checklist
8. Report summary and post it as a plain comment on the Plan issue

**Key detail:** Tier 1 deliverables are opt-OUT (must provide "N/A -- because [reason]" to skip). The Deliverables Manifest (Section 5.A) is the single source of truth for all project outputs -- there is no separate Artifact Manifest or Documentation Kit. `phases-waves.json` uses `plan_id` exclusively — the legacy `epic_id` field is retired.

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

Executes the next pending wave by launching a single deterministic **Dynamic Workflow** (`per-wave-workflow.js`) — the §3 spine: rehydrate prior state -> dynamic flight loop (parallel flights -> reconcile) -> trust gate -> promote to the protected branch. Control flow is JS, not LLM orchestration; agents are invoked only for the steps that need judgment (flight implementation, reconcile, gate review).

**When to use it:**
- After `/prepwaves` has created a wave plan (any topology)
- To execute the next wave in the sequence (one wave per invocation)
- When the previous wave has been promoted and you are ready to continue

**Examples:**

```
/nextwave
```

Launches one per-wave Workflow for the next pending wave and returns its verdict `{ gate, promoted, ... }`. The flight loop is dynamic — a dependency that surfaces mid-wave (reported by reconcile as `needs_rework`) re-opens the issue as the next group, with closed legal exits bounding non-convergence. In `interactive` mode the Workflow stops at a clean gate for the human to route the kahuna->protected merge; in `auto` it promotes when the trust gate passes.

**Key detail:** One wave per invocation, run as a background Workflow with `/workflows` observability and within-session resume. Source of truth: `skills/nextwave/SKILL.md` + `SEAMS.md`.

---

### `/wavemachine` -- Campaign Driver

Drives the campaign loop — one per-wave Workflow per pending wave — advancing ONLY on gate `PASS` **and** `promoted` (a clean gate that did not land on the protected branch HOLDs, never silently "succeeds"). The loop runs in the main session with closed legal exits; auto-vs-interactive is a one-line advance-vs-wait branch. Cold-start rehydrate prunes already-promoted waves.

**When to use it:**
- When a wave plan has multiple pending waves and you want the full plan executed end-to-end
- For walk-away campaigns (`auto`) or review-between-waves (`interactive`)

**Examples:**

```
/wavemachine
```

Reads the approved phase/wave plan, then iterates: launch the next wave's per-wave Workflow -> read its verdict -> advance on PASS-and-promoted (or STOP for the human in `interactive`). Continues until all waves are promoted (success) or a closed exit fires (`wave-hold`, `wave-breaker`, `runaway`, `cost`).

**Key detail:** The campaign loop is thin — all wave-internal work (flights, reconcile, gate, promotion) lives in the per-wave Workflow, billed off the main-session window. Per-wave handoff is a single tool-use boundary (no inter-wave narration). Source of truth: `skills/wavemachine/SKILL.md`.

---

### Agent Architecture -- the per-wave Dynamic Workflow

Wave execution is a deterministic **Dynamic Workflow** (`skills/nextwave/per-wave-workflow.js`, bundled to `per-wave-workflow.bundled.js`). The control flow -- the loop, the closed legal exits, the dynamic re-plan, the trust-gate fan-out -- is **JavaScript**, not an LLM. Agents are still used, but only for the steps that genuinely need judgment (implementing an issue, reconciling a merge, reviewing a diff); everything *between* them (sequencing, exits, aggregation) is code. State flows through schema-validated Workflow return values plus durable **wave-status** (`<target>/.claude/status/`) -- the legacy filesystem "wavebus" is retired.

**The spine (`docs/wavemachine-workflows-migration.md` §3).** One Workflow runs one wave, top to bottom:

1. **Rehydrate** (§3.3) -- seed loop state from durable wave-status so a killed wave resumes where it stopped (idempotent worktree re-attach, never `-b`).
2. **Dynamic flight loop** (§3.1) -- each iteration:
   - a **plan** `agent()` (judgment) picks the next group of still-pending issues from current state;
   - the group's issues run as **parallel flight `agent()`s** -- each in its own pre-created durable worktree (`<target>/.claude/.worktrees/wave-<id>/issue-<n>`), implementing one issue, running the mechanical half of `/precheck`, returning a schema-validated result (never pushing -- reconcile owns the merge);
   - a **reconcile** `agent()` (the only cross-flight view) runs `commutativity_verify` (pairwise, to prove the composed diff is safe to land as one), merges the group into the kahuna branch, resolves cross-flight interface breaks, and reports surfaced dependencies as `needs_rework` -- which re-open and re-schedule in a later group. Closed legal exits: `success` / `runaway` / `thrash` / `cost` / `impasse` / per-issue breaker / `reconcile-blocked`.
3. **Trust gate** (§3.4) -- only on the clean-success exit. Opens the kahuna→protected **draft PR first**, then four signals run in parallel and aggregate to PASS/HOLD: `commutativity_verify`, CI on the MR merge-result pipeline, `code-reviewer` on the kahuna-vs-protected diff, and trivy. Any signal's error is a conservative HOLD, never a silent PASS.
4. **Promote** -- on PASS in `auto` mode, mark the draft PR ready and merge it (kahuna→protected); `interactive` mode returns the verdict for a human to route. HOLD returns the failing signals.

**Where agents live vs. where code lives.** The `agent()` calls -- plan, flight, reconcile, and the gate's review signal -- are the judgment seams (all FILLED; contracts in `skills/nextwave/SEAMS.md`, #686/#687/#688). The Workflow runtime itself does the parallel fan-out (`parallel()` / `pipeline()`), so there is no "Orchestrator agent" spawning siblings -- the determinism that used to be an LLM driving a loop is now the JS engine.

**How `/wavemachine` relates to `/nextwave`.** `/nextwave` executes **one** wave via the Workflow above. `/wavemachine` is the **campaign driver**: a thin loop (in the skill / main session, since a Workflow cannot pause for human input) that launches one per-wave Workflow per pending wave and routes on its verdict -- advance only on `PASS` **and** promoted-to-protected, otherwise HOLD. The judgment is not in the driver; it is in the `agent()` calls inside each wave. Authoritative sources: `docs/wavemachine-workflows-migration.md` §3 and §5, `skills/{wavemachine,nextwave}/SKILL.md`, `skills/nextwave/SEAMS.md`.

**Historical note.** The legacy engine was an LLM **Orchestrator** agent driving the loop with the `Agent` tool, a **Prime** sub-agent per wave, **Flight** sub-agents per issue, and a `/tmp/wavemachine/` filesystem message bus. It was retired in the #691 cutover (epic #692); the migration was driven by the determinism + reliability wins (control flow as code, schema-validated returns, within-session resume) documented in `docs/wavemachine-workflows-migration.md`. The sub-agent tool-distribution constraint that shaped the old design (`lesson_cc_subagent_tools` -- sub-agents lack the `Agent` tool, so only the top level could fan out) is now moot: the Workflow runtime owns the fan-out.

---

### `/sdlc` -- SDLC Workflow Tools

Routes to sdlc-server MCP tools for work item creation and branch/PR compliance checking.

**When to use it:**
- To create work items (epics, stories, bugs, chores) via MCP instead of directly calling `gh`/`glab`
- To check issue/branch/PR workflow compliance for the current branch

**Examples:**

```
/sdlc work_item feature "Add retry logic to upload endpoint"
/sdlc ibm
```

All operations are handled by MCP tools (`work_item`, `ibm`). Platform detection (GitHub vs GitLab) is automatic.

---

### `/wave` -- Wave-Pattern Status

Shows the current wave-pattern execution status for the project via the `wave_show` MCP tool.

**When to use it:**
- To check which wave is currently active
- To see the overall progress of a wave plan
- To verify wave state after a merge or failure

**Examples:**

```
/wave            # Show wave-pattern status
/wave status     # Same as /wave
```

Read-only. Calls `wave_show` and formats the result.

---

## Troubleshooting Skills

These help diagnose and record incidents using the WTF flight recorder (backed by `wtf-server` MCP).

---

### `/wtf` -- Start Troubleshooting Session

Launches the WTF flight recorder for a new troubleshooting incident. Archives any prior incident, prompts for an optional title, then enters flight recorder mode where observations, theories, and corrective actions are journaled automatically.

**When to use it:**
- When something is broken and you want structured incident tracking
- When you need to hand off a debugging session with full context
- When you want automatic journaling of your diagnostic tool calls

**Examples:**

```
/wtf                          # Start a new troubleshooting session
/wtf record "DNS is flaky"   # Shorthand for /wtf now "DNS is flaky"
```

Archives the prior incident (if any) via `wtf_freshell`, then enters recording mode. All subsequent tool calls and observations are captured until `/wtf imout`.

---

### `/wtf happened` -- Incident Timeline

Retrieves a distilled timeline of the current troubleshooting incident and generates a runbook skeleton.

**When to use it:**
- After a troubleshooting session, to review what happened
- To generate a runbook from the incident for future reference
- To share context with another agent or human

**Examples:**

```
/wtf happened        # Summary timeline (max 50 lines)
/wtf happened full   # Full timeline, no truncation
```

Returns a structured timeline of observations, theories, and actions taken during the incident.

---

### `/wtf now` -- Record Manual Journal Entry

Adds a manual observation to the WTF flight recorder journal.

**When to use it:**
- To record an observation that isn't captured automatically (manual checks, external findings)
- To log a theory or hypothesis during debugging
- To note something for the timeline that didn't come from a tool call

**Examples:**

```
/wtf now the DNS resolver is returning stale records
/wtf now "checked nginx logs — 502s started at 14:32"
/wtf now theory: might be connection pool exhaustion
```

The entry is stored as a crafted (intentional) record. Classification is handled by the background classifier.

---

### `/wtf imout` -- Suspend Troubleshooting Session

Stops recording but preserves all captured data for later analysis via `/wtf happened`.

**When to use it:**
- When debugging is paused but not resolved
- When handing off to another session or agent
- When you want to stop automatic capture but keep the incident data

**Examples:**

```
/wtf imout
```

Does NOT delete captured data. The suspended incident remains viewable with `/wtf happened`. Starting a new `/wtf` session creates a new incident; the suspended one stays archived.

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

- [Cheat Sheet](cheatsheet.md) -- one-page skill + MCP tool quick reference
- [Getting Started](getting-started.md) -- hands-on walkthrough of your first session
- [Concepts](concepts.md) -- how the pieces fit together
- [Troubleshooting](troubleshooting.md) -- common failure modes and fixes
- [Discord Configuration](discord-config.md) -- setting up Discord integration
- [README](../README.md) -- full component reference
