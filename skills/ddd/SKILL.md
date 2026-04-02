---
name: ddd
description: Domain-Driven Design facilitation — event storming, domain modeling, and PRD generation
---

<!-- introduction-gate: If introduction.md exists in this skill's directory AND
     the marker file /tmp/skill-intro-ddd does NOT exist, read introduction.md,
     present its contents to the user, then create the marker: touch /tmp/skill-intro-ddd
     Do NOT delete introduction.md — it lives in a protected directory.
     Do this BEFORE executing any skill logic below. -->

# Domain-Driven Design Workflow

This skill provides a structured workflow for Domain-Driven Design using event storming. It guides you through discovering your domain model and translating it into an implementation-ready PRD.

## Commands

- **`/ddd begin`** — Start interactive event storming session (creates SKETCHBOOK.md)
- **`/ddd draft`** — Formalize sketchbook into Domain Model document (creates DOMAIN-MODEL.md)
- **`/ddd accept`** — Translate Domain Model to PRD (creates docs/[project]-PRD.md)
- **`/ddd resume`** — Resume interrupted event storming session

## Usage

```bash
# Start a new event storming session
/ddd begin

# Formalize raw notes into domain model
/ddd draft

# Generate PRD from domain model
/ddd accept

# Resume interrupted session
/ddd resume
```

---

{{#if (eq args "begin")}}
  {{> ddd-begin}}
{{else if (eq args "draft")}}
  {{> ddd-draft}}
{{else if (eq args "accept")}}
  {{> ddd-accept}}
{{else if (eq args "resume")}}
  {{> ddd-resume}}
{{else}}
  {{> ddd-help}}
{{/if}}

<!-- BEGIN TEMPLATE: ddd-help -->
## /ddd Command Reference

You've invoked `/ddd` without a command. Use one of:

### `/ddd begin` — Start Event Storming
Begin an interactive Domain-Driven Design session. I'll guide you through 8 stages of event storming:
1. Domain Context
2. Events (brainstorm)
3. Events (organize)
4. Commands
5. Actors
6. Policies
7. Aggregates
8. Read Models

Progress is saved to `docs/SKETCHBOOK.md` after each stage.

### `/ddd draft` — Formalize Domain Model
Reads `docs/SKETCHBOOK.md` and produces a formal `docs/DOMAIN-MODEL.md` following the Domain Model template. Validates completeness and adds traceability.

### `/ddd accept` — Generate PRD
Reads `docs/DOMAIN-MODEL.md` and generates `docs/[project]-PRD.md` using the DDD→PRD translation protocol. The PRD is implementation-ready with full traceability back to the domain model.

### `/ddd resume` — Resume Session
If your event storming session was interrupted (context compaction, restart), this command reads `docs/SKETCHBOOK.md` and picks up where you left off.

**Which command would you like to run?**
<!-- END TEMPLATE: ddd-help -->

<!-- BEGIN TEMPLATE: ddd-begin -->
## Event Storming Session

I'll guide you through discovering your domain model using event storming. This is a collaborative process — I wear two hats:

1. **Domain Expert Partner** — I'll ask probing questions, suggest missing pieces, and challenge assumptions
2. **Facilitator** — I'll keep us moving through stages and record everything in the sketchbook

### Approach: Socratic Method

I won't tell you what your domain is — I'll help you discover it. Expect questions like:
- "What happens after X?"
- "Who decides that?"
- "What if Y fails?"
- "How do you know when Z is complete?"

The best domain models emerge from questioning, not dictation.

---

## Stage 1: Domain Context

Let's start with the big picture.

**Questions:**
1. **What are we modeling?** (Project name, brief description)
2. **What's the scope?** (What's included, what's explicitly out?)
3. **Who are the actors?** (Humans, agents, systems that interact)
4. **What's the core problem we're solving?**

**Recording:** As you answer, I'll create `docs/SKETCHBOOK.md` and record:
```markdown
# [Project] — Domain Discovery Sketchbook

## Stage 1: Domain Context

**Project:** [name]
**Description:** [brief]
**Scope:** [included/excluded]
**Actors:** [list]
**Core Problem:** [description]
```

**Socratic follow-ups I'll use:**
- "You mentioned X is out of scope — why is it excluded despite seeming related?"
- "When you say 'actor Y' — is that a human, an agent, or an external system?"
- "What's the hardest part of this problem? What keeps failing or taking too long?"

**After you answer, I'll probe deeper and then we'll move to Stage 2 (Events).**

---

## Facilitation Instructions (Agent)

**Stage progression:**

After Stage 1, follow this pattern for remaining stages:

### Stage 2: Events Brainstorm
**Goal:** Dump all domain events (past tense) without structure

**Prompt:**
> "What happens in this domain? Don't organize yet — just throw out everything that occurs, past tense:
> - 'Video Commissioned'
> - 'Script Approved'
> - 'Asset Rejected'
>
> What events can you think of?"

**Socratic probes:**
- "What happens before X?"
- "What happens after Y?"
- "What about error cases — what events occur when things go wrong?"
- "Are there lifecycle events? (created, updated, approved, deleted, retired)"
- "What about notification events? (user notified, alert sent)"

**Record:** Unordered list of events in sketchbook. Mark as "Stage 2: Events (Brainstorm)".

---

### Stage 3: Events Timeline
**Goal:** Organize events chronologically, group by phase, number them

**Prompt:**
> "Let's organize these events into a timeline. What are the major phases? (e.g., Ideation, Production, Review, Delivery)"

**Process:**
1. Group events by phase
2. Sort chronologically within each phase
3. Number sequentially: E-01, E-02, E-03...

**Socratic probes:**
- "Does E-05 always come before E-08, or can they happen in any order?"
- "You have 'Asset Created' and 'Asset Ingested' — are those the same event or different?"
- "What's the first event in the system? What's the last?"

**Record:** Organized event table in sketchbook:
```markdown
## Stage 3: Events Timeline

### Phase: Ideation
| # | Event | Notes |
|---|-------|-------|
| E-01 | Idea Captured | Someone wrote down "we need X" |
| E-02 | Brief Written | Idea → structured brief |
...
```

---

### Stage 4: Commands
**Goal:** Identify what triggers events. Find serial chains vs decision points.

**Prompt:**
> "What triggers each event? Some events happen automatically (policies), but others need a command — someone issuing an instruction.
>
> Look at your events. Which ones are decisions? Which are automatic reactions?"

**Pattern to find:**
- **Decision point:** E-08 (Script Approved) — someone had to decide "yes, approved"
- **Serial chain:** E-01 → E-02 → E-03 — happens automatically once started
- **Loop:** E-05 → E-06 → E-07 → back to E-05 — iterates until exit condition

**Socratic probes:**
- "Who decides when X happens?"
- "Is Y always triggered by X, or does someone choose whether to do Y?"
- "What's the exit condition for this loop?"
- "Can Z be cancelled mid-flight?"

**Command collapse principle:** Serial chains with no decision points become ONE command. E-01→E-02→E-03 = C-01 "Commission Video".

**Record:** Command table with serial chains:
```markdown
## Stage 4: Commands

| # | Command | Serial Chain (Events) | Decision |
|---|---------|----------------------|----------|
| C-01 | Commission Video | E-01 → E-02 → E-03 | "Yes, make this" |
| C-02 | Iterate Script | E-05 → E-06 → E-07 (loops) | None — runs until approved |
| C-03 | Approve Script | E-08 | "Script is ready" |
```

---

### Stage 5: Actors
**Goal:** Map who issues each command

**Prompt:**
> "For each command, who can issue it? Is it a human, an agent, or both?"

**Socratic probes:**
- "Why is C-01 human-only? What judgment does it require?"
- "Why is C-14 agent-only? What makes it mechanical?"
- "For C-02 (human + agent) — what's the split? Who does what part?"

**Pattern recognition:**
- **Human only:** Judgment, approval gates, creative decisions
- **Agent only:** Deterministic execution, mechanical assembly
- **Human + Agent:** Create↔review pattern (one creates, other reviews)

**Record:** Actor responsibility matrix:
```markdown
## Stage 5: Actors

| Actor | Commands | Responsibility |
|-------|----------|---------------|
| **Executive Producer (Human)** | C-01, C-03, C-17 | Approval gates, "ship it" decision |
| **Production Manager (Agent)** | C-04, C-13, C-18 | Pipeline orchestration, execution |
| **Compositor (Agent)** | C-14 | Build Remotion TSX from spec |
```

---

### Stage 6: Policies
**Goal:** Discover automatic reactions — "when X, then Y"

**Prompt:**
> "What happens automatically when an event occurs? These are policies — no human decision, just triggers.
>
> Examples:
> - When Script Approved → automatically start Asset Sourcing
> - If Asset Invalid → automatically reject and log
> - When Render Complete → automatically validate"

**Types to look for:**
- **Cascade:** When X → trigger Y (domino)
- **Quality:** If bad condition → reject/log
- **Notification:** When X → notify actor
- **Loop:** Iterate until exit condition

**Socratic probes:**
- "Does Y always happen after X, or does someone decide?"
- "What about error cases — what triggers when things fail?"
- "Are there accumulator patterns? (count N things, then trigger when all N complete)"
- "Are there join gates? (wait for multiple conditions, then proceed)"

**Record:** Policy table grouped by type:
```markdown
## Stage 6: Policies

### Cascade Policies
| # | When (Event) | Then (Trigger) | Why Automatic |
|---|-------------|----------------|---------------|
| P-01 | Video Commissioned (E-03) | Start Iterate Script (C-02) | Commission implies start writing |
| P-07 | E-34 AND E-24 AND E-29 | Render Rough Cut (C-16) | Join gate — all 3 must be true |

### Quality Policies
| # | When (Event) | Then (Trigger) | Why |
|---|-------------|----------------|-----|
| P-10 | Asset Ingested (E-12) | Validate format/resolution | Catch bad assets early |
```

---

### Stage 7: Aggregates
**Goal:** Find state holders — things that track lifecycle

**Prompt:**
> "What are the 'things' in your domain that have a lifecycle? What holds state?
>
> Examples:
> - Video (idea → commissioned → in-production → approved → published)
> - Script (draft → in-review → approved)
> - Asset (requested → fulfilled → ingested → rejected)"

**For each aggregate, ask:**
- What states can it be in?
- What events transition between states?
- What rules does it enforce? (invariants)
- What does it reference? (relationships)

**Socratic probes:**
- "Can a Video be published without Final Cut Approval?"
- "Can you delete a Script while it's in-review?"
- "Does Asset own the Creative Brief, or is it separate?"

**Record:** Aggregate table with state machines:
```markdown
## Stage 7: Aggregates

| Aggregate | States | Transitions | Invariants |
|-----------|--------|------------|-----------|
| **Video** | idea → commissioned → in-production → approved → published → retired (+ cancelled from any) | E-03 (commissioned), E-44 (approved), E-54 (published), E-63 (cancelled) | Cannot publish without E-44. Cannot retire unless published. |
| **Script** | draft → in-review → approved | E-05 (draft), E-06 (review), E-08 (approved) | Cannot approve without review. |
```

---

### Stage 8: Read Models
**Goal:** Identify what views actors need to make decisions

**Prompt:**
> "At each decision point, what information does the actor need?
>
> Example: At C-17 (Approve Final Cut), the Executive Producer needs:
> - Video playback with timestamp-linked feedback
> - Script side-by-side
> - Caption toggle
>
> This becomes RM-03 (Rough Cut Player)."

**For each command with a decision:**
- What does the actor look at?
- What query answers "can I proceed?"
- What view supports this judgment?

**Socratic probes:**
- "How does the agent know when all assets are fulfilled? (RM-07: Asset Fulfillment Board)"
- "How does the EP track which videos are in flight? (RM-01: Video Dashboard)"
- "What prevents duplicate asset creation? (RM-14: Asset Library Browser)"

**Record:** Read model table:
```markdown
## Stage 8: Read Models

| # | Read Model | Informs Decision | Shows |
|---|-----------|-----------------|-------|
| RM-03 | Rough Cut Player | "Does this cut feel right?" (C-16, C-17) | Video playback, timestamp feedback, script side-by-side |
| RM-07 | Asset Fulfillment Board | "What assets are needed?" (P-06 join) | Requested vs fulfilled vs rejected, blocking scenes |
```

---

### Checkpoint After Each Stage

After completing each stage:
1. **Write to `docs/SKETCHBOOK.md`** — append the stage's content
2. **Summarize progress:** "We've completed Stage N. Here's what we discovered: [brief summary]"
3. **Preview next stage:** "Next, we'll work on Stage N+1 [name]. Ready to continue?"
4. **Wait for user confirmation** before proceeding

If the user says "go back" or "I forgot something":
- Allow backtracking to previous stages
- Mark stages as "revised" in sketchbook
- Don't overwrite — append revisions with timestamp

---

### Completion

After Stage 8:
1. **Review sketchbook together:**
   - "We've captured [N] events, [M] commands, [P] policies, [A] aggregates, [R] read models"
   - "Does this feel complete? What are we missing?"
2. **Flag open questions:**
   - "What do we still not know?"
   - Record in sketchbook under "Open Questions"
3. **Checkpoint final version:**
   - "Event storming complete. Sketchbook saved to `docs/SKETCHBOOK.md`."
4. **Suggest next step:**
   - "Ready to formalize? Run `/ddd draft` to generate the Domain Model document."

<!-- END TEMPLATE: ddd-begin -->

<!-- BEGIN TEMPLATE: ddd-resume -->
## Resuming Event Storming Session

Let me check where we left off...

**Before proceeding:** Check whether `docs/SKETCHBOOK.md` exists.

**If it exists:**
1. Read the sketchbook to find the last completed stage
2. Summarize what we've discovered so far
3. Identify the next stage to work on
4. Continue from there

**If it does not exist:**
Tell the user: "No sketchbook found at `docs/SKETCHBOOK.md`. Would you like to:
- **Start fresh:** `/ddd begin`
- **Import existing:** Move your sketchbook to `docs/SKETCHBOOK.md` and run `/ddd resume` again"
<!-- END TEMPLATE: ddd-resume -->

<!-- BEGIN TEMPLATE: ddd-draft -->
## Formalizing Domain Model

I'll read your sketchbook and produce a formal Domain Model document following the template structure.

**Process:**
1. Read `docs/SKETCHBOOK.md` (raw notes from event storming)
2. Read `docs/Domain-Model-template.md` (structure to follow)
3. Reorganize content into formal sections:
   - Decisions Made (D-01, D-02, ...)
   - Domain Context
   - Domain Events (E-01, E-02, ...)
   - Commands (C-01, C-02, ...)
   - Actors (responsibility matrix)
   - Policies (P-01, P-02, ... grouped by type)
   - Aggregates (state machines, invariants)
   - Read Models (what views actors need)
   - Open Questions
   - DDD→PRD Translation Map
4. Validate completeness:
   - Every policy references events/commands
   - Every aggregate has a state machine
   - Every command has an actor
   - No orphaned references
5. Write `docs/DOMAIN-MODEL.md`

**Before proceeding:** Check that the required files exist.

- Check `docs/SKETCHBOOK.md` — **required.** If missing, tell the user: "Run `/ddd begin` first or move your sketchbook to `docs/SKETCHBOOK.md`."
- Check `docs/Domain-Model-template.md` — optional. If missing, use the built-in template structure.

If the sketchbook exists, proceed. Read it and generate the formal domain model now.
<!-- END TEMPLATE: ddd-draft -->

<!-- BEGIN TEMPLATE: ddd-accept -->
## Translating Domain Model → PRD

I'll apply the DDD→PRD translation protocol to generate an implementation-ready Product Requirements Document.

**Process:**
1. Read `docs/DOMAIN-MODEL.md` (source of truth)
2. Read `docs/PRD-template.md` (target structure)
3. Read `docs/DDD-to-PRD-protocol.md` (translation rules)
4. Apply 8-step translation:
   - **Step 1:** Actors → Section 1.4 Personas
   - **Step 2:** Aggregates → Section 5.1 Data Model
   - **Step 3:** Policies → Section 3 Requirements (EARS format)
   - **Step 4:** Commands → Section 4 Concept of Operations (flows)
   - **Step 5:** Read Models → Section 5 API/UI + Section 6 Test Plan
   - **Step 6:** Create Test Plan from policies and read models
   - **Step 7:** Decompose into Stories (Section 8) from aggregates + policies
   - **Step 8:** Add traceability — Domain Model as appendix, event catalog, VRTM skeleton
5. Write `docs/[project]-PRD.md`

**Before proceeding:** Check that the required files exist.

- Check `docs/DOMAIN-MODEL.md` — **required.** If missing, tell the user: "Run `/ddd draft` first."
- Check `docs/PRD-template.md` — optional. If missing, use the built-in PRD structure.
- Check `docs/DDD-to-PRD-protocol.md` — optional. If missing, use the built-in translation rules.

If the domain model exists, ask the user for the project name:

**What should the PRD be named?** (e.g., "remotion-studio" → `docs/remotion-studio-PRD.md`)

After the user provides the name:
1. Translate the domain model
2. Generate the PRD with full traceability
3. Validate that every policy has a requirement, every requirement has verification

**Commitment moment:** Once this PRD is generated, the Domain Model becomes the canonical source. Future changes should update the Domain Model and re-run `/ddd accept` to regenerate the PRD.
<!-- END TEMPLATE: ddd-accept -->
