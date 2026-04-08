# [Project] — Domain Model

**Method:** Event Storming (Domain-Driven Design)
**Date:** [Date]
**Participants:** [Who participated in the event storming]
**Status:** Draft | Validated | Translated to Dev Spec

---

## Table of Contents

1. [Decisions Made](#1-decisions-made)
2. [Domain Context](#2-domain-context)
3. [Domain Events](#3-domain-events)
4. [Commands](#4-commands)
5. [Actors](#5-actors)
6. [Policies](#6-policies)
7. [Aggregates](#7-aggregates)
8. [Read Models](#8-read-models)
9. [Open Questions](#9-open-questions)
10. [DDD → Dev Spec Translation Map](#10-ddd--dev-spec-translation-map)

---

## 1. Decisions Made

[[Architectural decisions with rationale. Each decision should state what was chosen and why, referencing constraints or trade-offs. Number decisions sequentially (D-01, D-02, ...) for traceability.]]

| ID | Decision | Rationale |
|----|----------|-----------|
| D-01 | [[decision]] | [[why this choice]] |
| D-02 | [[decision]] | [[why this choice]] |

---

## 2. Domain Context

### 2.1 Project Overview

**What are we modeling:** [[project name and brief description]]

**Scope:**
- **In scope:** [[what's included]]
- **Out of scope:** [[what's explicitly excluded and why]]

### 2.2 Actors

[[List of actors — humans, agents, external systems — that interact with this domain]]

| Actor | Type | Description |
|-------|------|-------------|
| [[actor name]] | Human / Agent / System | [[role and responsibility]] |

### 2.3 Core Problem

[[The problem this domain model solves. What's hard about this? What keeps failing or taking too long?]]

---

## 3. Domain Events

[[Domain events are things that happened (past tense). Organized by phase and numbered sequentially (E-01, E-02, ...). Each event should include a brief note explaining what it represents.]]

### Phase: [[Phase Name]]

| # | Event | Notes |
|---|-------|-------|
| E-01 | [[Event Name]] | [[brief description]] |
| E-02 | [[Event Name]] | [[brief description]] |

### Phase: [[Phase Name]]

| # | Event | Notes |
|---|-------|-------|
| E-XX | [[Event Name]] | [[brief description]] |

**Total events:** [[N]]

---

## 4. Commands

[[Commands are triggers that cause events. They represent decision points or the start of serial chains. Number commands sequentially (C-01, C-02, ...). Each command should show its serial chain of events and identify whether it's a decision point.]]

**Command collapse principle:** Serial chains with no decision points become one command. E-01→E-02→E-03 with no branches = C-01.

| # | Command | Serial Chain (Events) | Decision |
|---|---------|----------------------|----------|
| C-01 | [[Command Name]] | E-XX → E-XX → E-XX | [[what decision, or "None — automatic chain"]] |
| C-02 | [[Command Name]] | E-XX → E-XX (loops via E-XX) | [[what decision, or "None — iterates until exit"]] |

**Total commands:** [[N]]

### Key Insights

[[Summary of command patterns found:]]
- **Approval gates:** [[list commands that are decision points]]
- **Agent-autonomous chains:** [[list commands that are fully automated]]
- **Iteration loops:** [[list commands that loop]]
- **Lifecycle commands:** [[list commands that transition aggregates]]

---

## 5. Actors

[[Map actors to commands. Shows who issues each command and why. Identifies the human↔agent boundary.]]

### Responsibility Matrix

| Actor | Commands | Responsibility |
|-------|----------|---------------|
| **[[Actor Name]]** | C-XX, C-XX, C-XX | [[what they're responsible for]] |

### Actor Pattern Summary

| Actor Type | Commands | Count |
|-----------|----------|:-----:|
| **Human only** | [[list]] | [[N]] |
| **Agent only** | [[list]] | [[N]] |
| **Human + Agent** | [[list]] | [[N]] |

**The split:** [[brief description of human vs agent boundary — e.g., "Human is in the loop at judgment/approval points, never at execution points."]]

---

## 6. Policies

[[Policies are automatic reactions — "when X, then Y". Organized by type. Number sequentially (P-01, P-02, ...). Each policy should reference the events/commands it triggers.]]

### 6.1 Cascade Policies (Dominos)

[[When one event triggers another event or command automatically — no human decision.]]

| # | When (Event) | Then (Trigger) | Why Automatic |
|---|-------------|----------------|---------------|
| P-01 | [[Event]] | [[Trigger command/event]] | [[rationale — why this is always true]] |

### 6.2 Quality Policies (Guardrails)

[[Validation, rejection, error handling — automatic quality checks.]]

| # | When (Event) | Then (Trigger) | Why |
|---|-------------|----------------|-----|
| P-XX | [[Event or condition]] | [[Reject/log/escalate]] | [[what this prevents]] |

### 6.3 Notification Policies (Alerts)

[[When an event occurs, notify an actor via a channel.]]

| # | When (Event) | Then (Notify) | Channel |
|---|-------------|---------------|---------|
| P-XX | [[Event]] | [[message to actor]] | [[Discord / Slack / email / etc.]] |

### 6.4 Loop Policies (Iteration)

[[Policies that cause iteration until an exit condition is met.]]

| # | When (Event) | Then | Exit Condition |
|---|-------------|------|----------------|
| P-XX | [[Event]] | [[Continue iteration]] | [[what stops the loop]] |

**Total policies:** [[N]]

### Key Insights

[[Summary of policy patterns found:]]
- **Join gates:** [[list policies where multiple conditions must converge — e.g., P-07: E-34 AND E-24 AND E-29]]
- **Critical cascades:** [[list policies that trigger major workflows — e.g., P-02: Script Approved → 3 parallel workstreams]]
- **Accumulators:** [[list policies that count/wait for multiple items — e.g., P-28: wait for all assets fulfilled]]

---

## 7. Aggregates

[[Aggregates are state holders — things that have a lifecycle and enforce rules. Each aggregate should document:
- What it holds (data/references)
- State machine (what states, transitions, events)
- Invariants (rules it enforces)
- Relationships (what it references)]]

### 7.1 Core Aggregates

#### [[Aggregate Name]] (Root Aggregate)

**What it holds:** [[description of data/structure]]

**State machine:**
- **States:** [[state1]] | [[state2]] | [[state3]] | ...
- **Transitions:** [[Event]] (state1 → state2), [[Event]] (state2 → state3), ...

**Invariants (rules enforced):**
- [[rule — e.g., "Cannot publish without E-44 (Final Cut Approved)"]]
- [[rule — e.g., "Cannot delete while state = in-review"]]

**Relationships:**
- [[references — e.g., "References Script (1:1), Creative Briefs (1:many)"]]

---

#### [[Aggregate Name]]

[[Repeat structure for each aggregate]]

### 7.2 Aggregate Relationships

[[Diagram showing ownership tree — which aggregates reference which]]

```
[[Root Aggregate]]
 ├── [[Child Aggregate]] (1:1)
 ├── [[Child Aggregate]] (1:many)
 │    └── [[Nested reference]]
 └── [[Child Aggregate]] (1:1)

[[Shared Aggregate]] (cross-aggregate)
 └── [[referenced by multiple roots]]
```

### 7.3 Aggregate Homes in Monorepo

[[If applicable — where each aggregate's data lives in the file structure]]

| Aggregate | Location | Notes |
|-----------|----------|-------|
| [[Aggregate]] | [[path]] | [[storage notes]] |

---

## 8. Read Models

[[Read models are views actors need to make decisions. Each read model should document:
- What decision it informs
- What it shows
- Who uses it]]

### 8.1 For [[Actor Type]]

| # | Read Model | Informs Decision | Shows |
|---|-----------|-----------------|-------|
| RM-01 | [[Model Name]] | [[what decision — reference command]] | [[what data/view it provides]] |

### 8.2 For [[Actor Type]]

| # | Read Model | Informs Decision | Shows |
|---|-----------|-----------------|-------|
| RM-XX | [[Model Name]] | [[what decision]] | [[what data/view]] |

**Total read models:** [[N]]

### Key Insights

[[Summary of critical read models:]]
- **Most critical:** [[which read model is essential for the workflow — e.g., RM-03 Rough Cut Player drives review loop]]
- **Agent key views:** [[which read models drive agent decisions — e.g., RM-07 Asset Fulfillment Board]]
- **Reuse potential:** [[which read models enable efficiency — e.g., RM-10 Brief Registry prevents duplicate work]]

---

## 9. Open Questions

[[Things we know we don't know yet. Each question should describe the decision space and, if possible, the options being considered. Open questions should be resolved before or during implementation.]]

1. **[[Question]]:** [[Description of decision space and options]]
2. **[[Question]]:** [[Description of decision space and options]]

---

## 10. DDD → Dev Spec Translation Map

[[This section documents how each DDD artifact maps to Dev Spec sections. This is reference material for `/ddd accept`.]]

| DDD Artifact | Dev Spec Section | Translation | Status |
|--------------|-------------|-------------|:------:|
| **Actors** | 1.4 Target Users (Personas) | Each actor → persona with use cases from commands issued | [[✓ / Pending]] |
| **Aggregates** | 5.1 Data Model | Each aggregate → entity with state machine, invariants, relationships | [[✓ / Pending]] |
| **Commands (serial chains)** | 4.X Concept of Operations | Each command → operational flow showing step-by-step events | [[✓ / Pending]] |
| **Policies (cascade)** | 3.X Requirements (Event-Driven EARS) | Each cascade policy → "When [event], system shall [action]" | [[✓ / Pending]] |
| **Policies (quality)** | 3.X Requirements (Unwanted EARS) | Each quality policy → "If [bad condition], then system shall [handle]" | [[✓ / Pending]] |
| **Policies (notification)** | 5.X Detailed Design (notification system) | Notification policies → alert/webhook design | [[✓ / Pending]] |
| **Policies (loop)** | 4.X Concept of Operations | Loop policies → iteration flows with exit conditions | [[✓ / Pending]] |
| **Read Models** | 5.X Detailed Design (API/UI) + 6.X Test Plan | Each read model → endpoint/view design + manual verification | [[✓ / Pending]] |
| **Events (full catalog)** | 9.X Appendix (Domain Event Catalog) | Full event list → reference appendix for traceability | [[✓ / Pending]] |
| **Aggregate relationships** | 5.1 Data Model (diagram) | Relationships → ownership structure diagram | [[✓ / Pending]] |

### Policy → Requirement Heuristics

[[Quick reference for translating policies to EARS-formatted requirements]]

| Policy Type | EARS Pattern | Template |
|-------------|-------------|----------|
| **Cascade** | Event-driven | When [event], the system shall [trigger command/event]. |
| **Quality** | Unwanted | If [bad condition], then the system shall [reject/log/escalate]. |
| **Notification** | Event-driven | When [event], the system shall [notify actor via channel]. |
| **Loop** | State-driven | While [condition not met], the system shall [repeat action]. |

---

## Appendix: Event Catalog

[[Complete list of all domain events for reference. Organized by phase, with triggering commands and resulting policies.]]

| # | Event | Phase | Triggered By | Policies |
|---|-------|-------|-------------|----------|
| E-01 | [[Event]] | [[Phase]] | [[C-XX or automatic]] | [[P-XX, P-XX]] |

---

## Appendix: Worked Example

[[Optional: Include one complete lineage showing DDD → Dev Spec translation for a single policy/aggregate. Useful for implementers to understand traceability.]]

**Example: P-07 Join Gate**

**From DDD (Policy):**
```
| P-07 | Composition Assembled (E-34) + Voiceover Approved (E-24) + Sound Designed (E-29) |
       Trigger Render Rough Cut (C-16) |
       First renderable state — join gate, all three must be true |
```

**→ Becomes Requirement (Dev Spec Section 3):**
```
| R-17 | Event-driven | When Composition Assembled (E-34) AND Voiceover Approved (E-24) AND Sound Designed (E-29), the system shall trigger Render Rough Cut (C-16). |
```

**→ Becomes Flow Step (Dev Spec Section 4):**
```
6. **Join Gate** (P-07)
   - Composition Assembled (E-34) — all scenes connected, assets wired
   - Voiceover Approved (E-24) — timing locked
   - Sound Designed (E-29) — mix levels set
   - **Trigger:** System automatically initiates Render Rough Cut (C-16)
```

**→ Becomes Implementation Story (Dev Spec Section 8):**
```
#### Story 2.5: Implement P-07 Join Gate
**Wave:** 2
**Dependencies:** Story 2.1, Story 2.3, Story 2.4

[Implementation steps...]

**Acceptance Criteria:**
- [ ] When E-34, E-24, E-29 all true, returns `True` [R-17]
- [ ] When any missing, returns `False` [R-17]
- [ ] Render command enqueued exactly once [R-17]
```

**Traceability:** Policy P-07 → Requirement R-17 → Flow step 6 → Story 2.5
