# SDLC MCP Server — Domain Discovery Sketchbook

## Stage 1: Domain Context

**Project:** mcp-server-sdlc
**Description:** MCP server that orchestrates an SDLC product creation pipeline. Two-fold purpose: (1) guide designers/developers (AI and human) through a standardized process yielding standardized results, and (2) provide status via easy-to-ingest data files and dashboards.

**Scope:**
- **Included:** Replicate the existing PoC skills-based implementation as MCP tools. The existing pipeline spans: `/ddd` (concept) → `/prd` (PRD creation/approval/upshift) → `/prepwaves` (wave planning) → `/nextwave` (wave execution) → `/dod` (verification). Supporting CLIs: `campaign-status` (stage tracking), `wave-status` (flight execution). Dashboard: `sdlc-dashboard` viewer.
- **Excluded:** TBD — need to clarify what stays as skills vs. moves to MCP.

**Actors:**
- The Pair (Agent + Human working as one unit — the fundamental collaboration unit)
- Dashboard viewers (humans monitoring pipeline progress)
- CI systems (may trigger or be triggered by pipeline stages)
- Org admins (manage process packs)

**Core Problem:** Token usage and maintainability. Skills are full markdown documents loaded into the context window (500+ lines each). Chaining 5+ skills through a pipeline costs thousands of tokens per invocation. Changes require editing markdown templates and reinstalling. An MCP server moves logic server-side — compact tool schemas in context, heavy lifting on the server.

**Prior art:** mcp-server-nerf followed this same skills→MCP migration pattern successfully.

### Design Evolution (during Stage 1 discussion)

**D-01: Content-agnostic process engine.** The MCP does NOT understand domain content (domain models, PRDs, code). It understands *process* — which stage you're in, what artifacts are expected, what gate criteria must pass. It's a configurable process advisor and enforcer.

**D-02: Prompt generator pattern.** The MCP returns guidance prompts to the Pair (Agent + Human). "Choose your own adventure" — the MCP offers options, the Pair picks, the MCP returns stage-appropriate guidance. The Pair does the actual work locally.

**D-03: Process Packs.** The process definition is data, not code. A "Process Pack" is a directory containing:
- `process.yml` — stage definitions, ordering, gate criteria (required vs encouraged tiers)
- `prompts/` — guidance text per stage (markdown)
- `templates/` — output templates (PRD, domain model, issue, etc.)
- `gates/` — validation criteria per stage (what files/sections must exist)

Packs can be cloned from a git repo for org-wide central management and versioning. Ship v1 with a default pack (our DDD/wave process) but design the pack interface from day one.

**D-04: Gate criteria tiers.** Gate checks have two tiers:
- **Required** — must pass to advance (hard block)
- **Encouraged** — nudged but skippable with rationale (soft guardrail)

**D-05: Filesystem access via git remote.** The MCP reads project state from GitHub/GitLab API, not local filesystem. This enforces "origin must be current" discipline and gives the MCP access without filesystem permissions.

**D-06: Wave tools as parallel namespace.** Wave-pattern execution lives in the same MCP but as standalone tools usable both within a pipeline (implementation stage) and independently (ad-hoc parallel work).

**D-07: MCP owns lifecycle and state.** The MCP is the single source of truth for pipeline state. Dashboards read from it — no separate status files. Replaces `campaign-status` CLI + `.sdlc/` files.

### Revised Scope

- **Included:** Process engine, prompt generation, gate validation, pipeline state management, dashboard data API, wave-pattern execution tools, process pack loading (local dir or git clone)
- **Excluded:** Content understanding (the MCP never parses the *meaning* of a domain model or PRD — just checks structural expectations)
- **Actors:** The Pair (Agent + Human as one unit), Dashboard viewers, CI systems, Org admins (manage process packs)

## Stage 2: Events (Brainstorm)

Raw event dump — unordered. Sourced from design discussion + mining all 6 existing SDLC skills (~90 specific events collapsed into 17 abstract events).

### Abstract Domain Events

1. **Campaign Started** — a new SDLC campaign is created for a project
2. **Process Pack Loaded** — the process definition (stages, prompts, gates, templates) is loaded from a local dir or git repo
3. **Stage Entered** — the Pair begins work on a pipeline stage (concept, PRD, backlog, implementation, DoD)
4. **Stage Completed** — a pipeline stage passes its gate and the Pair moves on
5. **Stage Skipped** — the Pair explicitly skips an entire stage (e.g., skip concept for a prototype)
6. **Gate Check Requested** — the Pair asks the MCP to validate the current stage's outputs
7. **Gate Check Passed** — all required gate criteria are met (encouraged items may be skipped)
8. **Gate Check Failed** — one or more required gate criteria are not met
9. **Gate Overridden** — the Pair pushes past a failing gate with explicit acknowledgment and rationale
10. **Artifact Produced** — a deliverable file was created or updated (PRD, domain model, test results, etc.)
11. **Artifact Verified** — a deliverable was checked and confirmed to meet structural expectations
12. **Foundation Fault Detected** — a defect from a prior stage is discovered during a later stage (e.g., design flaw found during implementation)
13. **Rework Started** — the campaign rewinds to an earlier stage to fix a foundation fault (target stage tracked)
14. **Critical Stoppage** — something went seriously wrong and work cannot continue
15. **Blocker Encountered** — work is on hold waiting for an external dependency or condition (campaign enters blocked state)
16. **Campaign Unblocked** — the blocking condition is resolved and work can resume
17. **Campaign Completed** — all stages are done, DoD is approved, project is closed

### Design Notes

- These 17 events can represent everything the ~90 skill-specific events covered
- The specifics (e.g., "Tier 2 Trigger Fired", "Planning Agent Launched", "Flight Started") become implementation details within stages, not events the MCP tracks at the pipeline level
- Wave execution events (flights, agents, merges) will be specified separately — the wave system is a candidate for detailed specification within the implementation stage
- Gate criteria details (what exactly is checked) live in the Process Pack, not in the event model
- "Foundation Fault Detected" names the case where the Pair is stuck in implementation because of a design error that needs to be addressed upstream
- "Gate Overridden" captures rationale for audit trail — "yes, we know DM-04 is missing, shipping anyway because X"
- "Blocker Encountered" / "Campaign Unblocked" are state transitions — the dashboard should reflect blocked status

## Stage 3: Events Timeline

### Phase: Setup
| # | Event | Notes |
|---|-------|-------|
| E-01 | Campaign Started | Creates campaign state, assigns project name |
| E-02 | Process Pack Loaded | Configures stages, prompts, gates, templates. Pack from local dir or git clone. |

### Phase: Stage Loop (repeats for each pipeline stage)
| # | Event | Notes |
|---|-------|-------|
| E-03 | Stage Entered | First stage from pack (e.g., concept). Repeats per stage. |
| E-04 | Artifact Produced | Declared by the Pair, recorded by MCP, queryable via status. Triggers no immediate action — MCP is a ledger, not a nanny. |
| E-05 | Gate Check Requested | Pair asks MCP to validate current stage outputs. |
| E-11 | Artifact Verified | Sub-event of gate check. MCP verifies each expected artifact structurally. Emitted per-artifact by the gate check, not by the Pair directly. All must pass for E-06. |
| E-06 | Gate Check Passed | All required artifacts verified, all required criteria met. Triggers E-07. Encouraged items may be skipped. |
| E-07 | Stage Completed | Stage is done, next stage becomes available. |
| E-08 | Gate Check Failed | One or more required criteria/artifacts not met. Pair stays in current stage. |
| E-09 | Gate Overridden | Pair pushes past failure with explicit rationale. Triggers E-07. Rationale recorded for audit trail. |
| E-10 | Stage Skipped | Pair skips entire stage with acknowledgment. Next stage becomes available. |

### Phase: Exception (can fire from any stage)
| # | Event | Notes |
|---|-------|-------|
| E-12 | Foundation Fault Detected | Design defect discovered during later stage. |
| E-13 | Rework Started | Campaign rewinds to target stage. That stage must be re-gated (or overridden) before forward progress resumes. |
| E-14 | Blocker Encountered | Work paused — external dependency. Campaign enters blocked state. Dashboard reflects. |
| E-15 | Campaign Unblocked | Blocking condition resolved. Work resumes from where it paused. |
| E-16 | Critical Stoppage | Unrecoverable error. Campaign halted. |

### Phase: Closeout
| # | Event | Notes |
|---|-------|-------|
| E-17 | Campaign Completed | All stages done, DoD approved, project closed. |

### Flow Diagram

```
E-01 → E-02 → ┌─────────────────────────────────────────┐
               │  STAGE LOOP (per stage from pack)        │
               │                                          │
               │  E-03 (enter)                            │
               │    ↓                                     │
               │  E-04* (artifacts produced, 0..N)        │
               │    ↓                                     │
               │  E-05 (gate check requested)             │
               │    ├─→ E-11* (per artifact verified)     │
               │    │     ↓                               │
               │    ├─→ E-06 (passed) → E-07 (complete) ─┤──→ next stage
               │    ├─→ E-08 (failed) → stay in stage    │
               │    └─→ E-09 (override) → E-07 ──────────┤──→ next stage
               │                                          │
               │  E-10 (skip) ────────────────────────────┤──→ next stage
               └──────────────────────────────────────────┘
                                    ↓ (last stage complete)
                                  E-17 (campaign completed)

EXCEPTIONS (interrupt from any stage):
  E-12 (foundation fault) → E-13 (rework → earlier stage, must re-gate)
  E-14 (blocker) → ... → E-15 (unblocked, resume)
  E-16 (critical stoppage — halt)
```

### Refinements from Discussion

**D-08: Artifact Produced is declared, not pushed.** The Pair tells the MCP "I produced X." The MCP records it and makes it queryable via status ("3 of 5 expected artifacts produced"). No immediate action triggered. This enables lightweight progress tracking without the MCP being a nanny.

**D-09: Gate check = artifact verification.** The gate check verifies all expected artifacts for the stage. E-11 (Artifact Verified) fires as a sub-event of E-05 — one per expected artifact. All must verify for E-06 (Gate Passed). The Process Pack defines which artifacts each stage expects.

**D-10: Rework forces re-gating.** E-13 (Rework Started) rewinds to a target stage. Any changes to that stage invalidate its previous gate pass. The stage must be re-gated (E-05 → E-06) or the Pair must override (E-09) before forward progress resumes. No silent pass-throughs.

## Stage 4: Commands

### Analysis

Each event classified as a **decision** (Pair chose it) or **chain** (automatic consequence):

- **Decisions:** E-01, E-04, E-05, E-09, E-10, E-12, E-14, E-15, E-16
- **Chains:** E-02 (after E-01), E-03 (after E-07/E-10/E-02), E-06 (after E-11s pass), E-07 (after E-06/E-09), E-08 (after E-11 fails), E-11 (sub-event of E-05), E-13 (after E-12), E-17 (after final E-07)

### Serial Chain Collapse

- E-01 → E-02 → E-03 = **one command** ("start campaign")
- E-05 → E-11* → E-06 → E-07 → E-03 = **one command** ("gate check") — happy path fires 5 events
- E-09 → E-07 → E-03 = **one command** ("override gate")
- E-10 → E-03 = **one command** ("skip stage")
- E-12 → E-13 = **one command** ("report fault + rewind target")
- E-17 = **automatic** (no command — fires when final stage completes)

### Command Table

| # | Command | Events (serial chain) | Decision |
|---|---------|----------------------|----------|
| C-01 | Start Campaign | E-01 → E-02 → E-03 | "Begin a new project with this pack" |
| C-02 | Request Gate Check | E-05 → E-11* → (E-06 → E-07 → E-03) or E-08 | "Check if I can advance" |
| C-03 | Override Gate | E-09 → E-07 → E-03 | "Push past failure with rationale" |
| C-04 | Skip Stage | E-10 → E-03 | "Skip this stage entirely" |
| C-05 | Report Fault | E-12 → E-13 | "Found a design flaw, rewind to stage X" |
| C-06 | Set/Clear Blocker | E-14 or E-15 | "We're blocked on X" / "Blocker cleared" |
| C-07 | Halt Campaign | E-16 | "This is dead, stop everything" |

Plus one read-only query (not a command — no state change):
- **Query: Next/Status** — "Where am I, what should I do?" Returns current stage, progress, guidance prompt.

### Command → MCP Tool Mapping

| # | Command | MCP Tool | Key Params |
|---|---------|----------|------------|
| C-01 | Start Campaign | `sdlc_start` | `project`, `pack` (path or git URL) |
| C-02 | Request Gate Check | `sdlc_gate` | (none — checks current stage) |
| C-03 | Override Gate | `sdlc_gate` | `override: true`, `rationale: "..."` |
| C-04 | Skip Stage | `sdlc_skip` | `rationale: "..."` |
| C-05 | Report Fault | `sdlc_fault` | `target_stage`, `description` |
| C-06 | Set/Clear Blocker | `sdlc_block` | `action: "set"/"clear"`, `reason` |
| C-07 | Halt Campaign | `sdlc_halt` | `reason` |
| — | Query Status + Prompt | `sdlc_next` | (none — returns current state + guidance) |

**Total: 7 MCP tools.** C-02 and C-03 share a tool (`sdlc_gate`) with an optional override flag.

### Design Decisions

**D-11: Artifact Produced (E-04) cut from commands.** The gate check discovers artifacts from the git remote at gate-check time. No need for the Pair to explicitly declare artifacts — the MCP checks what exists. E-04 is still a valid event in the audit log (emitted by the gate check when it finds an artifact), but there is no Pair-facing command for it.

**D-12: 7-tool surface.** The MCP tool surface is: `sdlc_start`, `sdlc_gate`, `sdlc_skip`, `sdlc_fault`, `sdlc_block`, `sdlc_halt`, `sdlc_next`. Wave-pattern tools (separate namespace) are additional but not counted here.

## Stage 5: Actors

### Responsibility Matrix

| Actor | Commands | Role |
|-------|----------|------|
| **The Pair** (Agent + Human) | C-01 through C-07 + status query | All commands. Every action is a judgment call. |
| **MCP** (reactor) | (none — responds only) | Manages state, emits events, validates gates, returns prompts |
| **Dashboard viewers** | (read-only) | Consume campaign state, never write |
| **CI systems** | (read-only, v1) | May trigger gate checks in future (v2), acting on behalf of the Pair |

### Per-Command Actor Assignment

| Command | Actor | Why This Actor |
|---------|-------|---------------|
| C-01 Start Campaign | Pair | Judgment: "we're starting a project" |
| C-02 Request Gate Check | Pair | Judgment: "I think I'm done with this stage" |
| C-03 Override Gate | Pair | Judgment: "I know it failed, here's why" |
| C-04 Skip Stage | Pair | Judgment: "we don't need this stage" |
| C-05 Report Fault | Pair | Judgment: "I found a design flaw upstream" |
| C-06 Set/Clear Blocker | Pair | Judgment: "we're stuck" / "we're unstuck" |
| C-07 Halt Campaign | Pair | Judgment: "kill it" |
| Query Status/Prompt | Pair | "Where am I, what should I do?" |

### Design Decision

**D-13 (revised): The MCP is a half-duplex director.** Every tool response contains a directive — what to do next, what the gate expects, how to come back. The Pair executes and returns. The pattern is: MCP→Pair "do the thing" ... Pair→MCP "ok we did the thing." The MCP drives the process through its responses.

### Post-Stage-5 Refinements (captured during discussion, before Stage 6)

**D-14: `sdlc_next` dissolved into 3 distinct tools.** The original `sdlc_next` was overloaded with 3 intents:
1. "Remind us what we're doing" → `sdlc_rebrief`
2. "Check our work, are we done yet?" → `sdlc_check` (progress, no advance)
3. "We're done, advance us" → `sdlc_submit` (formal gate + advance on pass, with optional override)

**D-15: Tool naming — verbs only.** Renamed for clarity:
- `sdlc_gate` → `sdlc_submit` (Pair submits work for review)
- `sdlc_next` → split into `sdlc_rebrief` + `sdlc_check`

**D-16: Revised 8-tool Pair→MCP surface:**

| Tool | Verb | Intent |
|------|------|--------|
| `sdlc_start` | start | Begin campaign with a process pack |
| `sdlc_rebrief` | rebrief | "Tell me again what I should be doing" |
| `sdlc_check` | check | "How close am I?" (progress, no advance) |
| `sdlc_submit` | submit | "I'm done, review and advance me" (optional override + rationale) |
| `sdlc_skip` | skip | Skip a stage |
| `sdlc_fault` | fault | Report upstream defect, rewind to target stage |
| `sdlc_block` | block | Set/clear a blocker |
| `sdlc_halt` | halt | Kill campaign |

**D-17: MCP→Pair response patterns (4 types):**

| Pattern | Triggered by | Content source |
|---------|-------------|----------------|
| **Instruct** | start, submit (pass), skip | `prompts/<stage>.md` from Process Pack |
| **Evaluate** | check, submit (fail) | `gates/<stage>.yml` criteria + git remote scan |
| **Rebrief** | rebrief | Current stage's prompt + progress so far |
| **Acknowledge** | block, halt, fault | State change confirmation + consequence |

**OPEN GAP: Status/Dashboard surface not yet defined.** D-07 says MCP owns state and dashboards read from it, but no tools/resources defined for dashboard consumers. Options discussed:
- MCP resource (read-only data endpoint) for structured campaign state JSON
- `sdlc_report` tool returning campaign snapshot
- MCP writes status files for static hosting
- Likely Option C (both tool + optional file output)
- Needs: current stage, per-stage status, gate history, blockers, artifact checklist, event timeline
- **RESOLVED in Stage 5.5 below.** The dashboard surface is the Campaign State Issue (D-21). Options A and C are killed (no MCP-hosted endpoints — incompatible with zero-config onboarding). Option B (`sdlc_report`) survives only as optional Pair-facing sugar.

## Stage 5.5: Watcher Context & Dashboard Model

This stage closes the gap that Stages 1-5 left open. Stages 1-5 modeled the Pair↔MCP dialog in detail but treated dashboards as a one-line "open gap" footnote. The system has THREE audiences (Pair, MCP, Watchers) but only two were modeled. Half the system's stated purpose — observability — was unspecified. This stage models the Watcher side as a first-class bounded context.

### Bounded Context Separation

The watcher-side concerns (browser polling, LIVE/STALE indicators, fetch cycles, notification rendering) live in a SEPARATE bounded context — the **Watcher context**. The MCP cannot observe browser-side events. The Watcher and Campaign contexts share a contract (the published state schema) but not a model.

```
┌──────────────────────┐  publish  ┌──────────────────────┐
│  Campaign Context    │  state    │  Watcher Context     │
│  (MCP + Pair)        │ ────────> │  (browser dashboard) │
│                      │           │                      │
│  Owns: events,       │           │  Owns: polling,      │
│  state, transitions  │           │  rendering, toasts   │
└──────────────────────┘           └──────────────────────┘
```

The **publication boundary** is the moment private state becomes public — when state crosses from one machine to "any watcher anywhere can see it."

### The Attention Demand Insight

The dashboard's job is not "show what changed" — it is "show the watcher where their attention is needed." Attention is the first-class concept; the dashboard is a projection of attention state. We design backwards from notification requirements, not forwards from MCP events.

Three levels (MVP):

| Level | Meaning | Example trigger |
|-------|---------|-----------------|
| `fyi` | Background hum, no action expected | Stage entered, artifact produced, stage completed |
| `look` | Should review when convenient | Stage entered review (waiting for human approval/merge) |
| `act` | Pipeline blocked, human needed NOW | Foundation fault, blocker raised, critical stoppage, publication failure |

### Additional Domain Events

| # | Event | Phase | Notes |
|---|-------|-------|-------|
| E-18 | **State Published** | Publication | Private→public transition. With D-21+D-25, this is "event comment successfully appended to the campaign state issue." Fires once per state-changing event in the campaign. Watchers can now see this event. |
| E-19 | **Publication Failed** | Publication | Comment append failed (network, auth, rate limit, missing issue). Watchers will not see this event. MCP records locally and retries. Exhausted retries → `act`-level event because observability is broken. |
| E-20 | **Attention Demand Raised** | Publication | Meta-event — system declares "a human needs to look at this." Carries a *level* (`fyi`/`look`/`act`) inherited from the upstream event that triggered it. |
| E-21 | **Review Requested** | Stage Loop | A gated stage transitions `active → review` (D-18). Canonical `look`-level signal. Fires from `sdlc_submit` when PR/MR exists and required artifacts are present. |

### Event-to-Attention Mapping

| Event | Level | Event | Level |
|-------|-------|-------|-------|
| E-01 Campaign Started | fyi | E-12 Foundation Fault Detected | **act** |
| E-02 Process Pack Loaded | fyi | E-13 Rework Started | fyi |
| E-03 Stage Entered | fyi | E-14 Blocker Encountered | **act** |
| E-04 Artifact Produced | fyi | E-15 Campaign Unblocked | fyi |
| E-05 Gate Check Requested | fyi | E-16 Critical Stoppage | **act** |
| E-06 Gate Check Passed | fyi | E-17 Campaign Completed | fyi |
| E-07 Stage Completed | fyi | E-18 State Published | (mechanism) |
| E-08 Gate Check Failed | fyi | E-19 Publication Failed | **act** |
| E-09 Gate Overridden | fyi | E-20 Attention Demand Raised | (varies) |
| E-10 Stage Skipped | fyi | E-21 Review Requested | **look** |
| E-11 Artifact Verified | fyi | | |

### Design Decisions

**D-18: `review` is a durable stage state.** Four-state model: `not_started → active → review → complete`. Not all stages have a review gate — the Process Pack defines which stages are gated. In the default pack: concept, prd, dod gated; backlog, implementation not. Rationale: dashboard watchers need to see "in review" — that is the canonical "you are needed" signal. Supersedes the verbal agreement made before Stage 6 that `review` was transient.

**D-19: PR/MR merge IS the gate mechanism.** `sdlc_submit` checks PR/MR existence + required artifacts. Missing artifacts → MCP comments on the PR (blocking merge), stage moves `active → review` (E-21 fires). Platform-native review/approval/merge happens normally. `sdlc_check` advances `review → complete` when MCP detects merge. The platform's code review IS the approval — MCP doesn't duplicate it.

**D-20: Every gated stage delivers via PR/MR.** The PR is the universal delivery mechanism — not just for code, but for concept docs, PRDs, DoD reports. Rationale: (1) artifacts don't "exist" until they're on origin — local files are drafts; (2) PR comments give an auditable log, durable rework notes, stakeholder visibility. Reconciles with D-05: MCP reads from origin via API.

**D-21: Dashboard state lives in a Campaign State Issue, not in the project repo's filesystem.** One designated issue per campaign:
- **Issue body** = current state snapshot (JSON in a code fence). Updated atomically via API on every state mutation.
- **Issue comments** = the event log. Each E-NN appended as a structured comment.
- **Issue is pinned** for discoverability. Labeled `sdlc::campaign-state` to filter from normal triage.

Rationale: kills six structural problems with the repo-files approach:
1. Branch coordination (`?branch=` switching, cutover lag) — issues are not branch-scoped
2. Commit pollution of project history
3. PR conflicts on machine-written JSON
4. Branch-protection bypass tokens for automation
5. `.sdlc/` folder polluting source tree
6. Coupling to the project's git workflow (GitFlow vs trunk-based)

Provides the highest GitHub/GitLab API alignment of any considered mechanism (~95% identical APIs for body/description and comments/notes). Compatible with the existing static Pages dashboard — the fetch URL changes from `raw.githubusercontent.com/...json` to `api.github.com/repos/.../issues/N` and `.../comments`. Dashboard JS gains ~200-300 lines (pagination, ETag conditional polling, code-fence parsing). CORS is supported on both platforms; rate limits give ~5.6× headroom at 4-second polling.

**D-22: Visual encoding reuses the existing cyberpunk palette.**
- Stage card glow: cyan (`fyi`/normal), orange (`look` — stage in review), red pulsing (`act` — unresolved fault/block on this stage)
- Toast notifications fire on transition into `look` or `act` only (`fyi` never toasts — too noisy)
- `look` toasts auto-dismiss after ~10s; `act` toasts persist until clicked
- The existing palette IS the attention encoding — no new design language

**D-23: Attention Demand is stateless on the server (MVP).** No raised → acknowledged → cleared lifecycle in the MCP. Attention level is *derived* on every dashboard poll from the recent unresolved events in the comment log. Each watcher independently tracks "what have I seen" via browser localStorage (`lastSeenEventId`). The MCP never knows whether a human saw a notification. This dodges multi-watcher coordination entirely.

**D-24: One active campaign state issue per repo at a time.** A repo may have many campaigns over its lifetime, but only one is "active" at any moment. This sidesteps GitHub's 3-pinned-issues-per-repo limit (the active campaign is always the pinned one), keeps watcher attention focused, and resolves the meta-repo-vs-project-repo question in favor of the project repo. Historical campaigns remain as closed issues for audit but are not pinned and not polled by watchers.

**D-25: Writers append, never overwrite. The comment stream is the source of truth; the issue body is a cached projection.** This is a refinement of D-21 that makes multi-actor collaboration safe.

- **All state mutations append a comment to the event log.** Atomic, conflict-free, append-only. Two concurrent Pair sessions can both append without losing each other's writes.
- **The issue body is a cached snapshot derived from the comment stream.** Any writer (or a periodic refresher) can rebuild the body by replaying comments. Last writer wins on the body update — and that's fine, because the body is regenerable.
- **The dashboard derives state from comments**, not the body. The body is a convenience for human readers and a fast-path for cold-load.
- **E-18 (State Published) fires when the comment append succeeds**, not when the body update succeeds. Body refresh is async and idempotent.

CRDT-friendly by construction. Eliminates the lost-update race that plagues body-only approaches.

**D-26: Event comment format = markdown header + JSON code fence.** Each event comment is structured as:

```
**E-21 Review Requested** — `prd` stage entered review at 14:32 UTC

​```json
{"event": "E-21", "stage": "prd", "level": "look", "timestamp": "2026-04-05T14:32:00Z", "ref": {"pr": 47}}
​```
```

Humans can skim the markdown header. Dashboards parse the JSON fence. The writer convention is fixed; the dashboard knows where to look. Comments without a recognizable JSON fence are treated as human commentary and ignored by the dashboard parser.

**D-27: Issue body carries `schema_version: 1`.** Cheap insurance. When the body shape changes later, dashboards encountering an old `schema_version` can render a degraded view or prompt for upgrade rather than crashing.

**D-28: Closed or missing campaign issue degrades gracefully.** Two failure modes, one policy:
- **Issue exists but is closed** — interpret as "observability shutting down." MCP still appends comments (most platforms allow comments on closed issues). Watchers can see historical state and the closure timestamp. Useful for archived campaigns.
- **Issue does not exist** (deleted, never created) — MCP logs a warning and continues campaign work. Observability is broken, but the campaign keeps running. The Pair can recreate the issue manually if they want to restore the dashboard.

The MCP never aborts a campaign because of an observability failure. Campaign work and publication are decoupled — the campaign can run blind.

### The Branch-Switching Pain (resolved)

Previously a structural problem with the repo-files approach: dashboard URL needed `?branch=` switching with cutover lag. **D-21 eliminates this entirely.** Issues are not branch-scoped — the dashboard fetches the same issue regardless of which branch the campaign is currently working on.

### Static Pages Compatibility (confirmed)

The dashboard remains a static Pages deployment. Only the JS fetch layer changes:
- Fetch from `api.github.com` / `gitlab.com/api/v4` instead of `raw.githubusercontent.com`
- PAT auth via `Authorization: Bearer` header (already used for raw fetches)
- ETag / `If-None-Match` for polite polling — 304 responses don't count against rate limit
- Track `lastSeenEventId` in localStorage for delta polling
- Parse JSON code fence out of issue body markdown
- Pagination handling for long-running campaigns (don't re-fetch the entire history on every poll)

### Open Questions

1. ~~Where does the campaign state issue live?~~ **RESOLVED by D-24** — project repo, one active per repo at a time.
2. ~~Structured comment format?~~ **RESOLVED by D-26** — markdown header + JSON code fence.
3. ~~What happens to the existing `.sdlc/` implementation?~~ **Owner has it.** Blast radius is one other unreleased project; no MCP-side concern.
4. **Does `sdlc_report` survive as Pair-facing sugar, or get cut entirely?** It would offer "show me my campaign without opening a browser" but duplicates what the issue body already provides. **Still open.**
5. **PR-as-gate semantics for DoD specifically.** Concept docs and PRDs as PRs make sense; DoD is verification, not delivery. Parked for now per agreement — revisit when implementing the DoD stage in the MCP.
