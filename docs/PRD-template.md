# [Project] — Product Requirements Document

**Version:** 1.0
**Date:** [Today's Date]
**Status:** Draft
**Authors:** bakerb, Claude (AI Partner)

---

## Table of Contents

1. [Problem Domain](#1-problem-domain)
2. [Constraints](#2-constraints)
3. [Requirements (EARS Format)](#3-requirements-ears-format)
4. [Concept of Operations](#4-concept-of-operations)
5. [Detailed Design](#5-detailed-design)
6. [Definition of Done](#6-definition-of-done)
7. [Phased Implementation Plan](#7-phased-implementation-plan)
8. [Appendices](#8-appendices)

---

## 1. Problem Domain

### 1.1 Background

[describe the domain in which we are working]

### 1.2 Problem Statement

[describe the problem we intend to solve]

### 1.3 Proposed Solution

[a brief description of the general pattern or approach to solving the problem]

### 1.4 Target Users

| Persona | Description | Primary Use Case |
|---------|-------------|------------------|
| **[persona 1]** | [describe this persona and their needs] | [describe how this persona would interact with this application to meet their needs]  |
| **[persona 2]** | [describe this persona and their needs] | [describe how this persona would interact with this application to meet their needs]  |

### 1.5 Non-Goals

[[Explicitly state what this project is NOT. Non-goals draw the boundary and prevent scope creep. They are as important as goals — they set expectations for what is out of scope and why.

Each non-goal should state what might reasonably be assumed to be in scope, and explain why it is not.]]

- **Not a [thing].** [Why this is excluded despite seeming related.]
- **Not a [thing].** [Why this is excluded despite seeming related.]

---

## 2. Constraints

### 2.1 Technical Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| CT-01 | [define the technical constraint] | [justify why the constraint is rigid] |
| CT-02 | [define the technical constraint] | [justify why the constraint is rigid] |

### 2.2 Product Constraints

| ID | Constraint | Rationale |
|----|-----------|-----------|
| CP-01 | [define the product constraint, usually more market-facing] | [justify why the constraint is rigid] |
| CP-02 | [define the product constraint, usually more market-facing] | [justify why the constraint is rigid] |

---

## 3. Requirements (EARS Format)

Requirements follow the **EARS** (Easy Approach to Requirements Syntax) notation:

- **Ubiquitous**: The system shall [function].
- **Event-driven**: When [event], the system shall [function].
- **State-driven**: While [state], the system shall [function].
- **Optional**: Where [feature/condition], the system shall [function].
- **Unwanted**: If [unwanted condition], then the system shall [function].

[[Create sections for requirements grouped by theme or topic, as many as are needed. Number requirements sequentially across all groups (R-01, R-02, ...).

TRACEABILITY: Every requirement ID must appear in at least one Acceptance Criteria item in Section 7. If a requirement has no corresponding AC item, it is unverified — either add verification or question whether the requirement is real. After implementation, the VRTM (Section 8) provides the formal forward and backward trace.]]

### 3.1 [[Requirement Group A]]

| ID | Type | Requirement |
|----|------|-------------|
| R-01 | [[requirement type]] | [[requirement]] |
| R-02 | [[requirement type]] | [[requirement]] |

### 3.2 [[Requirement Group B]]

| ID | Type | Requirement |
|----|------|-------------|
| R-03 | [[requirement type]] | [[requirement]] |
| R-04 | [[requirement type]] | [[requirement]] |

---

## 4. Concept of Operations

### 4.1 System Context

[[Diagram showing the system in its environment — what actors interact with it, what external systems it connects to, and where the boundaries are. ASCII art, Mermaid, or a linked image.]]

[[Add sub-sections for each major operational flow. Common flow categories to consider:

- **Primary user flow** — the main happy-path interaction (e.g., "user submits a request → system processes → result delivered")
- **Administrative / maintenance flow** — how operators manage, configure, or maintain the system
- **Integration flow** — how other systems interact with this one (APIs, events, data pipelines)
- **Error / recovery flow** — what happens when things go wrong, how the system recovers
- **Data lifecycle flow** — how data enters, transforms, ages, and is archived or purged

Not every project needs all of these. Include the flows that are necessary to give a reader a high-level understanding of how the system operates in practice.]]

### 4.2 [[Flow Name]]

[[describe the flow step by step]]

---

## 5. Detailed Design

[[Create sub-sections as needed to communicate a full and complete detailed design. Common sub-sections to consider:

- **Data Model / Schema** — core data structures, database schemas, file formats
- **API Surface** — endpoints, tool definitions, CLI interface, function signatures
- **File / Directory Layout** — where things live in the project structure
- **Technology Choices** — table of components with chosen technology and rationale
- **Deployment Architecture** — how the system is deployed and operated (if applicable)
- **Security Model** — authentication, authorization, secrets handling (if applicable)

Include diagrams where they add clarity. Prefer ASCII art or Mermaid for version-control-friendly diagrams.]]

### 5.1 [[Design Topic]]

[[detailed design content]]

### 5.N Open Questions

[[Capture things you know you don't know yet. Open questions prevent false confidence and flag areas needing research before or during implementation. Each question should describe the decision space and, if possible, the options being considered.

Open questions should be resolved before or during implementation. When resolved, update this section with the decision and rationale, or remove the question and update the relevant design section.]]

1. **[Question]:** [Description of the decision space and options under consideration.]
2. **[Question]:** [Description of the decision space and options under consideration.]

---

## 6. Definition of Done

[[Section 6 defines the GLOBAL Definition of Done for the project as a whole. Phase-level DoDs live in Section 7 under each Phase header.

The Global DoD serves as the **project-level test plan**. Each item verifies one or more requirements from Section 3. Annotate each item with the requirement IDs it satisfies — e.g., `[R-01, R-02]`. If a requirement ID does not appear in any DoD or AC item across the document, it is unverified.

After all phases are complete, the VRTM in Section 8 provides the formal proof that every requirement was verified.]]

- [ ] All Phase DoD checklists are satisfied
- [ ] [[cross-cutting condition — annotate with requirement IDs, e.g., [R-01, R-05] ]]
- [ ] [[cross-cutting condition [R-XX] ]]

---

## 7. Phased Implementation Plan

### How to read this section

**Phases map to Epics.** Each Phase is a major milestone with its own Definition of Done checklist. When a Phase is complete, its DoD is reviewed and confirmed before the Epic is closed.

**User Stories map to Issues.** Each story becomes a single issue in the project tracker. Stories contain step-by-step implementation instructions ("paint by numbers") and an Acceptance Criteria checklist. Every AC item must be satisfiable and verified before the MR/PR for that story is merged.

**Waves enable parallel development.** Stories are grouped into Waves — sets of stories with no inter-dependencies that can execute simultaneously (e.g., via parallel sub-agents). Each Wave has a Master Issue that orchestrates execution and lists its constituent stories.

**Requirement traceability.** Each AC item is annotated with the requirement ID(s) it verifies — e.g., `[R-01]`. This creates forward traceability from requirements to verification. After implementation, the VRTM in Section 8 captures the complete trace.

### Wave Map

[[Create an ASCII diagram showing the wave dependency flow. Each wave lists its stories. Arrows show which waves must complete before the next can start.]]

```
Wave 1 ─── [X.X] Story name (foundation)
              │
Wave 2 ─┬─ [X.X] Story A
         ├─ [X.X] Story B
         └─ [X.X] Story C
              │
Wave 3 ─── [X.X] Story D
```

[[Create a summary table of waves]]

| Wave | Stories | Master Issue | Parallel? |
|------|---------|-------------|-----------|
| 1 | X.X | Story X.X | Single story |
| 2 | X.X, X.X, X.X | Wave 2 Master | Yes — N independent stories |
| 3 | X.X | Story X.X | Single story |

---

### Phase N: [[Phase Name]] (Epic)

**Goal:** [[one-sentence description of what this phase proves or delivers]]

#### Phase N Definition of Done

[[A checklist of conditions that must ALL be true before this Phase/Epic is closed. These are confirmed as a checkpoint before moving to the next Phase. Items should be concrete and verifiable — not "it works" but "command X produces output Y".

Annotate each item with the requirement IDs it verifies. The Phase DoD functions as the acceptance test plan for the phase.]]

- [ ] [[verifiable condition [R-XX] ]]
- [ ] [[verifiable condition [R-XX, R-XX] ]]
- [ ] All Phase N unit tests pass

---

#### Story N.N: [[Story Title]]

**Wave:** [[wave number]]
**Dependencies:** [[list of story IDs that must complete first, or "None"]]

[[1-2 sentence description of what this story delivers and why]]

**Implementation Steps:**

[[Step-by-step instructions for implementing this story. Be specific enough that another developer (human or AI) could follow these instructions without guessing. Include:
- Exact file paths to create or modify
- Function signatures and key logic
- Data structures and schemas
- How to wire components together
- Test file locations and test case descriptions

Think "paint by numbers" — each step should be unambiguous. If a step requires judgment or exploration, say so explicitly rather than leaving it implicit.]]

1. [[specific implementation step]]
2. [[specific implementation step]]
3. [[specific implementation step]]

**Acceptance Criteria:**

[[A checklist of conditions that must ALL be verified before the MR/PR for this story is merged. Each item should be:
- Testable: can be verified by running a command, reading output, or inspecting code
- Specific: names exact functions, files, commands, or behaviors
- Complete: covers all functionality introduced by this story
- Traced: annotated with the requirement ID(s) it verifies — e.g., [R-01]

Do NOT include vague items like "code works" or "implementation is correct". Every item should be something a reviewer can check off by performing a concrete action.]]

- [ ] [[testable condition [R-XX] — e.g., "schema.yaml exists and is valid JSON Schema"]]
- [ ] [[testable condition [R-XX] — e.g., "schema.py rejects invalid archetype enum"]]
- [ ] [[testable condition [R-XX] — e.g., "all tests in test_schema.py pass"]]

---

[[repeat Story sections for each story in this phase]]

---

[[repeat Phase sections for each phase]]

---

## 8. Appendices

[[Use appendices for detailed reference material that supports the main document but would interrupt its flow. Common appendices:

- **Full examples** — complete annotated examples of data formats, API requests/responses, configuration files
- **Glossary** — domain-specific terms used throughout the document
- **Research notes** — background research, benchmarks, or comparisons that informed design decisions
- **Migration plans** — if replacing an existing system, how data or users transition]]

### Appendix A: [[Title]]

[[detailed reference content]]

### Appendix V: Verification Requirements Traceability Matrix (VRTM)

[[This appendix is populated AFTER implementation is complete. It provides formal proof that every requirement in Section 3 was implemented and verified.

The VRTM is generated by collecting all requirement ID annotations from Phase DoD items and Story AC items throughout Section 7. Any requirement ID that does not appear in this matrix represents a gap — either the requirement was not implemented, or the verification was not documented.

Complete this matrix as each Phase is closed. By the time all Phases are done, every row should have a Status.]]

| Req ID | Requirement (short) | Story | AC / DoD Item | Verification Method | Status |
|--------|-------------------|-------|--------------|-------------------|--------|
| R-01 | [[brief description]] | [[N.N]] | [[which AC or DoD item verifies this]] | [[unit test / integration test / manual / inspection]] | [[Pass / Fail / Pending]] |
| R-02 | [[brief description]] | [[N.N]] | [[which AC or DoD item verifies this]] | [[unit test / integration test / manual / inspection]] | [[Pass / Fail / Pending]] |

[[If a requirement is verified by multiple AC items across different stories, include one row per verification (a requirement may have multiple rows). This captures defense-in-depth verification.]]
